"""Map gaze into Qt logical and Windows physical coordinates."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint

ScreenGeometry = tuple[int, int, int, int]


@dataclass(frozen=True)
class GazeScreenPoint:
    logical: QPoint
    physical: QPoint


@dataclass(frozen=True)
class ScreenMapping:
    logical: ScreenGeometry
    physical: ScreenGeometry

    def normalized(self, x: float, y: float) -> GazeScreenPoint:
        x = min(1.0, max(0.0, x))
        y = min(1.0, max(0.0, y))
        return GazeScreenPoint(
            logical=_point(self.logical, x, y),
            physical=_point(self.physical, x, y),
        )

    def from_logical(self, point: QPoint) -> GazeScreenPoint:
        left, top, width, height = self.logical
        x = max(left, min(left + width - 1, point.x()))
        y = max(top, min(top + height - 1, point.y()))
        x_ratio = (x - left) / max(1, width - 1)
        y_ratio = (y - top) / max(1, height - 1)
        return GazeScreenPoint(
            logical=QPoint(x, y),
            physical=_point(self.physical, x_ratio, y_ratio),
        )


def _point(geometry: ScreenGeometry, x: float, y: float) -> QPoint:
    left, top, width, height = geometry
    return QPoint(
        round(left + x * max(1, width - 1)),
        round(top + y * max(1, height - 1)),
    )
