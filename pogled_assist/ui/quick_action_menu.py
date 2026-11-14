"""Fullscreen quick-action menu: a 3x3 grid of upright targets around the chosen point."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyle, QWidget

from .. import diagnostics
from ..interaction.gaze_selection import (
    DEFAULT_SELECTION_PAUSE_MS,
    MAX_SELECTION_PAUSE_MS,
    MIN_SELECTION_PAUSE_MS,
    GazeSelectionTimer,
)
from ..interaction.mouse_controller import (
    DOUBLE_LEFT_CLICK,
    LEFT_CLICK,
    PRESS_ENTER,
    RIGHT_CLICK,
    SCROLL_DOWN,
    SCROLL_UP,
    TYPE_HERE,
    action_label,
)
from ..windows.windows_z_order import force_window_topmost

logger = logging.getLogger(__name__)

CANCEL_QUICK_ACTION = "cancel_quick_action"
TOPMOST_REFRESH_INTERVAL_MS = 33

TILE_WIDTH = 150
TILE_HEIGHT = 190
TILE_GAP = 12
SCREEN_MARGIN = 8
ICON_SIZE = 40
LABEL_PIXEL_SIZE = 20
TILE_RADIUS = 12
# The opaque panel keeps every tile edge visible over any application. Its frame equals
# the screen margin, so the panel never leaves the screen.
PANEL_FRAME = SCREEN_MARGIN
PANEL_COLOR = "#15191f"


@dataclass(frozen=True)
class QuickActionTile:
    action: str
    icon_name: str
    fallback: QStyle.StandardPixmap
    row: int
    column: int


# The centre cell (1, 1) is the chosen point and is never a target.
TILES = (
    QuickActionTile(
        TYPE_HERE, "fa5s.keyboard", QStyle.StandardPixmap.SP_FileDialogDetailedView, 0, 0
    ),
    QuickActionTile(LEFT_CLICK, "fa5s.mouse-pointer", QStyle.StandardPixmap.SP_ArrowForward, 0, 1),
    QuickActionTile(SCROLL_UP, "fa5s.arrow-up", QStyle.StandardPixmap.SP_ArrowUp, 0, 2),
    QuickActionTile(
        CANCEL_QUICK_ACTION, "fa5s.times", QStyle.StandardPixmap.SP_DialogCancelButton, 1, 0
    ),
    QuickActionTile(RIGHT_CLICK, "fa5s.mouse", QStyle.StandardPixmap.SP_DialogApplyButton, 1, 2),
    QuickActionTile(
        PRESS_ENTER, "fa5s.level-down-alt", QStyle.StandardPixmap.SP_DialogOkButton, 2, 0
    ),
    QuickActionTile(
        DOUBLE_LEFT_CLICK, "fa5s.hand-pointer", QStyle.StandardPixmap.SP_BrowserReload, 2, 1
    ),
    QuickActionTile(SCROLL_DOWN, "fa5s.arrow-down", QStyle.StandardPixmap.SP_ArrowDown, 2, 2),
)


class QuickActionMenu(QWidget):
    """Action picker around the chosen point, selected by gaze dwell or mouse click."""

    action_selected = Signal(str)
    selection_progress_changed = Signal(QPoint, float, str)
    selection_cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._center_global = QPoint(0, 0)
        self._grid_global = QRect()
        self._candidate_action: str | None = None
        self._selected_action: str | None = None
        self._candidate_progress = 0.0
        self._selection_timer = GazeSelectionTimer("quick_menu")
        self._selection_pause_ms = DEFAULT_SELECTION_PAUSE_MS
        self._selection_dwell_ms = 500
        self._selection_emitted = False
        self._blocked_action: str | None = None
        self._last_topmost_ms = 0.0
        self._icons = {tile.action: self._icon(tile) for tile in TILES}

        self.setWindowTitle("Brze radnje")
        self.setWindowFlags(_overlay_window_flags())
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.hide()

        self._timer = QTimer(self)
        self._timer.setInterval(TOPMOST_REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self._refresh_windows_topmost_due)
        self._return_timer = QTimer(self)
        self._return_timer.setSingleShot(True)
        # A coarse timer may fire early; the grid must not return inside the cooldown.
        self._return_timer.setTimerType(Qt.PreciseTimer)
        self._return_timer.timeout.connect(self._return_after_scroll)
        self._target_ready: Callable[[], bool] = lambda: True

    def set_selection_dwell_ms(self, dwell_ms: int) -> None:
        self._selection_dwell_ms = max(150, min(5000, int(dwell_ms)))

    def set_selection_settings(self, *, pause_ms: int, dwell_ms: int, radius_px: int) -> None:
        # The radius is unused: progress continues anywhere inside the same large tile.
        del radius_px
        self._selection_pause_ms = max(
            MIN_SELECTION_PAUSE_MS,
            min(MAX_SELECTION_PAUSE_MS, int(pause_ms)),
        )
        self.set_selection_dwell_ms(dwell_ms)

    def show_at(self, center: QPoint) -> None:
        screen = self.screen()
        if screen is None:
            from PySide6.QtGui import QGuiApplication

            screen = QGuiApplication.primaryScreen()

        geometry = screen.geometry()
        self._return_timer.stop()
        self.setGeometry(geometry)
        self._center_global = QPoint(center)
        self._grid_global = grid_rect_around(center, geometry)
        # Near a screen edge the point can lie on a tile; gaze must leave it before it counts.
        self._blocked_action = self._action_for_global_point(center)
        self._candidate_action = None
        self._selected_action = None
        self._candidate_progress = 0.0
        self._selection_timer.cancel(reason="context_changed")
        self._selection_emitted = False
        self._show_grid()
        logger.info("Quick action menu opened at %s,%s.", center.x(), center.y())

    def hide_for_repeat(self, delay_ms: int, target_ready: Callable[[], bool]) -> None:
        """Hide while a scroll reaches the window below, then show the same grid again.

        The grid returns after ``delay_ms`` only while ``target_ready()`` is true and nothing
        closed it. The selection timer still blocks the tile that fired, so gaze must leave
        that tile before it can repeat.
        """
        self._timer.stop()
        self.hide()
        self._selected_action = None
        self._candidate_progress = 0.0
        self._selection_emitted = False
        self._target_ready = target_ready
        self._return_timer.start(max(1, int(delay_ms)))

    def close_menu(self, *, reason: str = "window_closed") -> None:
        was_visible = self.isVisible() or self._return_timer.isActive()
        self._return_timer.stop()
        self._candidate_action = None
        self._selected_action = None
        self._candidate_progress = 0.0
        self._selection_timer.cancel(reason=reason)
        self._selection_emitted = False
        self._blocked_action = None
        self._last_topmost_ms = 0.0
        self._timer.stop()
        self.hide()
        if was_visible:
            logger.info("Quick action menu closed.")

    def _return_after_scroll(self) -> None:
        if not self._target_ready():
            self.close_menu(reason="target_cleared")
            return
        self._show_grid()
        logger.info("Quick action menu returned for another scroll.")

    def _show_grid(self) -> None:
        self._timer.start()
        self.show()
        self.raise_()
        self._refresh_windows_topmost(force=True)

    def tile_rect(self, action: str) -> QRect | None:
        """Global rectangle of an action's tile, or None for an unknown action."""
        tile = next((item for item in TILES if item.action == action), None)
        if tile is None:
            return None
        return _cell_rect(self._grid_global, tile.row, tile.column)

    def handle_gaze(self, point: QPoint) -> None:
        if not self.isVisible() or self._selection_emitted:
            return

        now_ms = time.monotonic() * 1000
        action = self._action_for_global_point(point)
        # Only a look at another tile or the empty centre releases the tile under the point.
        # Gaze clamped to the screen edge lands outside the grid and must not release it.
        if action != self._blocked_action and (
            action is not None or _cell_rect(self._grid_global, 1, 1).contains(point)
        ):
            self._blocked_action = None
        if action is None or action == self._blocked_action:
            self._reset_gaze_candidate(notify=True)
            self.update()
            return

        if action != self._candidate_action:
            self._candidate_action = action
            self._candidate_progress = 0.0
            self._selected_action = None
            self._selection_timer.update(
                action,
                now_ms,
                pause_ms=self._selection_pause_ms,
                dwell_ms=self._selection_dwell_ms,
                restart=True,
            )
            self.update()
            return

        update = self._selection_timer.update(
            action,
            now_ms,
            pause_ms=self._selection_pause_ms,
            dwell_ms=self._selection_dwell_ms,
        )
        if update.progress is None:
            self._selected_action = None
            self._candidate_progress = 0.0
            self.update()
            return

        self._selected_action = action
        self._candidate_progress = update.progress
        self.selection_progress_changed.emit(
            self._selection_center_global(action),
            self._candidate_progress,
            _menu_label(action),
        )

        if update.ready:
            self._selection_timer.complete()
            self._selection_emitted = True
            logger.info("Quick action gaze selected: %s", action)
            diagnostics.invoke_action(
                lambda: self.action_selected.emit(action),
                source="gaze",
                selection=self._selection_timer,
            )
            return

        self.update()

    def mousePressEvent(self, event) -> None:
        self._reset_gaze_candidate(notify=True, require_leave=True)
        local_point = event.position().toPoint() if hasattr(event, "position") else event.pos()
        action = self._action_for_global_point(self.mapToGlobal(local_point))
        # A click on the centre or outside the tiles closes the menu without an action.
        action = action or CANCEL_QUICK_ACTION
        logger.info("Quick action mouse selected: %s", action)
        diagnostics.invoke_action(
            lambda: self.action_selected.emit(action), source="mouse", action=action
        )

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
        painter.fillRect(self.rect(), QColor(10, 13, 18, 140))
        offset = self.mapToGlobal(QPoint(0, 0))
        grid = self._grid_global.translated(-offset)
        centre = _cell_rect(grid, 1, 1)
        # The centre cell stays open so the dimmed content around the chosen point shows.
        panel = QPainterPath()
        panel.addRoundedRect(
            QRectF(grid).adjusted(-PANEL_FRAME, -PANEL_FRAME, PANEL_FRAME, PANEL_FRAME),
            TILE_RADIUS + PANEL_FRAME,
            TILE_RADIUS + PANEL_FRAME,
        )
        opening = QPainterPath()
        opening.addRoundedRect(QRectF(centre), TILE_RADIUS, TILE_RADIUS)
        painter.fillPath(panel.subtracted(opening), QColor(PANEL_COLOR))

        painter.setFont(_label_font())
        for tile in TILES:
            self._paint_tile(painter, tile, _cell_rect(grid, tile.row, tile.column))

        painter.setPen(QPen(QColor(184, 197, 210, 115), 2, Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(centre).adjusted(1, 1, -1, -1), TILE_RADIUS, TILE_RADIUS)
        point = self._center_global - offset
        painter.setPen(QPen(QColor("#15191f"), 3))
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(point, 5, 5)

    def _paint_tile(self, painter: QPainter, tile: QuickActionTile, rect: QRect) -> None:
        selected = tile.action == self._selected_action
        cancel = tile.action == CANCEL_QUICK_ACTION
        # The white selected border changes each edge pixel by at least 3:1, and every
        # border stays at least 3:1 against its own fill.
        if selected:
            fill, border, width = "#2e6478", "#ffffff", 4
        elif cancel:
            fill, border, width = "#2b1f27", "#af7a86", 2
        else:
            fill, border, width = "#283442", "#71869b", 2
        inset = width / 2
        painter.setPen(QPen(QColor(border), width))
        painter.setBrush(QColor(fill))
        painter.drawRoundedRect(
            QRectF(rect).adjusted(inset, inset, -inset, -inset), TILE_RADIUS, TILE_RADIUS
        )

        icon_rect = _icon_rect(rect)
        self._icons[tile.action].paint(painter, icon_rect)
        if selected and self._candidate_progress > 0:
            ring = QRectF(icon_rect).adjusted(-10, -10, 10, 10)
            painter.setPen(QPen(QColor(255, 255, 255, 235), 5, Qt.SolidLine, Qt.RoundCap))
            painter.setBrush(Qt.NoBrush)
            painter.drawArc(ring, 90 * 16, int(-360 * 16 * self._candidate_progress))

        painter.setPen(QColor("#edf2f7"))
        painter.drawText(
            _label_rect(rect),
            Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
            _menu_label(tile.action),
        )

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

    def _action_for_global_point(self, point: QPoint) -> str | None:
        """Return the tile under ``point``; gaps belong to the nearest tile."""
        half_gap = TILE_GAP // 2
        for tile in TILES:
            cell = _cell_rect(self._grid_global, tile.row, tile.column)
            if cell.adjusted(-half_gap, -half_gap, half_gap, half_gap).contains(point):
                return tile.action
        return None

    def _reset_gaze_candidate(self, *, notify: bool, require_leave: bool = False) -> None:
        had_candidate = self._candidate_action is not None
        self._selection_timer.cancel(
            require_leave=require_leave,
            reason="mouse_intervention" if require_leave else "target_departure",
        )
        self._candidate_action = None
        self._selected_action = None
        self._candidate_progress = 0.0
        if notify and had_candidate:
            self.selection_cancelled.emit()

    def _selection_center_global(self, action: str) -> QPoint:
        # The shared selection ring surrounds the same icon as the tile's own arc.
        rect = self.tile_rect(action)
        return QPoint(self._center_global) if rect is None else _icon_rect(rect).center()

    def _icon(self, tile: QuickActionTile) -> QIcon:
        try:
            import qtawesome as qta

            color = "#fff1f2" if tile.action == CANCEL_QUICK_ACTION else "#ffffff"
            return qta.icon(tile.icon_name, color=color)
        except Exception:
            logger.exception("Could not load quick action icon %s; using fallback.", tile.icon_name)
            return self.style().standardIcon(tile.fallback)


def grid_rect_around(center: QPoint, bounds: QRect) -> QRect:
    """Centre the grid on ``center`` and shift it inside ``bounds`` near an edge."""
    width = 3 * TILE_WIDTH + 2 * TILE_GAP
    height = 3 * TILE_HEIGHT + 2 * TILE_GAP
    area = bounds.adjusted(SCREEN_MARGIN, SCREEN_MARGIN, -SCREEN_MARGIN, -SCREEN_MARGIN)
    left = center.x() - width // 2
    top = center.y() - height // 2
    left = max(area.left(), min(left, area.right() + 1 - width))
    top = max(area.top(), min(top, area.bottom() + 1 - height))
    return QRect(left, top, width, height)


def _icon_rect(tile: QRect) -> QRect:
    """The icon sits just above the tile centre, with the label below it."""
    return QRect(
        tile.center().x() - ICON_SIZE // 2, tile.center().y() - ICON_SIZE, ICON_SIZE, ICON_SIZE
    )


def _label_rect(tile: QRect) -> QRect:
    """Every label must fit on one line in this rectangle below the icon."""
    return QRect(tile.left() + 8, tile.center().y() + 12, tile.width() - 16, 48)


def _label_font() -> QFont:
    font = QFont("Segoe UI")
    font.setPixelSize(LABEL_PIXEL_SIZE)
    font.setBold(True)
    return font


def _cell_rect(grid: QRect, row: int, column: int) -> QRect:
    return QRect(
        grid.left() + column * (TILE_WIDTH + TILE_GAP),
        grid.top() + row * (TILE_HEIGHT + TILE_GAP),
        TILE_WIDTH,
        TILE_HEIGHT,
    )


def _menu_label(action: str) -> str:
    return "Odustani" if action == CANCEL_QUICK_ACTION else action_label(action)


def _overlay_window_flags() -> Qt.WindowFlags:
    flags = Qt.FramelessWindowHint | Qt.Window | Qt.WindowStaysOnTopHint
    no_focus = getattr(Qt, "WindowDoesNotAcceptFocus", None)
    if no_focus is None:
        no_focus = getattr(Qt.WindowType, "WindowDoesNotAcceptFocus", None)
    if no_focus is not None:
        flags |= no_focus
    return flags
