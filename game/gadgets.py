"""Гаджеты: расчёт цены, проверка параметров и применение.

Покупка кладёт предмет в инвентарь, применение — отдельное действие.
Для областей w×h — ширина×высота (при применении можно повернуть: w и h меняются местами).
Для кораблей w — толщина, h — длина (ориентацию задаёт игрок при установке).
"""
import math
from abc import ABC, abstractmethod

from game.board import Board, GameError
from game.constants import GADGETS


class Gadget(ABC):
    kind: str = ""

    def __init__(self, w: int, h: int = 1):
        self.w = w
        self.h = h
        self.validate()

    @abstractmethod
    def validate(self) -> None: ...

    @abstractmethod
    def price(self) -> int: ...

    @property
    def title(self) -> str:
        return GADGETS[self.kind]["title"]


class AreaGadget(Gadget):
    """Общая часть для гаджетов, работающих по прямоугольнику w×h."""

    def validate(self) -> None:
        # Разрешены только формы из constants.py — клиент не может придумать свою
        shapes = [tuple(s) for s in GADGETS[self.kind]["shapes"]]
        if (self.w, self.h) not in shapes:
            raise GameError("Такой области нет в магазине")

    def price(self) -> int:
        cfg = GADGETS[self.kind]
        paid_cells = max(0, self.w * self.h - cfg["free_cells"])
        return max(1, math.ceil(round(paid_cells * cfg["per_cell"], 6)))

    def dims(self, rotated: bool) -> tuple[int, int]:
        """Размеры при применении: повёрнутая область меняет ширину и высоту местами."""
        return (self.h, self.w) if rotated else (self.w, self.h)


class ScanGadget(AreaGadget):
    kind = "scan"

    def apply(self, game, player, x: int, y: int, rotated: bool = False) -> dict:
        """Разведка: рассеивает туман войны в области. Область запоминается на доске,
        а видимость вражеских кораблей в ней считается заново при каждой отправке состояния."""
        w, h = self.dims(rotated)
        cells = Board.area_cells(x, y, w, h)          # заодно проверяет границы
        found = 0
        for c in cells:
            ship = game.board.ship_at(c)
            if ship is not None and ship.owner != player.index:
                found += 1
        game.board.add_reveal(x, y, w, h, player.index)
        from game.constants import SCAN_EXPOSES_OWN   # локальный импорт, чтобы не трогать шапку файла
        other_text = f"соперник разведал область {w}×{h} с угла ({x + 1}, {y + 1})"
        if SCAN_EXPOSES_OWN:
            other_text += ": ваши корабли в ней теперь видны ему"
        game.say(player.index,
                 f"разведка области {w}×{h} с угла ({x + 1}, {y + 1}): найдено клеток с кораблями — {found}"
                 + ("; ваши корабли в ней видны сопернику" if SCAN_EXPOSES_OWN else ""),
                 other_text)
        return {"found": found}


class AreaShotGadget(AreaGadget):
    kind = "area_shot"

    def apply(self, game, player, x: int, y: int, rotated: bool = False) -> dict:
        """Выстрел по всем доступным клеткам области."""
        w, h = self.dims(rotated)
        cells = Board.area_cells(x, y, w, h)
        ev = game.fire(player, cells, strict=False)
        hits = sum(1 for r in ev["cells"] if r["result"] != "miss")
        game.say(player.index,
                 f"выстрел по области {w}×{h} с угла ({x + 1}, {y + 1}): попаданий {hits}, потоплено {len(ev['sunk'])}")
        return ev


class ShipGadget(Gadget):
    kind = "ship"

    def validate(self) -> None:
        if (self.w, self.h) not in GADGETS["ship"]["prices"]:
            raise GameError("Нет такого корабля в магазине")

    def price(self) -> int:
        return GADGETS["ship"]["prices"][(self.w, self.h)]

    def apply(self, game, player, x: int, y: int, orientation: str):
        """Поставить купленный корабль. При совпадении с чужим — тонут оба."""
        cells = Board.ship_cells(x, y, self.w, self.h, orientation)
        ship, victims = game.deploy_ship(player, cells, "purchased")
        if victims:
            game.say(None, "купленный корабль совпал с кораблём соперника — оба уничтожены")
        else:
            game.say(player.index, f"новый корабль {self.w}×{self.h} на поле", "соперник поставил новый корабль")
        return ship, victims


GADGET_CLASSES = {"scan": ScanGadget, "area_shot": AreaShotGadget, "ship": ShipGadget}


def create_gadget(kind: str, w: int, h: int = 1) -> Gadget:
    cls = GADGET_CLASSES.get(kind)
    if cls is None:
        raise GameError("Неизвестный гаджет")
    return cls(w, h)


def price_table() -> dict:
    """Таблица для клиента: у каждого гаджета список форм с ценами (клиент цены не считает)."""
    table = {}
    for kind in ("scan", "area_shot"):
        cfg = GADGETS[kind]
        table[kind] = {
            "title": cfg["title"],
            "shapes": [{"w": w, "h": h, "price": create_gadget(kind, w, h).price()} for w, h in cfg["shapes"]],
        }
    prices = GADGETS["ship"]["prices"]
    table["ship"] = {
        "title": GADGETS["ship"]["title"],
        "shapes": [{"w": t, "h": l, "price": prices[(t, l)]}
                   for (t, l) in sorted(prices, key=lambda s: (s[0] * s[1], s))],
    }
    return table
