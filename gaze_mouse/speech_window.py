"""Full-screen Bosnian speech keyboard."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .gaze_feedback import set_gaze_feedback
from .logging_setup import get_project_root
from .speech_service import SpeechService, SpeechSettings


logger = logging.getLogger(__name__)

SPEECH_WINDOW_ACTION_PREFIX = "speech_window:"

BOSNIAN_LETTERS = [
    "A",
    "B",
    "C",
    "Č",
    "Ć",
    "D",
    "Dž",
    "Đ",
    "E",
    "F",
    "G",
    "H",
    "I",
    "J",
    "K",
    "L",
    "Lj",
    "M",
    "N",
    "Nj",
    "O",
    "P",
    "R",
    "S",
    "Š",
    "T",
    "U",
    "V",
    "Z",
    "Ž",
]
MULTI_CHARACTER_LETTERS = ("Dž", "Lj", "Nj")
GROUP_GRID_MAX_COLUMNS = 6
LETTER_GRID_MAX_COLUMNS = 6
KEY_GRID_MAX_ROWS = 8
GROUP_BUTTON_MIN_HEIGHT = 82
LETTER_BUTTON_MIN_HEIGHT = 92
UTILITY_BUTTON_MIN_HEIGHT = 86
PHRASE_BUTTON_MIN_HEIGHT = 72
PHRASE_ROW_HEIGHT = 72
PHRASES_PER_PAGE = 8
PHRASES_FILE = "speech_phrases.json"


@dataclass
class PhraseRecord:
    text: str
    uses: int = 0


class SpeechWindow(QWidget):
    """Fullscreen speech entry surface with gaze-selectable buttons."""

    closed = Signal()

    def __init__(
        self,
        speech: SpeechService,
        parent: QWidget | None = None,
        letters_per_group: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("speechWindow")
        self.setWindowTitle("Speech")
        self.setWindowFlags(
            Qt.Window
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
        )

        self._speech = speech
        initial_settings = speech.settings
        if letters_per_group is not None:
            initial_settings = replace(initial_settings, letters_per_group=max(1, letters_per_group))

        self._speech_settings = initial_settings
        self._letters_per_group = max(1, self._speech_settings.letters_per_group)
        self._letter_groups = _group_letters(BOSNIAN_LETTERS, self._letters_per_group)
        self._action_buttons: dict[str, QWidget] = {}
        self._dynamic_actions: set[str] = set()
        self._active_group_index: int | None = None
        self._gaze_target_action: str | None = None
        self._phrases = _load_phrases()
        self._phrase_page = 0
        self._speech_input_text = ""
        self._phrase_mode = "keyboard"

        self._build_ui()
        self._show_group_level()
        logger.info("Speech window initialized with %s letter groups.", len(self._letter_groups))

    def show_full_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())

        self._restore_input_if_editing_phrase()
        self._phrase_mode = "keyboard"
        self._input.setPlaceholderText("")
        self._show_group_level()
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self._input.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        logger.info("Speech window shown full-screen.")

    def update_settings(self, settings: SpeechSettings) -> None:
        old_letters_per_group = self._letters_per_group
        self._speech_settings = replace(settings)
        self._letters_per_group = max(1, self._speech_settings.letters_per_group)
        if self._letters_per_group != old_letters_per_group:
            self._letter_groups = _group_letters(BOSNIAN_LETTERS, self._letters_per_group)
            if self._phrase_mode == "phrases":
                self._show_phrase_level()
            else:
                self._show_group_level()

        logger.info("Speech window settings updated: %s", self._speech_settings)

    def closeEvent(self, event: QCloseEvent) -> None:
        logger.info("Speech window close event received.")
        self._restore_input_if_editing_phrase()
        self._set_gaze_target_action(None)
        self.closed.emit()
        super().closeEvent(event)

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
        if not action.startswith(SPEECH_WINDOW_ACTION_PREFIX):
            return

        logger.info("Speech window gaze action requested: %s", action)
        self._trigger_action(action)

    def cancel_gaze_interaction(self) -> None:
        self._set_gaze_target_action(None)

    def _build_ui(self) -> None:
        self.setStyleSheet(
            """
            QWidget#speechWindow {
                background: #111318;
                color: #f6f7fb;
                font-family: Segoe UI, Arial, sans-serif;
                font-size: 15px;
            }
            QLineEdit#speechInput {
                background: #0b0d11;
                border: 2px solid #303747;
                border-radius: 8px;
                color: #ffffff;
                font-size: 32px;
                padding: 10px 18px;
                placeholder-text-color: #aeb8c8;
                selection-background-color: #245f9f;
            }
            QPushButton, QToolButton {
                border: 1px solid #303747;
                border-radius: 8px;
                background: #1c2029;
                color: #eef2f8;
                font-weight: 700;
                padding: 10px;
            }
            QPushButton:hover, QToolButton:hover {
                background: #262c38;
                border-color: #4c5970;
            }
            QPushButton:pressed, QToolButton:pressed {
                background: #245f9f;
                border-color: #67b7dc;
            }
            QPushButton#groupButton {
                background: #1c2029;
                font-size: 28px;
            }
            QPushButton#letterButton {
                background: #1c2029;
                font-size: 34px;
            }
            QPushButton#utilityButton {
                background: #202631;
                border-color: #3b4658;
                font-size: 24px;
            }
            QToolButton#playButton {
                background: #245f9f;
                border-color: #67b7dc;
                color: #ffffff;
                font-size: 18px;
            }
            QToolButton#clearButton {
                background: #1c2029;
                font-size: 18px;
            }
            QToolButton#phrasesButton {
                background: #1c2029;
                border-color: #303747;
                color: #eef2f8;
                font-size: 16px;
            }
            QToolButton#phrasesButton:checked {
                background: #245f9f;
                border-color: #67b7dc;
                color: #ffffff;
            }
            QToolButton#phraseActionButton {
                background: #1c2029;
                border-color: #303747;
                color: #eef2f8;
                font-size: 17px;
            }
            QToolButton#phrasePageButton {
                background: #1c2029;
                border-color: #303747;
                color: #eef2f8;
                font-size: 17px;
            }
            QToolButton#phrasePageButton:disabled {
                background: #151821;
                border-color: #262c38;
                color: #697386;
            }
            QToolButton#closeButton {
                background: #4b2224;
                border-color: #7d383e;
                color: #ffffff;
            }
            QPushButton#phraseButton {
                background: #1c2029;
                border-color: #303747;
                color: #eef2f8;
                font-size: 22px;
                text-align: left;
                padding-left: 18px;
                min-height: 72px;
                max-height: 72px;
            }
            QPushButton#phraseButton:disabled {
                background: #151821;
                border-color: #262c38;
                color: #697386;
            }
            QPushButton#deletePhraseButton {
                background: #4b2224;
                border-color: #7d383e;
                color: #fecaca;
                font-size: 18px;
                min-height: 72px;
                max-height: 72px;
            }
            QPushButton[gazeTarget="true"][gazePulse="0"],
            QToolButton[gazeTarget="true"][gazePulse="0"] {
                background: #f0c84a;
                border: 4px solid #ffe58a;
                color: #111318;
            }
            QPushButton[gazeTarget="true"][gazePulse="1"],
            QToolButton[gazeTarget="true"][gazePulse="1"] {
                background: #16a34a;
                border: 4px solid #86efac;
                color: #ffffff;
            }
            QToolButton#closeButton[gazeTarget="true"][gazePulse="0"] {
                background: #f0c84a;
                border-color: #ffe58a;
                color: #111318;
            }
            QToolButton#closeButton[gazeTarget="true"][gazePulse="1"] {
                background: #dc2626;
                border-color: #fecaca;
                color: #ffffff;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(12)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(12)

        self._input = QLineEdit(self)
        self._input.setObjectName("speechInput")
        self._input.setAlignment(Qt.AlignCenter)
        self._input.setMinimumHeight(72)
        self._input.setMinimumWidth(320)
        self._input.setMaximumWidth(900)
        self._input.setMaxLength(260)
        self._input.returnPressed.connect(self._play)

        self._phrases_button = self._make_tool_button(
            text="Phrases",
            action=self._action("phrases"),
            icon_name="fa5s.list",
            fallback=QStyle.StandardPixmap.SP_FileDialogListView,
            object_name="phrasesButton",
            size=84,
            icon_color="#eef2f8",
            width=122,
            checkable=True,
        )
        self._clear_button = self._make_tool_button(
            text="Clear",
            action=self._action("clear"),
            icon_name="fa5s.eraser",
            fallback=QStyle.StandardPixmap.SP_DialogResetButton,
            object_name="clearButton",
            size=84,
            icon_color="#eef2f8",
        )
        self._play_button = self._make_tool_button(
            text="Play",
            action=self._action("play"),
            icon_name="fa5s.play",
            fallback=QStyle.StandardPixmap.SP_MediaPlay,
            object_name="playButton",
            size=84,
            icon_color="#ffffff",
        )
        self._close_button = self._make_tool_button(
            text="",
            action=self._action("close"),
            icon_name="fa5s.times",
            fallback=QStyle.StandardPixmap.SP_DialogCloseButton,
            object_name="closeButton",
            size=84,
            icon_color="#ffffff",
        )
        self._close_button.setToolTip("Close")

        input_row.addWidget(self._phrases_button)
        input_row.addWidget(self._input, 3)
        input_row.addWidget(self._clear_button)
        input_row.addWidget(self._play_button)
        input_row.addWidget(self._close_button)

        self._phrase_actions_host = QWidget(self)
        self._phrase_actions_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        phrase_actions = QHBoxLayout(self._phrase_actions_host)
        phrase_actions.setContentsMargins(0, 0, 0, 0)
        phrase_actions.setSpacing(12)
        self._previous_phrase_page_host = QWidget(self._phrase_actions_host)
        self._previous_phrase_page_host.setFixedWidth(160)
        previous_page_layout = QHBoxLayout(self._previous_phrase_page_host)
        previous_page_layout.setContentsMargins(0, 0, 0, 0)
        previous_page_layout.setSpacing(0)
        self._previous_phrase_page_button = self._make_tool_button(
            text="Previous",
            action=self._action("phrase:page:previous"),
            icon_name="fa5s.chevron-left",
            fallback=QStyle.StandardPixmap.SP_ArrowBack,
            object_name="phrasePageButton",
            size=62,
            icon_color="#eef2f8",
            width=148,
            tool_button_style=Qt.ToolButtonTextBesideIcon,
        )
        previous_page_layout.addWidget(self._previous_phrase_page_button, 0, Qt.AlignLeft)

        self._new_phrase_button = self._make_tool_button(
            text="New phrase",
            action=self._action("phrase:new"),
            icon_name="fa5s.plus",
            fallback=QStyle.StandardPixmap.SP_FileDialogNewFolder,
            object_name="phraseActionButton",
            size=62,
            icon_color="#eef2f8",
            width=190,
            tool_button_style=Qt.ToolButtonTextBesideIcon,
        )
        self._save_phrase_button = self._make_tool_button(
            text="Save phrase",
            action=self._action("phrase:save"),
            icon_name="fa5s.save",
            fallback=QStyle.StandardPixmap.SP_DialogSaveButton,
            object_name="phraseActionButton",
            size=62,
            icon_color="#eef2f8",
            width=176,
        )
        self._cancel_phrase_button = self._make_tool_button(
            text="Cancel",
            action=self._action("phrase:cancel"),
            icon_name="fa5s.times",
            fallback=QStyle.StandardPixmap.SP_DialogCancelButton,
            object_name="phraseActionButton",
            size=62,
            icon_color="#eef2f8",
            width=144,
        )
        self._next_phrase_page_host = QWidget(self._phrase_actions_host)
        self._next_phrase_page_host.setFixedWidth(160)
        next_page_layout = QHBoxLayout(self._next_phrase_page_host)
        next_page_layout.setContentsMargins(0, 0, 0, 0)
        next_page_layout.setSpacing(0)
        self._next_phrase_page_button = self._make_tool_button(
            text="Next",
            action=self._action("phrase:page:next"),
            icon_name="fa5s.chevron-right",
            fallback=QStyle.StandardPixmap.SP_ArrowForward,
            object_name="phrasePageButton",
            size=62,
            icon_color="#eef2f8",
            width=148,
            tool_button_style=Qt.ToolButtonTextBesideIcon,
        )
        next_page_layout.addWidget(self._next_phrase_page_button, 0, Qt.AlignRight)

        phrase_actions.addWidget(self._previous_phrase_page_host)
        phrase_actions.addStretch(1)
        phrase_actions.addWidget(self._new_phrase_button)
        phrase_actions.addWidget(self._save_phrase_button)
        phrase_actions.addWidget(self._cancel_phrase_button)
        phrase_actions.addStretch(1)
        phrase_actions.addWidget(self._next_phrase_page_host)
        self._phrase_actions_host.hide()

        self._keyboard_host = QWidget(self)
        self._keyboard_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._keyboard_layout = QVBoxLayout(self._keyboard_host)
        self._keyboard_layout.setContentsMargins(0, 0, 0, 0)
        self._keyboard_layout.setSpacing(16)

        self._key_grid_host = QWidget(self._keyboard_host)
        self._key_grid_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._key_grid = QGridLayout(self._key_grid_host)
        self._key_grid.setContentsMargins(0, 0, 0, 0)
        self._key_grid.setHorizontalSpacing(14)
        self._key_grid.setVerticalSpacing(14)

        self._utility_host = QWidget(self._keyboard_host)
        self._utility_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._utility_layout = QHBoxLayout(self._utility_host)
        self._utility_layout.setContentsMargins(0, 0, 0, 0)
        self._utility_layout.setSpacing(14)

        self._keyboard_layout.addWidget(self._key_grid_host, 1)
        self._keyboard_layout.addWidget(self._utility_host, 0)

        root.addLayout(input_row)
        root.addWidget(self._phrase_actions_host)
        root.addWidget(self._keyboard_host, 1)

    def _show_group_level(self) -> None:
        self._active_group_index = None
        self._clear_dynamic_buttons()
        self._set_phrase_controls_visible()

        columns = _grid_column_count(
            len(self._letter_groups),
            max_columns=GROUP_GRID_MAX_COLUMNS,
            preferred_min_columns=3,
            max_rows=5,
        )
        self._set_grid_stretch(len(self._letter_groups), columns)
        for index, group in enumerate(self._letter_groups):
            action = self._action(f"group:{index}")
            button = self._make_key_button(
                " ".join(group),
                action,
                "groupButton",
                self._key_grid_host,
                GROUP_BUTTON_MIN_HEIGHT,
            )
            row = index // columns
            column = index % columns
            self._key_grid.addWidget(button, row, column)

        self._add_utility_button("Space", self._action("space"), stretch=1)
        self._add_utility_button("Backspace", self._action("backspace"), stretch=1)

        self._set_status("")

    def _show_letter_level(self, group_index: int) -> None:
        if group_index < 0 or group_index >= len(self._letter_groups):
            return

        self._active_group_index = group_index
        self._clear_dynamic_buttons()
        self._set_phrase_controls_visible()

        group = self._letter_groups[group_index]
        columns = _grid_column_count(
            len(group),
            max_columns=LETTER_GRID_MAX_COLUMNS,
            preferred_min_columns=4,
            max_rows=2,
        )
        self._set_grid_stretch(len(group), columns)

        for index, letter in enumerate(group):
            action = self._action(f"letter:{group_index}:{index}")
            button = self._make_key_button(
                letter,
                action,
                "letterButton",
                self._key_grid_host,
                LETTER_BUTTON_MIN_HEIGHT,
            )
            row = index // columns
            column = index % columns
            self._key_grid.addWidget(button, row, column)

        self._add_utility_button("Groups", self._action("groups"), stretch=1)
        self._add_utility_button("Space", self._action("space"), stretch=1)
        self._add_utility_button("Backspace", self._action("backspace"), stretch=1)

        self._set_status("")

    def _show_phrase_level(self) -> None:
        self._phrase_mode = "phrases"
        self._active_group_index = None
        self._clamp_phrase_page()
        self._clear_dynamic_buttons()
        self._set_phrase_controls_visible()
        self._input.setPlaceholderText("")

        visible_phrases = self._visible_phrases()
        rows = max(1, len(visible_phrases))
        self._set_grid_stretch(rows, 2)
        self._key_grid.setColumnStretch(0, 1)
        self._key_grid.setColumnStretch(1, 0)
        for row in range(rows):
            self._key_grid.setRowMinimumHeight(row, PHRASE_ROW_HEIGHT)

        if not self._phrases:
            empty = QPushButton("No phrases saved", self._key_grid_host)
            empty.setObjectName("phraseButton")
            empty.setEnabled(False)
            empty.setFixedHeight(PHRASE_ROW_HEIGHT)
            self._key_grid.addWidget(empty, 0, 0, 1, 2)
            self._set_status("No phrases saved.")
            return

        page_start = self._phrase_page * PHRASES_PER_PAGE
        for row, record in enumerate(visible_phrases):
            index = page_start + row
            phrase = record.text
            delete_button = self._make_key_button(
                "Delete",
                self._action(f"phrase:delete:{index}"),
                "deletePhraseButton",
                self._key_grid_host,
                PHRASE_ROW_HEIGHT,
                fixed_height=True,
            )
            phrase_button = self._make_key_button(
                phrase,
                self._action(f"phrase:select:{index}"),
                "phraseButton",
                self._key_grid_host,
                PHRASE_ROW_HEIGHT,
                fixed_height=True,
            )
            self._key_grid.addWidget(phrase_button, row, 0)
            self._key_grid.addWidget(delete_button, row, 1)

        self._set_status(f"Phrases page {self._phrase_page + 1} of {self._phrase_page_count()}.")

    def _clear_dynamic_buttons(self) -> None:
        self._set_gaze_target_action(None)
        for action in self._dynamic_actions:
            self._action_buttons.pop(action, None)
        self._dynamic_actions.clear()

        self._clear_layout(self._key_grid)
        self._clear_layout(self._utility_layout)
        self._set_grid_stretch(0, 1)

    def _clear_layout(self, layout: QGridLayout | QHBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _set_grid_stretch(self, item_count: int, columns: int) -> None:
        for column in range(GROUP_GRID_MAX_COLUMNS):
            self._key_grid.setColumnStretch(column, 0)
        for row in range(KEY_GRID_MAX_ROWS):
            self._key_grid.setRowStretch(row, 0)

        rows = max(1, math.ceil(max(1, item_count) / max(1, columns)))
        for column in range(columns):
            self._key_grid.setColumnStretch(column, 1)
        for row in range(rows):
            self._key_grid.setRowStretch(row, 1)

    def _add_utility_button(self, text: str, action: str, stretch: int) -> None:
        self._utility_layout.addWidget(
            self._make_key_button(
                text,
                action,
                "utilityButton",
                self._utility_host,
                UTILITY_BUTTON_MIN_HEIGHT,
            ),
            stretch,
        )

    def _make_key_button(
        self,
        text: str,
        action: str,
        object_name: str,
        parent: QWidget,
        minimum_height: int,
        fixed_height: bool = False,
    ) -> QPushButton:
        button = QPushButton(text, parent)
        button.setObjectName(object_name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if fixed_height:
            button.setFixedHeight(minimum_height)
        else:
            button.setMinimumHeight(minimum_height)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        button.setToolTip(text)
        self._register_button(action, button, dynamic=True)
        return button

    def _make_tool_button(
        self,
        text: str,
        action: str,
        icon_name: str,
        fallback: QStyle.StandardPixmap,
        object_name: str,
        size: int,
        icon_color: str,
        width: int | None = None,
        checkable: bool = False,
        tool_button_style: Qt.ToolButtonStyle | None = None,
    ) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName(object_name)
        button.setText(text)
        button.setIcon(self._icon(icon_name, fallback, icon_color))
        button.setIconSize(QSize(24, 24))
        if tool_button_style is None:
            tool_button_style = Qt.ToolButtonTextUnderIcon if text else Qt.ToolButtonIconOnly
        button.setToolButtonStyle(tool_button_style)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setCheckable(checkable)
        button.setFixedSize(width or size, size)
        self._register_button(action, button, dynamic=False)
        return button

    def _register_button(self, action: str, button: QWidget, dynamic: bool) -> None:
        self._action_buttons[action] = button
        button.setProperty("gazeTarget", False)
        button.setProperty("gazePulse", "")
        if dynamic:
            self._dynamic_actions.add(action)

        if isinstance(button, (QPushButton, QToolButton)):
            button.clicked.connect(lambda _checked=False, item=action: self._trigger_action(item))

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

    def _set_phrase_controls_visible(self) -> None:
        phrase_mode = self._phrase_mode == "phrases"
        editor_mode = self._phrase_mode == "phrase_editor"
        self._phrases_button.setChecked(phrase_mode or editor_mode)
        self._phrase_actions_host.setVisible(phrase_mode or editor_mode)
        self._new_phrase_button.setVisible(phrase_mode)
        self._previous_phrase_page_button.setVisible(phrase_mode and self._has_previous_phrase_page())
        self._next_phrase_page_button.setVisible(phrase_mode and self._has_next_phrase_page())
        self._save_phrase_button.setVisible(editor_mode)
        self._cancel_phrase_button.setVisible(editor_mode)
        self._play_button.setEnabled(not editor_mode)

    def _trigger_action(self, action: str) -> None:
        command = action.removeprefix(SPEECH_WINDOW_ACTION_PREFIX)

        if command == "close":
            self.close()
        elif command == "clear":
            self._input.clear()
            self._set_status("Cleared.")
        elif command == "play":
            self._play()
        elif command == "phrases":
            self._toggle_phrases()
        elif command == "space":
            self._append_text(" ")
        elif command == "backspace":
            self._backspace()
        elif command == "groups":
            self._show_group_level()
        elif command.startswith("group:"):
            self._show_letter_level(int(command.split(":", 1)[1]))
        elif command.startswith("letter:"):
            _prefix, group_text, letter_text = command.split(":", 2)
            group_index = int(group_text)
            letter_index = int(letter_text)
            self._append_text(self._letter_groups[group_index][letter_index])
            self._show_group_level()
        elif command == "phrase:new":
            self._start_phrase_editor()
        elif command == "phrase:save":
            self._save_phrase_from_editor()
        elif command == "phrase:cancel":
            self._cancel_phrase_editor()
        elif command == "phrase:page:previous":
            self._change_phrase_page(-1)
        elif command == "phrase:page:next":
            self._change_phrase_page(1)
        elif command.startswith("phrase:select:"):
            self._select_phrase(int(command.rsplit(":", 1)[1]))
        elif command.startswith("phrase:delete:"):
            self._delete_phrase(int(command.rsplit(":", 1)[1]))

    def _toggle_phrases(self) -> None:
        if self._phrase_mode == "keyboard":
            self._show_phrase_level()
            return

        if self._phrase_mode == "phrase_editor":
            self._cancel_phrase_editor()
            return

        self._phrase_mode = "keyboard"
        self._input.setPlaceholderText("")
        self._show_group_level()

    def _start_phrase_editor(self) -> None:
        self._speech_input_text = self._input.text()
        self._input.clear()
        self._input.setPlaceholderText("Create phrase")
        self._phrase_mode = "phrase_editor"
        self._show_group_level()
        self._set_status("Create phrase.")

    def _save_phrase_from_editor(self) -> None:
        phrase = " ".join(self._input.text().split())
        self._input.setText(self._speech_input_text)
        self._input.setPlaceholderText("")
        self._phrase_mode = "phrases"

        if not phrase:
            self._show_phrase_level()
            self._set_status("Phrase was empty.")
            return

        if not self._phrase_exists(phrase):
            self._phrases.append(PhraseRecord(text=phrase))
            self._sort_phrases_by_usage()
            self._phrase_page = self._page_for_phrase(phrase)
            _save_phrases(self._phrases)
            status = "Phrase saved."
        else:
            status = "Phrase already exists."

        self._show_phrase_level()
        self._set_status(status)

    def _cancel_phrase_editor(self) -> None:
        self._restore_input_if_editing_phrase()
        self._input.setPlaceholderText("")
        self._phrase_mode = "phrases"
        self._show_phrase_level()
        self._set_status("Phrase cancelled.")

    def _restore_input_if_editing_phrase(self) -> None:
        if self._phrase_mode != "phrase_editor":
            return

        self._input.setText(self._speech_input_text)
        self._input.setPlaceholderText("")

    def _select_phrase(self, index: int) -> None:
        if index < 0 or index >= len(self._phrases):
            return

        record = self._phrases[index]
        self._append_phrase_to_input(record.text)
        record.uses += 1
        self._sort_phrases_by_usage()
        self._phrase_page = self._page_for_phrase(record.text)
        _save_phrases(self._phrases)
        self._show_phrase_level()
        self._set_status("Phrase added.")

    def _delete_phrase(self, index: int) -> None:
        if index < 0 or index >= len(self._phrases):
            return

        removed = self._phrases.pop(index)
        _save_phrases(self._phrases)
        self._clamp_phrase_page()
        logger.info("Deleted speech phrase: %s", removed.text)
        self._show_phrase_level()
        self._set_status("Phrase deleted.")

    def _change_phrase_page(self, delta: int) -> None:
        old_page = self._phrase_page
        self._phrase_page = max(0, min(self._phrase_page_count() - 1, self._phrase_page + delta))
        if self._phrase_page == old_page:
            return

        self._show_phrase_level()

    def _visible_phrases(self) -> list[PhraseRecord]:
        start = self._phrase_page * PHRASES_PER_PAGE
        end = start + PHRASES_PER_PAGE
        return self._phrases[start:end]

    def _phrase_page_count(self) -> int:
        return max(1, math.ceil(len(self._phrases) / PHRASES_PER_PAGE))

    def _clamp_phrase_page(self) -> None:
        self._phrase_page = max(0, min(self._phrase_page, self._phrase_page_count() - 1))

    def _has_previous_phrase_page(self) -> bool:
        return self._phrase_page > 0

    def _has_next_phrase_page(self) -> bool:
        return self._phrase_page < self._phrase_page_count() - 1

    def _phrase_exists(self, phrase: str) -> bool:
        return any(record.text == phrase for record in self._phrases)

    def _sort_phrases_by_usage(self) -> None:
        self._phrases.sort(key=lambda record: (-record.uses, record.text.casefold()))

    def _page_for_phrase(self, phrase: str) -> int:
        for index, record in enumerate(self._phrases):
            if record.text == phrase:
                return index // PHRASES_PER_PAGE
        return 0

    def _append_text(self, value: str) -> None:
        current = self._input.text()
        self._input.setText(f"{current}{value}")
        self._input.setFocus(Qt.FocusReason.MouseFocusReason)

    def _append_phrase_to_input(self, phrase: str) -> None:
        current = self._input.text()
        if current and not current.endswith(" "):
            current = f"{current} "
        self._input.setText(f"{current}{phrase.strip()} ")
        self._input.setFocus(Qt.FocusReason.MouseFocusReason)

    def _backspace(self) -> None:
        text = self._input.text()
        if not text:
            return

        for letter in MULTI_CHARACTER_LETTERS:
            if text.endswith(letter):
                self._input.setText(text[: -len(letter)])
                return

        self._input.setText(text[:-1])

    def _play(self) -> None:
        text = self._input.text().strip()
        if not text:
            self._set_status("Input is empty.")
            return

        if self._speech.speak(text, self._speech_settings):
            self._set_status("Playing speech.")
        else:
            self._set_status("Selected voice engine is not available.")

    def _set_status(self, text: str) -> None:
        if text:
            logger.info("Speech status: %s", text)
        self.setToolTip(text)

    def _action(self, name: str) -> str:
        return f"{SPEECH_WINDOW_ACTION_PREFIX}{name}"

    def _icon(self, icon_name: str, fallback: QStyle.StandardPixmap, color: str) -> QIcon:
        try:
            import qtawesome as qta

            return qta.icon(icon_name, color=color)
        except Exception:
            logger.exception("Could not load qtawesome icon %s; using fallback.", icon_name)
            return self.style().standardIcon(fallback)


def _group_letters(letters: list[str], letters_per_group: int) -> list[list[str]]:
    return [
        letters[index : index + letters_per_group]
        for index in range(0, len(letters), letters_per_group)
    ]


def _grid_column_count(
    item_count: int,
    *,
    max_columns: int,
    preferred_min_columns: int,
    max_rows: int,
) -> int:
    if item_count <= 0:
        return 1

    return min(
        item_count,
        max_columns,
        max(
            min(item_count, preferred_min_columns),
            math.ceil(item_count / max_rows),
        ),
    )


def _phrases_path() -> Path:
    return get_project_root() / "data" / PHRASES_FILE


def _load_phrases() -> list[PhraseRecord]:
    path = _phrases_path()
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Could not load speech phrases from %s.", path)
        return []

    if not isinstance(data, list):
        logger.warning("Speech phrases file did not contain a list: %s", path)
        return []

    phrases_by_text: dict[str, PhraseRecord] = {}
    for item in data:
        phrase, uses = _parse_phrase_record(item)
        if not phrase:
            continue

        existing = phrases_by_text.get(phrase)
        if existing is None:
            phrases_by_text[phrase] = PhraseRecord(text=phrase, uses=uses)
        else:
            existing.uses = max(existing.uses, uses)

    return _sorted_phrase_records(list(phrases_by_text.values()))


def _save_phrases(phrases: list[PhraseRecord]) -> None:
    path = _phrases_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(
            json.dumps(
                [
                    {
                        "text": record.text,
                        "uses": max(0, int(record.uses)),
                    }
                    for record in _sorted_phrase_records(phrases)
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        logger.info("Saved %s speech phrases to %s.", len(phrases), path)
    except Exception:
        logger.exception("Could not save speech phrases to %s.", path)


def _parse_phrase_record(item: object) -> tuple[str, int]:
    if isinstance(item, dict):
        text = item.get("text", item.get("phrase", ""))
        uses = _safe_int(item.get("uses", item.get("count", 0)))
    else:
        text = item
        uses = 0

    phrase = " ".join(str(text).split())
    return phrase, max(0, uses)


def _safe_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _sorted_phrase_records(phrases: list[PhraseRecord]) -> list[PhraseRecord]:
    return sorted(phrases, key=lambda record: (-record.uses, record.text.casefold()))
