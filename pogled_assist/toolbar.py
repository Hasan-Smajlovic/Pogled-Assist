"""Top hotbar UI."""

from __future__ import annotations

import logging
import sys
from dataclasses import replace

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QToolButton, QWidget

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
from .release_update import ReleaseUpdateError, ReleaseUpdateManager
from .settings_store import load_app_settings, save_app_settings
from .speech.speech_library import speech_library_store
from .speech.speech_service import SpeechService
from .suggestions.service import SuggestionService
from .tracking.gaze_provider import TobiiGazeProvider
from .tracking.mouse_gaze_provider import MouseGazeProvider
from .tracking.status import TrackingState, TrackingStatus
from .tracking.tobii_calibration import launch_tobii_guest_calibration, launch_tobii_settings
from .ui.controller_window import CONTROLLER_WINDOW_ACTION_PREFIX, ControllerWindow
from .ui.gaze_bubble import GazeBubbleWindow
from .ui.gaze_check_window import GazeCheckWindow
from .ui.gaze_feedback import set_gaze_feedback
from .ui.hotbar_controls import HotbarControls, no_focus_tool_window_flags
from .ui.interaction_overlay import InteractionOverlayWindow
from .ui.keyboard_window import KEYBOARD_WINDOW_ACTION_PREFIX, KeyboardWindow
from .ui.quick_action_menu import CANCEL_QUICK_ACTION, QuickActionRadialMenu
from .ui.quick_action_zoom import QuickActionZoomWindow
from .ui.settings_window import SettingsWindow
from .ui.speech_window import SPEECH_WINDOW_ACTION_PREFIX, SpeechWindow
from .windows.appbar import WindowsAppBar
from .windows.foreground_tracker import ForegroundTracker
from .windows.windows_input import WindowsInputController

logger = logging.getLogger(__name__)

SPEECH_TEST_TEXT = "Zdravo. Ovo je test govora na bosanskom jeziku."
ARABIC_SPEECH_TEST_TEXT = "مَرْحَبًا. هٰذَا اخْتِبَارٌ لِلصَّوْتِ بِاللُّغَةِ الْعَرَبِيَّةِ."


class HotbarWindow(QWidget):
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
        self._appbar = WindowsAppBar()
        self._gaze = MouseGazeProvider(self) if simulate_gaze else TobiiGazeProvider(self)
        self._initial_gaze_settings, self._initial_speech_settings = load_app_settings()
        self._speech = SpeechService()
        self._speech_test_id: int | None = None
        self._speech.playback_changed.connect(self._speech_playback_changed)
        self._settings_save_failed = False
        self._speech.update_settings(self._initial_speech_settings)
        self._speech_library_store = speech_library_store(get_project_root())
        self._speech_library_store.load()
        self._suggestions = SuggestionService(
            self, path=get_project_root() / "data" / "speech_learning.json"
        )
        self._release_update_manager = ReleaseUpdateManager(parent=self)
        self._speech_window: SpeechWindow | None = None
        self._keyboard_window: KeyboardWindow | None = None
        self._controller_window: ControllerWindow | None = None
        self._settings_window: SettingsWindow | None = None
        self._gaze_check_window: GazeCheckWindow | None = None
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

        self._build_ui()
        self._build_restore_button()
        self._connect_signals()
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
        self._closing = True
        if self._gaze_check_window is not None:
            self._gaze_check_window.close()
        if self._speech_window is not None:
            self._speech_window.close()
        if self._keyboard_window is not None:
            self._keyboard_window.close()
        if self._controller_window is not None:
            self._controller_window.close()
        if self._settings_window is not None:
            self._settings_window.close()
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
        self._gaze.gaze_updated.connect(self._mouse.handle_gaze)
        self._gaze.gaze_updated.connect(self._tracking_status.handle_gaze)
        self._gaze.eye_status_changed.connect(self._mouse.handle_eye_status)
        self._gaze.eye_status_changed.connect(self._handle_eye_status_changed)
        self._gaze.status_changed.connect(self._set_status)
        self._gaze.tracking_status_changed.connect(self._tracking_status.set_tracking_status)
        self._gaze.tracking_status_changed.connect(self._check_tracking_state)
        self._mouse.gaze_position_changed.connect(self._gaze_bubble.handle_gaze)
        self._mouse.gaze_position_changed.connect(self._quick_menu.handle_gaze)
        self._mouse.gaze_position_changed.connect(self._quick_zoom.handle_gaze)
        self._mouse.status_changed.connect(self._set_status)
        self._mouse.interaction_progress_changed.connect(self._interaction_overlay.show_progress)
        self._mouse.interaction_finished.connect(self._interaction_overlay.show_fired)
        self._mouse.interaction_cancelled.connect(self._interaction_overlay.clear)
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
        logger.info("Toolbar action requested by %s: %s", source, action)
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
        self._set_status("Otvoren je izbornik brzih radnji.")

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
        self._set_status("Prozor za govor je otvoren.")

    def _open_settings(self) -> None:
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

        window = SettingsWindow(
            self._mouse.settings,
            self._speech.settings,
            self,
            update_manager=self._release_update_manager,
            suggestions=self._suggestions,
        )
        window.gaze_settings_changed.connect(self._update_gaze_settings)
        window.speech_settings_changed.connect(self._update_speech_settings)
        window.save_retry_requested.connect(self._save_settings)
        window.calibration_requested.connect(self._launch_tobii_calibration)
        window.gaze_check_requested.connect(self._open_gaze_check)
        window.speech_test_requested.connect(self._test_current_speech_settings)
        window.update_requested.connect(self._start_release_update)
        window.quit_requested.connect(self._quit_application)
        window.closed.connect(self._settings_window_closed)
        self._mouse.gaze_position_changed.connect(window.handle_gaze)
        window.interaction_progress_changed.connect(self._interaction_overlay.show_progress)
        window.interaction_finished.connect(self._interaction_overlay.show_fired)
        window.interaction_cancelled.connect(self._interaction_overlay.clear)

        self._settings_window = window
        window.set_save_error(self._settings_save_failed)
        window.show_fullscreen_on_primary()
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
        window = GazeCheckWindow(self._mouse.settings, self, simulated=self._simulate_gaze)
        self._gaze_check_window = window
        window.closed.connect(self._gaze_check_closed)
        window.calibration_requested.connect(self._calibrate_from_gaze_check)
        self._gaze.diagnostics_updated.connect(window.handle_snapshot)
        self._gaze.eye_status_changed.connect(window.handle_eye_status)
        window.handle_tracking_status(self._check_status)
        window.handle_snapshot(self._gaze.check_snapshot())
        window.show_fullscreen_on_primary()

    def _gaze_check_closed(self) -> None:
        window = self._gaze_check_window
        if window is None:
            return
        self._gaze.diagnostics_updated.disconnect(window.handle_snapshot)
        self._gaze.eye_status_changed.disconnect(window.handle_eye_status)
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
            message = launch_tobii_settings()
        except Exception:
            logger.exception("Tobii settings launch from gaze check failed.")
            message = (
                "Otvorite Tobii ikonu pored sata, pa korisnikov profil > Test and recalibrate."
            )
            if self._gaze_check_window is not None:
                self._gaze_check_window.showNormal()
        self._set_status(message)

        if self._gaze_check_window is not None:
            self._gaze_check_window.set_calibration_notice(message)

    def _settings_window_closed(self) -> None:
        window = self._settings_window
        if window is None:
            return

        try:
            self._mouse.gaze_position_changed.disconnect(window.handle_gaze)
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

    def _start_release_update(self) -> None:
        try:
            self._release_update_manager.launch()
        except ReleaseUpdateError as error:
            logger.exception("Could not launch the release updater.")
            self._set_status("Pokretanje ažuriranja nije uspjelo.")
            if self._settings_window is not None:
                self._settings_window.show_update_error(str(error))
            return

        logger.info("Release updater started; closing the current application.")
        self._quit_application()

    def _update_gaze_settings(self, settings: object) -> None:
        self._mouse.update_settings(settings)
        self._gaze_bubble.set_enabled(bool(getattr(settings, "show_gaze_bubble", True)))
        self._interaction_overlay.set_enabled(
            bool(getattr(settings, "show_interaction_overlay", True))
        )
        if self._controller_window is not None:
            self._controller_window.update_gaze_settings(self._mouse.settings)
        self._save_settings()

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

    def _test_current_speech_settings(self) -> None:
        try:
            text = (
                ARABIC_SPEECH_TEST_TEXT
                if self._speech.settings.keyboard_script == "arabic"
                else SPEECH_TEST_TEXT
            )
            if self._speech.speak(text):
                self._speech_test_id = self._speech.request_id
                self._set_speech_test_status("Test govora je pokrenut.")
            else:
                self._set_speech_test_status(
                    "Govor nije uspio: odabrani glas nije pronađen ili se nije mogao pokrenuti.",
                    "Govor nije uspio.",
                )
        except Exception:
            logger.exception("Speech settings test failed.")
            self._set_speech_test_status("Govor nije uspio.")

    def _speech_playback_changed(self, request_id: int, state: str) -> None:
        if request_id != self._speech_test_id:
            return
        message = {
            "speaking": "Test govora je pokrenut.",
            "finished": "Test govora je završen.",
            "failed": "Govor nije uspio. Pokušajte ponovo.",
            "stopped": "Govor je zaustavljen.",
        }[state]
        self._set_speech_test_status(message)

    def _set_speech_test_status(self, text: str, settings_text: str | None = None) -> None:
        self._set_status(text)
        if self._settings_window is not None:
            self._settings_window.set_status(text if settings_text is None else settings_text)

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
        if left_open and right_open:
            return

        self._quick_zoom.close_zoom()
        self._quick_menu.close_menu()
        self._zoom_context = None
        self._mouse.cancel_zoomed_click(reset_mode=False)
        self._interaction_overlay.clear()
        if self._speech_window is not None:
            self._speech_window.cancel_gaze_interaction()
        if self._keyboard_window is not None:
            self._keyboard_window.cancel_gaze_interaction()
        if self._controller_window is not None:
            self._controller_window.cancel_gaze_interaction()
        if self._settings_window is not None:
            self._settings_window.pause_gaze_interaction()


def _is_visible(window: QWidget | None) -> bool:
    return window is not None and window.isVisible()
