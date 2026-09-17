"""Gaze-to-mouse movement and dwell-click behavior."""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QPoint, Signal
from PySide6.QtGui import QGuiApplication

from .gaze_selection import DEFAULT_SELECTION_PAUSE_MS, GazeSelectionTimer
from .windows_input import WindowsInputController

logger = logging.getLogger(__name__)

LEFT_CLICK = "left_click"
RIGHT_CLICK = "right_click"
DOUBLE_LEFT_CLICK = "double_left_click"
SPEECH = "speech"
KEYBOARD = "keyboard"
CONTROLLER = "controller"
SETTINGS = "settings"
HIDE_HOTBAR = "hide_hotbar"
SHOW_HOTBAR = "show_hotbar"
QUICK_ACTIONS = "quick_actions"

CLICK_ACTIONS = {LEFT_CLICK, RIGHT_CLICK, DOUBLE_LEFT_CLICK}
MIN_CURSOR_MOVE_DISTANCE_PX = 1.0
MOUSE_ERROR_LOG_INTERVAL_MS = 1000


@dataclass
class GazeSettings:
    smoothing: float = 1.0
    selection_pause_ms: int = DEFAULT_SELECTION_PAUSE_MS
    dwell_ms: int = 500
    dwell_radius_px: int = 48
    click_cooldown_ms: int = 350
    move_mouse: bool = True
    show_gaze_bubble: bool = True
    show_interaction_overlay: bool = True
    use_precision_zoom: bool = True
    start_with_windows: bool = False
    logging_enabled: bool = True
    show_launcher_window: bool = False


@dataclass(frozen=True)
class GazeScreenPoint:
    logical: QPoint
    physical: QPoint


class GazeMouseController(QObject):
    """Move the cursor with gaze and fire toolbar or click dwell actions."""

    gaze_position_changed = Signal(QPoint)
    mode_changed = Signal(object)
    toolbar_action_requested = Signal(str)
    toolbar_gaze_target_changed = Signal(object)
    quick_actions_mode_changed = Signal(bool)
    quick_action_zoom_requested = Signal(QPoint)
    quick_action_menu_requested = Signal(QPoint)
    click_zoom_requested = Signal(QPoint)
    interaction_progress_changed = Signal(QPoint, float, str)
    interaction_finished = Signal(QPoint, str)
    interaction_cancelled = Signal()
    action_fired = Signal(str, QPoint)
    status_changed = Signal(str)

    def __init__(
        self,
        toolbar_action_at: Callable[[QPoint], str | None],
        toolbar_action_center: Callable[[str, QPoint], QPoint | None],
        toolbar_contains: Callable[[QPoint], bool],
        parent: QObject | None = None,
        *,
        pointer_movement_enabled: bool = True,
    ) -> None:
        super().__init__(parent)
        self.settings = GazeSettings()
        self.active_mode: str | None = None
        self.quick_actions_enabled = False
        self._toolbar_action_at = toolbar_action_at
        self._toolbar_action_center = toolbar_action_center
        self._toolbar_contains = toolbar_contains
        self._pointer_movement_enabled = pointer_movement_enabled
        self._input: WindowsInputController | None = None
        self._smooth_physical_point: QPoint | None = None
        self._toolbar_gaze_target: str | None = None
        self._toolbar_selection = GazeSelectionTimer()
        self._target_anchor: QPoint | None = None
        self._target_selection = GazeSelectionTimer()
        self._quick_anchor: GazeScreenPoint | None = None
        self._quick_selection = GazeSelectionTimer()
        self._quick_target: GazeScreenPoint | None = None
        self._quick_menu_open = False
        self._click_zoom_open = False
        self._pending_zoom_click_mode: str | None = None
        self._native_menu_click_pending = False
        self._last_toolbar_ms = 0.0
        self._last_click_ms = 0.0
        self._pause_until_ms = 0.0
        self._logical_screen_rect: tuple[int, int, int, int] | None = None
        self._physical_screen_rect: tuple[int, int, int, int] | None = None
        self._last_cursor_point: QPoint | None = None
        self._last_mouse_error_ms = 0.0
        self._interaction_source: str | None = None
        self._both_eyes_open = False

    def start(self) -> None:
        logger.info("Starting mouse controller.")
        try:
            self._input = WindowsInputController()
            rect = self._input.primary_screen_rect()
            self._physical_screen_rect = (rect.left, rect.top, rect.width, rect.height)
            self._logical_screen_rect = _read_primary_screen_geometry()
        except Exception:
            logger.exception("Windows input backend failed.")
            self.status_changed.emit("Pomjeranje pokazivača nije dostupno.")
            return

        logger.info("Mouse controller ready with Windows user32 input backend.")
        self._log_screen_mapping()
        self.status_changed.emit("Upravljanje pokazivačem je spremno.")

    def set_mode(self, mode: str | None) -> None:
        if mode is not None and mode not in CLICK_ACTIONS:
            logger.warning("Ignoring unsupported mouse mode: %s", mode)
            return

        if mode is not None and self.quick_actions_enabled:
            self.set_quick_actions_enabled(False)

        if mode != self.active_mode:
            self._cancel_zoomed_click_state()
        if mode != LEFT_CLICK:
            self._native_menu_click_pending = False

        self.active_mode = mode
        self._reset_target_dwell()
        self.mode_changed.emit(mode)
        logger.info("Mouse action mode changed to: %s", mode or "none")

        if mode == LEFT_CLICK:
            self.status_changed.emit("Lijevi klik je spreman. Pogledajte željeni cilj.")
        elif mode == RIGHT_CLICK:
            self.status_changed.emit("Desni klik je spreman. Pogledajte željeni cilj.")
        elif mode == DOUBLE_LEFT_CLICK:
            self.status_changed.emit("Dvostruki klik je spreman. Pogledajte željeni cilj.")
        else:
            self.status_changed.emit("Nijedna radnja klika nije odabrana.")

    def set_quick_actions_enabled(self, enabled: bool) -> None:
        if self.quick_actions_enabled == enabled:
            return

        self.quick_actions_enabled = enabled
        self._reset_quick_dwell()
        if enabled:
            self.set_mode(None)
            self.status_changed.emit("Brze radnje su uključene. Pogledajte željeni cilj.")
        else:
            self.cancel_quick_action_menu()
            self.status_changed.emit("Brze radnje su isključene.")

        self.quick_actions_mode_changed.emit(enabled)
        logger.info("Quick actions mode changed to: %s", enabled)

    def execute_quick_action(self, action: str) -> None:
        if action not in CLICK_ACTIONS:
            self.cancel_quick_action_menu()
            self.status_changed.emit("Brza radnja je otkazana.")
            return

        target = self._quick_target
        self._quick_menu_open = False
        self._quick_target = None
        self._reset_quick_dwell()
        if target is None:
            logger.warning("Quick action %s ignored because no target is stored.", action)
            self.status_changed.emit("Brza radnja je preskočena jer cilj nije odabran.")
            return

        now_ms = time.monotonic() * 1000
        if now_ms - self._last_click_ms < self.settings.click_cooldown_ms:
            logger.info("Quick action skipped during click cooldown.")
            self.status_changed.emit("Brza radnja je preskočena tokom pauze između radnji.")
            return

        self._last_click_ms = now_ms
        self._pause_until_ms = now_ms + self.settings.click_cooldown_ms
        logger.info(
            "Quick action selected: %s at logical=%s,%s physical=%s,%s.",
            action,
            target.logical.x(),
            target.logical.y(),
            target.physical.x(),
            target.physical.y(),
        )
        self._fire_click(action, target, reset_mode=False, interaction_source="quick")

    def set_quick_target_from_logical(self, logical: QPoint) -> None:
        target = self._screen_point_from_logical(logical)
        self._quick_target = target
        self._quick_menu_open = True
        logger.info(
            "Quick action refined target set: logical=%s,%s physical=%s,%s.",
            target.logical.x(),
            target.logical.y(),
            target.physical.x(),
            target.physical.y(),
        )

    def cancel_quick_action_menu(self) -> None:
        self._quick_menu_open = False
        self._quick_target = None
        self._reset_quick_dwell()

    def cancel_toolbar_interaction(self, *, require_leave: bool = False) -> None:
        self._toolbar_selection.cancel(require_leave=require_leave)
        self._cancel_interaction("toolbar")
        self._set_toolbar_gaze_target(None)

    def cancel_gaze_interactions_for_mouse(self) -> None:
        self.cancel_toolbar_interaction(require_leave=True)
        self._target_selection.cancel(require_leave=True)
        self._quick_selection.cancel(require_leave=True)
        self._cancel_interaction("target")
        self._cancel_interaction("quick")

    def execute_zoomed_click(self, logical: QPoint) -> None:
        mode = self._pending_zoom_click_mode
        if mode not in CLICK_ACTIONS:
            logger.warning("Zoomed click ignored because no click mode is pending.")
            self._cancel_zoomed_click_state()
            self.status_changed.emit("Uvećani klik je preskočen jer nema odabrane radnje.")
            return

        target = self._screen_point_from_logical(logical)
        self._cancel_zoomed_click_state()
        now_ms = time.monotonic() * 1000
        self._last_click_ms = now_ms
        self._pause_until_ms = now_ms + self.settings.click_cooldown_ms
        logger.info(
            "Zoomed click target selected: action=%s logical=%s,%s physical=%s,%s.",
            mode,
            target.logical.x(),
            target.logical.y(),
            target.physical.x(),
            target.physical.y(),
        )
        self._fire_click(mode, target)

    def cancel_zoomed_click(self, *, reset_mode: bool = True) -> None:
        had_pending = self._click_zoom_open or self._pending_zoom_click_mode is not None
        self._cancel_zoomed_click_state()
        self._reset_target_dwell()
        if reset_mode:
            self.set_mode(None)
        if had_pending:
            self.status_changed.emit("Uvećani klik je otkazan.")

    def update_settings(self, settings: GazeSettings) -> None:
        self.settings = settings
        self._smooth_physical_point = None
        self._last_cursor_point = None
        if not self.settings.use_precision_zoom:
            self._cancel_zoomed_click_state()
        logger.info("Gaze mouse settings updated: %s", settings)
        self.status_changed.emit("Postavke su ažurirane.")

    def handle_eye_status(self, left_open: bool, right_open: bool) -> None:
        both_open = bool(left_open) and bool(right_open)
        if both_open == self._both_eyes_open:
            return

        self._both_eyes_open = both_open
        if both_open:
            logger.info("Both eyes are open; gaze control is active.")
            self.status_changed.emit("Oba oka su prepoznata.")
            return

        logger.info(
            "Gaze control paused because both eyes are not open: left=%s right=%s.",
            left_open,
            right_open,
        )
        self._smooth_physical_point = None
        self._last_cursor_point = None
        self._pause_toolbar_dwell()
        self._pause_target_dwell()
        self._cancel_zoomed_click_state()
        self._native_menu_click_pending = False
        self._quick_menu_open = False
        self._quick_target = None
        self._pause_quick_dwell()
        self._set_toolbar_gaze_target(None)
        self.status_changed.emit("Upravljanje pogledom je pauzirano: oba oka moraju biti otvorena.")

    def handle_gaze(self, normalized_x: float, normalized_y: float, _timestamp: object) -> None:
        if not self._both_eyes_open:
            self._set_toolbar_gaze_target(None)
            return

        now_ms = time.monotonic() * 1000
        point = self._map_to_screen(normalized_x, normalized_y)
        cursor_point = self._smooth_physical(point.physical)
        quick_menu_was_open = self._quick_menu_open
        click_zoom_was_open = self._click_zoom_open

        self.gaze_position_changed.emit(point.logical)

        if (
            quick_menu_was_open
            or self._quick_menu_open
            or click_zoom_was_open
            or self._click_zoom_open
        ):
            return

        toolbar_action = self._toolbar_action_at(point.logical)
        pointer_over_app_ui = toolbar_action is not None or self._toolbar_contains(point.logical)

        if not pointer_over_app_ui:
            self._move_cursor(cursor_point)

        if now_ms < self._pause_until_ms:
            if toolbar_action is None:
                self._reset_toolbar_dwell()
            else:
                self._cancel_interaction("toolbar")
                self._set_toolbar_gaze_target(None)
            return

        if toolbar_action is not None:
            self._reset_target_dwell()
            self._reset_quick_dwell()
            target_center = (
                self._toolbar_action_center(toolbar_action, point.logical) or point.logical
            )
            self._handle_toolbar_dwell(toolbar_action, target_center, now_ms)
            return

        self._reset_toolbar_dwell()

        if pointer_over_app_ui:
            self._reset_target_dwell()
            self._reset_quick_dwell()
            return

        if self.quick_actions_enabled:
            self._reset_target_dwell()
            self._handle_quick_action_dwell(point, now_ms)
            return

        self._reset_quick_dwell()
        self._handle_target_dwell(point, now_ms)

    def _map_to_screen(self, normalized_x: float, normalized_y: float) -> GazeScreenPoint:
        logical_left, logical_top, logical_width, logical_height = self._logical_screen_geometry()
        x = _clamp(normalized_x, 0.0, 1.0)
        y = _clamp(normalized_y, 0.0, 1.0)
        logical = QPoint(
            round(logical_left + x * max(1, logical_width - 1)),
            round(logical_top + y * max(1, logical_height - 1)),
        )
        physical_left, physical_top, physical_width, physical_height = (
            self._physical_screen_geometry()
        )
        physical = QPoint(
            round(physical_left + x * max(1, physical_width - 1)),
            round(physical_top + y * max(1, physical_height - 1)),
        )
        return GazeScreenPoint(logical=logical, physical=physical)

    def _smooth_physical(self, raw_point: QPoint) -> QPoint:
        alpha = _clamp(self.settings.smoothing, 0.01, 1.0)
        if self._smooth_physical_point is None or alpha >= 1.0:
            self._smooth_physical_point = raw_point
            return raw_point

        old = self._smooth_physical_point
        smoothed = QPoint(
            round(old.x() + (raw_point.x() - old.x()) * alpha),
            round(old.y() + (raw_point.y() - old.y()) * alpha),
        )
        self._smooth_physical_point = smoothed
        return smoothed

    def _move_cursor(self, point: QPoint) -> None:
        if (
            not self._pointer_movement_enabled
            or not self.settings.move_mouse
            or self._input is None
        ):
            return

        if (
            self._last_cursor_point is not None
            and _distance(self._last_cursor_point, point) < MIN_CURSOR_MOVE_DISTANCE_PX
        ):
            return

        try:
            self._input.move_to(point.x(), point.y())
            self._last_cursor_point = QPoint(point)
            self._last_mouse_error_ms = 0.0
        except Exception as exc:
            now_ms = time.monotonic() * 1000
            if now_ms - self._last_mouse_error_ms >= MOUSE_ERROR_LOG_INTERVAL_MS:
                self._last_mouse_error_ms = now_ms
                logger.exception("Mouse move failed.")
                self.status_changed.emit("Pomjeranje pokazivača nije uspjelo.")
            else:
                logger.debug("Mouse move failed during rate-limit window: %s", exc)

    def _handle_toolbar_dwell(self, action: str, center: QPoint, now_ms: float) -> None:
        update = self._toolbar_selection.update(
            action,
            now_ms,
            pause_ms=self.settings.selection_pause_ms,
            dwell_ms=self.settings.dwell_ms,
        )
        if update.progress is None:
            self._cancel_interaction("toolbar")
            self._set_toolbar_gaze_target(None)
            return

        self._set_toolbar_gaze_target(action)
        self._emit_interaction_progress("toolbar", center, update.progress, _action_label(action))

        cooled = now_ms - self._last_toolbar_ms >= self.settings.click_cooldown_ms
        if update.ready and cooled:
            self._last_toolbar_ms = now_ms
            self._pause_until_ms = now_ms + self.settings.click_cooldown_ms
            self._toolbar_selection.complete()
            self._finish_interaction("toolbar", center, _action_label(action))
            self._set_toolbar_gaze_target(None)
            logger.info("Toolbar dwell action fired: %s", action)
            self.toolbar_action_requested.emit(action)

    def _handle_target_dwell(self, point: GazeScreenPoint, now_ms: float) -> None:
        if self.active_mode is None:
            self._reset_target_dwell()
            return

        if (
            self._target_anchor is None
            or _distance(self._target_anchor, point.logical) > self.settings.dwell_radius_px
        ):
            self._target_anchor = point.logical
            self._target_selection.update(
                "desktop-target",
                now_ms,
                pause_ms=self.settings.selection_pause_ms,
                dwell_ms=self.settings.dwell_ms,
                restart=True,
            )
            self._cancel_interaction("target")
            return

        update = self._target_selection.update(
            "desktop-target",
            now_ms,
            pause_ms=self.settings.selection_pause_ms,
            dwell_ms=self.settings.dwell_ms,
        )
        if update.progress is None:
            self._cancel_interaction("target")
            return

        self._emit_interaction_progress(
            "target", self._target_anchor, update.progress, _action_label(self.active_mode)
        )

        cooled = now_ms - self._last_click_ms >= self.settings.click_cooldown_ms
        if update.ready and cooled:
            self._target_selection.complete()
            use_precision_zoom = (
                self.settings.use_precision_zoom and not self._native_menu_click_pending
            )
            if use_precision_zoom:
                self._pending_zoom_click_mode = self.active_mode
                self._click_zoom_open = True
                self._pause_until_ms = now_ms + self.settings.click_cooldown_ms
                self._finish_interaction(
                    "target", self._target_anchor, _action_label(self.active_mode)
                )
                self.click_zoom_requested.emit(QPoint(self._target_anchor))
                self._reset_target_dwell()
                self.status_changed.emit("Otvoreno je precizno uvećanje za klik.")
                return

            self._last_click_ms = now_ms
            self._pause_until_ms = now_ms + self.settings.click_cooldown_ms
            self._fire_click(self.active_mode, point)

    def _handle_quick_action_dwell(self, point: GazeScreenPoint, now_ms: float) -> None:
        if (
            self._quick_anchor is None
            or _distance(self._quick_anchor.logical, point.logical) > self.settings.dwell_radius_px
        ):
            self._quick_anchor = point
            self._quick_selection.update(
                "quick-target",
                now_ms,
                pause_ms=self.settings.selection_pause_ms,
                dwell_ms=self.settings.dwell_ms,
                restart=True,
            )
            self._cancel_interaction("quick")
            return

        update = self._quick_selection.update(
            "quick-target",
            now_ms,
            pause_ms=self.settings.selection_pause_ms,
            dwell_ms=self.settings.dwell_ms,
        )
        if update.progress is None:
            self._cancel_interaction("quick")
            return

        self._emit_interaction_progress(
            "quick", self._quick_anchor.logical, update.progress, "Brza radnja"
        )

        cooled = now_ms - self._last_click_ms >= self.settings.click_cooldown_ms
        if update.ready and cooled:
            self._quick_selection.complete()
            self._quick_target = self._quick_anchor
            self._quick_menu_open = True
            self._finish_interaction("quick", self._quick_anchor.logical, "Brza radnja")
            if self.settings.use_precision_zoom:
                self.quick_action_zoom_requested.emit(QPoint(self._quick_anchor.logical))
            else:
                self.quick_action_menu_requested.emit(QPoint(self._quick_anchor.logical))
            self._reset_quick_dwell()
            status = (
                "Otvoreno je precizno uvećanje za brzu radnju."
                if self.settings.use_precision_zoom
                else "Otvoren je izbornik brzih radnji."
            )
            self.status_changed.emit(status)

    def _fire_click(
        self,
        mode: str,
        point: GazeScreenPoint,
        *,
        reset_mode: bool = True,
        interaction_source: str = "target",
    ) -> None:
        if self._input is None:
            logger.warning("Click skipped because Windows input backend is unavailable.")
            self.status_changed.emit("Klik je preskočen jer upravljanje pokazivačem nije dostupno.")
            self._cancel_interaction(interaction_source)
            return

        try:
            logger.info(
                "Firing click action %s at physical=%s,%s logical=%s,%s.",
                mode,
                point.physical.x(),
                point.physical.y(),
                point.logical.x(),
                point.logical.y(),
            )
            if mode == LEFT_CLICK:
                self._input.click(point.physical.x(), point.physical.y(), button="left")
            elif mode == RIGHT_CLICK:
                self._input.click(point.physical.x(), point.physical.y(), button="right")
            elif mode == DOUBLE_LEFT_CLICK:
                self._input.click(
                    point.physical.x(), point.physical.y(), button="left", clicks=2, interval=0.04
                )
        except Exception:
            logger.exception("Click action failed.")
            self.status_changed.emit("Klik nije uspio.")
            self._cancel_interaction(interaction_source)
            return

        self._finish_interaction(interaction_source, point.logical, _action_label(mode))
        self.action_fired.emit(mode, point.physical)
        if mode == RIGHT_CLICK:
            self._native_menu_click_pending = True
            self.set_mode(LEFT_CLICK)
            self.status_changed.emit(
                "Desni klik je otvorio izbornik. Lijevi klik je spreman za odabir."
            )
            return

        self._native_menu_click_pending = False
        if reset_mode:
            self.set_mode(None)

    def _reset_toolbar_dwell(self) -> None:
        self._toolbar_selection.cancel()
        self._cancel_interaction("toolbar")
        self._set_toolbar_gaze_target(None)

    def _pause_toolbar_dwell(self) -> None:
        self._toolbar_selection.pause()
        self._cancel_interaction("toolbar")
        self._set_toolbar_gaze_target(None)

    def _set_toolbar_gaze_target(self, action: str | None) -> None:
        if action == self._toolbar_gaze_target:
            return

        self._toolbar_gaze_target = action
        self.toolbar_gaze_target_changed.emit(action)

    def _reset_target_dwell(self) -> None:
        self._target_selection.cancel()
        self._cancel_interaction("target")
        self._target_anchor = None

    def _pause_target_dwell(self) -> None:
        self._target_selection.pause()
        self._cancel_interaction("target")
        self._target_anchor = None

    def _reset_quick_dwell(self) -> None:
        self._quick_selection.cancel()
        self._cancel_interaction("quick")
        self._quick_anchor = None

    def _pause_quick_dwell(self) -> None:
        self._quick_selection.pause()
        self._cancel_interaction("quick")
        self._quick_anchor = None

    def _cancel_zoomed_click_state(self) -> None:
        self._click_zoom_open = False
        self._pending_zoom_click_mode = None

    def _emit_interaction_progress(
        self,
        source: str,
        center: QPoint,
        progress: float,
        label: str,
    ) -> None:
        self._interaction_source = source
        self.interaction_progress_changed.emit(QPoint(center), progress, label)

    def _finish_interaction(self, source: str, center: QPoint, label: str) -> None:
        if self._interaction_source == source:
            self._interaction_source = None
        self.interaction_finished.emit(QPoint(center), label)

    def _cancel_interaction(self, source: str) -> None:
        if self._interaction_source != source:
            return

        self._interaction_source = None
        self.interaction_cancelled.emit()

    def _physical_screen_geometry(self) -> tuple[int, int, int, int]:
        if self._physical_screen_rect is not None:
            return self._physical_screen_rect

        if self._logical_screen_rect is not None:
            return self._logical_screen_rect

        return _read_primary_screen_geometry()

    def _logical_screen_geometry(self) -> tuple[int, int, int, int]:
        if self._logical_screen_rect is None:
            self._logical_screen_rect = _read_primary_screen_geometry()
        return self._logical_screen_rect

    def _screen_point_from_logical(self, logical: QPoint) -> GazeScreenPoint:
        logical_left, logical_top, logical_width, logical_height = self._logical_screen_geometry()
        logical_right = logical_left + logical_width - 1
        logical_bottom = logical_top + logical_height - 1
        logical_x = max(logical_left, min(logical_right, logical.x()))
        logical_y = max(logical_top, min(logical_bottom, logical.y()))
        x_ratio = (logical_x - logical_left) / max(1, logical_width - 1)
        y_ratio = (logical_y - logical_top) / max(1, logical_height - 1)
        physical_left, physical_top, physical_width, physical_height = (
            self._physical_screen_geometry()
        )
        physical = QPoint(
            round(physical_left + x_ratio * max(1, physical_width - 1)),
            round(physical_top + y_ratio * max(1, physical_height - 1)),
        )
        return GazeScreenPoint(logical=QPoint(logical_x, logical_y), physical=physical)

    def _log_screen_mapping(self) -> None:
        logical_left, logical_top, logical_width, logical_height = self._logical_screen_geometry()
        physical_left, physical_top, physical_width, physical_height = (
            self._physical_screen_geometry()
        )
        logger.info(
            "Gaze screen mapping: logical=%s,%s %sx%s physical=%s,%s %sx%s.",
            logical_left,
            logical_top,
            logical_width,
            logical_height,
            physical_left,
            physical_top,
            physical_width,
            physical_height,
        )


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


def _distance(first: QPoint, second: QPoint) -> float:
    return math.hypot(first.x() - second.x(), first.y() - second.y())


def _read_primary_screen_geometry() -> tuple[int, int, int, int]:
    screen = QGuiApplication.primaryScreen()
    geometry = screen.geometry()
    return geometry.left(), geometry.top(), geometry.width(), geometry.height()


def _action_label(action: str | None) -> str:
    labels = {
        LEFT_CLICK: "Lijevi klik",
        RIGHT_CLICK: "Desni klik",
        DOUBLE_LEFT_CLICK: "Dvostruki klik",
        SPEECH: "Govor",
        KEYBOARD: "Tastatura",
        CONTROLLER: "Upravljač",
        SETTINGS: "Postavke",
        HIDE_HOTBAR: "Sakrij",
        SHOW_HOTBAR: "Prikaži",
        QUICK_ACTIONS: "Brza radnja",
    }
    if action is None:
        return "Odaberi"
    return labels.get(action, "Odaberi")
