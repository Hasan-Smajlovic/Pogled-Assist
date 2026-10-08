"""Painting and target geometry for the caregiver gaze check."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..tracking.gaze_check import CheckSnapshot, FixationResult

TARGETS = (
    ("Sredina", 0.5, 0.5),
    ("Gore lijevo", 0.04, 0.06),
    ("Gore desno", 0.96, 0.06),
    ("Dolje lijevo", 0.04, 0.94),
    ("Dolje desno", 0.96, 0.94),
)
COLORS = {True: "#70dfa1", False: "#f0c84a", None: "#bac5d4"}


class EyePositionView(QWidget):
    """Projection of the reported normalized box; not a camera image."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.snapshot = CheckSnapshot()
        self.setMinimumHeight(170)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        box = QRectF(26, 12, max(1, self.width() - 52), max(1, self.height() - 76))
        painter.setPen(QPen(QColor("#58647a"), 2, Qt.DashLine))
        painter.drawRoundedRect(box, 10, 10)
        positions = (self.snapshot.left_position, self.snapshot.right_position)
        for name, position in zip(("L", "D"), positions, strict=True):
            if position is None:
                continue
            # TBCS x runs right to left. Show a front projection with user-eye labels.
            x = box.left() + (1 - min(1.0, max(0.0, position[0]))) * box.width()
            y = box.top() + min(1.0, max(0.0, position[1])) * box.height()
            inside = all(0 <= value <= 1 for value in position)
            painter.setPen(QPen(QColor(COLORS[inside]), 3))
            painter.setBrush(QColor("#1c2029"))
            painter.drawEllipse(QPointF(x, y), 16, 16)
            painter.drawText(QRectF(x - 16, y - 16, 32, 32), Qt.AlignCenter, name)
        painter.setPen(QColor("#bac5d4"))
        if all(position is None for position in positions):
            painter.drawText(box, Qt.AlignCenter, "Položaj očiju nije dostupan")
        depth = QRectF(26, self.height() - 43, max(1, self.width() - 52), 8)
        painter.setBrush(QColor("#394253"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(depth, 4, 4)
        for position in positions:
            if position is not None:
                painter.setBrush(QColor(COLORS[0 <= position[2] <= 1]))
                painter.drawEllipse(
                    QPointF(
                        depth.left() + min(1.0, max(0.0, position[2])) * depth.width(),
                        depth.center().y(),
                    ),
                    6,
                    6,
                )
        painter.setPen(QColor("#bac5d4"))
        font = QFont("Segoe UI")
        font.setPixelSize(15)
        painter.setFont(font)
        labels = QRectF(26, self.height() - 29, self.width() - 52, 25)
        painter.drawText(labels, Qt.AlignLeft | Qt.AlignVCenter, "Bliže uređaju")
        painter.drawText(labels, Qt.AlignRight | Qt.AlignVCenter, "Dalje od uređaja")


class CheckTargetView(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.target_index = 0
        self.trial = False
        self.free = False
        self.gaze_point: QPoint | None = None
        self.progress = 0.0
        self.progress_target: int | None = None
        self.radius = 36
        self.hide()

    def center(self) -> QPoint:
        if self.trial:
            return self.button_rect().center()
        _, x, y = TARGETS[self.target_index]
        return QPoint(round(x * (self.width() - 1)), round(y * (self.height() - 1)))

    @property
    def expected_button(self) -> int:
        return (1, 0, 2)[self.target_index]

    def button_rect(self, index: int | None = None) -> QRect:
        index = self.expected_button if index is None else index
        width, height, gap, left, top = (
            (136, 64, 12, 64, 14),
            (96, 88, 10, 64, self.height() - 230),
            (180, 72, 12, self.width() // 2 - 282, self.height() // 2 - 36),
        )[self.target_index]
        return QRect(left + index * (width + gap), top, width, height)

    def free_centers(self) -> list[QPoint]:
        return [
            QPoint(round(x * (self.width() - 1)), round(y * (self.height() - 1)))
            for y in (0.06, 0.5, 0.94)
            for x in (0.04, 0.5, 0.96)
        ]

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#111318"))
        painter.setPen(QPen(QColor("#8bd5f5"), 2))
        painter.setBrush(QColor("#1c2029"))
        center = self.center()
        if self.trial:
            font = QFont("Segoe UI")
            font.setPixelSize(24)
            painter.setFont(font)
            for index in range(3):
                rect = self.button_rect(index)
                color = "#8bd5f5" if index == self.expected_button else "#58647a"
                painter.setPen(QPen(QColor(color), 2))
                painter.drawRoundedRect(rect, 10, 10)
                if index == self.progress_target:
                    painter.fillRect(
                        QRect(
                            rect.left() + 4,
                            rect.bottom() - 12,
                            round((rect.width() - 8) * self.progress),
                            8,
                        ),
                        QColor("#70dfa1"),
                    )
                painter.setPen(QColor("#eef2f8"))
                label = "Pogledaj" if index == self.expected_button else "Susjed"
                painter.drawText(rect, Qt.AlignCenter, label)
        else:
            for point in self.free_centers() if self.free else [center]:
                painter.setPen(QPen(QColor("#8bd5f5"), 2))
                painter.drawEllipse(point, self.radius, self.radius)
                painter.setPen(QPen(QColor("#eef2f8"), 3))
                painter.drawLine(point + QPoint(-9, 0), point + QPoint(9, 0))
                painter.drawLine(point + QPoint(0, -9), point + QPoint(0, 9))
            if self.free and self.gaze_point is not None:
                painter.setPen(QPen(QColor("#70dfa1"), 3))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(self.gaze_point, 10, 10)


class ResultMapView(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.results: list[FixationResult] = []
        self.targets: list[tuple[str, float, float]] = []
        self.setMinimumSize(230, 140)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        box = QRectF(12, 12, self.width() - 24, self.height() - 24)
        painter.fillRect(box, QColor("#111318"))
        painter.setPen(QPen(QColor("#58647a"), 1))
        painter.drawRect(box)
        for result, (_, x, y) in zip(self.results, self.targets, strict=False):
            target = QPointF(box.left() + x * box.width(), box.top() + y * box.height())
            painter.setPen(QPen(QColor(COLORS[result.near]), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(target, 8, 8)
            if result.gaze_center is not None:
                gx, gy = result.gaze_center
                # Keep off-screen measurements visible at the map edge, never alter metrics.
                gaze = QPointF(
                    box.left() + min(1.0, max(0.0, gx)) * box.width(),
                    box.top() + min(1.0, max(0.0, gy)) * box.height(),
                )
                painter.drawLine(target, gaze)
                painter.setBrush(QColor(COLORS[result.near]))
                painter.drawEllipse(gaze, 4, 4)
