"""Zoomed precision target picker for quick actions."""

from __future__ import annotations

import logging
import math
import time

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from .windows_z_order import force_window_topmost

logger = logging.getLogger(__name__)
TOPMOST_REFRESH_INTERVAL_MS = 33


class QuickActionZoomWindow(QWidget):
    """Fullscreen overlay that magnifies a target area before quick actions."""

    target_selected = Signal(QPoint)
    cancelled = Signal()
    selection_progress_changed = Signal(QPoint, float, str)
    selection_cancelled = Signal()

    SOURCE_SIZE = 180
    DISPLAY_SIZE = 540
    OPEN_GAZE_GRACE_MS = 220

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._screen_geometry = QRect()
        self._source_rect = QRect()
        self._display_rect = QRect()
        self._pixmap = QPixmap()
        self._candidate_anchor: QPoint | None = None
        self._candidate_started_ms = 0.0
        self._candidate_progress = 0.0
        self._candidate_local: QPoint | None = None
        self._selection_dwell_ms = 500
        self._selection_radius_px = 48
        self._opened_ms = 0.0
        self._selection_emitted = False
        self._phase = 0.0
        self._last_topmost_ms = 0.0

        self.setWindowTitle("Quick Action Zoom")
        self.setWindowFlags(_overlay_window_flags())
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.hide()

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    def set_selection_settings(self, *, dwell_ms: int, radius_px: int) -> None:
        self._selection_dwell_ms = max(150, min(5000, int(dwell_ms)))
        self._selection_radius_px = max(16, min(160, int(radius_px)))

    def show_at(self, target: QPoint) -> None:
        screen = QGuiApplication.primaryScreen()
        geometry = screen.geometry()
        self._screen_geometry = QRect(geometry)
        self._source_rect = _square_around(target, self.SOURCE_SIZE, geometry)
        self._display_rect = _centered_square(geometry, self.DISPLAY_SIZE)
        self._pixmap = screen.grabWindow(
            0,
            self._source_rect.x(),
            self._source_rect.y(),
            self._source_rect.width(),
            self._source_rect.height(),
        )
        self.setGeometry(geometry)
        self._candidate_anchor = None
        self._candidate_started_ms = 0.0
        self._candidate_progress = 0.0
        self._candidate_local = None
        self._opened_ms = time.monotonic() * 1000
        self._selection_emitted = False
        self._timer.start()
        self.show()
        self.raise_()
        self._refresh_windows_topmost(force=True)
        logger.info(
            "Quick action zoom opened: target=%s,%s source=%s,%s %sx%s display=%s,%s %sx%s.",
            target.x(),
            target.y(),
            self._source_rect.x(),
            self._source_rect.y(),
            self._source_rect.width(),
            self._source_rect.height(),
            self._display_rect.x(),
            self._display_rect.y(),
            self._display_rect.width(),
            self._display_rect.height(),
        )

    def close_zoom(self) -> None:
        self._timer.stop()
        self._candidate_anchor = None
        self._candidate_started_ms = 0.0
        self._candidate_progress = 0.0
        self._candidate_local = None
        self._selection_emitted = False
        self._last_topmost_ms = 0.0
        self.hide()
        logger.info("Quick action zoom closed.")

    def handle_gaze(self, point: QPoint) -> None:
        if not self.isVisible() or self._selection_emitted:
            return

        now_ms = time.monotonic() * 1000
        if now_ms - self._opened_ms < self.OPEN_GAZE_GRACE_MS:
            return

        local = QPoint(
            point.x() - self._screen_geometry.left(),
            point.y() - self._screen_geometry.top(),
        )
        if not self._display_rect.contains(local):
            self._reset_gaze_candidate(notify=True)
            self.update()
            return

        if (
            self._candidate_anchor is None
            or _distance(self._candidate_anchor, point) > self._selection_radius_px
        ):
            self._candidate_anchor = QPoint(point)
            self._candidate_local = QPoint(local)
            self._candidate_started_ms = now_ms
            self._candidate_progress = 0.0
            self.selection_progress_changed.emit(QPoint(point), 0.0, "Zoom target")
            self.update()
            return

        self._candidate_local = QPoint(local)
        self._candidate_progress = min(
            1.0,
            (now_ms - self._candidate_started_ms) / max(1, self._selection_dwell_ms),
        )
        self.selection_progress_changed.emit(QPoint(point), self._candidate_progress, "Zoom target")

        if self._candidate_progress >= 1.0:
            selected = self._map_display_to_screen(local)
            self._selection_emitted = True
            logger.info(
                "Quick action zoom selected: display=%s,%s screen=%s,%s.",
                local.x(),
                local.y(),
                selected.x(),
                selected.y(),
            )
            self.target_selected.emit(selected)
            return

        self.update()

    def mousePressEvent(self, event) -> None:
        local = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if self._display_rect.contains(local):
            selected = self._map_display_to_screen(local)
            logger.info("Quick action zoom mouse selected: %s,%s.", selected.x(), selected.y())
            self.target_selected.emit(selected)
            return

        logger.info("Quick action zoom cancelled by mouse outside zoom square.")
        self.cancelled.emit()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            logger.info("Quick action zoom cancelled by Escape.")
            self.cancelled.emit()
            return

        super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:
        if not self.isVisible():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 116))

        shadow_rect = QRect(self._display_rect).adjusted(-10, -10, 10, 10)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 130))
        painter.drawRoundedRect(shadow_rect, 12, 12)

        if not self._pixmap.isNull():
            painter.drawPixmap(self._display_rect, self._pixmap)
        else:
            painter.fillRect(self._display_rect, QColor(20, 24, 31, 240))

        pulse = (math.sin(self._phase) + 1.0) / 2.0
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 235), 4))
        painter.drawRect(self._display_rect)
        painter.setPen(QPen(QColor(96, 165, 250, 210), 2 + int(2 * pulse)))
        painter.drawRect(self._display_rect.adjusted(8, 8, -8, -8))

        center = self._candidate_local or self._display_rect.center()
        if self._display_rect.contains(center):
            self._draw_crosshair(painter, center)

    def _draw_crosshair(self, painter: QPainter, center: QPoint) -> None:
        pulse = (math.sin(self._phase) + 1.0) / 2.0
        radius = 18 + int(4 * pulse)
        painter.setPen(QPen(QColor(15, 23, 42, 210), 6, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(center.x() - 28, center.y(), center.x() - 8, center.y())
        painter.drawLine(center.x() + 8, center.y(), center.x() + 28, center.y())
        painter.drawLine(center.x(), center.y() - 28, center.x(), center.y() - 8)
        painter.drawLine(center.x(), center.y() + 8, center.x(), center.y() + 28)
        painter.setPen(QPen(QColor(255, 255, 255, 235), 2, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(center.x() - 28, center.y(), center.x() - 8, center.y())
        painter.drawLine(center.x() + 8, center.y(), center.x() + 28, center.y())
        painter.drawLine(center.x(), center.y() - 28, center.x(), center.y() - 8)
        painter.drawLine(center.x(), center.y() + 8, center.x(), center.y() + 28)

        painter.setPen(QPen(QColor(34, 197, 94, 235), 3))
        painter.drawEllipse(center, radius, radius)
        if self._candidate_progress > 0:
            painter.setPen(QPen(QColor(250, 204, 21, 245), 5, Qt.SolidLine, Qt.RoundCap))
            progress_rect = QRectF(
                center.x() - radius - 8,
                center.y() - radius - 8,
                (radius + 8) * 2,
                (radius + 8) * 2,
            )
            painter.drawArc(progress_rect, 90 * 16, int(-360 * 16 * self._candidate_progress))

    def _map_display_to_screen(self, local: QPoint) -> QPoint:
        x_ratio = (local.x() - self._display_rect.left()) / max(1, self._display_rect.width() - 1)
        y_ratio = (local.y() - self._display_rect.top()) / max(1, self._display_rect.height() - 1)
        x = round(self._source_rect.left() + x_ratio * max(1, self._source_rect.width() - 1))
        y = round(self._source_rect.top() + y_ratio * max(1, self._source_rect.height() - 1))
        return QPoint(
            max(self._source_rect.left(), min(self._source_rect.right(), x)),
            max(self._source_rect.top(), min(self._source_rect.bottom(), y)),
        )

    def _reset_gaze_candidate(self, *, notify: bool) -> None:
        had_candidate = self._candidate_anchor is not None
        self._candidate_anchor = None
        self._candidate_started_ms = 0.0
        self._candidate_progress = 0.0
        self._candidate_local = None
        if notify and had_candidate:
            self.selection_cancelled.emit()

    def _tick(self) -> None:
        self._phase += 0.24
        self._refresh_windows_topmost_due()
        self.update()

    def _refresh_windows_topmost_due(self) -> None:
        if not self.isVisible():
            return

        now_ms = time.monotonic() * 1000
        if now_ms - self._last_topmost_ms >= TOPMOST_REFRESH_INTERVAL_MS:
            self._refresh_windows_topmost(now_ms=now_ms)

    def _refresh_windows_topmost(
        self,
        *,
        force: bool = False,
        now_ms: float | None = None,
    ) -> None:
        if not force and not self.isVisible():
            return

        force_window_topmost(self, show=True, aggressive=True)
        self._last_topmost_ms = now_ms if now_ms is not None else time.monotonic() * 1000


def _square_around(center: QPoint, size: int, bounds: QRect) -> QRect:
    size = max(40, min(size, bounds.width(), bounds.height()))
    half = size // 2
    x = center.x() - half
    y = center.y() - half
    x = max(bounds.left(), min(bounds.right() - size + 1, x))
    y = max(bounds.top(), min(bounds.bottom() - size + 1, y))
    return QRect(x, y, size, size)


def _centered_square(bounds: QRect, preferred_size: int) -> QRect:
    available = max(80, min(bounds.width(), bounds.height()) - 48)
    size = max(80, min(preferred_size, available))
    x = bounds.left() + (bounds.width() - size) // 2
    y = bounds.top() + (bounds.height() - size) // 2
    return QRect(x - bounds.left(), y - bounds.top(), size, size)


def _distance(first: QPoint, second: QPoint) -> float:
    return math.hypot(first.x() - second.x(), first.y() - second.y())


def _overlay_window_flags() -> Qt.WindowFlags:
    flags = Qt.FramelessWindowHint | Qt.Window | Qt.WindowStaysOnTopHint
    no_focus = getattr(Qt, "WindowDoesNotAcceptFocus", None)
    if no_focus is None:
        no_focus = getattr(Qt.WindowType, "WindowDoesNotAcceptFocus", None)
    if no_focus is not None:
        flags |= no_focus
    return flags
