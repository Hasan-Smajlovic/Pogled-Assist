"""Animated overlay for active gaze interactions."""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QApplication, QComboBox, QWidget

from .overlay_window import OverlayStacking, overlay_window_flags

logger = logging.getLogger(__name__)

MIN_PROGRESS_UPDATE_INTERVAL_MS = 20
MIN_PROGRESS_MOVE_DISTANCE_PX = 2
MIN_PROGRESS_DELTA = 0.015


class InteractionOverlayWindow(QWidget):
    """Click-through progress marker for a gaze dwell action."""

    OVERLAY_SIZE = 138
    FIRED_DURATION_MS = 220

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._enabled = True
        self._active = False
        self._mode = "progress"
        self._progress = 0.0
        self._ring_diameter = 64.0
        self._label = ""
        self._fired_started_ms = 0.0
        self._last_progress_point: QPoint | None = None
        self._last_progress_update_ms = 0.0
        self._last_raise_ms = 0.0
        self._stacking = OverlayStacking(self)

        self.setWindowTitle("Prikaz radnje pogledom")
        self.setWindowFlags(overlay_window_flags(click_through=True))
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(self.OVERLAY_SIZE, self.OVERLAY_SIZE)

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def set_enabled(self, enabled: bool) -> None:
        if self._enabled == enabled:
            return

        self._enabled = enabled
        logger.info("Interaction overlay %s.", "enabled" if enabled else "disabled")
        if not enabled:
            self._hide_now()

    def show_progress(self, point: QPoint, progress: float, label: str) -> None:
        if not self._enabled:
            return

        clamped_progress = _clamp(progress, 0.0, 1.0)
        compact_label = _compact_label(label)
        center, diameter = _ring_geometry_at(point)
        now_ms = time.monotonic() * 1000
        if diameter == self._ring_diameter and self._progress_update_skippable(
            point, clamped_progress, compact_label, now_ms
        ):
            return

        self._active = True
        self._mode = "progress"
        self._progress = clamped_progress
        self._ring_diameter = diameter
        self._label = compact_label
        self._last_progress_point = QPoint(point)
        self._last_progress_update_ms = now_ms
        self._move_center_to(center)
        self._ensure_visible()
        self.update()

    def show_fired(self, point: QPoint, label: str) -> None:
        if not self._enabled:
            return

        self._active = True
        self._mode = "fired"
        self._progress = 1.0
        center, self._ring_diameter = _ring_geometry_at(point)
        self._label = _compact_label(label)
        self._last_progress_point = QPoint(point)
        self._last_progress_update_ms = time.monotonic() * 1000
        self._fired_started_ms = time.monotonic() * 1000
        self._move_center_to(center)
        self._ensure_visible()
        self.update()

    def set_paused(self, paused: bool) -> None:
        if self._active and self._mode != "fired":
            self._mode = "paused" if paused else "progress"
            self.update()

    def clear(self) -> None:
        if self._mode == "fired":
            return

        self._hide_now()

    def paintEvent(self, _event) -> None:
        if not self._active:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        self._paint_calm(painter)

    def _paint_calm(self, painter: QPainter) -> None:
        center = QRectF(self.rect()).center()
        diameter = self._ring_diameter - 3
        if diameter <= 0:
            return
        arc_rect = QRectF(center.x() - diameter / 2, center.y() - diameter / 2, diameter, diameter)
        color = QColor("#84c5d9")
        track = QColor(color)
        track.setAlpha(51)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(track, 3))
        painter.drawEllipse(arc_rect)
        painter.setPen(QPen(color, 3, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(arc_rect, 90 * 16, int(-360 * 16 * self._progress))
        if self._mode == "paused":
            painter.setPen(color)
            font = QFont("Segoe UI")
            font.setPixelSize(min(12, int(diameter / 2)))
            painter.setFont(font)
            pause_rect = QRectF(center.x() - 10, center.y() + self._ring_diameter / 2 - 14, 20, 14)
            painter.drawText(pause_rect, Qt.AlignCenter, "Ⅱ")

    def _tick(self) -> None:
        if self._mode == "fired":
            elapsed_ms = time.monotonic() * 1000 - self._fired_started_ms
            if elapsed_ms >= self.FIRED_DURATION_MS:
                self._hide_now()
                return

        self._stacking.refresh_if_due()
        self.update()

    def _move_center_to(self, point: QPoint) -> None:
        self.move(point.x() - self.width() // 2, point.y() - self.height() // 2)

    def _progress_update_skippable(
        self,
        point: QPoint,
        progress: float,
        label: str,
        now_ms: float,
    ) -> bool:
        if not self._active or self._mode != "progress":
            return False
        if self._label != label:
            return False

        if abs(progress - self._progress) >= MIN_PROGRESS_DELTA:
            return False

        if self._last_progress_point is None:
            return False

        distance = abs(point.x() - self._last_progress_point.x()) + abs(
            point.y() - self._last_progress_point.y()
        )
        if distance >= MIN_PROGRESS_MOVE_DISTANCE_PX:
            return False

        return now_ms - self._last_progress_update_ms < MIN_PROGRESS_UPDATE_INTERVAL_MS

    def _ensure_visible(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

        if not self.isVisible() or self._raise_due():
            self.show()
            self._stacking.apply_click_through()
            self.raise_()
            self._stacking.refresh(force=True)
            self._last_raise_ms = time.monotonic() * 1000

    def _raise_due(self) -> bool:
        return time.monotonic() * 1000 - self._last_raise_ms >= 150

    def _hide_now(self) -> None:
        self._active = False
        self._mode = "progress"
        self._progress = 0.0
        self._label = ""
        self._last_progress_point = None
        self._last_progress_update_ms = 0.0
        self._stacking.reset()
        self._timer.stop()
        self.hide()


def _compact_label(label: str) -> str:
    normalized = " ".join(label.split())
    if len(normalized) <= 13:
        return normalized
    if normalized in {"Dvostruki klik", "Dvostruki lijevi klik"}:
        return "Dvostruki"
    return normalized[:13]


def _ring_geometry_at(point: QPoint) -> tuple[QPoint, float]:
    # Walk Qt children so native click-through overlays cannot hide the target control.
    for window in QApplication.topLevelWidgets():
        if not window.isVisible() or window.testAttribute(Qt.WA_TransparentForMouseEvents):
            continue
        widget = window.childAt(window.mapFromGlobal(point)) or window
        while widget is not None:
            if isinstance(widget, (QAbstractButton, QComboBox)) and point == widget.mapToGlobal(
                widget.rect().center()
            ):
                center = widget.mapToGlobal(QPoint(widget.width() // 2, widget.height() // 2))
                diameter = max(0, min(64, widget.width() - 16, widget.height() - 16))
                return center, diameter
            widget = widget.parentWidget()
    return point, 64


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))
