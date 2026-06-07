"""Fullscreen radial quick-action menu."""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QStyle, QWidget

from .mouse_controller import DOUBLE_LEFT_CLICK, LEFT_CLICK, RIGHT_CLICK
from .windows_z_order import force_window_topmost


logger = logging.getLogger(__name__)

CANCEL_QUICK_ACTION = "cancel_quick_action"
TOPMOST_REFRESH_INTERVAL_MS = 33


@dataclass(frozen=True)
class QuickActionSector:
    action: str
    icon_name: str
    fallback: QStyle.StandardPixmap
    center_degrees: float
    color: QColor


SECTORS = (
    QuickActionSector(
        action=LEFT_CLICK,
        icon_name="fa5s.mouse-pointer",
        fallback=QStyle.StandardPixmap.SP_ArrowForward,
        center_degrees=270.0,
        color=QColor(20, 184, 166, 126),
    ),
    QuickActionSector(
        action=RIGHT_CLICK,
        icon_name="fa5s.mouse",
        fallback=QStyle.StandardPixmap.SP_DialogApplyButton,
        center_degrees=0.0,
        color=QColor(59, 130, 246, 126),
    ),
    QuickActionSector(
        action=DOUBLE_LEFT_CLICK,
        icon_name="fa5s.hand-pointer",
        fallback=QStyle.StandardPixmap.SP_BrowserReload,
        center_degrees=90.0,
        color=QColor(168, 85, 247, 126),
    ),
    QuickActionSector(
        action=CANCEL_QUICK_ACTION,
        icon_name="fa5s.times",
        fallback=QStyle.StandardPixmap.SP_DialogCancelButton,
        center_degrees=180.0,
        color=QColor(239, 68, 68, 126),
    ),
)


class QuickActionRadialMenu(QWidget):
    """Icon-only radial action picker selected by gaze dwell angle or mouse click."""

    action_selected = Signal(str)
    selection_progress_changed = Signal(QPoint, float, str)
    selection_cancelled = Signal()

    MENU_RADIUS = 124
    INNER_RADIUS = 54
    OPEN_GAZE_GRACE_MS = 180

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._center_global = QPoint(0, 0)
        self._center_local = QPoint(0, 0)
        self._candidate_action: str | None = None
        self._candidate_anchor: QPoint | None = None
        self._selected_action: str | None = None
        self._candidate_started_ms = 0.0
        self._candidate_progress = 0.0
        self._selection_dwell_ms = 500
        self._selection_radius_px = 48
        self._opened_ms = 0.0
        self._selection_emitted = False
        self._phase = 0.0
        self._last_topmost_ms = 0.0
        self._icons = {sector.action: self._icon(sector) for sector in SECTORS}

        self.setWindowTitle("Quick Actions")
        self.setWindowFlags(_overlay_window_flags())
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.hide()

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    def set_selection_dwell_ms(self, dwell_ms: int) -> None:
        self._selection_dwell_ms = max(150, min(5000, int(dwell_ms)))

    def set_selection_settings(self, *, dwell_ms: int, radius_px: int) -> None:
        self.set_selection_dwell_ms(dwell_ms)
        self._selection_radius_px = max(16, min(160, int(radius_px)))

    def show_at(self, center: QPoint) -> None:
        screen = self.screen()
        if screen is None:
            from PySide6.QtGui import QGuiApplication

            screen = QGuiApplication.primaryScreen()

        geometry = screen.geometry()
        self.setGeometry(geometry)
        self._center_global = QPoint(center)
        self._center_local = QPoint(center.x() - geometry.left(), center.y() - geometry.top())
        self._candidate_action = None
        self._candidate_anchor = None
        self._selected_action = None
        self._candidate_started_ms = 0.0
        self._candidate_progress = 0.0
        self._opened_ms = time.monotonic() * 1000
        self._selection_emitted = False
        self._timer.start()
        self.show()
        self.raise_()
        self._refresh_windows_topmost(force=True)
        logger.info("Quick action radial menu opened at %s,%s.", center.x(), center.y())

    def close_menu(self) -> None:
        self._candidate_action = None
        self._candidate_anchor = None
        self._selected_action = None
        self._candidate_started_ms = 0.0
        self._candidate_progress = 0.0
        self._selection_emitted = False
        self._last_topmost_ms = 0.0
        self._timer.stop()
        self.hide()
        logger.info("Quick action radial menu closed.")

    def handle_gaze(self, point: QPoint) -> None:
        if not self.isVisible() or self._selection_emitted:
            return

        now_ms = time.monotonic() * 1000
        if now_ms - self._opened_ms < self.OPEN_GAZE_GRACE_MS:
            return

        action = self._action_for_global_point(point)
        if action is None:
            self._reset_gaze_candidate(notify=True)
            self.update()
            return

        self._selected_action = action
        if (
            action != self._candidate_action
            or self._candidate_anchor is None
            or _distance(self._candidate_anchor, point) > self._selection_radius_px
        ):
            self._candidate_action = action
            self._candidate_anchor = QPoint(point)
            self._candidate_started_ms = now_ms
            self._candidate_progress = 0.0
            self.selection_progress_changed.emit(
                self._selection_center_global(action),
                0.0,
                _action_label(action),
            )
            self.update()
            return

        self._candidate_progress = min(
            1.0,
            (now_ms - self._candidate_started_ms) / max(1, self._selection_dwell_ms),
        )
        self.selection_progress_changed.emit(
            self._selection_center_global(action),
            self._candidate_progress,
            _action_label(action),
        )

        if self._candidate_progress >= 1.0:
            self._selection_emitted = True
            logger.info("Quick action radial gaze selected: %s", action)
            self.action_selected.emit(action)
            return

        self.update()

    def mousePressEvent(self, event) -> None:
        local_point = event.position().toPoint() if hasattr(event, "position") else event.pos()
        action = self._action_for_global_point(self.mapToGlobal(local_point), allow_center=True)
        if action is not None:
            logger.info("Quick action radial mouse selected: %s", action)
            self.action_selected.emit(action)
            return

        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.action_selected.emit(CANCEL_QUICK_ACTION)
            return

        super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:
        if not self.isVisible():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 42))

        pulse = (math.sin(self._phase) + 1.0) / 2.0
        center = self._center_local
        radius = self.MENU_RADIUS
        inner_radius = self.INNER_RADIUS

        painter.setPen(Qt.NoPen)
        for sector in SECTORS:
            selected = sector.action == self._selected_action
            color = QColor(sector.color)
            color.setAlpha(186 if selected else 118)
            painter.setBrush(color)
            painter.drawPolygon(_sector_polygon(center, radius, sector.center_degrees - 45, sector.center_degrees + 45))

            if selected:
                painter.setPen(QPen(QColor(255, 255, 255, 220), 4 + int(2 * pulse)))
                painter.setBrush(Qt.NoBrush)
                painter.drawArc(
                    QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2),
                    int((360 - (sector.center_degrees + 45)) * 16),
                    int(90 * 16),
                )
                painter.setPen(Qt.NoPen)

            icon_rect = _icon_rect(center, sector.center_degrees, radius)
            self._icons[sector.action].paint(painter, icon_rect)
            if selected and self._candidate_progress > 0:
                progress_rect = QRectF(icon_rect).adjusted(-8, -8, 8, 8)
                painter.setPen(QPen(QColor(255, 255, 255, 235), 5, Qt.SolidLine, Qt.RoundCap))
                painter.setBrush(Qt.NoBrush)
                painter.drawArc(progress_rect, 90 * 16, int(-360 * 16 * self._candidate_progress))
                painter.setPen(Qt.NoPen)

        painter.setPen(QPen(QColor(255, 255, 255, 215), 3))
        painter.setBrush(QColor(15, 23, 42, 210))
        painter.drawEllipse(center, inner_radius, inner_radius)
        painter.setPen(QPen(QColor(255, 255, 255, 120), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(center, radius, radius)

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

    def _action_for_global_point(self, point: QPoint, *, allow_center: bool = False) -> str | None:
        dx = point.x() - self._center_global.x()
        dy = point.y() - self._center_global.y()
        distance = math.hypot(dx, dy)
        if distance < self.INNER_RADIUS and not allow_center:
            return None

        if distance < 1:
            return CANCEL_QUICK_ACTION

        angle = (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0
        if 225 <= angle < 315:
            return LEFT_CLICK
        if angle >= 315 or angle < 45:
            return RIGHT_CLICK
        if 45 <= angle < 135:
            return DOUBLE_LEFT_CLICK
        return CANCEL_QUICK_ACTION

    def _reset_gaze_candidate(self, *, notify: bool) -> None:
        had_candidate = self._candidate_action is not None
        self._candidate_action = None
        self._candidate_anchor = None
        self._selected_action = None
        self._candidate_started_ms = 0.0
        self._candidate_progress = 0.0
        if notify and had_candidate:
            self.selection_cancelled.emit()

    def _selection_center_global(self, action: str) -> QPoint:
        sector = next((item for item in SECTORS if item.action == action), None)
        if sector is None:
            return QPoint(self._center_global)

        radians = math.radians(sector.center_degrees)
        return QPoint(
            int(round(self._center_global.x() + math.cos(radians) * self.MENU_RADIUS * 0.58)),
            int(round(self._center_global.y() + math.sin(radians) * self.MENU_RADIUS * 0.58)),
        )

    def _icon(self, sector: QuickActionSector) -> QIcon:
        try:
            import qtawesome as qta

            color = "#ffffff" if sector.action != CANCEL_QUICK_ACTION else "#fff1f2"
            return qta.icon(sector.icon_name, color=color)
        except Exception:
            logger.exception("Could not load quick action icon %s; using fallback.", sector.icon_name)
            return self.style().standardIcon(sector.fallback)


def _sector_polygon(center: QPoint, radius: int, start_degrees: float, end_degrees: float) -> QPolygonF:
    path = QPainterPath()
    path.moveTo(center)
    steps = 18
    for index in range(steps + 1):
        degrees = start_degrees + (end_degrees - start_degrees) * index / steps
        radians = math.radians(degrees)
        path.lineTo(center.x() + math.cos(radians) * radius, center.y() + math.sin(radians) * radius)
    path.closeSubpath()
    return path.toFillPolygon()


def _icon_rect(center: QPoint, degrees: float, radius: int) -> QRect:
    radians = math.radians(degrees)
    icon_center = QPoint(
        int(round(center.x() + math.cos(radians) * radius * 0.58)),
        int(round(center.y() + math.sin(radians) * radius * 0.58)),
    )
    size = 38
    return QRect(icon_center.x() - size // 2, icon_center.y() - size // 2, size, size)


def _distance(first: QPoint, second: QPoint) -> float:
    return math.hypot(first.x() - second.x(), first.y() - second.y())


def _action_label(action: str) -> str:
    labels = {
        LEFT_CLICK: "Left click",
        RIGHT_CLICK: "Right click",
        DOUBLE_LEFT_CLICK: "Double click",
        CANCEL_QUICK_ACTION: "Cancel",
    }
    return labels.get(action, "Quick")


def _overlay_window_flags() -> Qt.WindowFlags:
    flags = Qt.FramelessWindowHint | Qt.Window | Qt.WindowStaysOnTopHint
    no_focus = getattr(Qt, "WindowDoesNotAcceptFocus", None)
    if no_focus is None:
        no_focus = getattr(Qt.WindowType, "WindowDoesNotAcceptFocus", None)
    if no_focus is not None:
        flags |= no_focus
    return flags
