"""Top hotbar UI."""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import replace

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QToolButton, QWidget

from . import diagnostics
from .diagnostic_recording import GAZE_KEYS, RecordingStore, recording_context
from .hotbar_speech import HotbarSpeech
from .interaction.eye_tracking_policy import EyeState, eyes_usable
from .interaction.mouse_controller import (
    CLICK_ACTIONS,
    CONTROLLER,
    DOUBLE_LEFT_CLICK,
    HIDE_HOTBAR,
    KEYBOARD,
    LEFT_CLICK,
    QUICK_ACTIONS,
    RIGHT_CLICK,
    SETTINGS,
    SHOW_HOTBAR,
    SPEECH,
    GazeMouseController,
)
from .logging_setup import get_project_root
from .release_update import ReleaseUpdateError, ReleaseUpdateManager, StableVersion
from .settings_store import load_app_settings, save_app_settings
from .speech.speech_library import speech_library_store
from .speech.speech_service import SpeechService
from .suggestions.service import SuggestionService
from .tracking.feedback import TrackingNotice
from .tracking.gaze_check_store import GazeCheckStore
from .tracking.gaze_provider import TobiiGazeProvider
from .tracking.mouse_gaze_provider import MouseGazeProvider
from .tracking.status import TrackingState, TrackingStatus
from .tracking.tobii_calibration import launch_tobii_guest_calibration, launch_tobii_settings
from .ui.controller_window import CONTROLLER_WINDOW_ACTION_PREFIX, ControllerWindow
from .ui.diagnostic_recordings import DiagnosticRecordings
from .ui.diagnostics_window import DiagnosticsWindow
from .ui.gaze_bubble import GazeBubbleWindow
from .ui.gaze_check_reports import GazeCheckReports
from .ui.gaze_check_window import GazeCheckWindow
from .ui.gaze_feedback import set_gaze_feedback, set_gaze_paused
from .ui.hotbar_controls import HotbarControls, no_focus_tool_window_flags
from .ui.interaction_overlay import InteractionOverlayWindow
from .ui.keyboard_window import KEYBOARD_WINDOW_ACTION_PREFIX, KeyboardWindow
from .ui.quick_action_menu import CANCEL_QUICK_ACTION, QuickActionRadialMenu
from .ui.quick_action_zoom import QuickActionZoomWindow
from .ui.recording_badge import RecordingBadge
from .ui.settings_window import SettingsServices, SettingsWindow
from .ui.speech_window import SPEECH_WINDOW_ACTION_PREFIX, SpeechWindow
from .ui.tracking_feedback import TrackingFeedback
from .windows.appbar import WindowsAppBar
from .windows.foreground_tracker import ForegroundTracker
from .windows.windows_input import WindowsInputController

logger = logging.getLogger(__name__)


class HotbarWindow(HotbarSpeech, QWidget):
    """Frameless top toolbar that reserves desktop work area on Windows."""

    BAR_HEIGHT = 76

    def __init__(self, *, simulate_gaze: bool = False) -> None:
        super().__init__()
        logger.info("Creating hotbar window.")
        self.setWindowTitle("Pogled Assist")
        self.setWindowFlags(no_focus_tool_window_flags())
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedHeight(self.BAR_HEIGHT)

        self._started = False
        self._closing = False
        self._simulate_gaze = simulate_gaze
        self._buttons: dict[str, QToolButton] = {}
        self._diagnostic_context = diagnostics.TargetContext("hotbar")
        self._appbar = WindowsAppBar()
        self._gaze = MouseGazeProvider(self) if simulate_gaze else TobiiGazeProvider(self)
        self._initial_gaze_settings, self._initial_speech_settings = load_app_settings()
        self._setup_speech(SpeechService(), speech_library_store(get_project_root()))
        self._suggestions = SuggestionService(
            self, path=get_project_root() / "data" / "speech_learning.json"
        )
        self._release_update_manager = ReleaseUpdateManager(parent=self)
        self._release_update_manager.install_ready.connect(self._release_install_ready)
        self._release_update_manager.install_failed.connect(self._release_install_failed)
        self._restarting_for_update = False
        self._speech_window: SpeechWindow | None = None
        self._keyboard_window: KeyboardWindow | None = None
        self._controller_window: ControllerWindow | None = None
        self._settings_window: SettingsWindow | None = None
        self._gaze_check_window: GazeCheckWindow | None = None
        self._diagnostics_window: DiagnosticsWindow | None = None
        self._diagnostic_recordings = DiagnosticRecordings(
            RecordingStore(get_project_root() / "logs" / "diagnostic-recordings"), self
        )
        self._gaze_check_reports = GazeCheckReports(
            GazeCheckStore(get_project_root() / "logs" / "gaze-check"), self
        )
        self._check_status = TrackingStatus(TrackingState.STOPPED)
        self._restore_button: QToolButton | None = None
        self._zoom_context: str | None = None
        self._foreground = ForegroundTracker(self, self, WindowsInputController)
        self._quick_menu = QuickActionRadialMenu()
        self._quick_zoom = QuickActionZoomWindow()
        self._mouse = GazeMouseController(
            self,
            self,
            pointer_movement_enabled=not simulate_gaze,
        )
        self._mouse.update_settings(self._initial_gaze_settings)
        self._gaze_bubble = GazeBubbleWindow()
        self._gaze_bubble.set_enabled(self._mouse.settings.show_gaze_bubble)
        self._interaction_overlay = InteractionOverlayWindow()
        self._interaction_overlay.set_enabled(self._mouse.settings.show_interaction_overlay)
        self._tracking_feedback = TrackingFeedback(
            self,
            self._tracking_feedback_active,
            enabled=self._mouse.settings.show_tracking_notifications,
        )

        self._build_ui()
        self._recording_badge = RecordingBadge(self._buttons[SETTINGS], compact=True)
        self._recording_badge.bind_indicator(self._diagnostic_recordings.indicator)
        self._diagnostic_recordings.changed.connect(self._recording_changed)
        self._build_restore_button()
        self._connect_signals()
        self._configure_eye_tracking()
        self._install_shortcuts()
        self._foreground.prime()
        logger.info("Hotbar window initialized.")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        logger.info("Hotbar show event received.")
        self._position_on_primary_screen()
        if not self._started:
            self._started = True
            QTimer.singleShot(0, self._start_services)

    def closeEvent(self, event: QCloseEvent) -> None:
        logger.info("Hotbar close event received.")
        if not self._restarting_for_update:
            self._release_update_manager.finish_cancel()
        self._closing = True
        if self._diagnostics_window is not None:
            self._diagnostics_window.close()
        self._diagnostic_recordings.shutdown()
        self._tracking_feedback.stop()
        for name in (
            "_gaze_check_window",
            "_speech_window",
            "_keyboard_window",
            "_controller_window",
            "_settings_window",
        ):
            window = getattr(self, name)
            if window is not None:
                window.close()
        self._quick_zoom.close_zoom()
        self._quick_menu.close_menu()
        self._gaze_bubble.set_enabled(False)
        self._interaction_overlay.set_enabled(False)
        self._gaze_bubble.close()
        self._interaction_overlay.close()
        self._foreground.stop()
        if self._restore_button is not None:
            self._restore_button.close()
        self._speech.stop()
        self._suggestions.close()
        self._gaze.stop()
        self._appbar.unregister()
        self._gaze_check_reports.shutdown()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:
        if hasattr(self, "_mouse"):
            self._mouse.cancel_toolbar_interaction(require_leave=True)
        super().resizeEvent(event)

    def action_at_global_point(self, point: QPoint) -> str | None:
        if self._quick_overlay_visible():
            return None
        window = self._window_at_global_point(point)
        if window is not None:
            return window.action_at_global_point(point)
        if _is_visible(self._settings_window):
            return None

        for action in self._buttons:
            rect = self._hotbar_action_bounds(action)
            if rect is not None and rect.contains(point):
                return action

        return None

    def action_center_at_global_point(self, action: str, point: QPoint) -> QPoint | None:
        if self._quick_overlay_visible():
            return None
        window = self._window_at_global_point(point)
        if window is not None:
            return window.action_center_at_global_point(action, point)
        button = self._available_button(action)
        if button is None:
            return None

        top_left = button.mapToGlobal(QPoint(0, 0))
        rect = QRect(top_left, button.size())
        bounds = self._hotbar_action_bounds(action)
        if bounds is None or not bounds.contains(point):
            return None

        return rect.center()

    def action_bounds(self, action: str) -> QRect | None:
        if self._quick_overlay_visible():
            return None
        if _is_visible(self._speech_window):
            return self._speech_window.action_bounds(action)
        if _is_visible(self._settings_window):
            return None
        if action.startswith(KEYBOARD_WINDOW_ACTION_PREFIX):
            if self._keyboard_window is not None:
                return self._keyboard_window.action_bounds(action)
            return None
        return self._hotbar_action_bounds(action)

    def selection_bounds(self, action: str) -> QRect | None:
        controller_action = isinstance(action, str) and action.startswith(
            CONTROLLER_WINDOW_ACTION_PREFIX
        )
        if controller_action and _is_visible(self._controller_window):
            return self._controller_window.action_bounds(action)
        return self.action_bounds(action)

    def _hotbar_action_bounds(self, action: str) -> QRect | None:
        button = self._available_button(action)
        if button is None:
            return None
        rect = QRect(button.mapToGlobal(QPoint(0, 0)), button.size())
        if self.isVisible() and button is not self._restore_button:
            # Gaze clamped to the screen's top edge must still reach the buttons.
            # Preserve each horizontal span so adjacent targets never overlap.
            rect.setTop(self.mapToGlobal(QPoint(0, 0)).y())
        return rect

    def contains_global_point(self, point: QPoint) -> bool:
        if self._quick_overlay_visible():
            return True
        if self._window_at_global_point(point) is not None:
            return True
        if _is_visible(self._settings_window):
            return True
        if _is_visible(self._restore_button):
            top_left = self._restore_button.mapToGlobal(QPoint(0, 0))
            if QRect(top_left, self._restore_button.size()).contains(point):
                return True

        if not self.isVisible():
            return False

        top_left = self.mapToGlobal(QPoint(0, 0))
        return QRect(top_left, self.size()).contains(point)

    def _quick_overlay_visible(self) -> bool:
        return self._quick_zoom.isVisible() or self._quick_menu.isVisible()

    def _window_at_global_point(
        self, point: QPoint
    ) -> SpeechWindow | KeyboardWindow | ControllerWindow | None:
        for window in (self._speech_window, self._keyboard_window, self._controller_window):
            if window is not None and window.contains_global_point(point):
                return window
        return None

    def _available_button(self, action: str) -> QToolButton | None:
        button = self._buttons.get(action)
        if not _is_visible(button):
            return None
        return button if button.isEnabled() else None

    def diagnostic_context(self, action: str | None) -> diagnostics.TargetContext:
        if not action:
            return self._diagnostic_context
        surfaces = (
            (SPEECH_WINDOW_ACTION_PREFIX, self._speech_window),
            (KEYBOARD_WINDOW_ACTION_PREFIX, self._keyboard_window),
            (CONTROLLER_WINDOW_ACTION_PREFIX, self._controller_window),
        )
        for prefix, window in surfaces:
            if window is not None and action.startswith(prefix):
                if prefix == SPEECH_WINDOW_ACTION_PREFIX:
                    return window._diagnostic_context
                return window.diagnostic_context(action)
        return self._diagnostic_context

    def _build_ui(self) -> None:
        self._controls = HotbarControls(
            self, self._run_toolbar_action, self._mouse.cancel_gaze_interactions_for_mouse
        )
        self._controls.build()
        self._buttons = self._controls.buttons
        self._hide_button = self._controls.hide_button
        self._settings_button = self._controls.settings_button
        self._quick_actions_button = self._controls.quick_actions_button
        self._tracking_status = self._controls.tracking_status

    def _build_restore_button(self) -> None:
        self._restore_button = self._controls.build_restore_button()

    def _connect_signals(self) -> None:
        self._foreground.status_changed.connect(self._set_status)
        self._gaze.gaze_updated.connect(self._forward_gaze)
        if hasattr(self._gaze, "eye_state_changed"):
            self._gaze.eye_state_changed.connect(self._forward_eye_state)
            self._gaze.continuity_lost.connect(self._reset_tracking_continuity)
            if hasattr(self._gaze, "gaze_invalidated"):
                self._gaze.gaze_invalidated.connect(self._invalidate_gaze)
        self._gaze.eye_status_changed.connect(self._handle_eye_status_changed)
        self._gaze.eye_status_changed.connect(self._tracking_feedback.handle_eyes)
        self._gaze.status_changed.connect(self._set_status)
        self._gaze.tracking_status_changed.connect(self._tracking_status.set_tracking_status)
        self._gaze.tracking_status_changed.connect(self._check_tracking_state)
        self._gaze.tracking_status_changed.connect(self._tracking_feedback.handle_status)
        self._tracking_feedback.changed.connect(self._show_tracking_notice)
        self._mouse.gaze_position_changed.connect(self._gaze_bubble.handle_gaze)
        self._mouse.desktop_gaze_position_changed.connect(self._quick_menu.handle_gaze)
        self._mouse.desktop_gaze_position_changed.connect(self._quick_zoom.handle_gaze)
        self._mouse.status_changed.connect(self._set_status)
        self._mouse.interaction_progress_changed.connect(self._interaction_overlay.show_progress)
        self._mouse.interaction_finished.connect(self._interaction_overlay.show_fired)
        self._mouse.interaction_cancelled.connect(self._interaction_overlay.clear)
        self._mouse.interaction_hold_changed.connect(self._set_interaction_paused)
        self._mouse._eye_gate.hold_started.connect(
            lambda _at: self._tracking_status.set_holding(True)
        )
        self._mouse._eye_gate.hold_finished.connect(
            lambda: self._tracking_status.set_holding(False)
        )
        self._mouse._eye_gate.interrupted.connect(lambda: self._tracking_status.set_holding(False))
        self._mouse.toolbar_action_requested.connect(
            lambda action: self._run_toolbar_action(action, source="gaze")
        )
        self._mouse.toolbar_gaze_target_changed.connect(self._set_toolbar_gaze_target)
        self._mouse.mode_changed.connect(self._sync_mode_buttons)
        self._mouse.quick_actions_mode_changed.connect(self._sync_quick_actions_button)
        self._mouse.quick_action_zoom_requested.connect(self._open_quick_action_zoom)
        self._mouse.quick_action_menu_requested.connect(self._open_quick_action_menu)
        self._mouse.click_zoom_requested.connect(self._open_click_action_zoom)
        self._mouse.action_fired.connect(self._show_action_fired)
        self._quick_zoom.selection_progress_changed.connect(self._interaction_overlay.show_progress)
        self._quick_zoom.selection_cancelled.connect(self._interaction_overlay.clear)
        self._quick_zoom.target_selected.connect(self._quick_zoom_target_selected)
        self._quick_zoom.cancelled.connect(self._quick_zoom_cancelled)
        self._quick_menu.selection_progress_changed.connect(self._interaction_overlay.show_progress)
        self._quick_menu.selection_cancelled.connect(self._interaction_overlay.clear)
        self._quick_menu.action_selected.connect(self._quick_action_selected)

    def _install_shortcuts(self) -> None:
        self._quit_shortcut = QShortcut(QKeySequence("Ctrl+Q"), self)
        self._quit_shortcut.activated.connect(self.close)
        self._simulation_shortcuts: list[QShortcut] = []
        if self._simulate_gaze:
            for key, action in (
                ("F6", self._gaze.toggle_left_eye),
                ("F7", self._gaze.toggle_right_eye),
                ("F8", self._gaze.toggle_gaze),
                ("F9", self._gaze.toggle_connection),
                ("F10", self._gaze.reset),
            ):
                shortcut = QShortcut(QKeySequence(key), self)
                shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
                shortcut.setAutoRepeat(False)
                shortcut.activated.connect(action)
                self._simulation_shortcuts.append(shortcut)

    def _start_services(self) -> None:
        logger.info("Starting hotbar services.")
        self._position_on_primary_screen()
        self._register_appbar()
        self._mouse.start()
        self._foreground.start()
        self._gaze.start()

    def _position_on_primary_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        geometry = screen.geometry()
        logger.info(
            "Positioning hotbar on primary screen: left=%s top=%s width=%s height=%s.",
            geometry.left(),
            geometry.top(),
            geometry.width(),
            geometry.height(),
        )
        self.setGeometry(geometry.left(), geometry.top(), geometry.width(), self.BAR_HEIGHT)
        if self._appbar.supported:
            self._appbar.set_position(self.height())

    def _register_appbar(self) -> None:
        if self._appbar.register(int(self.winId()), self.height()):
            self._set_status("Gornji dio radne površine je zauzet.")
        elif sys.platform == "win32":
            self._set_status("Radna površina nije rezervisana; alatna traka ostaje iznad prozora.")

    def _run_toolbar_action(
        self,
        action: str,
        *,
        checked: bool | None = None,
        source: str = "unknown",
    ) -> None:
        logger.info("Toolbar action requested by %s: %s", source, diagnostics.safe_action(action))
        if source == "mouse":
            self._mouse.cancel_gaze_interactions_for_mouse()
        if self._route_window_action(action):
            return
        if action in CLICK_ACTIONS:
            self._select_click_mode(action, checked, source)
            return
        for button_action, button in self._buttons.items():
            if button_action in CLICK_ACTIONS:
                button.setChecked(False)
        self._run_hotbar_action(action, checked, source)

    def _route_window_action(self, action: str) -> bool:
        for prefix, window in (
            (KEYBOARD_WINDOW_ACTION_PREFIX, self._keyboard_window),
            (CONTROLLER_WINDOW_ACTION_PREFIX, self._controller_window),
            (SPEECH_WINDOW_ACTION_PREFIX, self._speech_window),
        ):
            if not action.startswith(prefix):
                continue
            if window is not None:
                window.handle_gaze_action(action)
            return True
        return False

    def _select_click_mode(self, action: str, checked: bool | None, source: str) -> None:
        deselected = source == "mouse" and checked is False and self._mouse.active_mode == action
        self._mouse.set_mode(None if deselected else action)

    def _run_hotbar_action(self, action: str, checked: bool | None, source: str) -> None:
        if action == KEYBOARD:
            self._mouse.set_mode(None)
            self._toggle_keyboard(checked, source)
        elif action == CONTROLLER:
            self._mouse.set_mode(None)
            self._toggle_controller(checked, source)
        elif action == SPEECH:
            self._mouse.set_mode(None)
            self._open_speech()
        elif action == SETTINGS:
            self._mouse.set_mode(None)
            self._open_settings()
        elif action == QUICK_ACTIONS:
            self._toggle_quick_actions(checked, source)
        elif action == HIDE_HOTBAR:
            self._mouse.set_mode(None)
            self._hide_hotbar()
        elif action == SHOW_HOTBAR:
            self._mouse.set_mode(None)
            self._show_hotbar()

    def _sync_mode_buttons(self, mode: object) -> None:
        for action, button in self._buttons.items():
            if action in CLICK_ACTIONS:
                button.setChecked(action == mode)

    def _sync_quick_actions_button(self, enabled: bool) -> None:
        button = self._buttons.get(QUICK_ACTIONS)
        if button is not None:
            button.setChecked(enabled)
        self._set_click_action_buttons_visible(not enabled)

    def _set_click_action_buttons_visible(self, visible: bool) -> None:
        for action in CLICK_ACTIONS:
            button = self._buttons.get(action)
            if button is not None:
                button.setVisible(visible)

    def _set_toolbar_gaze_target(self, action: object) -> None:
        self._interaction_overlay.set_calm(
            isinstance(action, str) and action.startswith(SPEECH_WINDOW_ACTION_PREFIX)
        )
        for button_action, button in self._buttons.items():
            set_gaze_feedback(button, button_action == action)
        if self._speech_window is not None:
            speech_action = (
                action
                if isinstance(action, str) and action.startswith(SPEECH_WINDOW_ACTION_PREFIX)
                else None
            )
            self._speech_window.set_gaze_target_action(speech_action)
        if self._keyboard_window is not None:
            keyboard_action = (
                action
                if isinstance(action, str) and action.startswith(KEYBOARD_WINDOW_ACTION_PREFIX)
                else None
            )
            self._keyboard_window.set_gaze_target_action(keyboard_action)
        if self._controller_window is not None:
            controller_action = (
                action
                if isinstance(action, str) and action.startswith(CONTROLLER_WINDOW_ACTION_PREFIX)
                else None
            )
            self._controller_window.set_gaze_target_action(controller_action)

    def _show_action_fired(self, action: str, point: QPoint) -> None:
        names = {
            LEFT_CLICK: "Lijevi klik",
            RIGHT_CLICK: "Desni klik",
            DOUBLE_LEFT_CLICK: "Dvostruki klik",
        }
        self._set_status(f"{names.get(action, action)} na {point.x()}, {point.y()}.")

    def _toggle_quick_actions(self, checked: bool | None, source: str) -> None:
        if source == "mouse" and checked is not None:
            enabled = checked
        else:
            enabled = not self._mouse.quick_actions_enabled

        self._quick_zoom.close_zoom()
        self._quick_menu.close_menu()
        self._zoom_context = None
        self._mouse.cancel_zoomed_click(reset_mode=False)
        self._mouse.cancel_quick_action_menu()
        self._mouse.set_quick_actions_enabled(enabled)

    def _open_quick_action_zoom(self, center: QPoint) -> None:
        self._open_zoom(center, "quick")
        self._set_status("Otvoreno je precizno uvećanje za brzu radnju.")

    def _open_click_action_zoom(self, center: QPoint) -> None:
        self._open_zoom(center, "click")
        self._set_status("Otvoreno je precizno uvećanje za klik.")

    def _open_zoom(self, center: QPoint, context: str) -> None:
        self._zoom_context = context
        self._interaction_overlay.clear()
        self._quick_menu.close_menu()
        self._configure_selection_overlay(self._quick_zoom)
        self._quick_zoom.show_at(center)

    def _configure_selection_overlay(self, overlay) -> None:
        overlay.set_selection_settings(
            pause_ms=self._mouse.settings.selection_pause_ms,
            dwell_ms=self._mouse.settings.dwell_ms,
            radius_px=self._mouse.settings.dwell_radius_px,
        )

    def _quick_zoom_target_selected(self, point: QPoint) -> None:
        context = self._zoom_context
        self._zoom_context = None
        self._quick_zoom.close_zoom()
        self._interaction_overlay.clear()
        if context == "click":
            self._mouse.execute_zoomed_click(point)
            self._set_status("Odabran je uvećani cilj klika.")
            return

        if context == "quick":
            self._mouse.set_quick_target_from_logical(point)
            self._open_quick_action_menu(point)
            self._set_status("Odabran je cilj brze radnje.")
            return

        self._mouse.cancel_zoomed_click(reset_mode=False)
        self._mouse.cancel_quick_action_menu()
        self._set_status("Cilj uvećanja je zanemaren.")

    def _quick_zoom_cancelled(self) -> None:
        context = self._zoom_context
        self._zoom_context = None
        self._quick_zoom.close_zoom()
        self._interaction_overlay.clear()
        if context == "click":
            self._mouse.cancel_zoomed_click()
            self._set_status("Uvećani klik je otkazan.")
            return

        self._mouse.cancel_zoomed_click(reset_mode=False)
        self._mouse.cancel_quick_action_menu()
        self._set_status("Brza radnja je otkazana.")

    def _open_quick_action_menu(self, center: QPoint) -> None:
        self._interaction_overlay.clear()
        self._quick_zoom.close_zoom()
        self._configure_selection_overlay(self._quick_menu)
        self._quick_menu.show_at(center)
        self._set_status("Otvoren je meni brzih radnji.")

    def _quick_action_selected(self, action: str) -> None:
        self._quick_menu.close_menu()
        self._interaction_overlay.clear()
        if action == CANCEL_QUICK_ACTION:
            self._mouse.cancel_quick_action_menu()
            self._set_status("Brza radnja je otkazana.")
            return

        self._mouse.execute_quick_action(action)

    def _hide_hotbar(self) -> None:
        logger.info("Hiding hotbar.")
        self._mouse.cancel_toolbar_interaction(require_leave=True)
        self._reset_hotbar_overlays()
        self._interaction_overlay.clear()
        self._appbar.unregister()
        self.hide()
        self._resize_visible_sidebars(0, full_height=True)
        self._show_restore_button()
        self._set_status("Alatna traka je sakrivena.")

    def _show_hotbar(self) -> None:
        logger.info("Showing hotbar.")
        self._reset_hotbar_overlays()
        if self._restore_button is not None:
            self._restore_button.hide()
        self.show()
        self._position_on_primary_screen()
        self._register_appbar()
        self._resize_visible_sidebars(self.BAR_HEIGHT, full_height=False)
        self.raise_()
        self._set_status("Alatna traka je prikazana.")

    def _reset_hotbar_overlays(self) -> None:
        self._set_toolbar_gaze_target(None)
        self._quick_zoom.close_zoom()
        self._quick_menu.close_menu()
        self._zoom_context = None
        self._mouse.cancel_zoomed_click(reset_mode=False)
        self._mouse.cancel_quick_action_menu()

    def _resize_visible_sidebars(self, top_height: int, *, full_height: bool) -> None:
        for window in (self._keyboard_window, self._controller_window):
            if _is_visible(window):
                window.set_reserved_top_height(top_height)
                window.set_full_height(full_height)

    def _show_restore_button(self) -> None:
        if self._restore_button is None:
            return

        self._position_restore_button()
        self._restore_button.show()
        self._restore_button.raise_()

    def set_external_window(self, hwnd: int) -> None:
        for window in (self._keyboard_window, self._controller_window):
            if window is not None:
                window.set_target_window(hwnd)

    def set_external_cursor(self, position: tuple[int, int]) -> None:
        if self._controller_window is not None:
            self._controller_window.set_target_cursor_position(position)

    def _position_restore_button(self) -> None:
        if self._restore_button is None:
            return

        screen = QGuiApplication.primaryScreen()
        geometry = screen.geometry()
        margin = 18
        x = geometry.left() + margin
        y = geometry.top() + margin
        self._restore_button.move(x, y)

    def _toggle_keyboard(self, checked: bool | None, source: str) -> None:
        enabled = self._sidebar_should_open(self._keyboard_window, checked, source)
        if enabled:
            self._show_keyboard_sidebar()
        else:
            self._hide_keyboard_sidebar()

    def _show_keyboard_sidebar(self) -> None:
        self._hide_controller_sidebar()
        if self._keyboard_window is None:
            self._keyboard_window = KeyboardWindow(self._speech.settings, self)
            self._keyboard_window.closed.connect(self._keyboard_window_closed)
            self._keyboard_window.keyboard_script_changed.connect(self._change_keyboard_script)
            self._keyboard_window.status_changed.connect(self._set_status)
            self._keyboard_window.interaction_context_changed.connect(
                lambda: self._mouse.cancel_toolbar_interaction(require_leave=True)
            )
            self._keyboard_window.mouse_action_started.connect(
                self._mouse.cancel_gaze_interactions_for_mouse
            )

        self._foreground.update()
        self._keyboard_window.set_target_window(self._foreground.window)
        self._keyboard_window.set_reserved_top_height(self.BAR_HEIGHT if self.isVisible() else 0)
        self._keyboard_window.update_settings(self._speech.settings)
        self._keyboard_window.show_sidebar(full_height=not self.isVisible())
        self._recording_changed()
        self._set_keyboard_button_checked(True)
        self._set_status("Tastatura je otvorena.")

    def _hide_keyboard_sidebar(self) -> None:
        if self._keyboard_window is not None and self._keyboard_window.isVisible():
            self._keyboard_window.hide_sidebar()
            self._set_status("Tastatura je zatvorena.")
        self._set_keyboard_button_checked(False)

    def _keyboard_window_closed(self) -> None:
        self._set_keyboard_button_checked(False)
        self._set_status("Tastatura je zatvorena.")

    def _set_keyboard_button_checked(self, checked: bool) -> None:
        button = self._buttons.get(KEYBOARD)
        if button is not None:
            button.setChecked(checked)

    def _toggle_controller(self, checked: bool | None, source: str) -> None:
        enabled = self._sidebar_should_open(self._controller_window, checked, source)
        if enabled:
            self._show_controller_sidebar()
        else:
            self._hide_controller_sidebar()

    def _sidebar_should_open(self, window, checked: bool | None, source: str) -> bool:
        if source == "mouse" and checked is not None:
            return checked
        return not _is_visible(window)

    def _show_controller_sidebar(self) -> None:
        self._hide_keyboard_sidebar()
        if self._controller_window is None:
            self._controller_window = ControllerWindow(
                self._mouse.settings,
                self._speech.settings,
                self,
            )
            self._controller_window.closed.connect(self._controller_window_closed)
            self._controller_window.keyboard_script_changed.connect(self._change_keyboard_script)
            self._controller_window.status_changed.connect(self._set_status)
            self._controller_window.speech_requested.connect(self._open_speech_from_controller)
            self._controller_window.gaze_settings_changed.connect(self._update_gaze_settings)
            self._controller_window.interaction_context_changed.connect(
                lambda: self._mouse.cancel_toolbar_interaction(require_leave=True)
            )
            self._controller_window.mouse_action_started.connect(
                self._mouse.cancel_gaze_interactions_for_mouse
            )

        self._foreground.update()
        self._controller_window.set_target_window(self._foreground.window)
        self._controller_window.set_target_cursor_position(self._foreground.cursor)
        self._controller_window.set_reserved_top_height(self.BAR_HEIGHT if self.isVisible() else 0)
        self._controller_window.update_gaze_settings(self._mouse.settings)
        self._controller_window.update_speech_settings(self._speech.settings)
        self._controller_window.show_sidebar(full_height=not self.isVisible())
        self._recording_changed()
        self._set_controller_button_checked(True)
        self._set_status("Upravljač je otvoren.")

    def _hide_controller_sidebar(self) -> None:
        if self._controller_window is not None and self._controller_window.isVisible():
            self._controller_window.hide_sidebar()
            self._set_status("Upravljač je zatvoren.")
        self._set_controller_button_checked(False)

    def _controller_window_closed(self) -> None:
        self._set_controller_button_checked(False)
        self._set_status("Upravljač je zatvoren.")

    def _set_controller_button_checked(self, checked: bool) -> None:
        button = self._buttons.get(CONTROLLER)
        if button is not None:
            button.setChecked(checked)

    def _open_speech_from_controller(self) -> None:
        self._hide_controller_sidebar()
        self._open_speech()

    def _open_speech(self) -> None:
        logger.info("Opening speech window.")
        if self._speech_window is None:
            self._speech_window = SpeechWindow(
                self._speech,
                self,
                library_store=self._speech_library_store,
                suggestions=self._suggestions,
            )
            self._speech_window.keyboard_script_changed.connect(self._change_keyboard_script)
            self._speech_window.closed.connect(
                lambda: self._set_status("Prozor za govor je zatvoren.")
            )
            self._speech_window.interaction_context_changed.connect(
                lambda: self._mouse.cancel_toolbar_interaction(require_leave=True)
            )
            self._speech_window.mouse_action_started.connect(
                self._mouse.cancel_gaze_interactions_for_mouse
            )
            self._speech_window.quit_requested.connect(self._quit_application)
        self._speech_window.update_settings(self._speech.settings)

        self._speech_window.show_full_screen()
        self._recording_changed()
        self._tracking_feedback.refresh()
        self._show_tracking_notice(self._tracking_feedback.notice)
        self._set_status("Prozor za govor je otvoren.")

    def _tracking_feedback_active(self) -> bool:
        window = self._speech_window
        return (
            not self._closing
            and window is not None
            and window.isVisible()
            and not window.isMinimized()
            and window.accepts_tracking_notice()
            and self._gaze_check_window is None
            and not _is_visible(self._settings_window)
        )

    def _show_tracking_notice(self, notice: TrackingNotice | None) -> None:
        diagnostics.emit(
            "tracking_notice_host",
            host="speech"
            if self._speech_window is not None and self._speech_window.isVisible()
            else "none",
            tone=notice.tone if notice is not None else None,
        )
        if self._speech_window is not None:
            self._speech_window.set_tracking_notice(
                notice, immediate=not self._mouse.settings.show_tracking_notifications
            )

    def _open_settings(self) -> None:
        if self._diagnostics_window is not None:
            self._diagnostics_window.raise_()
            self._diagnostics_window.activateWindow()
            return
        if self._gaze_check_window is not None:
            self._gaze_check_window.showNormal()
            self._gaze_check_window.raise_()
            self._gaze_check_window.activateWindow()
            return
        logger.info("Opening fullscreen settings window.")
        self._quick_zoom.close_zoom()
        self._quick_menu.close_menu()
        self._zoom_context = None
        self._mouse.cancel_zoomed_click(reset_mode=False)
        self._mouse.cancel_quick_action_menu()
        self._hide_keyboard_sidebar()
        self._hide_controller_sidebar()
        if self._settings_window is not None and self._settings_window.isVisible():
            self._settings_window.raise_()
            self._settings_window.activateWindow()
            return

        requested_at = time.monotonic()
        diagnostics.emit("settings_open_started", priority=True)
        window = SettingsWindow(
            self._mouse.settings,
            self._speech.settings,
            self,
            services=SettingsServices(
                update_manager=self._release_update_manager,
                suggestions=self._suggestions,
                account=self._speech.account,
                clear_audio=self._speech.audio_cache.clear,
            ),
        )
        diagnostics.emit(
            "settings_constructed",
            priority=True,
            duration_ms=(time.monotonic() - requested_at) * 1000,
        )
        window.gaze_settings_changed.connect(self._update_gaze_settings)
        window.speech_settings_changed.connect(self._update_speech_settings)
        window.save_retry_requested.connect(self._save_settings)
        window.calibration_requested.connect(self._launch_tobii_calibration)
        window.gaze_check_requested.connect(self._open_gaze_check)
        window.diagnostics_requested.connect(self._open_diagnostics)
        window.speech_test_requested.connect(self._test_current_speech_settings)
        window.efendija_test_requested.connect(self._test_efendija)
        window.speech_stop_requested.connect(self._speech.stop)
        window.update_requested.connect(self._start_release_update)
        window.restart_confirmed.connect(self._restart_for_update)
        window.install_cancelled.connect(self._release_update_manager.finish_cancel)
        window.quit_requested.connect(self._quit_application)
        window.closed.connect(self._settings_window_closed)
        self._mouse.gaze_position_changed.connect(self._forward_settings_gaze)
        window.interaction_progress_changed.connect(self._interaction_overlay.show_progress)
        window.interaction_finished.connect(self._interaction_overlay.show_fired)
        window.interaction_cancelled.connect(self._interaction_overlay.clear)
        window.interaction_hold_changed.connect(self._set_interaction_paused)
        window.handle_eye_status(*self._mouse._eye_gate.eyes)

        self._settings_window = window
        self._recording_changed()
        window.set_speech_playback_state(self._speech.playback_state)
        window.set_save_error(self._settings_save_failed)
        window.show_fullscreen_on_primary()
        diagnostics.emit(
            "settings_shown", priority=True, duration_ms=(time.monotonic() - requested_at) * 1000
        )
        self._set_status("Postavke su otvorene.")

    def _open_gaze_check(self) -> None:
        if self._gaze_check_window is not None:
            self._gaze_check_window.showNormal()
            self._gaze_check_window.raise_()
            return
        self._mouse.set_input_suspended(True)
        self._gaze.set_check_active(True)
        self._quick_zoom.close_zoom()
        self._quick_menu.close_menu()
        self._zoom_context = None
        self._interaction_overlay.clear()
        self._gaze_bubble.set_enabled(False)
        if self._settings_window is not None:
            self._settings_window.cancel_gaze_interaction()
            self._settings_window.hide()
        window = GazeCheckWindow(
            self._mouse.settings,
            self,
            simulated=self._simulate_gaze,
            reports=self._gaze_check_reports,
            environment=lambda: self._gaze.check_environment(),
        )
        self._gaze_check_window = window
        self._recording_changed()
        window.closed.connect(self._gaze_check_closed)
        window.calibration_requested.connect(self._calibrate_from_gaze_check)
        window.diagnostics_requested.connect(self._open_diagnostics)
        self._gaze.diagnostics_updated.connect(window.handle_snapshot)
        window.handle_eye_status(*self._mouse._eye_gate.eyes)
        window.handle_tracking_status(self._check_status)
        window.handle_snapshot(self._gaze.check_snapshot())
        window.show_fullscreen_on_primary()

    def _recording_context(self) -> dict:
        environment = self._gaze.check_environment()
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geometry = screen.geometry()
            environment.update(
                logical_screen=[geometry.x(), geometry.y(), geometry.width(), geometry.height()],
                device_pixel_ratio=screen.devicePixelRatio(),
                logical_dpi=screen.logicalDotsPerInch(),
            )
        environment["physical_screen"] = self._mouse._physical_screen_rect
        return recording_context(
            {key: getattr(self._mouse.settings, key, None) for key in GAZE_KEYS},
            environment,
            simulated=self._simulate_gaze,
        )

    def _open_diagnostics(self) -> None:
        if self._diagnostics_window is not None:
            self._diagnostics_window.raise_()
            return
        check = self._gaze_check_window
        if check is not None and check._phase in ("precision", "trial"):
            return
        self._mouse.set_input_suspended(True)
        self._quick_zoom.close_zoom()
        self._quick_menu.close_menu()
        self._interaction_overlay.clear()
        self._gaze_bubble.set_enabled(False)
        if check is not None:
            check._timer.stop()
            check.hide()
            self._gaze.set_check_active(False)
        if self._settings_window is not None:
            self._settings_window.cancel_gaze_interaction()
            self._settings_window.hide()
        window = DiagnosticsWindow(
            self._diagnostic_recordings,
            self._gaze_check_reports,
            self._recording_context,
            logging_enabled=lambda: self._mouse.settings.logging_enabled,
            origin="Provjeru pogleda" if check else "Postavke",
            parent=self,
        )
        self._diagnostics_window = window
        window.closed.connect(self._diagnostics_closed)
        window.show_fullscreen_on_primary()

    def _diagnostics_closed(self) -> None:
        window = self._diagnostics_window
        self._diagnostics_window = None
        if window is not None:
            window.deleteLater()
        if self._closing:
            return
        if self._gaze_check_window is not None:
            self._gaze.set_check_active(True)
            self._gaze_check_window.show_fullscreen_on_primary()
        else:
            self._mouse.set_input_suspended(False)
            self._gaze_bubble.set_enabled(self._mouse.settings.show_gaze_bubble)
            if self._settings_window is not None:
                self._settings_window.show_fullscreen_on_primary()

    def _recording_changed(self) -> None:
        indicator = self._diagnostic_recordings.indicator
        indicator.set_status(self._diagnostic_recordings.status)
        for window in (
            self._settings_window,
            self._keyboard_window,
            self._controller_window,
            self._gaze_check_window,
        ):
            if window is not None:
                window._recording_badge.bind_indicator(indicator)
        if self._speech_window is not None:
            self._speech_window.bind_recording_indicator(indicator)
        if self._gaze_check_window is not None:
            self._gaze_check_window._test_recording_badge.bind_indicator(indicator)

    def _gaze_check_closed(self) -> None:
        window = self._gaze_check_window
        if window is None:
            return
        self._gaze.diagnostics_updated.disconnect(window.handle_snapshot)
        self._gaze_check_window = None
        self._gaze.set_check_active(False)
        window.deleteLater()
        self._mouse.set_input_suspended(False)
        self._gaze_bubble.set_enabled(self._mouse.settings.show_gaze_bubble and not self._closing)
        if self._settings_window is not None and not self._closing:
            self._settings_window.show_fullscreen_on_primary()

    def _check_tracking_state(self, status: TrackingStatus) -> None:
        self._check_status = status
        if self._gaze_check_window is not None:
            self._gaze_check_window.handle_tracking_status(status)

    def _calibrate_from_gaze_check(self) -> None:
        # The check remains open/minimized and normal gaze input stays suspended.
        try:
            diagnostics.emit(
                "gaze_check_handoff", priority=True, action="tobii_settings", outcome="requested"
            )
            message = launch_tobii_settings()
            diagnostics.emit(
                "gaze_check_handoff",
                priority=True,
                action="tobii_settings",
                outcome="launcher_returned",
                calibration_completed="unknown",
            )
        except Exception:
            logger.exception("Tobii settings launch from gaze check failed.")
            message = "Tobii postavke se nisu otvorile. Otvorite Tobii ikonu pored sata."
            if self._gaze_check_window is not None:
                self._gaze_check_window.showNormal()
        self._set_status(message)

        if self._gaze_check_window is not None:
            self._gaze_check_window.set_calibration_notice(message)

    def _settings_window_closed(self) -> None:
        if self._efendija_test_id == self._speech.request_id:
            self._speech.stop()
        self._efendija_test_id = None
        if not self._restarting_for_update:
            self._release_update_manager.finish_cancel()
        window = self._settings_window
        if window is None:
            return

        try:
            self._mouse.gaze_position_changed.disconnect(self._forward_settings_gaze)
        except (RuntimeError, TypeError):
            logger.info("Settings gaze handler was already disconnected.")

        try:
            window.interaction_progress_changed.disconnect(self._interaction_overlay.show_progress)
            window.interaction_finished.disconnect(self._interaction_overlay.show_fired)
            window.interaction_cancelled.disconnect(self._interaction_overlay.clear)
        except (RuntimeError, TypeError):
            logger.info("Settings interaction overlay handlers were already disconnected.")

        self._settings_window = None
        window.deleteLater()
        self._set_status("Postavke su zatvorene.")

    def _quit_application(self) -> None:
        logger.info("Quit application requested.")
        self._set_toolbar_gaze_target(None)
        self._quick_zoom.close_zoom()
        self._quick_menu.close_menu()
        self._zoom_context = None
        self._mouse.cancel_zoomed_click(reset_mode=False)
        self._mouse.cancel_quick_action_menu()
        self._hide_keyboard_sidebar()
        self._hide_controller_sidebar()
        self._interaction_overlay.clear()
        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _start_release_update(self, version: StableVersion) -> None:
        try:
            if self._settings_save_failed or self._suggestions.store.error:
                raise ReleaseUpdateError(
                    "Prvo sačuvajte postavke i naučene riječi pa pokušajte ponovo."
                )
            self._release_update_manager.prepare(version)
        except ReleaseUpdateError as error:
            self._release_install_failed(str(error))

    def _release_install_failed(self, message: str) -> None:
        self._set_status("Instalacija nije pokrenuta.")
        if self._settings_window is not None:
            self._settings_window.show_update_error(message)

    def _release_install_ready(self) -> None:
        if self._closing or not self._release_update_manager.ready:
            return
        if self._speech_window is not None and self._speech_window.has_unsaved_input:
            self._open_settings()
            self._settings_window.confirm_update_restart()
            return
        self._restart_for_update()

    def _restart_for_update(self) -> None:
        try:
            if self._settings_save_failed or self._suggestions.store.error:
                raise ReleaseUpdateError(
                    "Prvo sačuvajte postavke i naučene riječi pa pokušajte ponovo."
                )
            self._release_update_manager.authorize_restart()
        except ReleaseUpdateError as error:
            self._release_update_manager.finish_cancel()
            self._release_install_failed(str(error))
            return
        self._restarting_for_update = True
        logger.info("Selected release verified; closing the current application.")
        self._quit_application()

    def _update_gaze_settings(self, settings: object) -> None:
        previous = (
            self._mouse.settings.eye_tracking_policy,
            self._mouse.settings.eye_tracking_hold_ms,
        )
        self._mouse.update_settings(settings)
        if previous != (settings.eye_tracking_policy, settings.eye_tracking_hold_ms):
            self._reset_tracking_continuity()
        self._configure_eye_tracking()
        self._tracking_feedback.set_enabled(self._mouse.settings.show_tracking_notifications)
        if not self._mouse.settings.show_tracking_notifications:
            self._show_tracking_notice(None)
        self._gaze_bubble.set_enabled(bool(getattr(settings, "show_gaze_bubble", True)))
        self._interaction_overlay.set_enabled(
            bool(getattr(settings, "show_interaction_overlay", True))
        )
        if self._controller_window is not None:
            self._controller_window.update_gaze_settings(self._mouse.settings)
        self._save_settings()

    def _configure_eye_tracking(self) -> None:
        policy = self._mouse.settings.eye_tracking_policy
        setter = getattr(self._gaze, "set_eye_tracking_policy", None)
        if setter is not None:
            setter(policy)
        self._tracking_status.set_eye_tracking_policy(policy)
        self._tracking_feedback.set_eye_tracking_policy(policy)

    def _forward_gaze(self, x: float, y: float, timestamp: object) -> None:
        # SDK timestamps use a different clock. Keep local native receipt age
        # across Qt dispatch, without changing the provider's three-argument signal.
        received_at = self._gaze.gaze_received_at
        self._mouse.handle_gaze(x, y, timestamp, received_at)
        self._tracking_status.handle_gaze(x, y, timestamp, received_at)
        self._tracking_feedback.handle_gaze(x, y, timestamp, received_at)

    def _forward_settings_gaze(self, point: QPoint) -> None:
        if self._settings_window is not None:
            self._settings_window.handle_gaze(point, self._mouse.gaze_received_at)

    def _forward_eye_state(self, state: EyeState) -> None:
        self._mouse.handle_eye_status(state.left, state.right, state.received_at)
        for window in (self._settings_window, self._gaze_check_window):
            if window is not None:
                window.handle_eye_status(state.left, state.right, state.received_at)

    def _reset_tracking_continuity(self) -> None:
        self._mouse._eye_gate.cancel()
        self._close_tracking_overlays()
        self._interaction_overlay.clear()
        if self._settings_window is not None:
            self._settings_window._eye_gate.cancel()
        if self._gaze_check_window is not None:
            self._gaze_check_window._eye_gate.cancel()

    def _invalidate_gaze(self, received_at: float) -> None:
        self._mouse._eye_gate.invalidate_gaze(received_at)
        for window in (self._settings_window, self._gaze_check_window):
            if window is not None:
                window._eye_gate.invalidate_gaze(received_at)
        self._close_tracking_overlays()
        held = self._mouse._toolbar_selection.tracking_held
        if self._settings_window is not None:
            held |= self._settings_window._gaze_selection.tracking_held
        if not held:
            self._interaction_overlay.clear()

    def _close_tracking_overlays(self) -> None:
        self._quick_zoom.close_zoom()
        self._quick_menu.close_menu()
        self._zoom_context = None
        self._gaze_bubble.clear()
        self._tracking_status.invalidate_gaze()
        self._tracking_feedback.invalidate_gaze()

    def _set_interaction_paused(self, paused: bool) -> None:
        self._interaction_overlay.set_paused(paused)
        for widget in QApplication.allWidgets():
            if widget.property("gazeTarget") or widget.property("gazePaused"):
                set_gaze_paused(widget, paused)

    def _update_speech_settings(self, settings: object) -> None:
        self._speech.update_settings(settings)
        if self._speech_window is not None:
            self._speech_window.update_settings(self._speech.settings)
        if self._keyboard_window is not None:
            self._keyboard_window.update_settings(self._speech.settings)
        if self._controller_window is not None:
            self._controller_window.update_speech_settings(self._speech.settings)
        if self._settings_window is not None:
            self._settings_window.update_speech_settings(self._speech.settings)
        self._save_settings()

    def _save_settings(self) -> None:
        self._settings_save_failed = not save_app_settings(
            self._mouse.settings, self._speech.settings
        )
        # Keep this indicator visible even when the change came from a sidebar.
        self._settings_button.setText("Postavke *" if self._settings_save_failed else "Postavke")
        self._settings_button.setToolTip(
            "Postavke nisu sačuvane. Otvorite Postavke za ponovni pokušaj."
            if self._settings_save_failed
            else "Postavke"
        )
        if self._settings_window is not None:
            self._settings_window.set_save_error(self._settings_save_failed)
            self._settings_window.set_status(
                "Postavke nisu sačuvane." if self._settings_save_failed else "Postavke su sačuvane."
            )

    def _change_keyboard_script(self, script: str) -> None:
        self._update_speech_settings(replace(self._speech.settings, keyboard_script=script))

    def _launch_tobii_calibration(self) -> None:
        if self._settings_window is not None:
            self._settings_window.cancel_gaze_interaction()
            self._settings_window.hide()
            self._interaction_overlay.clear()

        try:
            message = launch_tobii_guest_calibration()
            self._set_status(message)
            if self._settings_window is not None:
                self._settings_window.set_status(message)
        except Exception:
            logger.exception("Tobii calibration launch failed.")
            self._set_status("Kalibracija nije uspjela.")
            if self._settings_window is not None:
                self._settings_window.set_status("Kalibracija nije uspjela.")

    def _set_status(self, text: str) -> None:
        logger.info("Status: %s", text)
        self.setToolTip(text)
        if self._restore_button is not None:
            self._restore_button.setToolTip(text)

    def _handle_eye_status_changed(self, left_open: bool, right_open: bool) -> None:
        self._tracking_status.set_eye_status(left_open, right_open)
        if (left_open, right_open) != self._mouse._eye_gate.eyes:
            self._mouse.handle_eye_status(left_open, right_open)
            for window in (self._settings_window, self._gaze_check_window):
                if window is not None:
                    window.handle_eye_status(left_open, right_open)
        if left_open and right_open:
            return

        if not eyes_usable(self._mouse.settings.eye_tracking_policy, left_open, right_open):
            self._gaze_bubble.clear()
        self._quick_zoom.close_zoom()
        self._quick_menu.close_menu()
        self._zoom_context = None
        self._mouse.cancel_zoomed_click(reset_mode=False)


def _is_visible(window: QWidget | None) -> bool:
    return window is not None and window.isVisible()
