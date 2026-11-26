"""Корабль: координаты, размер, состояние."""
from dataclasses import dataclass, field
from enum import Enum

Cell = tuple[int, int]  # (x, y)


class ShipStatus(str, Enum):
    ACTIVE = "active"        # на плаву
    SUNK = "sunk"            # потоплен выстрелом
    COLLIDED = "collided"    # уничтожен из-за совпадения клеток с чужим кораблём


@dataclass(eq=False)
class Ship:
    id: int
    owner: int                       # индекс игрока (0/1)
    cells: tuple[Cell, ...]
    origin: str = "initial"          # "initial" — из стартового флота, "purchased" — куплен
    hits: set[Cell] = field(default_factory=set)
    status: ShipStatus = ShipStatus.ACTIVE

    @property
    def size(self) -> int:
        return len(self.cells)

    @property
    def active(self) -> bool:
        return self.status is ShipStatus.ACTIVE

    @property
    def fully_hit(self) -> bool:
        """Все клетки подбиты — корабль должен затонуть."""
        return len(self.hits) >= len(self.cells)

    def to_dict(self) -> dict:
        """Представление для ВЛАДЕЛЬЦА корабля (чужие корабли клиенту не отправляются)."""
        return {
            "id": self.id,
            "size": self.size,
            "cells": [list(c) for c in self.cells],
            "hits": [list(c) for c in self.hits],
            "status": self.status.value,
            "origin": self.origin,
        }
