"""One boundary for finding gaze actions and their current visible bounds."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from PySide6.QtCore import QPoint, QRect


class GazeTarget(Protocol):
    def action_at_global_point(self, point: QPoint) -> str | None: ...

    def action_center_at_global_point(self, action: str, point: QPoint) -> QPoint | None: ...

    def contains_global_point(self, point: QPoint) -> bool: ...

    def action_bounds(self, action: str) -> QRect | None: ...


@dataclass(frozen=True)
class GazeTargets:
    action_at: Callable[[QPoint], str | None]
    action_center: Callable[[str, QPoint], QPoint | None]
    contains: Callable[[QPoint], bool]
    bounds: Callable[[str], QRect | None] | None = None

    def action_at_global_point(self, point: QPoint) -> str | None:
        return self.action_at(point)

    def action_center_at_global_point(self, action: str, point: QPoint) -> QPoint | None:
        return self.action_center(action, point)

    def contains_global_point(self, point: QPoint) -> bool:
        return self.contains(point)

    def action_bounds(self, action: str) -> QRect | None:
        return self.bounds(action) if self.bounds is not None else None
