"""Общее поле 100×100. Хранит занятость, выстрелы и «мёртвые» клетки."""
from game.constants import BOARD_SIZE
from game.ship import Cell, Ship


class GameError(Exception):
    """Нарушение правил / невалидное действие. Текст показывается игроку."""

    def __init__(self, message: str, code: str = "error"):
        super().__init__(message)
        self.code = code


class Board:
    def __init__(self, size: int = BOARD_SIZE):
        self.size = size
        self._occupied: dict[Cell, Ship] = {}   # клетка -> ЖИВОЙ корабль (не более одного!)
        self.shots: dict[Cell, str] = {}        # клетка -> "hit" | "miss" (публичные крестики)
        self.dead: set[Cell] = set()            # потопленные / уничтоженные клетки (публичные)
        self.reveals: list[tuple[int, int, int, int, int]] = []   # разведанные области: (x, y, w, h, кто разведал)


    # ---------- проверки клеток ----------
    def in_bounds(self, c: Cell) -> bool:
        return 0 <= c[0] < self.size and 0 <= c[1] < self.size

    def is_functional(self, c: Cell) -> bool:
        """Функциональная клетка: в поле, не обстреляна и не «мёртвая»."""
        return self.in_bounds(c) and c not in self.shots and c not in self.dead

    def ship_at(self, c: Cell) -> Ship | None:
        return self._occupied.get(c)

    # ---------- изменение состояния ----------
    def add_ship(self, ship: Ship) -> None:
        for c in ship.cells:
            self._occupied[c] = ship

    def remove_ship(self, ship: Ship) -> None:
        for c in ship.cells:
            if self._occupied.get(c) is ship:
                del self._occupied[c]

    def mark_dead(self, cells) -> None:
        self.dead.update(cells)

    # ---------- геометрия ----------
    def add_reveal(self, x: int, y: int, w: int, h: int, by: int) -> None:
        """Запомнить разведанную область (туман войны рассеивается навсегда)."""
        rect = (x, y, w, h, by)
        if rect not in self.reveals:
            self.reveals.append(rect)

    def is_revealed_by(self, c: Cell, idx: int) -> bool:
        cx, cy = c
        return any(by == idx and x <= cx < x + w and y <= cy < y + h for x, y, w, h, by in self.reveals)

    def is_revealed(self, c: Cell) -> bool:
        """Клетка лежит в области, разведанной любым из игроков."""
        cx, cy = c
        return any(x <= cx < x + w and y <= cy < y + h for x, y, w, h, _by in self.reveals)

    def encode(self, c: Cell) -> int:
        """Клетка -> одно число (компактная передача по сети)."""
        return c[1] * self.size + c[0]

    @staticmethod
    def ship_cells(x: int, y: int, thick: int, length: int, orientation: str, size: int = BOARD_SIZE) -> tuple[Cell, ...]:
        """Клетки корабля-прямоугольника с левым верхним углом (x,y).
        'h' — длина вдоль оси X, 'v' — длина вдоль оси Y."""
        if orientation not in ("h", "v"):
            raise GameError("Неизвестная ориентация корабля")
        w, h = (length, thick) if orientation == "h" else (thick, length)
        if x < 0 or y < 0 or x + w > size or y + h > size:
            raise GameError("Корабль выходит за границы поля")
        return tuple((x + dx, y + dy) for dy in range(h) for dx in range(w))

    @staticmethod
    def area_cells(x: int, y: int, w: int, h: int, size: int = BOARD_SIZE) -> list[Cell]:
        """Прямоугольник w×h (ширина×высота) с левым верхним углом (x,y)."""
        if x < 0 or y < 0 or x + w > size or y + h > size:
            raise GameError("Область выходит за границы поля")
        return [(cx, cy) for cy in range(y, y + h) for cx in range(x, x + w)]

    def encoded_shots(self) -> tuple[list[int], list[int]]:
        hits = [self.encode(c) for c, r in self.shots.items() if r == "hit"]
        misses = [self.encode(c) for c, r in self.shots.items() if r == "miss"]
        return hits, misses
