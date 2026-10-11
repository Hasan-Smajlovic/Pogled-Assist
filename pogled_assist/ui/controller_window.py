"""Right-side gaze-selectable controller shortcuts panel."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..diagnostics import safe_action
from ..interaction.mouse_controller import GazeSettings
from ..keyboard_layouts import (
    ARABIC_SCRIPT,
    KeyboardGroupPage,
    group_label,
    key_label,
    keyboard_group_page,
    other_script,
    sidebar_key_groups,
    switch_label,
)
from ..speech.speech_service import SpeechSettings
from ..windows.windows_input import WindowsInputController
from .icons import themed_icon
from .sidebar_panel import SidebarPanel

logger = logging.getLogger(__name__)

CONTROLLER_WINDOW_ACTION_PREFIX = "controller_window:"

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

BUTTON_HEIGHTS = {
    "tabButton": TAB_HEIGHT,
    "shortcutButton": ACTION_MIN_HEIGHT,
    "checkButton": SETTINGS_MIN_HEIGHT,
    "groupButton": KEY_MIN_HEIGHT,
    "keyButton": KEY_MIN_HEIGHT,
    "utilityButton": UTILITY_MIN_HEIGHT,
    "keyboardSubTabButton": KEYBOARD_SUBTAB_HEIGHT,
}

CONTROLLER_STYLESHEET = """
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

GENERAL_ACTIONS = (
    ("left_click", "Lijevi klik", "fa5s.mouse-pointer"),
    ("right_click", "Desni klik", "fa5s.mouse"),
    ("double_left_click", "Dvostruki klik", "fa5s.hand-pointer"),
    ("enter", "Potvrdi", "fa5s.level-down-alt"),
    ("scroll_up", "Pomjeri gore", "fa5s.arrow-up"),
    ("scroll_down", "Pomjeri dolje", "fa5s.arrow-down"),
)


class ControllerWindow(SidebarPanel):
    """Right-side AppBar panel for common gaze shortcuts and quick settings."""

    speech_requested = Signal()
    gaze_settings_changed = Signal(object)

    log_name = "Controller"
    full_height_status = "Upravljač koristi punu visinu ekrana."
    reserved_status = "Upravljač je zauzeo desni dio radne površine."
    unreserved_status = "Upravljač je prikazan bez rezervacije radne površine."
    input_unavailable_status = "Upravljanje nije dostupno."

    def __init__(
        self,
        gaze_settings: GazeSettings,
        speech_settings: SpeechSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("controllerWindow")
        self.setWindowTitle("Upravljač")

        self._gaze_settings = replace(gaze_settings)
        self._speech_settings = replace(speech_settings)
        self._letters_per_group = max(1, self._speech_settings.letters_per_group)
        self._rebuild_key_groups()
        self._keyboard_group_page = 0
        self._active_tab = TAB_GENERAL
        self._keyboard_active_tab = KEYBOARD_TAB_LETTERS
        self._keyboard_active_group_index: int | None = None
        self._keyboard_tab_buttons: dict[str, QToolButton] = {}
        self._target_cursor_position: tuple[int, int] | None = None
        self._precision_zoom_button: QToolButton | None = None
        self._gaze_cursor_button: QToolButton | None = None
        self._commands: dict[str, Callable[[], None]] = {
            "tab:general": self._show_general_tab,
            "tab:keyboard": self._show_keyboard_tab,
            "tab:speech": self.speech_requested.emit,
            "tab:settings": self._show_settings_tab,
            "keyboard_tab:letters": self._show_keyboard_letter_groups,
            "keyboard_tab:numpad": self._show_keyboard_numpad,
            "keyboard_tab:symbols": self._show_keyboard_symbols,
            "keyboard_groups": self._show_keyboard_current_group_level,
            "keyboard_space": lambda: self._type_text(" "),
            "keyboard_backspace": lambda: self._press_key("backspace"),
            "enter": self._press_enter,
            "scroll_up": lambda: self._scroll(3),
            "scroll_down": lambda: self._scroll(-3),
            "settings:precision_zoom": self._toggle_precision_zoom,
            "settings:gaze_cursor": self._toggle_gaze_cursor,
        }
        self._click_commands = {
            "left_click": ("left", 1),
            "right_click": ("right", 1),
            "double_left_click": ("left", 2),
        }
        self._argument_commands: dict[str, Callable[[str], None]] = {
            "keyboard_group": lambda index: self._show_keyboard_letter_group(int(index)),
            "keyboard_letter": self._type_keyboard_letter,
            "keyboard_numpad_group": lambda index: self._show_keyboard_numpad_group(int(index)),
            "keyboard_symbol_group": lambda index: self._show_keyboard_symbol_group(int(index)),
            "keyboard_numpad": self._type_keyboard_numpad_key,
            "keyboard_symbol": self._type_keyboard_symbol,
        }

        self._build_ui()
        self._show_general_tab()
        logger.info("Controller sidebar initialized.")

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
        old_script = self._speech_settings.keyboard_script
        self._speech_settings = replace(settings)
        self._letters_per_group = max(1, self._speech_settings.letters_per_group)
        if (
            old_letters_per_group != self._letters_per_group
            or old_script != settings.keyboard_script
        ):
            self._rebuild_key_groups()
            self._keyboard_group_page = 0
            self._script_button.setText(switch_label(settings.keyboard_script))
            self._keyboard_active_group_index = None
            if self._active_tab == TAB_KEYBOARD:
                self._show_keyboard_current_group_level()

        logger.info("Controller sidebar speech settings updated: %s", self._speech_settings)

    def _rebuild_key_groups(self) -> None:
        self._letter_groups, self._numpad_groups, self._symbol_groups = sidebar_key_groups(
            self._speech_settings.keyboard_script, self._letters_per_group
        )

    def _switch_keyboard_script(self) -> None:
        script = other_script(self._speech_settings.keyboard_script)
        self.update_speech_settings(replace(self._speech_settings, keyboard_script=script))
        self.keyboard_script_changed.emit(script)

    def handle_gaze_action(self, action: str) -> None:
        if not action.startswith(CONTROLLER_WINDOW_ACTION_PREFIX):
            return

        logger.info("Controller sidebar gaze action requested: %s", safe_action(action))
        self._trigger_action(action, source="gaze")

    def _build_ui(self) -> None:
        self.setStyleSheet(CONTROLLER_STYLESHEET)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        tab_row = QHBoxLayout()
        tab_row.setContentsMargins(0, 0, 0, 0)
        tab_row.setSpacing(8)
        self._tab_buttons: dict[str, QToolButton] = {}
        for tab, label in (
            (TAB_GENERAL, "Opće"),
            (TAB_KEYBOARD, "Tastatura"),
            (TAB_SPEECH, "Govor"),
            (TAB_SETTINGS, "Postavke"),
        ):
            button = self._make_button(
                label,
                self._action(f"tab:{tab}"),
                "tabButton",
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
        self._script_button = self._make_button(
            switch_label(self._speech_settings.keyboard_script),
            self._action("script-toggle"),
            "tabButton",
            dynamic=False,
        )
        root.addWidget(self._script_button)
        root.addWidget(self._content_host, 1)

    def _show_general_tab(self) -> None:
        self._active_tab = TAB_GENERAL
        self._clear_dynamic_buttons()
        self._sync_tabs()
        self._set_grid_stretch(len(GENERAL_ACTIONS), 2)

        for index, (command, label, icon_name) in enumerate(GENERAL_ACTIONS):
            button = self._make_button(label, self._action(command), "shortcutButton", dynamic=True)
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setIcon(themed_icon(icon_name, "#f8f7f2", self.style()))
            self._content_layout.addWidget(button, index // 2, index % 2)

    def _show_keyboard_tab(self) -> None:
        self._keyboard_group_page = 0
        self._keyboard_active_tab = KEYBOARD_TAB_LETTERS
        self._keyboard_active_group_index = None
        self._show_keyboard_letter_groups()

    def _show_keyboard_letter_groups(self) -> None:
        self._show_keyboard_group_buttons(
            KEYBOARD_TAB_LETTERS, self._letter_groups, "keyboard_group", columns=2
        )

    def _show_keyboard_letter_group(self, group_index: int) -> None:
        if group_index < 0 or group_index >= len(self._letter_groups):
            return

        self._active_tab = TAB_KEYBOARD
        self._keyboard_active_tab = KEYBOARD_TAB_LETTERS
        self._keyboard_active_group_index = group_index
        self._clear_dynamic_buttons()
        self._sync_tabs()
        columns = 3
        self._add_keyboard_subtabs(columns)

        group = self._letter_groups[group_index]
        start_row = 1
        rows = self._set_grid_stretch(len(group), columns, start_row=start_row)
        for index, letter in enumerate(group):
            button = self._make_button(
                letter,
                self._action(f"keyboard_letter:{group_index}:{index}"),
                "keyButton",
                dynamic=True,
            )
            column = (
                columns - 1 - index % columns
                if self._speech_settings.keyboard_script == ARABIC_SCRIPT
                else index % columns
            )
            self._content_layout.addWidget(button, start_row + index // columns, column)

        self._add_keyboard_utility_row(start_row + rows, columns, groups_visible=True)

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
        if self._keyboard_active_tab != tab:
            self._keyboard_group_page = 0
        self._active_tab = TAB_KEYBOARD
        self._keyboard_active_tab = tab
        self._keyboard_active_group_index = None
        self._clear_dynamic_buttons()
        self._sync_tabs()
        self._add_keyboard_subtabs(columns)

        start_row = 1
        arabic = self._speech_settings.keyboard_script == ARABIC_SCRIPT
        page = keyboard_group_page(groups, self._keyboard_group_page)
        self._keyboard_group_page = page.index
        rows = self._set_grid_stretch(len(page.groups), columns, start_row=start_row)
        for offset, group in enumerate(page.groups):
            index = page.start + offset
            button = self._make_button(
                group_label(group, self._speech_settings.keyboard_script),
                self._action(f"{action_prefix}:{index}"),
                "groupButton",
                dynamic=True,
            )
            button.setLayoutDirection(Qt.RightToLeft if arabic else Qt.LeftToRight)
            column = columns - 1 - offset % columns if arabic else offset % columns
            self._content_layout.addWidget(button, start_row + offset // columns, column)

        if page.count > 1:
            self._add_keyboard_page_buttons(page, start_row + rows)
            rows += 1

        self._add_keyboard_utility_row(start_row + rows, columns, groups_visible=False)

    def _add_keyboard_page_buttons(self, page: KeyboardGroupPage, row: int) -> None:
        for column, (delta, label) in enumerate(((-1, "Prethodna"), (1, "Sljedeća"))):
            button = self._make_button(
                label, self._action(f"keyboard-page:{delta}"), "keyboardSubTabButton", dynamic=True
            )
            button.setEnabled(0 <= page.index + delta < page.count)
            self._content_layout.addWidget(button, row, column)

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
        columns = 3
        self._add_keyboard_subtabs(columns)

        group = groups[group_index]
        start_row = 1
        rows = self._set_grid_stretch(len(group), columns, start_row=start_row)
        for index, label in enumerate(group):
            button = self._make_button(
                key_label(label),
                self._action(f"{action_prefix}:{index}"),
                "keyButton",
                dynamic=True,
            )
            self._content_layout.addWidget(button, start_row + index // columns, index % columns)

        self._add_keyboard_utility_row(start_row + rows, columns, groups_visible=True)

    def _add_keyboard_row(self, row: int, columns: int) -> QHBoxLayout:
        host = QWidget(self._content_host)
        host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._content_layout.addWidget(host, row, 0, 1, columns)
        return layout

    def _add_keyboard_subtabs(self, columns: int) -> None:
        layout = self._add_keyboard_row(0, columns)
        self._keyboard_tab_buttons = {}
        for tab, label in (
            (KEYBOARD_TAB_LETTERS, "Slova"),
            (KEYBOARD_TAB_NUMPAD, "Brojevi"),
            (KEYBOARD_TAB_SYMBOLS, "Znakovi"),
        ):
            button = self._make_button(
                label,
                self._action(f"keyboard_tab:{tab}"),
                "keyboardSubTabButton",
                dynamic=True,
            )
            button.setCheckable(True)
            button.setChecked(tab == self._keyboard_active_tab)
            self._keyboard_tab_buttons[tab] = button
            layout.addWidget(button, 1)

    def _add_keyboard_utility_row(self, row: int, columns: int, *, groups_visible: bool) -> None:
        layout = self._add_keyboard_row(row, columns)
        groups_button = self._make_button(
            "Grupe",
            self._action("keyboard_groups"),
            "utilityButton",
            dynamic=True,
        )
        groups_button.setVisible(groups_visible)
        space_button = self._make_button(
            "Razmak",
            self._action("keyboard_space"),
            "utilityButton",
            dynamic=True,
        )
        backspace_button = self._make_button(
            "Obriši",
            self._action("keyboard_backspace"),
            "utilityButton",
            dynamic=True,
        )
        for button in (groups_button, space_button, backspace_button):
            layout.addWidget(button, 1)

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
            dynamic=True,
        )
        self._precision_zoom_button.setCheckable(True)

        self._gaze_cursor_button = self._make_button(
            "",
            self._action("settings:gaze_cursor"),
            "checkButton",
            dynamic=True,
        )
        self._gaze_cursor_button.setCheckable(True)

        self._content_layout.addWidget(self._precision_zoom_button, 0, 0)
        self._content_layout.addWidget(self._gaze_cursor_button, 1, 0)
        self._sync_settings_buttons()

    def _trigger_action(self, action: str, *, source: str = "unknown") -> None:
        command = action.removeprefix(CONTROLLER_WINDOW_ACTION_PREFIX)
        if command.startswith("keyboard_tab:"):
            self._keyboard_group_page = 0
        if command == "script-toggle":
            self._switch_keyboard_script()
            return
        if command.startswith("keyboard-page:"):
            self._turn_keyboard_page(command.split(":", 1)[1])
            return

        handler = self._commands.get(command)
        if handler is not None:
            handler()
            return

        click = self._click_commands.get(command)
        if click is not None:
            button, clicks = click
            self._click_current(button, clicks=clicks, source=source)
            return

        name, separator, argument = command.partition(":")
        argument_handler = self._argument_commands.get(name) if separator else None
        if argument_handler is not None:
            argument_handler(argument)

    def _turn_keyboard_page(self, delta: str) -> None:
        self._keyboard_group_page = max(0, self._keyboard_group_page + int(delta))
        self._show_keyboard_current_group_level()

    def _type_keyboard_letter(self, position: str) -> None:
        group_text, letter_text = position.split(":", 1)
        group_index, letter_index = int(group_text), int(letter_text)
        self._type_text(self._letter_groups[group_index][letter_index])
        self._show_keyboard_letter_groups()

    def _type_keyboard_numpad_key(self, index: str) -> None:
        group = self._numpad_groups[self._keyboard_active_group_index or 0]
        self._type_key_label(group[int(index)])
        self._show_keyboard_numpad()

    def _type_keyboard_symbol(self, index: str) -> None:
        group = self._symbol_groups[self._keyboard_active_group_index or 0]
        self._type_text(group[int(index)])
        self._show_keyboard_symbols()

    def _shortcut_input(self) -> WindowsInputController | None:
        self._ensure_input_controller()
        if self._input is None:
            self._emit_status(self.input_unavailable_status)
        return self._input

    def _click_current(self, button: str, *, clicks: int, source: str) -> None:
        shortcut_input = self._shortcut_input()
        if shortcut_input is None:
            return

        try:
            target = self._click_target_for_source(source)
            if source == "mouse" and target is None:
                self._emit_status("Još nije zabilježen cilj pokazivača izvan aplikacije.")
                return

            if target is None:
                shortcut_input.click_current(button=button, clicks=clicks, interval=0.04)
            else:
                shortcut_input.click(
                    target[0],
                    target[1],
                    button=button,
                    clicks=clicks,
                    interval=0.04,
                )
            labels = {"left": "Lijevi klik", "right": "Desni klik"}
            label = "Dvostruki lijevi klik" if clicks > 1 else labels.get(button, "Klik")
            self._emit_status(f"{label} je poslan.")
        except Exception:
            logger.exception("Controller click failed.")
            self._emit_status("Klik nije uspio.")

    def _click_target_for_source(self, source: str) -> tuple[int, int] | None:
        if source == "mouse":
            return self._target_cursor_position
        if self.contains_global_point(QCursor.pos()):
            return self._target_cursor_position
        return None

    def _press_enter(self) -> None:
        shortcut_input = self._shortcut_input()
        if shortcut_input is None:
            return

        try:
            self._restore_target_window()
            shortcut_input.press_key("enter")
            self._emit_status("Tipka za potvrdu je poslana.")
        except Exception:
            logger.exception("Controller ENTER failed.")
            self._emit_status("Slanje tipke za potvrdu nije uspjelo.")

    def _scroll(self, units: int) -> None:
        shortcut_input = self._shortcut_input()
        if shortcut_input is None:
            return

        try:
            shortcut_input.scroll(units)
            direction = "gore" if units > 0 else "dolje"
            self._emit_status(f"Pomjeranje {direction} je poslano.")
        except Exception:
            logger.exception("Controller scroll failed.")
            self._emit_status("Pomjeranje nije uspjelo.")

    def _toggle_precision_zoom(self) -> None:
        enabled = not self._gaze_settings.use_precision_zoom
        self._gaze_settings = replace(self._gaze_settings, use_precision_zoom=enabled)
        self._sync_settings_buttons()
        self.gaze_settings_changed.emit(replace(self._gaze_settings))
        state = "uključeno" if enabled else "isključeno"
        self._emit_status(f"Precizno uvećanje je {state}.")

    def _toggle_gaze_cursor(self) -> None:
        enabled = not self._gaze_settings.show_gaze_bubble
        self._gaze_settings = replace(self._gaze_settings, show_gaze_bubble=enabled)
        self._sync_settings_buttons()
        self.gaze_settings_changed.emit(replace(self._gaze_settings))
        state = "uključena" if enabled else "isključena"
        self._emit_status(f"Oznaka pogleda je {state}.")

    def _make_button(self, text: str, action: str, role: str, *, dynamic: bool) -> QToolButton:
        parent = self._content_host if dynamic else self
        button = QToolButton(parent)
        button.setObjectName(role)
        button.setText(text)
        button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        button.setIconSize(QSize(24, 24))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.NoFocus)
        button.setMinimumHeight(BUTTON_HEIGHTS[role])
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        button.setProperty("gazeTarget", False)
        button.setProperty("gazePulse", "")
        button.pressed.connect(self.mouse_action_started.emit)
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
        self.interaction_context_changed.emit()
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
        self._script_button.setVisible(self._active_tab == TAB_KEYBOARD)
        for tab, button in self._tab_buttons.items():
            button.setChecked(tab == self._active_tab)

    def _sync_settings_buttons(self) -> None:
        self._sync_check_button(
            self._precision_zoom_button,
            "Precizno uvećanje",
            self._gaze_settings.use_precision_zoom,
        )
        self._sync_check_button(
            self._gaze_cursor_button, "Oznaka pogleda", self._gaze_settings.show_gaze_bubble
        )

    def _sync_check_button(self, button: QToolButton | None, label: str, checked: bool) -> None:
        if button is None:
            return
        button.setChecked(checked)
        button.setText(f"[{'X' if checked else ' '}] {label}")

    def _action(self, name: str) -> str:
        return f"{CONTROLLER_WINDOW_ACTION_PREFIX}{name}"
