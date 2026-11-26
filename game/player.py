"""Игрок: имя, очки, корабли, инвентарь гаджетов."""
from dataclasses import dataclass, field

from game.constants import START_POINTS
from game.ship import Cell, Ship


@dataclass(eq=False)
class Player:
    index: int                  # 0 — создатель лобби, 1 — подключившийся
    name: str
    token: str                  # секрет для переподключения (знает только сам игрок)
    points: int = START_POINTS
    ready: bool = False
    connected: bool = True
    disconnect_deadline: float | None = None     # unix-время, когда засчитается поражение
    ships: list[Ship] = field(default_factory=list)
    to_place: dict[int, int] = field(default_factory=dict)   # сколько кораблей каждого размера осталось поставить
    inventory: list[dict] = field(default_factory=list)      # купленные гаджеты: {id, kind, size, price}
    scan_ship: set[Cell] = field(default_factory=set)        # результаты разведки (ПРИВАТНО)
    scan_empty: set[Cell] = field(default_factory=set)

    def active_ships(self) -> list[Ship]:
        return [s for s in self.ships if s.active]

    def has_active_ships(self) -> bool:
        return any(s.active for s in self.ships)
