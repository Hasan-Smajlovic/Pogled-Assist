"""Right-side gaze-selectable keyboard panel."""

from __future__ import annotations

import logging
import math
import sys
import time
from dataclasses import replace

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..speech.speech_service import SpeechSettings
from ..windows.appbar import ABE_RIGHT, WindowsAppBar
from ..windows.windows_input import WindowsInputController
from .gaze_feedback import set_gaze_feedback
from .speech_window import BOSNIAN_LETTERS

logger = logging.getLogger(__name__)

KEYBOARD_WINDOW_ACTION_PREFIX = "keyboard_window:"

SIDEBAR_WIDTH = 380
MIN_SIDEBAR_WIDTH = 320
MAX_SIDEBAR_WIDTH_FRACTION = 0.36
KEY_MIN_HEIGHT = 54
UTILITY_MIN_HEIGHT = 58
TAB_HEIGHT = 52

TAB_LETTERS = "letters"
TAB_NUMPAD = "numpad"
TAB_SYMBOLS = "symbols"

NUMPAD_KEYS = [
    "7",
    "8",
    "9",
    "4",
    "5",
    "6",
    "1",
    "2",
    "3",
    "0",
    ".",
    "Potvrdi",
    "+",
    "-",
    "*",
    "/",
    "=",
]

SYMBOL_KEYS = [
    ".",
    ",",
    "@",
    "/",
    "?",
    "!",
    "$",
    "%",
    "&",
    "*",
    "(",
    ")",
    "-",
    "_",
    "+",
    "=",
    ":",
    ";",
    "'",
    '"',
    "#",
    "\\",
    "|",
    "<",
    ">",
    "[",
    "]",
    "{",
    "}",
    "~",
    "`",
    "^",
]


class KeyboardWindow(QWidget):
    """Right-side AppBar keyboard that can be selected by mouse or gaze."""

    closed = Signal()
    status_changed = Signal(str)
    interaction_context_changed = Signal()
    mouse_action_started = Signal()

    def __init__(
        self,
        settings: SpeechSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("keyboardWindow")
        self.setWindowTitle("Tastatura")
        self.setWindowFlags(_keyboard_window_flags())
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)

        self._settings = replace(settings)
        self._letters_per_group = max(1, self._settings.letters_per_group)
        self._letter_groups = _group_letters(BOSNIAN_LETTERS, self._letters_per_group)
        self._numpad_groups = _group_letters(NUMPAD_KEYS, self._letters_per_group)
        self._symbol_groups = _group_letters(SYMBOL_KEYS, self._letters_per_group)
        self._active_tab = TAB_LETTERS
        self._active_group_index: int | None = None
        self._action_buttons: dict[str, QToolButton] = {}
        self._dynamic_actions: set[str] = set()
        self._gaze_target_action: str | None = None
        self._appbar = WindowsAppBar()
        self._input: WindowsInputController | None = None
        self._target_window: int | None = None
        self._full_height = False
        self._reserved_top_height = 0

        self._build_ui()
        self._show_letter_groups()
        logger.info("Keyboard sidebar initialized.")

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
        logger.info("Keyboard sidebar shown.")

    def hide_sidebar(self) -> None:
        self._set_gaze_target_action(None)
        self._appbar.unregister()
        self.hide()
        logger.info("Keyboard sidebar hidden.")

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
        logger.info("Keyboard sidebar resized to %s.", mode)

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
        logger.info("Keyboard target window set externally: hwnd=%s.", hwnd)

    def update_settings(self, settings: SpeechSettings) -> None:
        old_letters_per_group = self._letters_per_group
        self._settings = replace(settings)
        self._letters_per_group = max(1, self._settings.letters_per_group)
        if old_letters_per_group != self._letters_per_group:
            self._letter_groups = _group_letters(BOSNIAN_LETTERS, self._letters_per_group)
            self._numpad_groups = _group_letters(NUMPAD_KEYS, self._letters_per_group)
            self._symbol_groups = _group_letters(SYMBOL_KEYS, self._letters_per_group)
            self._active_group_index = None
            self._show_current_group_level()

        logger.info("Keyboard sidebar settings updated: %s", self._settings)

    def action_at_global_point(self, point: QPoint) -> str | None:
        for action, button in self._action_buttons.items():
            if not button.isVisible() or not button.isEnabled():
                continue

            top_left = button.mapToGlobal(QPoint(0, 0))
            rect = QRect(top_left, button.size())
            if rect.contains(point):
                return action

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
        if not action.startswith(KEYBOARD_WINDOW_ACTION_PREFIX):
            return

        logger.info("Keyboard sidebar gaze action requested: %s", action)
        self._trigger_action(action)

    def cancel_gaze_interaction(self) -> None:
        self._set_gaze_target_action(None)

    def set_gaze_target_action(self, action: str | None) -> None:
        self._set_gaze_target_action(action)

    def closeEvent(self, event: QCloseEvent) -> None:
        logger.info("Keyboard sidebar close event received.")
        self.hide_sidebar()
        self.closed.emit()
        super().closeEvent(event)

    def _build_ui(self) -> None:
        self.setStyleSheet(
            """
            QWidget#keyboardWindow {
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
            QToolButton#groupButton {
                font-size: 19px;
            }
            QToolButton#keyButton {
                font-size: 22px;
            }
            QToolButton#utilityButton {
                background: #2b1f27;
                border-color: #684354;
                font-size: 16px;
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
            (TAB_LETTERS, "Slova"),
            (TAB_NUMPAD, "Brojevi"),
            (TAB_SYMBOLS, "Znakovi"),
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

        self._key_host = QWidget(self)
        self._key_host.setStyleSheet("background: transparent;")
        self._key_layout = QGridLayout(self._key_host)
        self._key_layout.setContentsMargins(0, 0, 0, 0)
        self._key_layout.setHorizontalSpacing(8)
        self._key_layout.setVerticalSpacing(8)

        utility_row = QHBoxLayout()
        utility_row.setContentsMargins(0, 0, 0, 0)
        utility_row.setSpacing(8)
        self._groups_button = self._make_button(
            "Grupe",
            self._action("groups"),
            "utilityButton",
            minimum_height=UTILITY_MIN_HEIGHT,
            dynamic=False,
        )
        self._space_button = self._make_button(
            "Razmak",
            self._action("space"),
            "utilityButton",
            minimum_height=UTILITY_MIN_HEIGHT,
            dynamic=False,
        )
        self._backspace_button = self._make_button(
            "Obriši",
            self._action("backspace"),
            "utilityButton",
            minimum_height=UTILITY_MIN_HEIGHT,
            dynamic=False,
        )
        utility_row.addWidget(self._groups_button, 1)
        utility_row.addWidget(self._space_button, 2)
        utility_row.addWidget(self._backspace_button, 2)

        root.addLayout(tab_row)
        root.addWidget(self._key_host, 1)
        root.addLayout(utility_row)

    def _show_letter_groups(self) -> None:
        self._active_tab = TAB_LETTERS
        self._active_group_index = None
        self._clear_dynamic_buttons()
        self._sync_tabs()
        self._groups_button.setVisible(False)

        columns = 2
        self._set_grid_stretch(len(self._letter_groups), columns)
        for index, group in enumerate(self._letter_groups):
            button = self._make_button(
                " ".join(group),
                self._action(f"group:{index}"),
                "groupButton",
                minimum_height=KEY_MIN_HEIGHT,
                dynamic=True,
            )
            self._key_layout.addWidget(button, index // columns, index % columns)

    def _show_letter_group(self, group_index: int) -> None:
        if group_index < 0 or group_index >= len(self._letter_groups):
            return

        self._active_tab = TAB_LETTERS
        self._active_group_index = group_index
        self._clear_dynamic_buttons()
        self._sync_tabs()
        self._groups_button.setVisible(True)

        group = self._letter_groups[group_index]
        columns = 3
        self._set_grid_stretch(len(group), columns)
        for index, letter in enumerate(group):
            button = self._make_button(
                letter,
                self._action(f"letter:{group_index}:{index}"),
                "keyButton",
                minimum_height=KEY_MIN_HEIGHT,
                dynamic=True,
            )
            self._key_layout.addWidget(button, index // columns, index % columns)

    def _show_numpad(self) -> None:
        self._active_tab = TAB_NUMPAD
        self._active_group_index = None
        self._show_group_buttons(self._numpad_groups, "numpad_group", columns=2)

    def _show_symbols(self) -> None:
        self._active_tab = TAB_SYMBOLS
        self._active_group_index = None
        self._show_group_buttons(self._symbol_groups, "symbol_group", columns=2)

    def _show_numpad_group(self, group_index: int) -> None:
        self._show_key_group(TAB_NUMPAD, self._numpad_groups, group_index, "numpad")

    def _show_symbol_group(self, group_index: int) -> None:
        self._show_key_group(TAB_SYMBOLS, self._symbol_groups, group_index, "symbol")

    def _show_group_buttons(
        self, groups: list[list[str]], action_prefix: str, columns: int
    ) -> None:
        self._clear_dynamic_buttons()
        self._sync_tabs()
        self._groups_button.setVisible(False)
        self._set_grid_stretch(len(groups), columns)
        for index, group in enumerate(groups):
            button = self._make_button(
                " ".join(group),
                self._action(f"{action_prefix}:{index}"),
                "groupButton",
                minimum_height=KEY_MIN_HEIGHT,
                dynamic=True,
            )
            self._key_layout.addWidget(button, index // columns, index % columns)

    def _show_key_group(
        self,
        tab: str,
        groups: list[list[str]],
        group_index: int,
        action_prefix: str,
    ) -> None:
        if group_index < 0 or group_index >= len(groups):
            return

        self._active_tab = tab
        self._active_group_index = group_index
        self._clear_dynamic_buttons()
        self._sync_tabs()
        self._groups_button.setVisible(True)

        group = groups[group_index]
        columns = 3
        self._set_grid_stretch(len(group), columns)
        for index, label in enumerate(group):
            button = self._make_button(
                label,
                self._action(f"{action_prefix}:{index}"),
                "keyButton",
                minimum_height=KEY_MIN_HEIGHT,
                dynamic=True,
            )
            self._key_layout.addWidget(button, index // columns, index % columns)

    def _trigger_action(self, action: str) -> None:
        command = action.removeprefix(KEYBOARD_WINDOW_ACTION_PREFIX)

        if command == "tab:letters":
            self._show_letter_groups()
        elif command == "tab:numpad":
            self._show_numpad()
        elif command == "tab:symbols":
            self._show_symbols()
        elif command == "groups":
            self._show_current_group_level()
        elif command == "space":
            self._type_text(" ")
        elif command == "backspace":
            self._press_key("backspace")
        elif command.startswith("group:"):
            self._show_letter_group(int(command.split(":", 1)[1]))
        elif command.startswith("letter:"):
            _prefix, group_text, letter_text = command.split(":", 2)
            group_index = int(group_text)
            letter_index = int(letter_text)
            self._type_text(self._letter_groups[group_index][letter_index])
            self._show_letter_groups()
        elif command.startswith("numpad_group:"):
            self._show_numpad_group(int(command.split(":", 1)[1]))
        elif command.startswith("symbol_group:"):
            self._show_symbol_group(int(command.split(":", 1)[1]))
        elif command.startswith("numpad:"):
            key = self._numpad_groups[self._active_group_index or 0][int(command.split(":", 1)[1])]
            self._type_key_label(key)
            self._show_numpad()
        elif command.startswith("symbol:"):
            key = self._symbol_groups[self._active_group_index or 0][int(command.split(":", 1)[1])]
            self._type_text(key)
            self._show_symbols()

    def _type_key_label(self, label: str) -> None:
        if label == "Potvrdi":
            self._press_key("enter")
        else:
            self._type_text(label)

    def _type_text(self, text: str) -> None:
        self._ensure_input_controller()
        if self._input is None:
            self._emit_status("Unos putem tastature nije dostupan.")
            return

        try:
            self._restore_target_window()
            self._input.type_text(text)
            self._emit_status(f"Uneseno je {text!r}.")
        except Exception:
            logger.exception("Keyboard text input failed.")
            self._emit_status("Unos putem tastature nije uspio.")

    def _press_key(self, key: str) -> None:
        self._ensure_input_controller()
        if self._input is None:
            self._emit_status("Unos putem tastature nije dostupan.")
            return

        try:
            self._restore_target_window()
            self._input.press_key(key)
            key_name = {"backspace": "brisanje", "enter": "potvrda"}.get(key, key)
            self._emit_status(f"Pritisnuta je tipka za {key_name}.")
        except Exception:
            logger.exception("Keyboard key press failed.")
            self._emit_status("Pritisak tipke nije uspio.")

    def _ensure_input_controller(self) -> None:
        if self._input is not None:
            return

        try:
            self._input = WindowsInputController()
        except Exception:
            logger.exception("Could not initialize keyboard input backend.")
            self._emit_status("Unos putem tastature nije dostupan.")

    def _emit_status(self, text: str) -> None:
        logger.info("Keyboard sidebar status: %s", text)
        self.setToolTip(text)
        self.status_changed.emit(text)

    def _remember_foreground_target(self) -> None:
        if self._input is None:
            return

        hwnd = self._input.foreground_window()
        if hwnd is None:
            return
        if self._input.belongs_to_current_process(hwnd):
            logger.info("Keyboard foreground target is an app window; keeping previous target.")
            return

        self._target_window = hwnd
        logger.info("Keyboard target window captured: hwnd=%s.", hwnd)

    def _restore_target_window(self) -> bool:
        if self._input is None:
            return False

        current = self._input.foreground_window()
        if current is not None and not self._input.belongs_to_current_process(current):
            self._target_window = current
            return True

        if self._target_window is None:
            logger.warning("Keyboard has no external target window to restore.")
            return False

        if not self._input.is_window(self._target_window):
            logger.warning(
                "Keyboard target window is no longer valid: hwnd=%s.", self._target_window
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
                "Could not restore keyboard target window: hwnd=%s.", self._target_window
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
    ) -> QToolButton:
        button = QToolButton(self._key_host if dynamic else self)
        button.setObjectName(object_name)
        button.setText(text)
        button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.NoFocus)
        button.setMinimumHeight(minimum_height)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        button.setProperty("gazeTarget", False)
        button.setProperty("gazePulse", "")
        button.pressed.connect(self.mouse_action_started.emit)
        button.clicked.connect(lambda _checked=False, item=action: self._trigger_action(item))
        self._action_buttons[action] = button
        if dynamic:
            self._dynamic_actions.add(action)
        return button

    def _clear_dynamic_buttons(self) -> None:
        self._set_gaze_target_action(None)
        self.interaction_context_changed.emit()
        for action in self._dynamic_actions:
            self._action_buttons.pop(action, None)
        self._dynamic_actions.clear()

        while self._key_layout.count():
            item = self._key_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _set_grid_stretch(self, item_count: int, columns: int) -> None:
        for column in range(4):
            self._key_layout.setColumnStretch(column, 0)
        for row in range(48):
            self._key_layout.setRowStretch(row, 0)

        rows = max(1, math.ceil(max(1, item_count) / max(1, columns)))
        for column in range(columns):
            self._key_layout.setColumnStretch(column, 1)
        for row in range(rows):
            self._key_layout.setRowStretch(row, 1)

    def _sync_tabs(self) -> None:
        for tab, button in self._tab_buttons.items():
            button.setChecked(tab == self._active_tab)

    def _show_current_group_level(self) -> None:
        if self._active_tab == TAB_NUMPAD:
            self._show_numpad()
        elif self._active_tab == TAB_SYMBOLS:
            self._show_symbols()
        else:
            self._show_letter_groups()

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
        return f"{KEYBOARD_WINDOW_ACTION_PREFIX}{name}"

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
            self._emit_status("Tastatura koristi punu visinu ekrana.")
            return

        if self._appbar.register(int(self.winId()), self.width(), edge=ABE_RIGHT):
            self._emit_status("Tastatura je zauzela desni dio radne površine.")
        elif sys.platform == "win32":
            self._emit_status("Tastatura je prikazana bez rezervacije radne površine.")


def _group_letters(letters: list[str], letters_per_group: int) -> list[list[str]]:
    return [
        letters[index : index + letters_per_group]
        for index in range(0, len(letters), letters_per_group)
    ]


def _keyboard_window_flags() -> Qt.WindowFlags:
    flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
    no_focus = getattr(Qt, "WindowDoesNotAcceptFocus", None)
    if no_focus is None:
        no_focus = getattr(Qt.WindowType, "WindowDoesNotAcceptFocus", None)
    if no_focus is not None:
        flags |= no_focus
    return flags
