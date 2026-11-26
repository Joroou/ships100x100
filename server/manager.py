"""Менеджер лобби и сессий: связывает WebSocket-соединения с играми.

Каждое лобби — отдельная партия (GameState) со своим asyncio.Lock, поэтому
действия двух игроков обрабатываются строго по очереди.
"""
import asyncio
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass, field

from fastapi import WebSocket

from game.constants import (LOBBY_CODE_ALPHABET, LOBBY_CODE_LENGTH, MAX_LOBBIES,
                            MAX_NAME_LEN, RECONNECT_TIMEOUT)
from game.game_state import GameError, GameState, Phase
from server import messages as M

log = logging.getLogger("seabattle.manager")


@dataclass(eq=False)
class Session:
    """Одно WebSocket-соединение."""
    ws: WebSocket
    lobby: "Lobby | None" = None
    pidx: int = -1


@dataclass(eq=False)
class Lobby:
    game: GameState
    sessions: dict[int, Session] = field(default_factory=dict)    # индекс игрока -> соединение
    timers: dict[int, asyncio.Task] = field(default_factory=dict)  # таймеры ожидания переподключения
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def clean_name(raw: str) -> str:
    name = re.sub(r"[\x00-\x1f\x7f<>]", "", raw)
    name = re.sub(r"\s+", " ", name).strip()[:MAX_NAME_LEN]
    return name or "Игрок"


class LobbyManager:
    def __init__(self) -> None:
        self.lobbies: dict[str, Lobby] = {}

    # ============================================================ отправка
    async def _send(self, session: Session, payload: dict) -> None:
        try:
            await session.ws.send_json(payload)
        except Exception:  # соединение уже закрыто — не страшно
            log.debug("Не удалось отправить сообщение", exc_info=True)

    async def _error(self, session: Session, message: str, code: str = "error") -> None:
        await self._send(session, M.build(M.S_ERROR, message=message, code=code))

    async def _broadcast(self, lobby: Lobby) -> None:
        """Каждому игроку — его персональное (отфильтрованное) состояние."""
        for pidx, s in list(lobby.sessions.items()):
            await self._send(s, M.build(M.S_STATE, state=lobby.game.view_for(pidx)))

    async def _flush(self, lobby: Lobby) -> None:
        """Разослать накопленные события и актуальное состояние."""
        game = lobby.game
        events = game.pop_events()
        for kind, data in events:
            if kind == "shot_result":
                for pidx, s in list(lobby.sessions.items()):
                    await self._send(s, M.build(M.S_SHOT_RESULT, **game.event_view(data, pidx)))
        await self._broadcast(lobby)
        for kind, data in events:
            if kind == "game_over":
                for pidx, s in list(lobby.sessions.items()):
                    await self._send(s, M.build(M.S_GAME_OVER, **game.event_view(data, pidx)))

    # ============================================================ вход сообщений
    async def handle_raw(self, session: Session, raw: str) -> None:
        if len(raw) > 4096:
            return await self._error(session, "Слишком большое сообщение")
        try:
            msg = M.parse_client_message(json.loads(raw))
        except ValueError:
            return await self._error(session, "Некорректное сообщение")
        try:
            if isinstance(msg, M.CreateLobby):
                await self._create(session, msg)
            elif isinstance(msg, M.JoinLobby):
                await self._join(session, msg)
            elif isinstance(msg, M.Reconnect):
                await self._reconnect(session, msg)
            elif isinstance(msg, M.LeaveLobby):
                await self._leave(session)
            else:
                await self._game_action(session, msg)
        except GameError as e:
            await self._error(session, str(e), e.code)
        except Exception:
            log.exception("Ошибка обработки сообщения")
            await self._error(session, "Внутренняя ошибка сервера")

    # ============================================================ лобби
    def _new_code(self) -> str:
        while True:
            code = "".join(secrets.choice(LOBBY_CODE_ALPHABET) for _ in range(LOBBY_CODE_LENGTH))
            if code not in self.lobbies:
                return code

    async def _create(self, session: Session, msg: M.CreateLobby) -> None:
        if session.lobby is not None:
            raise GameError("Вы уже находитесь в лобби")
        if len(self.lobbies) >= MAX_LOBBIES:
            raise GameError("Сервер перегружен, попробуйте позже")
        code = self._new_code()
        game = GameState(code)
        player = game.add_player(clean_name(msg.name), secrets.token_urlsafe(16))
        lobby = Lobby(game)
        lobby.sessions[0] = session
        self.lobbies[code] = lobby
        session.lobby, session.pidx = lobby, 0
        log.info("Создано лобби %s", code)
        await self._send(session, M.build(M.S_LOBBY_CREATED, code=code, token=player.token,
                                          state=game.view_for(0)))

    async def _join(self, session: Session, msg: M.JoinLobby) -> None:
        if session.lobby is not None:
            raise GameError("Вы уже находитесь в лобби")
        lobby = self.lobbies.get(msg.code.strip().upper())
        if lobby is None:
            raise GameError("Лобби с таким кодом не найдено")
        async with lobby.lock:
            game = lobby.game
            player = game.add_player(clean_name(msg.name), secrets.token_urlsafe(16))  # GameError, если занято
            lobby.sessions[player.index] = session
            session.lobby, session.pidx = lobby, player.index
            await self._send(session, M.build(M.S_LOBBY_JOINED, code=game.code, token=player.token,
                                              state=game.view_for(player.index)))
            creator = lobby.sessions.get(0)
            if creator:
                await self._send(creator, M.build(M.S_OPPONENT_JOINED, name=player.name,
                                                  state=game.view_for(0)))

    async def _reconnect(self, session: Session, msg: M.Reconnect) -> None:
        if session.lobby is not None:
            raise GameError("Вы уже находитесь в лобби")
        lobby = self.lobbies.get(msg.code.strip().upper())
        if lobby is None:
            raise GameError("Партия не найдена", "reconnect_failed")
        async with lobby.lock:
            game = lobby.game
            token = msg.token.encode()
            player = next((p for p in game.players if secrets.compare_digest(p.token.encode(), token)), None)
            if player is None:
                raise GameError("Неверный ключ переподключения", "reconnect_failed")
            old = lobby.sessions.get(player.index)
            if old is not None and old is not session:   # старая вкладка/соединение
                old.lobby = None
                try:
                    await old.ws.close()
                except Exception:
                    pass
            lobby.sessions[player.index] = session
            session.lobby, session.pidx = lobby, player.index
            player.connected, player.disconnect_deadline = True, None
            timer = lobby.timers.pop(player.index, None)
            if timer:
                timer.cancel()
            log.info("Игрок %s переподключился к %s", player.index, game.code)
            await self._broadcast(lobby)

    async def _leave(self, session: Session) -> None:
        """Игрок сам вышел из лобби/партии."""
        lobby = session.lobby
        if lobby is None:
            return
        async with lobby.lock:
            await self._remove_locked(lobby, session)

    async def _remove_locked(self, lobby: Lobby, session: Session) -> None:
        """Убрать игрока из лобби (вызывать только под lobby.lock)."""
        game, pidx = lobby.game, session.pidx
        if lobby.sessions.get(pidx) is session:
            del lobby.sessions[pidx]
        session.lobby, session.pidx = None, -1
        timer = lobby.timers.pop(pidx, None)
        if timer:
            timer.cancel()

        if game.phase == Phase.LOBBY:
            if pidx == 0:
                # Создатель ушёл — лобби закрывается, второго игрока возвращаем в меню
                other = lobby.sessions.pop(1, None)
                if other:
                    other.lobby, other.pidx = None, -1
                    await self._error(other, "Создатель закрыл лобби", "lobby_closed")
                self._drop(lobby)
                return
            game.remove_player(1)
            await self._broadcast(lobby)
        elif game.phase in (Phase.PLACEMENT, Phase.BATTLE):
            game.forfeit(pidx, "left")        # выход посреди партии = поражение
            await self._flush(lobby)
        if not lobby.sessions:
            self._drop(lobby)

    def _drop(self, lobby: Lobby) -> None:
        """Удалить лобби и остановить все его таймеры."""
        for t in lobby.timers.values():
            t.cancel()
        lobby.timers.clear()
        self.lobbies.pop(lobby.game.code, None)
        log.info("Лобби %s удалено", lobby.game.code)

    # ============================================================ игровые действия
    async def _game_action(self, session: Session, msg) -> None:
        lobby = session.lobby
        if lobby is None:
            raise GameError("Сначала создайте игру или подключитесь к лобби")
        async with lobby.lock:                       # действия игроков — строго по очереди
            game, i = lobby.game, session.pidx
            if isinstance(msg, M.StartGame):
                game.start_game(i)
            elif isinstance(msg, M.PlaceShip):
                game.place_ship(i, msg.x, msg.y, msg.thick, msg.length, msg.orientation)
            elif isinstance(msg, M.Ready):
                game.set_ready(i)
            elif isinstance(msg, M.Shoot):
                game.shoot(i, msg.x, msg.y)
            elif isinstance(msg, M.BuyGadget):
                game.buy_gadget(i, msg.kind, msg.w, msg.h)
            elif isinstance(msg, M.UseGadget):
                game.use_gadget(i, msg.item_id, msg.x, msg.y, msg.rotated)
            elif isinstance(msg, M.PlacePurchasedShip):
                game.place_purchased_ship(i, msg.item_id, msg.x, msg.y, msg.orientation)
            else:
                raise GameError("Неизвестное действие")
            await self._flush(lobby)                 # разослать события и новое состояние

    # ============================================================ разрыв соединения
    async def disconnect(self, session: Session) -> None:
        """Вызывается при закрытии WebSocket."""
        lobby = session.lobby
        if lobby is None:
            return
        async with lobby.lock:
            game, pidx = lobby.game, session.pidx
            if session.lobby is None or lobby.sessions.get(pidx) is not session:
                return                               # соединение уже заменено переподключением
            if game.phase in (Phase.PLACEMENT, Phase.BATTLE):
                # Даём 60 секунд на возвращение, потом — техническое поражение
                del lobby.sessions[pidx]
                player = game.players[pidx]
                player.connected = False
                player.disconnect_deadline = time.time() + RECONNECT_TIMEOUT
                old = lobby.timers.pop(pidx, None)
                if old:
                    old.cancel()
                lobby.timers[pidx] = asyncio.create_task(self._forfeit_timer(lobby, pidx))
                await self._broadcast(lobby)         # сопернику покажется «ожидание переподключения»
            else:
                await self._remove_locked(lobby, session)

    async def _forfeit_timer(self, lobby: Lobby, pidx: int) -> None:
        try:
            await asyncio.sleep(RECONNECT_TIMEOUT)
        except asyncio.CancelledError:
            return
        async with lobby.lock:
            player = lobby.game.players[pidx]
            if player.connected:
                return
            lobby.timers.pop(pidx, None)             # убираем себя, чтобы _drop не отменил текущую задачу
            lobby.game.forfeit(pidx, "disconnect")
            await self._flush(lobby)
            if not lobby.sessions:
                self._drop(lobby)
