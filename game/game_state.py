"""Состояние одной партии: фазы, правила, валидация всех действий.

Сервер — единственный источник истины. Клиенту уходит только то, что ему
разрешено видеть (view_for): чужие живые корабли НИКОГДА не отправляются,
кроме клеток внутри областей, которые игрок сам разведал (туман войны).
"""
import itertools
import random
import time
from enum import Enum

from game.board import Board, GameError
from game.constants import BOARD_SIZE, FLEET, LOG_LIMIT, REWARDS, SCAN_EXPOSES_OWN, TURN_INCOME, shape_key
from game.gadgets import ShipGadget, create_gadget, price_table
from game.player import Player
from game.ship import Cell, Ship, ShipStatus

__all__ = ["GameState", "GameError", "Phase"]


class Phase(str, Enum):
    LOBBY = "lobby"
    PLACEMENT = "placement"
    BATTLE = "battle"
    FINISHED = "finished"


class GameState:
    def __init__(self, code: str):
        self.code = code
        self.board = Board()
        self.players: list[Player] = []
        self.phase = Phase.LOBBY
        self.turn: int | None = None
        self.winner: int | None = None          # индекс игрока, -1 — ничья
        self.finish_reason = ""
        self._ship_ids = itertools.count(1)
        self._item_ids = itertools.count(1)
        self._log: list[dict] = []
        self._events: list[tuple[str, dict]] = []   # очередь событий для рассылки

    # ------------------------------------------------------------ служебное
    def say(self, actor: int | None, text: str, text_other: str | None = None) -> None:
        """Запись в журнал. actor=None — системное сообщение."""
        self._log.append({"actor": actor, "text": text, "text_other": text_other or text})
        del self._log[:-LOG_LIMIT]

    def pop_events(self) -> list[tuple[str, dict]]:
        ev, self._events = self._events, []
        return ev

    def event_view(self, data: dict, viewer: int) -> dict:
        """Переводит индексы игроков в 'you'/'opponent' для конкретного получателя."""
        out = dict(data)
        if "by" in out:
            out["by"] = "you" if out["by"] == viewer else "opponent"
        if "winner" in out:
            w = out["winner"]
            out["winner"] = "draw" if w == -1 else ("you" if w == viewer else "opponent")
        return out

    def _require_phase(self, *phases: Phase) -> None:
        if self.phase not in phases:
            raise GameError("Сейчас это действие недоступно")

    def _require_turn(self, idx: int) -> None:
        self._require_phase(Phase.BATTLE)
        if self.turn != idx:
            raise GameError("Сейчас не ваш ход")

    # ------------------------------------------------------------ лобби
    def add_player(self, name: str, token: str) -> Player:
        if self.phase != Phase.LOBBY or len(self.players) >= 2:
            raise GameError("Лобби заполнено или игра уже идёт")
        p = Player(index=len(self.players), name=name, token=token)
        self.players.append(p)
        return p

    def remove_player(self, idx: int) -> None:
        if self.phase == Phase.LOBBY and idx == 1 and len(self.players) == 2:
            self.players.pop()

    def start_game(self, idx: int) -> None:
        self._require_phase(Phase.LOBBY)
        if idx != 0:
            raise GameError("Начать игру может только создатель лобби")
        if len(self.players) < 2:
            raise GameError("Нужен второй игрок")
        self.phase = Phase.PLACEMENT
        for p in self.players:
            # ключи вида "2x5" (толщина x длина) — удобно передавать в JSON
            p.to_place = {shape_key(t, l): n for (t, l), n in FLEET.items()}
        self.say(None, "Фаза 1: расставьте корабли на общем поле и нажмите «Готов»")

    # ------------------------------------------------------------ фаза 1
    def place_ship(self, idx: int, x: int, y: int, thick: int, length: int, orientation: str) -> None:
        self._require_phase(Phase.PLACEMENT)
        p = self.players[idx]
        if p.ready:
            raise GameError("Вы уже нажали «Готов»")
        key = shape_key(thick, length)
        if p.to_place.get(key, 0) <= 0:
            raise GameError(f"Кораблей {thick}×{length} больше не осталось")
        cells = Board.ship_cells(x, y, thick, length, orientation)
        self.deploy_ship(p, cells, "initial")   # если исключение — to_place не трогаем
        p.to_place[key] -= 1

    def deploy_ship(self, player: Player, cells: tuple[Cell, ...], origin: str):
        """Общая логика установки (фаза 1 и купленные корабли).

        Правило двойной установки: корабль на клетку с живым ЧУЖИМ кораблём —
        оба корабля целиком уничтожаются, их клетки становятся «мёртвыми».
        Свой корабль перекрывать нельзя. Возвращает (корабль, [уничтоженные чужие]).
        """
        board = self.board
        enemies: dict[int, Ship] = {}
        for c in cells:
            if not board.is_functional(c):
                raise GameError("Нельзя ставить корабль на обстрелянные или потопленные клетки")
            other = board.ship_at(c)
            if other is not None:
                if other.owner == player.index:
                    raise GameError("Здесь уже стоит ваш корабль")
                enemies[other.id] = other
        ship = Ship(id=next(self._ship_ids), owner=player.index, cells=tuple(cells), origin=origin)
        player.ships.append(ship)
        if not enemies:
            board.add_ship(ship)
            return ship, []
        ship.status = ShipStatus.COLLIDED
        board.mark_dead(ship.cells)
        victims = list(enemies.values())
        for v in victims:
            v.status = ShipStatus.COLLIDED
            board.remove_ship(v)
            board.mark_dead(v.cells)
        if self.phase == Phase.PLACEMENT:
            self.say(None, "Два корабля совпали по координатам — оба уничтожены")
        self._check_victory()
        return ship, victims

    def set_ready(self, idx: int) -> None:
        self._require_phase(Phase.PLACEMENT)
        p = self.players[idx]
        p.ready = True
        self.say(idx, "готов к бою")
        if all(pl.ready for pl in self.players):
            self.phase = Phase.BATTLE
            first = random.choice([0, 1])
            self.say(None, f"Фаза 2: бой! Первым ходит {self.players[first].name}")
            self._begin_turn(first)
            self._check_victory()   # у кого-то могли не остаться кораблей

    # ------------------------------------------------------------ фаза 2
    def _begin_turn(self, idx: int) -> None:
        """Передать ход игроку idx и начислить ему доход за ход."""
        self.turn = idx
        self.players[idx].points += TURN_INCOME
        self.say(idx, f"начало хода: +{TURN_INCOME} очков", f"начало хода соперника: +{TURN_INCOME} очков")

    def shoot(self, idx: int, x: int, y: int) -> None:
        self._require_turn(idx)
        ev = self.fire(self.players[idx], [(x, y)], strict=True)
        res = ev["cells"][0]["result"]
        word = {"miss": "промах", "hit": "попадание", "sunk": "корабль потоплен!"}[res]
        self.say(idx, f"выстрел ({x + 1}, {y + 1}) — {word}")

    def fire(self, player: Player, cells: list[Cell], strict: bool = False) -> dict:
        """Обстрел списка клеток. Попадание сохраняет ход, промах передаёт его."""
        board = self.board
        results, sunk_ships, gained = [], [], 0
        for c in cells:
            if not board.is_functional(c):
                if strict:
                    raise GameError("Эта клетка уже обстреляна или потоплена")
                continue
            ship = board.ship_at(c)
            if ship is not None and ship.owner == player.index:
                if strict:
                    raise GameError("Нельзя стрелять по своему кораблю")
                continue
            if ship is None:
                board.shots[c] = "miss"
                results.append({"x": c[0], "y": c[1], "result": "miss"})
                continue
            board.shots[c] = "hit"
            ship.hits.add(c)
            gained += REWARDS["hit"]
            res = "hit"
            if ship.fully_hit:
                ship.status = ShipStatus.SUNK
                board.remove_ship(ship)
                board.mark_dead(ship.cells)
                gained += REWARDS["sunk"]
                sunk_ships.append([list(sc) for sc in ship.cells])
                res = "sunk"
            results.append({"x": c[0], "y": c[1], "result": res})
        if not results:
            raise GameError("В области нет клеток, доступных для выстрела")
        player.points += gained
        any_hit = any(r["result"] != "miss" for r in results)
        if not any_hit:
            self._begin_turn(1 - player.index)
        ev = {"by": player.index, "cells": results, "hit": any_hit, "sunk": sunk_ships, "gained": gained}
        self._events.append(("shot_result", ev))
        self._check_victory()
        return ev

    # ------------------------------------------------------------ гаджеты
    def buy_gadget(self, idx: int, kind: str, w: int, h: int) -> dict:
        self._require_turn(idx)
        p = self.players[idx]
        gadget = create_gadget(kind, w, h)       # проверяет, что такая форма есть в магазине
        price = gadget.price()
        if p.points < price:
            raise GameError(f"Не хватает очков: нужно {price}, у вас {p.points}")
        p.points -= price
        item = {"id": next(self._item_ids), "kind": kind, "w": w, "h": h, "price": price}
        p.inventory.append(item)
        dims = f"{w}×{h}"
        self.say(idx, f"покупка: {gadget.title.lower()} ({dims}) за {price}", "совершена покупка")
        return item

    def _take_item(self, p: Player, item_id: int) -> dict:
        for it in p.inventory:
            if it["id"] == item_id:
                return it
        raise GameError("У вас нет такого предмета")

    def use_gadget(self, idx: int, item_id: int, x: int, y: int, rotated: bool = False) -> None:
        self._require_turn(idx)
        p = self.players[idx]
        item = self._take_item(p, item_id)
        if item["kind"] == "ship":
            raise GameError("Корабль нужно ставить через «поставить купленный корабль»")
        create_gadget(item["kind"], item["w"], item["h"]).apply(self, p, x, y, rotated)
        p.inventory.remove(item)   # удаляем только после успешного применения

    def place_purchased_ship(self, idx: int, item_id: int, x: int, y: int, orientation: str) -> None:
        self._require_turn(idx)
        p = self.players[idx]
        item = self._take_item(p, item_id)
        if item["kind"] != "ship":
            raise GameError("Этот предмет — не корабль")
        gadget = create_gadget("ship", item["w"], item["h"])
        assert isinstance(gadget, ShipGadget)
        gadget.apply(self, p, x, y, orientation)
        p.inventory.remove(item)
        self._check_victory()

    # ------------------------------------------------------------ завершение
    def _check_victory(self) -> None:
        if self.phase != Phase.BATTLE:
            return
        alive = [p.has_active_ships() for p in self.players]
        if all(alive):
            return
        if not any(alive):
            self._finish(-1, "mutual_destruction")
        else:
            self._finish(alive.index(True), "all_ships_sunk")

    def _finish(self, winner: int, reason: str) -> None:
        if self.phase == Phase.FINISHED:
            return
        self.phase = Phase.FINISHED
        self.turn = None
        self.winner = winner
        self.finish_reason = reason
        self._events.append(("game_over", {"winner": winner, "reason": reason}))

    def forfeit(self, idx: int, reason: str = "disconnect") -> None:
        """Техническое поражение (разрыв соединения > 60 с или выход из партии)."""
        if self.phase in (Phase.PLACEMENT, Phase.BATTLE):
            self._finish(1 - idx, reason)

    # ------------------------------------------------------------ вид для клиента
    def view_for(self, idx: int, now: float | None = None) -> dict:
        """Полное состояние для игрока idx. Скрытые данные (чужие корабли) фильтруются ЗДЕСЬ."""
        now = time.time() if now is None else now
        me = self.players[idx]
        opp = self.players[1 - idx] if len(self.players) == 2 else None
        b = self.board
        hits, misses = b.encoded_shots()
        finished = self.phase == Phase.FINISHED

        if self.winner is None:
            winner = None
        else:
            winner = "draw" if self.winner == -1 else ("you" if self.winner == idx else "opponent")

        opp_ships = opp.ships if opp else []

        return {
            "lobby": self.code,
            "phase": self.phase.value,
            "turn": None if self.turn is None else ("you" if self.turn == idx else "opponent"),
            "config": {
                "board_size": BOARD_SIZE,
                "fleet": [{"t": t, "l": l, "count": n} for (t, l), n in FLEET.items()],
                "gadgets": price_table(),
                "rewards": REWARDS,
            },
            "you": {
                "name": me.name, "index": idx, "is_creator": idx == 0,
                "points": me.points, "ready": me.ready,
                "to_place": me.to_place,
                "inventory": me.inventory,
                "ships": [s.to_dict() for s in me.ships],      # только СВОИ корабли
            },
            "opponent": None if opp is None else {
                "name": opp.name, "ready": opp.ready, "points": opp.points,
                "connected": opp.connected,
                "reconnect_seconds": 0 if opp.connected or opp.disconnect_deadline is None
                else max(0, int(opp.disconnect_deadline - now)),
            },
            # Публичные метки: крестики (попадания/промахи) и потопленные клетки
            "marks": {"hit": hits, "miss": misses, "dead": [b.encode(c) for c in b.dead]},
            # Туман войны: разведанные области видят ОБА игрока (прямоугольники x,y,w,h).
            # "seen" — клетки ЖИВЫХ кораблей соперника внутри областей, разведанных именно вами.
            # Считается при каждой отправке, поэтому новые корабли соперника появляются сразу.
            "fog": {
                "mine": [[x, y, w, h] for x, y, w, h, by in b.reveals if by == idx],
                "opp": [[x, y, w, h] for x, y, w, h, by in b.reveals if by != idx],
                "seen": [b.encode(c) for s in opp_ships if s.active
                         for c in s.cells
                         if b.is_revealed_by(c, idx) or (SCAN_EXPOSES_OWN and b.is_revealed(c))],
            },
            # После конца игры раскрываем уцелевшие корабли соперника
            "reveal": [b.encode(c) for s in opp_ships if s.active for c in s.cells] if finished else [],
            "winner": winner,
            "finish_reason": self.finish_reason,
            "log": [
                {"who": "system" if e["actor"] is None else ("you" if e["actor"] == idx else "opponent"),
                 "text": e["text"] if e["actor"] in (None, idx) else e["text_other"]}
                for e in self._log
            ],
        }
