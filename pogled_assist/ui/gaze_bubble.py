"""Transparent gaze position marker overlay."""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .. import diagnostics
from ..tracking.gaze_provider import GAZE_DELIVERY_GAP_SECONDS
from .overlay_window import TOPMOST_REFRESH_INTERVAL_MS, OverlayStacking, overlay_window_flags

logger = logging.getLogger(__name__)

MIN_MOVE_INTERVAL_MS = 20
MIN_MOVE_DISTANCE_PX = 2


class GazeBubbleWindow(QWidget):
    """Small click-through overlay that follows the latest gaze point."""

    BUBBLE_SIZE = 46

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._enabled = True
        self._last_point: QPoint | None = None
        self._last_moved_point: QPoint | None = None
        self._last_move_ms = 0.0
        self._last_gaze_ms = 0.0
        self._last_raise_ms = 0.0
        self._stacking = OverlayStacking(self)
        self._diagnostic_gaze_at: float | None = None
        self._diagnostic_hide_reason = "hidden_or_closed"
        self._diagnostic_metrics = diagnostics.StreamMetrics(event_name="marker_summary")
        self._topmost_timer = QTimer(self)
        self._topmost_timer.setInterval(TOPMOST_REFRESH_INTERVAL_MS)
        self._topmost_timer.timeout.connect(self._refresh_windows_topmost)

        self.setWindowTitle("Oznaka pogleda")
        self.setWindowFlags(overlay_window_flags(click_through=True))
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(self.BUBBLE_SIZE, self.BUBBLE_SIZE)
        self.hide()

    def set_enabled(self, enabled: bool) -> None:
        if self._enabled == enabled:
            return

        self._enabled = enabled
        logger.info("Gaze bubble %s.", "enabled" if enabled else "disabled")
        if not enabled:
            self.clear(reason="disabled")
            return

        if self._last_point is not None and self._gaze_is_fresh():
            self._move_center_to(self._last_point)
            self._last_moved_point = QPoint(self._last_point)
            self._last_move_ms = time.monotonic() * 1000
            self._show_without_focus()
        else:
            self.clear(reason="no_fresh_gaze")

    def clear(self, *, reason: str = "input_invalidated") -> None:
        self._diagnostic_hide_reason = reason
        self._topmost_timer.stop()
        self._last_point = None
        self._last_moved_point = None
        self.hide()

    def handle_gaze(self, point: QPoint) -> None:
        self._diagnostic_gaze_at = time.monotonic()
        self._diagnostic_metrics.summary(event_name="marker_summary")
        self._last_point = QPoint(point)
        self._last_gaze_ms = time.monotonic() * 1000
        if not self._enabled:
            return

        now_ms = time.monotonic() * 1000
        if self.isVisible() and not self._move_due(point, now_ms):
            return

        self._move_center_to(point)
        self._last_moved_point = QPoint(point)
        self._last_move_ms = now_ms
        if not self.isVisible() or self._raise_due():
            self._show_without_focus()

    def showEvent(self, event) -> None:
        self._diagnostic_hide_reason = "hidden_or_closed"
        super().showEvent(event)
        self._observe_visibility(True, "shown")

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._observe_visibility(False, self._diagnostic_hide_reason)

    def _observe_visibility(self, visible: bool, reason: str) -> None:
        self._diagnostic_metrics.event(
            "marker_visibility",
            visible=visible,
            reason=reason,
            gaze_age_ms=(time.monotonic() - self._diagnostic_gaze_at) * 1000
            if self._diagnostic_gaze_at is not None
            else None,
        )

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = QRectF(self.rect())
        ring = rect.adjusted(3, 3, -3, -3)

        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(11, 23, 35, 190), 4.5))
        painter.drawEllipse(ring)
        painter.setPen(QPen(QColor(132, 197, 217, 240), 2.5))
        painter.drawEllipse(ring)

        painter.setPen(QPen(QColor(11, 23, 35, 220), 1.5))
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.drawEllipse(rect.center(), 3, 3)

    def _move_center_to(self, point: QPoint) -> None:
        self.move(point.x() - self.width() // 2, point.y() - self.height() // 2)

    def _move_due(self, point: QPoint, now_ms: float) -> bool:
        if self._last_moved_point is None:
            return True

        distance = abs(point.x() - self._last_moved_point.x()) + abs(
            point.y() - self._last_moved_point.y()
        )
        if distance >= MIN_MOVE_DISTANCE_PX:
            return True

        return now_ms - self._last_move_ms >= MIN_MOVE_INTERVAL_MS

    def _show_without_focus(self) -> None:
        self.show()
        self._stacking.apply_click_through()
        self.raise_()
        self._refresh_windows_topmost()
        if not self._topmost_timer.isActive():
            self._topmost_timer.start()
        self._last_raise_ms = time.monotonic() * 1000

    def _raise_due(self) -> bool:
        return time.monotonic() * 1000 - self._last_raise_ms >= 250

    def _refresh_windows_topmost(self) -> None:
        if not self.isVisible():
            self._topmost_timer.stop()
            return

        if not self._gaze_is_fresh():
            self.clear(reason="gaze_stale")
            return

        self._stacking.refresh()

    def _gaze_is_fresh(self) -> bool:
        return time.monotonic() * 1000 - self._last_gaze_ms < GAZE_DELIVERY_GAP_SECONDS * 1000
