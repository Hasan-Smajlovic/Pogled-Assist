"""Right-side gaze-selectable keyboard panel."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..diagnostics import safe_action
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
from .sidebar_panel import SidebarPanel

logger = logging.getLogger(__name__)

KEYBOARD_WINDOW_ACTION_PREFIX = "keyboard_window:"

KEY_MIN_HEIGHT = 54
UTILITY_MIN_HEIGHT = 58
TAB_HEIGHT = 52

TAB_LETTERS = "letters"
TAB_NUMPAD = "numpad"
TAB_SYMBOLS = "symbols"

BUTTON_HEIGHTS = {
    "tabButton": TAB_HEIGHT,
    "groupButton": KEY_MIN_HEIGHT,
    "keyButton": KEY_MIN_HEIGHT,
    "utilityButton": UTILITY_MIN_HEIGHT,
}

KEYBOARD_STYLESHEET = """
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


class KeyboardWindow(SidebarPanel):
    """Right-side AppBar keyboard that can be selected by mouse or gaze."""

    log_name = "Keyboard"
    full_height_status = "Tastatura koristi punu visinu ekrana."
    reserved_status = "Tastatura je zauzela desni dio radne površine."
    unreserved_status = "Tastatura je prikazana bez rezervacije radne površine."
    input_unavailable_status = "Unos putem tastature nije dostupan."

    def __init__(
        self,
        settings: SpeechSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("keyboardWindow")
        self.setWindowTitle("Tastatura")

        self._settings = replace(settings)
        self._letters_per_group = max(1, self._settings.letters_per_group)
        self._rebuild_key_groups()
        self._group_page = 0
        self._active_tab = TAB_LETTERS
        self._active_group_index: int | None = None
        self._commands: dict[str, Callable[[], None]] = {
            "script-toggle": self._switch_keyboard_script,
            "tab:letters": self._show_letter_groups,
            "tab:numpad": self._show_numpad,
            "tab:symbols": self._show_symbols,
            "groups": self._show_current_group_level,
            "space": lambda: self._type_text(" "),
            "backspace": lambda: self._press_key("backspace"),
        }
        self._argument_commands: dict[str, Callable[[str], None]] = {
            "group-page": self._turn_group_page,
            "group": lambda index: self._show_letter_group(int(index)),
            "letter": self._type_letter,
            "numpad_group": lambda index: self._show_numpad_group(int(index)),
            "symbol_group": lambda index: self._show_symbol_group(int(index)),
            "numpad": self._type_numpad_key,
            "symbol": self._type_symbol,
        }

        self._build_ui()
        self._show_letter_groups()
        logger.info("Keyboard sidebar initialized.")

    def hideEvent(self, event) -> None:
        self.interaction_context_changed.emit()
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:
        self.interaction_context_changed.emit()
        super().resizeEvent(event)

    def update_settings(self, settings: SpeechSettings) -> None:
        old_letters_per_group = self._letters_per_group
        old_script = self._settings.keyboard_script
        self._settings = replace(settings)
        self._letters_per_group = max(1, self._settings.letters_per_group)
        if (
            old_letters_per_group != self._letters_per_group
            or old_script != settings.keyboard_script
        ):
            self._rebuild_key_groups()
            self._group_page = 0
            self._script_button.setText(switch_label(settings.keyboard_script))
            self._active_group_index = None
            self._show_current_group_level()

        logger.info("Keyboard sidebar settings updated: %s", self._settings)

    def _rebuild_key_groups(self) -> None:
        self._letter_groups, self._numpad_groups, self._symbol_groups = sidebar_key_groups(
            self._settings.keyboard_script, self._letters_per_group
        )

    def _switch_keyboard_script(self) -> None:
        script = other_script(self._settings.keyboard_script)
        self.update_settings(replace(self._settings, keyboard_script=script))
        self.keyboard_script_changed.emit(script)

    def handle_gaze_action(self, action: str) -> None:
        if not action.startswith(KEYBOARD_WINDOW_ACTION_PREFIX):
            return

        logger.info("Keyboard sidebar gaze action requested: %s", safe_action(action))
        self._trigger_action(action)

    def _build_ui(self) -> None:
        self.setStyleSheet(KEYBOARD_STYLESHEET)

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
            dynamic=False,
        )
        self._space_button = self._make_button(
            "Razmak",
            self._action("space"),
            "utilityButton",
            dynamic=False,
        )
        self._backspace_button = self._make_button(
            "Obriši",
            self._action("backspace"),
            "utilityButton",
            dynamic=False,
        )
        utility_row.addWidget(self._groups_button, 1)
        utility_row.addWidget(self._space_button, 2)
        utility_row.addWidget(self._backspace_button, 2)

        root.addLayout(tab_row)
        self._script_button = self._make_button(
            switch_label(self._settings.keyboard_script),
            self._action("script-toggle"),
            "tabButton",
            dynamic=False,
        )
        root.addWidget(self._script_button)
        root.addWidget(self._key_host, 1)
        root.addLayout(utility_row)

    def _show_letter_groups(self) -> None:
        self._active_tab = TAB_LETTERS
        self._active_group_index = None
        self._show_group_buttons(self._letter_groups, "group", columns=2)

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
                dynamic=True,
            )
            column = (
                columns - 1 - index % columns
                if self._settings.keyboard_script == ARABIC_SCRIPT
                else index % columns
            )
            self._key_layout.addWidget(button, index // columns, column)

    def _show_numpad(self) -> None:
        if self._active_tab != TAB_NUMPAD:
            self._group_page = 0
        self._active_tab = TAB_NUMPAD
        self._active_group_index = None
        self._show_group_buttons(self._numpad_groups, "numpad_group", columns=2)

    def _show_symbols(self) -> None:
        if self._active_tab != TAB_SYMBOLS:
            self._group_page = 0
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
        arabic = self._settings.keyboard_script == ARABIC_SCRIPT
        page = keyboard_group_page(groups, self._group_page)
        self._group_page = page.index
        self._set_grid_stretch(len(page.groups), columns)
        for offset, group in enumerate(page.groups):
            index = page.start + offset
            button = self._make_button(
                group_label(group, self._settings.keyboard_script),
                self._action(f"{action_prefix}:{index}"),
                "groupButton",
                dynamic=True,
            )
            button.setLayoutDirection(Qt.RightToLeft if arabic else Qt.LeftToRight)
            column = columns - 1 - offset % columns if arabic else offset % columns
            self._key_layout.addWidget(button, offset // columns, column)
        if page.count > 1:
            self._add_page_buttons(page, math.ceil(len(page.groups) / columns))

    def _add_page_buttons(self, page: KeyboardGroupPage, row: int) -> None:
        for column, (delta, label) in enumerate(((-1, "Prethodna"), (1, "Sljedeća"))):
            button = self._make_button(
                label, self._action(f"group-page:{delta}"), "tabButton", dynamic=True
            )
            button.setEnabled(0 <= page.index + delta < page.count)
            self._key_layout.addWidget(button, row, column)

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
                key_label(label),
                self._action(f"{action_prefix}:{index}"),
                "keyButton",
                dynamic=True,
            )
            self._key_layout.addWidget(button, index // columns, index % columns)

    def _trigger_action(self, action: str) -> None:
        command = action.removeprefix(KEYBOARD_WINDOW_ACTION_PREFIX)
        if command.startswith("tab:"):
            self._group_page = 0

        handler = self._commands.get(command)
        if handler is not None:
            handler()
            return

        name, separator, argument = command.partition(":")
        argument_handler = self._argument_commands.get(name) if separator else None
        if argument_handler is not None:
            argument_handler(argument)

    def _turn_group_page(self, delta: str) -> None:
        self._group_page = max(0, self._group_page + int(delta))
        self._show_current_group_level()

    def _type_letter(self, position: str) -> None:
        group_text, letter_text = position.split(":", 1)
        group_index, letter_index = int(group_text), int(letter_text)
        self._type_text(self._letter_groups[group_index][letter_index])
        self._show_letter_groups()

    def _type_numpad_key(self, index: str) -> None:
        self._type_key_label(self._numpad_groups[self._active_group_index or 0][int(index)])
        self._show_numpad()

    def _type_symbol(self, index: str) -> None:
        self._type_text(self._symbol_groups[self._active_group_index or 0][int(index)])
        self._show_symbols()

    def _make_button(self, text: str, action: str, role: str, *, dynamic: bool) -> QToolButton:
        button = QToolButton(self._key_host if dynamic else self)
        button.setObjectName(role)
        button.setText(text)
        button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.NoFocus)
        button.setMinimumHeight(BUTTON_HEIGHTS[role])
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

    def _action(self, name: str) -> str:
        return f"{KEYBOARD_WINDOW_ACTION_PREFIX}{name}"
