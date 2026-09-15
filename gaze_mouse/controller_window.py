"""Right-side gaze-selectable controller shortcuts panel."""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import replace

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QCloseEvent, QCursor, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .appbar import ABE_RIGHT, WindowsAppBar
from .gaze_feedback import set_gaze_feedback
from .keyboard_window import NUMPAD_KEYS, SYMBOL_KEYS, _group_letters
from .mouse_controller import GazeSettings
from .speech_service import SpeechSettings
from .speech_window import BOSNIAN_LETTERS
from .windows_input import WindowsInputController

logger = logging.getLogger(__name__)

CONTROLLER_WINDOW_ACTION_PREFIX = "controller_window:"

SIDEBAR_WIDTH = 380
MIN_SIDEBAR_WIDTH = 320
MAX_SIDEBAR_WIDTH_FRACTION = 0.36
TAB_HEIGHT = 52
ACTION_MIN_HEIGHT = 76
SETTINGS_MIN_HEIGHT = 70
KEY_MIN_HEIGHT = 52
UTILITY_MIN_HEIGHT = 56
KEYBOARD_SUBTAB_HEIGHT = 46

TAB_GENERAL = "general"
TAB_KEYBOARD = "keyboard"
TAB_SPEECH = "speech"
TAB_SETTINGS = "settings"

KEYBOARD_TAB_LETTERS = "letters"
KEYBOARD_TAB_NUMPAD = "numpad"
KEYBOARD_TAB_SYMBOLS = "symbols"

GENERAL_ACTIONS = (
    ("left_click", "Left Click", "fa5s.mouse-pointer"),
    ("right_click", "Right Click", "fa5s.mouse"),
    ("double_left_click", "Double Left Click", "fa5s.hand-pointer"),
    ("enter", "ENTER", "fa5s.level-down-alt"),
    ("scroll_up", "Scroll Up", "fa5s.arrow-up"),
    ("scroll_down", "Scroll Down", "fa5s.arrow-down"),
)


class ControllerWindow(QWidget):
    """Right-side AppBar panel for common gaze shortcuts and quick settings."""

    closed = Signal()
    status_changed = Signal(str)
    speech_requested = Signal()
    gaze_settings_changed = Signal(object)

    def __init__(
        self,
        gaze_settings: GazeSettings,
        speech_settings: SpeechSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("controllerWindow")
        self.setWindowTitle("Controller")
        self.setWindowFlags(_controller_window_flags())
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)

        self._gaze_settings = replace(gaze_settings)
        self._speech_settings = replace(speech_settings)
        self._letters_per_group = max(1, self._speech_settings.letters_per_group)
        self._letter_groups = _group_letters(BOSNIAN_LETTERS, self._letters_per_group)
        self._numpad_groups = _group_letters(NUMPAD_KEYS, self._letters_per_group)
        self._symbol_groups = _group_letters(SYMBOL_KEYS, self._letters_per_group)
        self._active_tab = TAB_GENERAL
        self._keyboard_active_tab = KEYBOARD_TAB_LETTERS
        self._keyboard_active_group_index: int | None = None
        self._action_buttons: dict[str, QToolButton] = {}
        self._dynamic_actions: set[str] = set()
        self._gaze_target_action: str | None = None
        self._keyboard_tab_buttons: dict[str, QToolButton] = {}
        self._appbar = WindowsAppBar()
        self._input: WindowsInputController | None = None
        self._target_window: int | None = None
        self._target_cursor_position: tuple[int, int] | None = None
        self._full_height = False
        self._reserved_top_height = 0
        self._precision_zoom_button: QToolButton | None = None
        self._gaze_cursor_button: QToolButton | None = None

        self._build_ui()
        self._show_general_tab()
        logger.info("Controller sidebar initialized.")

    def show_sidebar(self, *, full_height: bool = False) -> None:
        self._full_height = bool(full_height)
        self._ensure_input_controller()
        self._remember_foreground_target()
        if self._full_height:
            self._appbar.unregister()
        self._position_on_primary_screen()
        self.show()
        self.raise_()
        self._register_appbar()
        self._restore_target_window()
        logger.info("Controller sidebar shown.")

    def hide_sidebar(self) -> None:
        self._set_gaze_target_action(None)
        self._appbar.unregister()
        self.hide()
        logger.info("Controller sidebar hidden.")

    def set_full_height(self, full_height: bool) -> None:
        full_height = bool(full_height)
        if self._full_height == full_height:
            return

        self._full_height = full_height
        if not self.isVisible():
            return

        if self._full_height:
            self._appbar.unregister()
        self._position_on_primary_screen()
        self._register_appbar()
        mode = "full screen height" if self._full_height else "available work area height"
        logger.info("Controller sidebar resized to %s.", mode)

    def set_reserved_top_height(self, height: int) -> None:
        height = max(0, int(height))
        if height == self._reserved_top_height:
            return

        self._reserved_top_height = height
        if self.isVisible() and not self._full_height:
            self._position_on_primary_screen()
            self._register_appbar()

    def set_target_window(self, hwnd: int | None) -> None:
        if hwnd is None:
            return
        if hwnd == self._target_window:
            return

        self._target_window = hwnd
        logger.info("Controller target window set externally: hwnd=%s.", hwnd)

    def set_target_cursor_position(self, position: tuple[int, int] | None) -> None:
        if position is None:
            return

        x, y = position
        target = (int(x), int(y))
        if target == self._target_cursor_position:
            return

        self._target_cursor_position = target
        logger.debug("Controller target cursor set externally: x=%s y=%s.", x, y)

    def update_gaze_settings(self, settings: GazeSettings) -> None:
        self._gaze_settings = replace(settings)
        self._sync_settings_buttons()
        logger.info("Controller sidebar settings updated: %s", self._gaze_settings)

    def update_speech_settings(self, settings: SpeechSettings) -> None:
        old_letters_per_group = self._letters_per_group
        self._speech_settings = replace(settings)
        self._letters_per_group = max(1, self._speech_settings.letters_per_group)
        if old_letters_per_group != self._letters_per_group:
            self._letter_groups = _group_letters(BOSNIAN_LETTERS, self._letters_per_group)
            self._numpad_groups = _group_letters(NUMPAD_KEYS, self._letters_per_group)
            self._symbol_groups = _group_letters(SYMBOL_KEYS, self._letters_per_group)
            self._keyboard_active_group_index = None
            if self._active_tab == TAB_KEYBOARD:
                self._show_keyboard_current_group_level()

        logger.info("Controller sidebar speech settings updated: %s", self._speech_settings)

    def action_at_global_point(self, point: QPoint) -> str | None:
        for action, button in self._action_buttons.items():
            if not button.isVisible() or not button.isEnabled():
                continue

            top_left = button.mapToGlobal(QPoint(0, 0))
            rect = QRect(top_left, button.size())
            if rect.contains(point):
                self._set_gaze_target_action(action)
                return action

        self._set_gaze_target_action(None)
        return None

    def action_center_at_global_point(self, action: str, point: QPoint) -> QPoint | None:
        button = self._action_buttons.get(action)
        if button is None or not button.isVisible() or not button.isEnabled():
            return None

        top_left = button.mapToGlobal(QPoint(0, 0))
        rect = QRect(top_left, button.size())
        if not rect.contains(point):
            return None

        return rect.center()

    def contains_global_point(self, point: QPoint) -> bool:
        if not self.isVisible():
            return False

        top_left = self.mapToGlobal(QPoint(0, 0))
        return QRect(top_left, self.size()).contains(point)

    def handle_gaze_action(self, action: str) -> None:
        if not action.startswith(CONTROLLER_WINDOW_ACTION_PREFIX):
            return

        logger.info("Controller sidebar gaze action requested: %s", action)
        self._trigger_action(action, source="gaze")

    def cancel_gaze_interaction(self) -> None:
        self._set_gaze_target_action(None)

    def closeEvent(self, event: QCloseEvent) -> None:
        logger.info("Controller sidebar close event received.")
        self.hide_sidebar()
        self.closed.emit()
        super().closeEvent(event)

    def _build_ui(self) -> None:
        self.setStyleSheet(
            """
            QWidget#controllerWindow {
                background: #111318;
                color: #f6f7fb;
                font-family: Segoe UI, Arial, sans-serif;
                font-size: 13px;
            }
            QToolButton {
                background: #1c2029;
                border: 1px solid #303747;
                border-radius: 8px;
                color: #eef2f8;
                font-weight: 700;
                padding: 6px;
            }
            QToolButton:hover {
                background: #262c38;
                border-color: #4c5970;
            }
            QToolButton:checked {
                background: #245f9f;
                border-color: #67b7dc;
                color: #ffffff;
            }
            QToolButton#tabButton {
                font-size: 13px;
            }
            QToolButton#shortcutButton {
                font-size: 16px;
            }
            QToolButton#keyboardSubTabButton {
                font-size: 12px;
            }
            QToolButton#groupButton {
                font-size: 17px;
            }
            QToolButton#keyButton {
                font-size: 21px;
            }
            QToolButton#utilityButton {
                background: #2b1f27;
                border-color: #684354;
                font-size: 15px;
            }
            QToolButton#checkButton {
                background: #17212b;
                border-color: #345164;
                font-size: 15px;
                text-align: left;
            }
            QToolButton#checkButton:checked {
                background: #245f9f;
                border-color: #67b7dc;
            }
            QToolButton[gazeTarget="true"][gazePulse="0"] {
                background: #f0c84a;
                border: 3px solid #ffe58a;
                color: #111318;
            }
            QToolButton[gazeTarget="true"][gazePulse="1"] {
                background: #16a34a;
                border: 3px solid #bbf7d0;
                color: #ffffff;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        tab_row = QHBoxLayout()
        tab_row.setContentsMargins(0, 0, 0, 0)
        tab_row.setSpacing(8)
        self._tab_buttons: dict[str, QToolButton] = {}
        for tab, label in (
            (TAB_GENERAL, "General"),
            (TAB_KEYBOARD, "Keyboard"),
            (TAB_SPEECH, "Speech"),
            (TAB_SETTINGS, "Settings"),
        ):
            button = self._make_button(
                label,
                self._action(f"tab:{tab}"),
                "tabButton",
                minimum_height=TAB_HEIGHT,
                dynamic=False,
            )
            button.setCheckable(True)
            self._tab_buttons[tab] = button
            tab_row.addWidget(button, 1)

        self._content_host = QWidget(self)
        self._content_host.setStyleSheet("background: transparent;")
        self._content_layout = QGridLayout(self._content_host)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setHorizontalSpacing(8)
        self._content_layout.setVerticalSpacing(8)

        root.addLayout(tab_row)
        root.addWidget(self._content_host, 1)

    def _show_general_tab(self) -> None:
        self._active_tab = TAB_GENERAL
        self._clear_dynamic_buttons()
        self._sync_tabs()
        self._set_grid_stretch(len(GENERAL_ACTIONS), 2)

        for index, (command, label, icon_name) in enumerate(GENERAL_ACTIONS):
            button = self._make_button(
                label,
                self._action(command),
                "shortcutButton",
                minimum_height=ACTION_MIN_HEIGHT,
                dynamic=True,
                icon_name=icon_name,
            )
            self._content_layout.addWidget(button, index // 2, index % 2)

    def _show_keyboard_tab(self) -> None:
        self._keyboard_active_tab = KEYBOARD_TAB_LETTERS
        self._keyboard_active_group_index = None
        self._show_keyboard_letter_groups()

    def _show_keyboard_letter_groups(self) -> None:
        self._active_tab = TAB_KEYBOARD
        self._keyboard_active_tab = KEYBOARD_TAB_LETTERS
        self._keyboard_active_group_index = None
        self._clear_dynamic_buttons()
        self._sync_tabs()
        self._add_keyboard_subtabs()

        columns = 2
        start_row = 1
        rows = self._set_grid_stretch(len(self._letter_groups), columns, start_row=start_row)
        for index, group in enumerate(self._letter_groups):
            button = self._make_button(
                " ".join(group),
                self._action(f"keyboard_group:{index}"),
                "groupButton",
                minimum_height=KEY_MIN_HEIGHT,
                dynamic=True,
            )
            self._content_layout.addWidget(button, start_row + index // columns, index % columns)

        self._add_keyboard_utility_row(start_row + rows, groups_visible=False)

    def _show_keyboard_letter_group(self, group_index: int) -> None:
        if group_index < 0 or group_index >= len(self._letter_groups):
            return

        self._active_tab = TAB_KEYBOARD
        self._keyboard_active_tab = KEYBOARD_TAB_LETTERS
        self._keyboard_active_group_index = group_index
        self._clear_dynamic_buttons()
        self._sync_tabs()
        self._add_keyboard_subtabs()

        group = self._letter_groups[group_index]
        columns = 3
        start_row = 1
        rows = self._set_grid_stretch(len(group), columns, start_row=start_row)
        for index, letter in enumerate(group):
            button = self._make_button(
                letter,
                self._action(f"keyboard_letter:{group_index}:{index}"),
                "keyButton",
                minimum_height=KEY_MIN_HEIGHT,
                dynamic=True,
            )
            self._content_layout.addWidget(button, start_row + index // columns, index % columns)

        self._add_keyboard_utility_row(start_row + rows, groups_visible=True)

    def _show_keyboard_numpad(self) -> None:
        self._show_keyboard_group_buttons(
            KEYBOARD_TAB_NUMPAD,
            self._numpad_groups,
            "keyboard_numpad_group",
            columns=2,
        )

    def _show_keyboard_symbols(self) -> None:
        self._show_keyboard_group_buttons(
            KEYBOARD_TAB_SYMBOLS,
            self._symbol_groups,
            "keyboard_symbol_group",
            columns=2,
        )

    def _show_keyboard_numpad_group(self, group_index: int) -> None:
        self._show_keyboard_key_group(
            KEYBOARD_TAB_NUMPAD,
            self._numpad_groups,
            group_index,
            "keyboard_numpad",
        )

    def _show_keyboard_symbol_group(self, group_index: int) -> None:
        self._show_keyboard_key_group(
            KEYBOARD_TAB_SYMBOLS,
            self._symbol_groups,
            group_index,
            "keyboard_symbol",
        )

    def _show_keyboard_group_buttons(
        self,
        tab: str,
        groups: list[list[str]],
        action_prefix: str,
        *,
        columns: int,
    ) -> None:
        self._active_tab = TAB_KEYBOARD
        self._keyboard_active_tab = tab
        self._keyboard_active_group_index = None
        self._clear_dynamic_buttons()
        self._sync_tabs()
        self._add_keyboard_subtabs()

        start_row = 1
        rows = self._set_grid_stretch(len(groups), columns, start_row=start_row)
        for index, group in enumerate(groups):
            button = self._make_button(
                " ".join(group),
                self._action(f"{action_prefix}:{index}"),
                "groupButton",
                minimum_height=KEY_MIN_HEIGHT,
                dynamic=True,
            )
            self._content_layout.addWidget(button, start_row + index // columns, index % columns)

        self._add_keyboard_utility_row(start_row + rows, groups_visible=False)

    def _show_keyboard_key_group(
        self,
        tab: str,
        groups: list[list[str]],
        group_index: int,
        action_prefix: str,
    ) -> None:
        if group_index < 0 or group_index >= len(groups):
            return

        self._active_tab = TAB_KEYBOARD
        self._keyboard_active_tab = tab
        self._keyboard_active_group_index = group_index
        self._clear_dynamic_buttons()
        self._sync_tabs()
        self._add_keyboard_subtabs()

        group = groups[group_index]
        columns = 3
        start_row = 1
        rows = self._set_grid_stretch(len(group), columns, start_row=start_row)
        for index, label in enumerate(group):
            button = self._make_button(
                label,
                self._action(f"{action_prefix}:{index}"),
                "keyButton",
                minimum_height=KEY_MIN_HEIGHT,
                dynamic=True,
            )
            self._content_layout.addWidget(button, start_row + index // columns, index % columns)

        self._add_keyboard_utility_row(start_row + rows, groups_visible=True)

    def _add_keyboard_subtabs(self) -> None:
        self._keyboard_tab_buttons = {}
        for index, (tab, label) in enumerate(
            (
                (KEYBOARD_TAB_LETTERS, "Letters"),
                (KEYBOARD_TAB_NUMPAD, "Numpad"),
                (KEYBOARD_TAB_SYMBOLS, "Symbols"),
            )
        ):
            button = self._make_button(
                label,
                self._action(f"keyboard_tab:{tab}"),
                "keyboardSubTabButton",
                minimum_height=KEYBOARD_SUBTAB_HEIGHT,
                dynamic=True,
            )
            button.setCheckable(True)
            button.setChecked(tab == self._keyboard_active_tab)
            self._keyboard_tab_buttons[tab] = button
            self._content_layout.addWidget(button, 0, index)

    def _add_keyboard_utility_row(self, row: int, *, groups_visible: bool) -> None:
        groups_button = self._make_button(
            "Groups",
            self._action("keyboard_groups"),
            "utilityButton",
            minimum_height=UTILITY_MIN_HEIGHT,
            dynamic=True,
        )
        groups_button.setVisible(groups_visible)
        space_button = self._make_button(
            "Space",
            self._action("keyboard_space"),
            "utilityButton",
            minimum_height=UTILITY_MIN_HEIGHT,
            dynamic=True,
        )
        backspace_button = self._make_button(
            "Backspace",
            self._action("keyboard_backspace"),
            "utilityButton",
            minimum_height=UTILITY_MIN_HEIGHT,
            dynamic=True,
        )
        self._content_layout.addWidget(groups_button, row, 0)
        self._content_layout.addWidget(space_button, row, 1)
        self._content_layout.addWidget(backspace_button, row, 2)

    def _show_keyboard_current_group_level(self) -> None:
        if self._keyboard_active_tab == KEYBOARD_TAB_NUMPAD:
            self._show_keyboard_numpad()
        elif self._keyboard_active_tab == KEYBOARD_TAB_SYMBOLS:
            self._show_keyboard_symbols()
        else:
            self._show_keyboard_letter_groups()

    def _show_settings_tab(self) -> None:
        self._active_tab = TAB_SETTINGS
        self._clear_dynamic_buttons()
        self._sync_tabs()
        self._set_grid_stretch(2, 1)

        self._precision_zoom_button = self._make_button(
            "",
            self._action("settings:precision_zoom"),
            "checkButton",
            minimum_height=SETTINGS_MIN_HEIGHT,
            dynamic=True,
        )
        self._precision_zoom_button.setCheckable(True)

        self._gaze_cursor_button = self._make_button(
            "",
            self._action("settings:gaze_cursor"),
            "checkButton",
            minimum_height=SETTINGS_MIN_HEIGHT,
            dynamic=True,
        )
        self._gaze_cursor_button.setCheckable(True)

        self._content_layout.addWidget(self._precision_zoom_button, 0, 0)
        self._content_layout.addWidget(self._gaze_cursor_button, 1, 0)
        self._sync_settings_buttons()

    def _trigger_action(self, action: str, *, source: str = "unknown") -> None:
        command = action.removeprefix(CONTROLLER_WINDOW_ACTION_PREFIX)

        if command == "tab:general":
            self._show_general_tab()
        elif command == "tab:keyboard":
            self._show_keyboard_tab()
        elif command == "tab:speech":
            self.speech_requested.emit()
        elif command == "tab:settings":
            self._show_settings_tab()
        elif command == "keyboard_tab:letters":
            self._show_keyboard_letter_groups()
        elif command == "keyboard_tab:numpad":
            self._show_keyboard_numpad()
        elif command == "keyboard_tab:symbols":
            self._show_keyboard_symbols()
        elif command == "keyboard_groups":
            self._show_keyboard_current_group_level()
        elif command == "keyboard_space":
            self._type_text(" ")
        elif command == "keyboard_backspace":
            self._press_key("backspace")
        elif command.startswith("keyboard_group:"):
            self._show_keyboard_letter_group(int(command.split(":", 1)[1]))
        elif command.startswith("keyboard_letter:"):
            _prefix, group_text, letter_text = command.split(":", 2)
            group_index = int(group_text)
            letter_index = int(letter_text)
            self._type_text(self._letter_groups[group_index][letter_index])
            self._show_keyboard_letter_groups()
        elif command.startswith("keyboard_numpad_group:"):
            self._show_keyboard_numpad_group(int(command.split(":", 1)[1]))
        elif command.startswith("keyboard_symbol_group:"):
            self._show_keyboard_symbol_group(int(command.split(":", 1)[1]))
        elif command.startswith("keyboard_numpad:"):
            key = self._numpad_groups[self._keyboard_active_group_index or 0][
                int(command.split(":", 1)[1])
            ]
            self._type_key_label(key)
            self._show_keyboard_numpad()
        elif command.startswith("keyboard_symbol:"):
            key = self._symbol_groups[self._keyboard_active_group_index or 0][
                int(command.split(":", 1)[1])
            ]
            self._type_text(key)
            self._show_keyboard_symbols()
        elif command == "left_click":
            self._click_current("left", clicks=1, source=source)
        elif command == "right_click":
            self._click_current("right", clicks=1, source=source)
        elif command == "double_left_click":
            self._click_current("left", clicks=2, source=source)
        elif command == "enter":
            self._press_enter()
        elif command == "scroll_up":
            self._scroll(3)
        elif command == "scroll_down":
            self._scroll(-3)
        elif command == "settings:precision_zoom":
            self._toggle_precision_zoom()
        elif command == "settings:gaze_cursor":
            self._toggle_gaze_cursor()

    def _type_key_label(self, label: str) -> None:
        if label == "Enter":
            self._press_key("enter")
        else:
            self._type_text(label)

    def _type_text(self, text: str) -> None:
        self._ensure_input_controller()
        if self._input is None:
            self._emit_status("Controller keyboard input is unavailable.")
            return

        try:
            self._restore_target_window()
            self._input.type_text(text)
            self._emit_status(f"Typed {text!r}.")
        except Exception as exc:
            logger.exception("Controller keyboard text input failed.")
            self._emit_status(f"Keyboard input failed: {exc}")

    def _press_key(self, key: str) -> None:
        self._ensure_input_controller()
        if self._input is None:
            self._emit_status("Controller keyboard input is unavailable.")
            return

        try:
            self._restore_target_window()
            self._input.press_key(key)
            self._emit_status(f"Pressed {key}.")
        except Exception as exc:
            logger.exception("Controller keyboard key press failed.")
            self._emit_status(f"Keyboard key failed: {exc}")

    def _click_current(self, button: str, *, clicks: int, source: str) -> None:
        self._ensure_input_controller()
        if self._input is None:
            self._emit_status("Controller input is unavailable.")
            return

        try:
            target = self._click_target_for_source(source)
            if source == "mouse" and target is None:
                self._emit_status("No external cursor target recorded yet.")
                return

            if target is None:
                self._input.click_current(button=button, clicks=clicks, interval=0.04)
            else:
                self._input.click(
                    target[0],
                    target[1],
                    button=button,
                    clicks=clicks,
                    interval=0.04,
                )
            label = "Double left click" if clicks > 1 else f"{button.title()} click"
            self._emit_status(f"{label} sent.")
        except Exception as exc:
            logger.exception("Controller click failed.")
            self._emit_status(f"Controller click failed: {exc}")

    def _click_target_for_source(self, source: str) -> tuple[int, int] | None:
        if source == "mouse":
            return self._target_cursor_position
        if self._cursor_is_over_panel():
            return self._target_cursor_position
        return None

    def _press_enter(self) -> None:
        self._ensure_input_controller()
        if self._input is None:
            self._emit_status("Controller input is unavailable.")
            return

        try:
            self._restore_target_window()
            self._input.press_key("enter")
            self._emit_status("ENTER sent.")
        except Exception as exc:
            logger.exception("Controller ENTER failed.")
            self._emit_status(f"ENTER failed: {exc}")

    def _scroll(self, units: int) -> None:
        self._ensure_input_controller()
        if self._input is None:
            self._emit_status("Controller input is unavailable.")
            return

        try:
            self._input.scroll(units)
            direction = "up" if units > 0 else "down"
            self._emit_status(f"Scroll {direction} sent.")
        except Exception as exc:
            logger.exception("Controller scroll failed.")
            self._emit_status(f"Scroll failed: {exc}")

    def _toggle_precision_zoom(self) -> None:
        enabled = not self._gaze_settings.use_precision_zoom
        self._gaze_settings = replace(self._gaze_settings, use_precision_zoom=enabled)
        self._sync_settings_buttons()
        self.gaze_settings_changed.emit(replace(self._gaze_settings))
        state = "enabled" if enabled else "disabled"
        self._emit_status(f"Gaze focus mode {state}.")

    def _toggle_gaze_cursor(self) -> None:
        enabled = not self._gaze_settings.show_gaze_bubble
        self._gaze_settings = replace(self._gaze_settings, show_gaze_bubble=enabled)
        self._sync_settings_buttons()
        self.gaze_settings_changed.emit(replace(self._gaze_settings))
        state = "enabled" if enabled else "disabled"
        self._emit_status(f"Gaze cursor {state}.")

    def _ensure_input_controller(self) -> None:
        if self._input is not None:
            return

        try:
            self._input = WindowsInputController()
        except Exception as exc:
            logger.exception("Could not initialize controller input backend.")
            self._emit_status(f"Controller input unavailable: {exc}")

    def _emit_status(self, text: str) -> None:
        logger.info("Controller sidebar status: %s", text)
        self.setToolTip(text)
        self.status_changed.emit(text)

    def _remember_foreground_target(self) -> None:
        if self._input is None:
            return

        hwnd = self._input.foreground_window()
        if hwnd is None:
            return
        if self._input.belongs_to_current_process(hwnd):
            logger.info("Controller foreground target is an app window; keeping previous target.")
            return

        self._target_window = hwnd
        logger.info("Controller target window captured: hwnd=%s.", hwnd)

    def _restore_target_window(self) -> bool:
        if self._input is None:
            return False

        current = self._input.foreground_window()
        if current is not None and not self._input.belongs_to_current_process(current):
            self._target_window = current
            return True

        if self._target_window is None:
            logger.warning("Controller has no external target window to restore.")
            return False

        if not self._input.is_window(self._target_window):
            logger.warning(
                "Controller target window is no longer valid: hwnd=%s.", self._target_window
            )
            self._target_window = None
            return False

        if current == self._target_window:
            return True

        restored = self._input.set_foreground_window(self._target_window)
        if restored:
            time.sleep(0.01)
        else:
            logger.warning(
                "Could not restore controller target window: hwnd=%s.", self._target_window
            )
        return restored

    def _make_button(
        self,
        text: str,
        action: str,
        object_name: str,
        *,
        minimum_height: int,
        dynamic: bool,
        icon_name: str = "",
    ) -> QToolButton:
        parent = self._content_host if dynamic else self
        button = QToolButton(parent)
        button.setObjectName(object_name)
        button.setText(text)
        button.setToolButtonStyle(
            Qt.ToolButtonTextUnderIcon if icon_name else Qt.ToolButtonTextOnly
        )
        button.setIconSize(QSize(24, 24))
        if icon_name:
            button.setIcon(self._icon(icon_name))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.NoFocus)
        button.setMinimumHeight(minimum_height)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        button.setProperty("gazeTarget", False)
        button.setProperty("gazePulse", "")
        button.clicked.connect(
            lambda _checked=False, item=action: self._trigger_action(
                item,
                source="mouse",
            )
        )
        self._action_buttons[action] = button
        if dynamic:
            self._dynamic_actions.add(action)
        return button

    def _clear_dynamic_buttons(self) -> None:
        self._set_gaze_target_action(None)
        for action in self._dynamic_actions:
            self._action_buttons.pop(action, None)
        self._dynamic_actions.clear()

        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._precision_zoom_button = None
        self._gaze_cursor_button = None
        self._keyboard_tab_buttons = {}

    def _set_grid_stretch(self, item_count: int, columns: int, *, start_row: int = 0) -> int:
        for column in range(4):
            self._content_layout.setColumnStretch(column, 0)
        for row in range(48):
            self._content_layout.setRowStretch(row, 0)

        rows = max(1, (max(1, item_count) + max(1, columns) - 1) // max(1, columns))
        for column in range(columns):
            self._content_layout.setColumnStretch(column, 1)
        for row in range(start_row, start_row + rows):
            self._content_layout.setRowStretch(row, 1)
        return rows

    def _sync_tabs(self) -> None:
        for tab, button in self._tab_buttons.items():
            button.setChecked(tab == self._active_tab)

    def _sync_settings_buttons(self) -> None:
        precision = getattr(self, "_precision_zoom_button", None)
        if precision is not None:
            precision.setChecked(self._gaze_settings.use_precision_zoom)
            precision.setText(
                _checkbox_text(
                    "Gaze focus mode",
                    self._gaze_settings.use_precision_zoom,
                )
            )

        cursor = getattr(self, "_gaze_cursor_button", None)
        if cursor is not None:
            cursor.setChecked(self._gaze_settings.show_gaze_bubble)
            cursor.setText(
                _checkbox_text(
                    "Gaze cursor",
                    self._gaze_settings.show_gaze_bubble,
                )
            )

    def _set_gaze_target_action(self, action: str | None) -> None:
        if action == self._gaze_target_action:
            return

        if self._gaze_target_action is not None:
            previous = self._action_buttons.get(self._gaze_target_action)
            if previous is not None:
                set_gaze_feedback(previous, False)

        self._gaze_target_action = action

        if self._gaze_target_action is not None:
            current = self._action_buttons.get(self._gaze_target_action)
            if current is not None:
                set_gaze_feedback(current, True)

    def _action(self, name: str) -> str:
        return f"{CONTROLLER_WINDOW_ACTION_PREFIX}{name}"

    def _icon(self, icon_name: str) -> QIcon:
        try:
            import qtawesome as qta

            return qta.icon(icon_name, color="#f8f7f2")
        except Exception:
            logger.exception("Could not load qtawesome icon %s; using fallback.", icon_name)
            return self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)

    def _cursor_is_over_panel(self) -> bool:
        if not self.isVisible():
            return False

        point = QCursor.pos()
        top_left = self.mapToGlobal(QPoint(0, 0))
        return QRect(top_left, self.size()).contains(point)

    def _position_on_primary_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        geometry = screen.geometry() if self._full_height else screen.availableGeometry()
        if not self._full_height and self._reserved_top_height > 0:
            screen_geometry = screen.geometry()
            top = max(geometry.top(), screen_geometry.top() + self._reserved_top_height)
            geometry = QRect(
                geometry.left(),
                top,
                geometry.width(),
                max(1, geometry.bottom() - top + 1),
            )
        width = min(
            SIDEBAR_WIDTH,
            max(MIN_SIDEBAR_WIDTH, int(geometry.width() * MAX_SIDEBAR_WIDTH_FRACTION)),
        )
        self.setGeometry(
            geometry.right() - width + 1,
            geometry.top(),
            width,
            geometry.height(),
        )

    def _register_appbar(self) -> None:
        if self._full_height:
            self._appbar.unregister()
            self._emit_status("Controller panel using full screen height.")
            return

        if self._appbar.register(int(self.winId()), self.width(), edge=ABE_RIGHT):
            self._emit_status("Controller panel reserved right work area.")
        elif sys.platform == "win32":
            self._emit_status("Controller panel shown without AppBar reservation.")


def _checkbox_text(label: str, checked: bool) -> str:
    mark = "X" if checked else " "
    return f"[{mark}] {label}"


def _controller_window_flags() -> Qt.WindowFlags:
    flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
    no_focus = getattr(Qt, "WindowDoesNotAcceptFocus", None)
    if no_focus is None:
        no_focus = getattr(Qt.WindowType, "WindowDoesNotAcceptFocus", None)
    if no_focus is not None:
        flags |= no_focus
    return flags
