"""Full-screen Bosnian speech keyboard."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication, QPaintEvent, QPalette, QResizeEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionButton,
    QStylePainter,
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
    "DŽ",
    "Đ",
    "E",
    "F",
    "G",
    "H",
    "I",
    "J",
    "K",
    "L",
    "LJ",
    "M",
    "N",
    "NJ",
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
MULTI_CHARACTER_LETTERS = ("DŽ", "LJ", "NJ")
SYMBOLS = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "0", ".", "?")
GROUP_GRID_MAX_COLUMNS = 6
KEY_GRID_MAX_ROWS = 8
GROUP_BUTTON_MIN_HEIGHT = 72
PHRASE_BUTTON_MIN_HEIGHT = 64
PHRASES_PER_PAGE = 6
PHRASES_FILE = "speech_phrases.json"


@dataclass
class PhraseRecord:
    text: str
    uses: int = 0


class SpeechWindow(QWidget):
    """Fullscreen speech entry surface with gaze-selectable buttons."""

    closed = Signal()
    interaction_context_changed = Signal()

    def __init__(
        self,
        speech: SpeechService,
        parent: QWidget | None = None,
        letters_per_group: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("speechWindow")
        self.setWindowTitle("Govor")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)

        self._speech = speech
        initial_settings = speech.settings
        if letters_per_group is not None:
            initial_settings = replace(
                initial_settings, letters_per_group=max(1, letters_per_group)
            )

        self._speech_settings = initial_settings
        self._letters_per_group = max(1, self._speech_settings.letters_per_group)
        self._letter_groups = _group_letters(BOSNIAN_LETTERS, self._letters_per_group)
        self._action_buttons: dict[str, QPushButton] = {}
        self._main_dynamic_actions: set[str] = set()
        self._letter_dialog_actions: set[str] = set()
        self._dialog_actions: set[str] = set()
        self._active_dialog: QDialog | None = None
        self._gaze_target_action: str | None = None
        self._phrases = _load_phrases()
        self._phrase_page = 0
        self._speech_input_text = ""
        self._view_mode = "keyboard"
        self._symbols_mode = False

        self._build_ui()
        self._build_dialogs()
        self._show_group_level()
        logger.info("Speech window initialized with %s letter groups.", len(self._letter_groups))

    def show_full_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())

        self._restore_input_if_editing_phrase()
        self._view_mode = "keyboard"
        self._symbols_mode = False
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
            self._close_dialog()
            self._letter_groups = _group_letters(BOSNIAN_LETTERS, self._letters_per_group)
            if self._view_mode == "phrases":
                self._show_phrase_level()
            elif self._view_mode == "categories":
                self._show_category_level()
            elif self._symbols_mode:
                self._show_symbols_level()
            else:
                self._show_group_level()

        logger.info("Speech window settings updated: %s", self._speech_settings)

    def closeEvent(self, event: QCloseEvent) -> None:
        logger.info("Speech window close event received.")
        self._restore_input_if_editing_phrase()
        if self._active_dialog is not None:
            self._active_dialog.done(0)
        self._set_gaze_target_action(None)
        self.interaction_context_changed.emit()
        self.closed.emit()
        super().closeEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._modal_backdrop.setGeometry(self.rect())
        if self._active_dialog is not None:
            self._position_dialog(self._active_dialog)

    def action_at_global_point(self, point: QPoint) -> str | None:
        actions = (
            self._dialog_actions if self._active_dialog is not None else self._action_buttons.keys()
        )
        for action in tuple(actions):
            button = self._action_buttons.get(action)
            if button is None or not button.isVisible() or not button.isEnabled():
                continue
            top_left = button.mapToGlobal(QPoint(0, 0))
            if QRect(top_left, button.size()).contains(point):
                self._set_gaze_target_action(action)
                return action

        self._set_gaze_target_action(None)
        return None

    def action_center_at_global_point(self, action: str, point: QPoint) -> QPoint | None:
        if self._active_dialog is not None and action not in self._dialog_actions:
            return None
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
        if self._active_dialog is not None and action not in self._dialog_actions:
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
            QLabel#sectionLabel, QLabel#messageLabel, QLabel#statusLabel {
                color: #bac5d4;
                font-weight: 500;
            }
            QLabel#sectionLabel { font-size: 16px; }
            QLabel#messageLabel, QLabel#statusLabel { font-size: 13px; }
            QLineEdit#speechInput {
                background: #0b0d11;
                border: 2px solid #465268;
                border-radius: 8px;
                color: #ffffff;
                font-size: 30px;
                padding: 8px 16px;
                placeholder-text-color: #a0adbf;
                selection-background-color: #245f9f;
            }
            QPushButton {
                border: 1px solid #303747;
                border-radius: 8px;
                background: #1c2029;
                color: #eef2f8;
                font-size: 20px;
                font-weight: 700;
                padding: 8px;
            }
            QPushButton:hover { background: #262c38; border-color: #4c5970; }
            QPushButton:pressed, QPushButton:checked {
                background: #245f9f;
                border-color: #67b7dc;
            }
            QPushButton:disabled {
                background: #171a22;
                border-color: #2a303d;
                color: #667184;
            }
            QPushButton#clearButton {
                border-color: #67b7dc;
                background: #252b36;
                color: #ffe58a;
            }
            QPushButton#primaryButton {
                background: #2d68a8;
                border-color: #67b7dc;
                color: #ffffff;
                font-size: 23px;
            }
            QPushButton#predictionButton {
                background: #173447;
                border-color: #366c8d;
                color: #7995a7;
                font-size: 22px;
            }
            QPushButton#groupButton {
                background: #1c2029;
                font-size: 29px;
                letter-spacing: 2px;
            }
            QPushButton#symbolButton { font-size: 32px; }
            QPushButton#utilityButton { font-size: 22px; }
            QPushButton#systemAlarm {
                background: #552326;
                border-color: #94434a;
                color: #dbaeb1;
                font-size: 27px;
            }
            QPushButton#systemSleep {
                background: #202538;
                border-color: #5b658c;
                color: #afb6d2;
                font-size: 27px;
            }
            QPushButton#systemExit {
                background: #1c2029;
                border-color: #303747;
                color: #8791a3;
                font-size: 27px;
            }
            QPushButton#phraseButton {
                font-size: 19px;
            }
            QPushButton#deletePhraseButton {
                background: #4b2224;
                border-color: #7d383e;
                color: #fecaca;
                font-size: 16px;
            }
            QPushButton#headerActionButton { font-size: 15px; }
            QPushButton#closeSpeechButton {
                background: #252a34;
                color: #cbd4e2;
                font-size: 14px;
                font-weight: 600;
            }
            QFrame#modalBackdrop { background: rgba(0, 0, 0, 190); }
            QDialog#speechDialog {
                background: #111318;
                border: 2px solid #67b7dc;
                border-radius: 12px;
                color: #eef2f8;
            }
            QDialog#speechDialog QLabel#dialogTitle {
                color: #eef2f8;
                font-size: 27px;
                font-weight: 500;
            }
            QDialog#speechDialog QLabel#dialogCopy { color: #dce6f3; font-size: 20px; }
            QDialog#speechDialog QPushButton#dialogLetterButton {
                font-size: 34px;
                min-height: 100px;
            }
            QDialog#speechDialog QPushButton#dialogBackButton {
                font-size: 20px;
                min-height: 100px;
            }
            QDialog#speechDialog QPushButton#dialogConfirmButton {
                background: #552326;
                border-color: #94434a;
                color: #ffd5d7;
                min-height: 92px;
            }
            QDialog#speechDialog QPushButton#dialogCancelButton { min-height: 92px; }
            QWidget#speechWindow QPushButton[gazeTarget="true"][gazePulse="0"],
            QWidget#speechWindow QDialog#speechDialog QPushButton[gazeTarget="true"][gazePulse="0"] {
                background: #f0c84a;
                border: 4px solid #ffe58a;
                color: #111318;
            }
            QWidget#speechWindow QPushButton[gazeTarget="true"][gazePulse="1"],
            QWidget#speechWindow QDialog#speechDialog QPushButton[gazeTarget="true"][gazePulse="1"] {
                background: #16a34a;
                border: 4px solid #86efac;
                color: #ffffff;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(10)

        topbar = QHBoxLayout()
        topbar.setContentsMargins(0, 0, 0, 0)
        topbar.setSpacing(10)
        self._clear_button = self._make_button("Obriši", "clear", "clearButton", minimum_height=86)
        self._categories_button = self._make_button(
            "Kategorije", "categories", "topButton", minimum_height=86, checkable=True
        )

        message_box = QWidget(self)
        message_layout = QVBoxLayout(message_box)
        message_layout.setContentsMargins(0, 0, 0, 0)
        message_layout.setSpacing(4)
        self._message_label = QLabel("Vaša poruka", message_box)
        self._message_label.setObjectName("messageLabel")
        self._input = QLineEdit(message_box)
        self._input.setObjectName("speechInput")
        self._input.setAlignment(Qt.AlignCenter)
        self._input.setMinimumHeight(62)
        self._input.setMaxLength(260)
        self._input.setPlaceholderText("Odaberite grupu slova…")
        self._input.returnPressed.connect(self._play)
        message_layout.addWidget(self._message_label)
        message_layout.addWidget(self._input, 1)

        self._play_button = self._make_button(
            "Izgovori", "play", "primaryButton", minimum_height=86
        )
        self._phrases_button = self._make_button(
            "Fraze", "phrases", "topButton", minimum_height=86, checkable=True
        )
        topbar.addWidget(self._clear_button, 8)
        topbar.addWidget(self._categories_button, 10)
        topbar.addWidget(message_box, 40)
        topbar.addWidget(self._play_button, 10)
        topbar.addWidget(self._phrases_button, 9)

        predictions = QVBoxLayout()
        predictions.setContentsMargins(0, 0, 0, 0)
        predictions.setSpacing(6)
        prediction_label = QLabel("Brzi izbor", self)
        prediction_label.setObjectName("sectionLabel")
        predictions.addWidget(prediction_label)
        prediction_row = QHBoxLayout()
        prediction_row.setContentsMargins(0, 0, 0, 0)
        prediction_row.setSpacing(10)
        for _index in range(5):
            placeholder = QPushButton("·", self)
            placeholder.setObjectName("predictionButton")
            placeholder.setEnabled(False)
            placeholder.setMinimumHeight(66)
            placeholder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            prediction_row.addWidget(placeholder, 1)
        predictions.addLayout(prediction_row)

        workspace = QHBoxLayout()
        workspace.setContentsMargins(0, 0, 0, 0)
        workspace.setSpacing(10)
        main_panel = QWidget(self)
        main_layout = QVBoxLayout(main_panel)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)
        view_header = QHBoxLayout()
        view_header.setContentsMargins(0, 0, 0, 0)
        view_header.setSpacing(8)
        self._view_title = QLabel("Odaberite grupu slova", main_panel)
        self._view_title.setObjectName("sectionLabel")
        self._page_label = QLabel("", main_panel)
        self._page_label.setObjectName("sectionLabel")
        self._previous_phrase_button = self._make_button(
            "Prethodna", "phrase:page:previous", "headerActionButton", minimum_height=44
        )
        self._new_phrase_button = self._make_button(
            "Dodaj frazu", "phrase:new", "headerActionButton", minimum_height=44
        )
        self._save_phrase_button = self._make_button(
            "Sačuvaj", "phrase:save", "primaryButton", minimum_height=44
        )
        self._cancel_phrase_button = self._make_button(
            "Odustani", "phrase:cancel", "headerActionButton", minimum_height=44
        )
        self._next_phrase_button = self._make_button(
            "Sljedeća", "phrase:page:next", "headerActionButton", minimum_height=44
        )
        view_header.addWidget(self._view_title, 1)
        view_header.addWidget(self._previous_phrase_button)
        view_header.addWidget(self._page_label)
        view_header.addWidget(self._new_phrase_button)
        view_header.addWidget(self._save_phrase_button)
        view_header.addWidget(self._cancel_phrase_button)
        view_header.addWidget(self._next_phrase_button)

        self._key_grid_host = QWidget(main_panel)
        self._key_grid_host.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._key_grid = QGridLayout(self._key_grid_host)
        self._key_grid.setContentsMargins(0, 0, 0, 0)
        self._key_grid.setHorizontalSpacing(10)
        self._key_grid.setVerticalSpacing(10)
        main_layout.addLayout(view_header)
        main_layout.addWidget(self._key_grid_host, 1)

        system_panel = QWidget(self)
        system_layout = QVBoxLayout(system_panel)
        system_layout.setContentsMargins(0, 0, 0, 0)
        system_layout.setSpacing(8)
        controls_label = QLabel("Kontrole", system_panel)
        controls_label.setObjectName("sectionLabel")
        system_layout.addWidget(controls_label)
        for title, subtitle, object_name in (
            ("Alarm", "Pozovi pomoć", "systemAlarm"),
            ("Sleep", "Odmori oči", "systemSleep"),
            ("Izlaz", "Zatvori aplikaciju", "systemExit"),
        ):
            button = QPushButton(f"{title}\n{subtitle}", system_panel)
            button.setObjectName(object_name)
            button.setEnabled(False)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            system_layout.addWidget(button, 1)

        workspace.addWidget(main_panel, 145)
        workspace.addWidget(system_panel, 100)

        utility_row = QHBoxLayout()
        utility_row.setContentsMargins(0, 0, 0, 0)
        utility_row.setSpacing(10)
        self._space_button = self._make_button(
            "Razmak", "space", "utilityButton", minimum_height=76
        )
        self._backspace_button = self._make_button(
            "Obriši slovo", "backspace", "utilityButton", minimum_height=76
        )
        self._keyboard_toggle_button = self._make_button(
            "Brojevi i znakovi", "keyboard-toggle", "utilityButton", minimum_height=76
        )
        utility_row.addWidget(self._space_button, 14)
        utility_row.addWidget(self._backspace_button, 10)
        utility_row.addWidget(self._keyboard_toggle_button, 10)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(10)
        self._status_label = QLabel("Odaberite grupu, zatim slovo.", self)
        self._status_label.setObjectName("statusLabel")
        self._status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._close_speech_button = self._make_button(
            "Zatvori govor", "close", "closeSpeechButton", minimum_height=40
        )
        self._close_speech_button.setMinimumWidth(160)
        footer.addWidget(self._status_label, 1)
        footer.addWidget(self._close_speech_button)

        root.addLayout(topbar)
        root.addLayout(predictions)
        root.addLayout(workspace, 1)
        root.addLayout(utility_row)
        root.addLayout(footer)

        self._modal_backdrop = QFrame(self)
        self._modal_backdrop.setObjectName("modalBackdrop")
        self._modal_backdrop.hide()

    def _build_dialogs(self) -> None:
        self._letter_dialog = self._new_dialog()
        letter_layout = QVBoxLayout(self._letter_dialog)
        letter_layout.setContentsMargins(24, 22, 24, 24)
        letter_layout.setSpacing(18)
        self._letter_dialog_title = QLabel("Odaberite slovo", self._letter_dialog)
        self._letter_dialog_title.setObjectName("dialogTitle")
        self._letter_grid_host = QWidget(self._letter_dialog)
        self._letter_grid = QGridLayout(self._letter_grid_host)
        self._letter_grid.setContentsMargins(0, 0, 0, 0)
        self._letter_grid.setHorizontalSpacing(16)
        self._letter_grid.setVerticalSpacing(16)
        letter_layout.addWidget(self._letter_dialog_title)
        letter_layout.addWidget(self._letter_grid_host, 1)
        self._letter_dialog.finished.connect(
            lambda _result, dialog=self._letter_dialog: self._dialog_finished(dialog)
        )

        self._confirm_dialog = self._new_dialog()
        confirm_layout = QVBoxLayout(self._confirm_dialog)
        confirm_layout.setContentsMargins(24, 22, 24, 24)
        confirm_layout.setSpacing(18)
        confirm_title = QLabel("Obrisati sav tekst?", self._confirm_dialog)
        confirm_title.setObjectName("dialogTitle")
        self._confirm_copy = QLabel("Cijela poruka bit će obrisana.", self._confirm_dialog)
        self._confirm_copy.setObjectName("dialogCopy")
        self._confirm_copy.setWordWrap(True)
        confirm_actions = QHBoxLayout()
        confirm_actions.setContentsMargins(0, 0, 0, 0)
        confirm_actions.setSpacing(18)
        cancel = self._make_button(
            "Odustani",
            "clear:cancel",
            "dialogCancelButton",
            parent=self._confirm_dialog,
            minimum_height=92,
        )
        confirm = self._make_button(
            "Obriši tekst",
            "clear:confirm",
            "dialogConfirmButton",
            parent=self._confirm_dialog,
            minimum_height=92,
        )
        confirm_actions.addWidget(cancel, 1)
        confirm_actions.addWidget(confirm, 1)
        confirm_layout.addWidget(confirm_title)
        confirm_layout.addWidget(self._confirm_copy)
        confirm_layout.addStretch(1)
        confirm_layout.addLayout(confirm_actions)
        self._confirm_dialog.finished.connect(
            lambda _result, dialog=self._confirm_dialog: self._dialog_finished(dialog)
        )

    def _new_dialog(self) -> QDialog:
        dialog = QDialog(self)
        dialog.setObjectName("speechDialog")
        dialog.setModal(True)
        dialog.setWindowModality(Qt.ApplicationModal)
        dialog.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        return dialog

    def _show_group_level(self) -> None:
        self._symbols_mode = False
        if self._view_mode != "phrase_editor":
            self._view_mode = "keyboard"
        self._clear_main_grid()
        self._view_title.setText("Odaberite grupu slova")

        group_count = len(self._letter_groups)
        columns = self._group_column_count(group_count)
        self._set_grid_stretch(group_count, columns)
        for index, group in enumerate(self._letter_groups):
            action = self._action(f"group:{index}")
            button = self._make_dynamic_button(" ".join(group), action, "groupButton")
            self._key_grid.addWidget(button, index // columns, index % columns)

        self._update_view_controls()
        self._set_status("Odaberite grupu, zatim slovo.")
        self._context_changed()

    def _show_symbols_level(self) -> None:
        if self._view_mode != "phrase_editor":
            self._view_mode = "keyboard"
        self._symbols_mode = True
        self._clear_main_grid()
        self._view_title.setText("Brojevi i znakovi")
        self._set_grid_stretch(len(SYMBOLS), 4)
        for index, symbol in enumerate(SYMBOLS):
            action = self._action(f"symbol:{index}")
            button = self._make_dynamic_button(symbol, action, "symbolButton")
            self._key_grid.addWidget(button, index // 4, index % 4)

        self._update_view_controls()
        self._set_status("Odaberite broj ili znak.")
        self._context_changed()

    def _show_category_level(self) -> None:
        self._view_mode = "categories"
        self._symbols_mode = False
        self._clear_main_grid()
        self._view_title.setText("Kategorije")
        self._set_grid_stretch(1, 1)
        empty = QPushButton("Nema dostupnih kategorija.", self._key_grid_host)
        empty.setObjectName("phraseButton")
        empty.setEnabled(False)
        empty.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._key_grid.addWidget(empty, 0, 0)
        self._update_view_controls()
        self._set_status("Nema dostupnih kategorija.")
        self._context_changed()

    def _show_phrase_level(self) -> None:
        self._view_mode = "phrases"
        self._symbols_mode = False
        self._clamp_phrase_page()
        self._clear_main_grid()
        self._view_title.setText("Moje fraze")

        visible_phrases = self._visible_phrases()
        self._set_grid_stretch(PHRASES_PER_PAGE, 2)

        if not self._phrases:
            empty = QPushButton("Nema sačuvanih fraza.", self._key_grid_host)
            empty.setObjectName("phraseButton")
            empty.setEnabled(False)
            self._key_grid.addWidget(empty, 0, 0, 3, 2)
            self._set_status("Nema sačuvanih fraza.")
        else:
            page_start = self._phrase_page * PHRASES_PER_PAGE
            for position, record in enumerate(visible_phrases):
                index = page_start + position
                card = QWidget(self._key_grid_host)
                card_layout = QVBoxLayout(card)
                card_layout.setContentsMargins(0, 0, 0, 0)
                card_layout.setSpacing(4)
                phrase_button = self._make_dynamic_button(
                    record.text, self._action(f"phrase:select:{index}"), "phraseButton"
                )
                delete_button = self._make_dynamic_button(
                    "Obriši", self._action(f"phrase:delete:{index}"), "deletePhraseButton"
                )
                phrase_button.setMinimumHeight(PHRASE_BUTTON_MIN_HEIGHT)
                delete_button.setMinimumHeight(40)
                delete_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                card_layout.addWidget(phrase_button, 1)
                card_layout.addWidget(delete_button)
                self._key_grid.addWidget(card, position // 2, position % 2)
            self._set_status(
                f"Fraze, stranica {self._phrase_page + 1} od {self._phrase_page_count()}."
            )

        self._update_view_controls()
        self._context_changed()

    def _populate_letter_dialog(self, group_index: int) -> None:
        self._clear_letter_dialog()
        group = self._letter_groups[group_index]
        self._letter_dialog_title.setText(f"Odaberite slovo: {' '.join(group)}")
        item_count = len(group) + 1
        columns = 3 if item_count <= 6 else 4
        rows = math.ceil(item_count / columns)
        for column in range(4):
            self._letter_grid.setColumnStretch(column, 1 if column < columns else 0)
        for row in range(5):
            self._letter_grid.setRowStretch(row, 1 if row < rows else 0)

        for index, letter in enumerate(group):
            action = self._action(f"letter:{group_index}:{index}")
            button = self._make_button(
                letter,
                action,
                "dialogLetterButton",
                parent=self._letter_dialog,
                minimum_height=100,
            )
            self._letter_dialog_actions.add(action)
            self._letter_grid.addWidget(button, index // columns, index % columns)

        back_action = self._action("letters:close")
        back = self._make_button(
            "Nazad na grupe",
            back_action,
            "dialogBackButton",
            parent=self._letter_dialog,
            minimum_height=100,
        )
        self._letter_dialog_actions.add(back_action)
        back_index = len(group)
        self._letter_grid.addWidget(back, back_index // columns, back_index % columns)

    def _open_letter_dialog(self, group_index: int) -> None:
        if group_index < 0 or group_index >= len(self._letter_groups):
            return
        self._populate_letter_dialog(group_index)
        self._dialog_actions = set(self._letter_dialog_actions)
        item_count = len(self._letter_groups[group_index]) + 1
        columns = 3 if item_count <= 6 else 4
        rows = math.ceil(item_count / columns)
        self._open_dialog(self._letter_dialog, min(760, 172 + rows * 126))

    def _open_clear_dialog(self) -> None:
        if not self._input.text():
            self._set_status("Poruka je već prazna.")
            return
        if self._view_mode == "phrase_editor":
            self._confirm_copy.setText(
                "Obrisat će se samo nova fraza. Vaša poruka za razgovor ostaje sačuvana."
            )
        else:
            self._confirm_copy.setText("Cijela poruka bit će obrisana.")
        self._dialog_actions = {self._action("clear:cancel"), self._action("clear:confirm")}
        self._open_dialog(self._confirm_dialog, 330)

    def _open_dialog(self, dialog: QDialog, height: int) -> None:
        self._context_changed()
        self._active_dialog = dialog
        self._modal_backdrop.setGeometry(self.rect())
        self._modal_backdrop.show()
        self._modal_backdrop.raise_()
        width = max(520, min(960, self.width() - 80))
        dialog.resize(width, min(height, max(300, self.height() - 64)))
        self._position_dialog(dialog)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _position_dialog(self, dialog: QDialog) -> None:
        center = self.mapToGlobal(self.rect().center())
        dialog.move(center.x() - dialog.width() // 2, center.y() - dialog.height() // 2)

    def _close_dialog(self) -> None:
        if self._active_dialog is not None:
            self._active_dialog.done(0)

    def _dialog_finished(self, dialog: QDialog) -> None:
        if dialog is not self._active_dialog:
            return
        self._active_dialog = None
        self._dialog_actions.clear()
        self._modal_backdrop.hide()
        self._context_changed()

    def _clear_main_grid(self) -> None:
        self._set_gaze_target_action(None)
        for action in self._main_dynamic_actions:
            self._action_buttons.pop(action, None)
        self._main_dynamic_actions.clear()
        self._clear_layout(self._key_grid)
        self._set_grid_stretch(0, 1)

    def _clear_letter_dialog(self) -> None:
        for action in self._letter_dialog_actions:
            self._action_buttons.pop(action, None)
        self._letter_dialog_actions.clear()
        self._clear_layout(self._letter_grid)

    def _clear_layout(self, layout: QGridLayout | QHBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
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

    def _group_column_count(self, item_count: int) -> int:
        if item_count <= 1:
            return 1
        if item_count <= 8:
            return 2
        return min(GROUP_GRID_MAX_COLUMNS, math.ceil(item_count / 5))

    def _make_dynamic_button(self, text: str, action: str, object_name: str) -> QPushButton:
        button = self._make_button(
            text,
            action,
            object_name,
            parent=self._key_grid_host,
            minimum_height=GROUP_BUTTON_MIN_HEIGHT,
        )
        self._main_dynamic_actions.add(action)
        return button

    def _make_button(
        self,
        text: str,
        command: str,
        object_name: str,
        *,
        parent: QWidget | None = None,
        minimum_height: int,
        checkable: bool = False,
    ) -> QPushButton:
        button_type = (
            _WrappedButton if object_name in ("groupButton", "phraseButton") else QPushButton
        )
        button = button_type(text, self if parent is None else parent)
        button.setObjectName(object_name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setCheckable(checkable)
        button.setMinimumHeight(minimum_height)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        if isinstance(button, _WrappedButton):
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        action = (
            self._action(command)
            if not command.startswith(SPEECH_WINDOW_ACTION_PREFIX)
            else command
        )
        self._register_button(action, button)
        return button

    def _register_button(self, action: str, button: QPushButton) -> None:
        self._action_buttons[action] = button
        button.setProperty("gazeTarget", False)
        button.setProperty("gazePulse", "")
        button.clicked.connect(lambda _checked=False, item=action: self._trigger_action(item))

    def _set_gaze_target_action(self, action: str | None) -> None:
        if action == self._gaze_target_action:
            return
        if self._gaze_target_action is not None:
            previous = self._action_buttons.get(self._gaze_target_action)
            if previous is not None:
                set_gaze_feedback(previous, False)
        self._gaze_target_action = action
        if action is not None:
            current = self._action_buttons.get(action)
            if current is not None:
                set_gaze_feedback(current, True)

    def _context_changed(self) -> None:
        self._set_gaze_target_action(None)
        self.interaction_context_changed.emit()

    def _update_view_controls(self) -> None:
        phrase_mode = self._view_mode == "phrases"
        editor_mode = self._view_mode == "phrase_editor"
        category_mode = self._view_mode == "categories"
        self._categories_button.setChecked(category_mode)
        self._categories_button.setText("Tastatura" if category_mode else "Kategorije")
        self._phrases_button.setChecked(phrase_mode or editor_mode)
        self._phrases_button.setText("Tastatura" if phrase_mode or editor_mode else "Fraze")
        self._categories_button.setEnabled(not editor_mode)
        self._play_button.setEnabled(not editor_mode)
        self._previous_phrase_button.setVisible(phrase_mode and self._has_previous_phrase_page())
        self._next_phrase_button.setVisible(phrase_mode and self._has_next_phrase_page())
        self._page_label.setVisible(phrase_mode)
        self._page_label.setText(
            f"{self._phrase_page + 1}/{self._phrase_page_count()}" if phrase_mode else ""
        )
        self._new_phrase_button.setVisible(phrase_mode)
        self._save_phrase_button.setVisible(editor_mode)
        self._cancel_phrase_button.setVisible(editor_mode)
        self._message_label.setText("Nova fraza" if editor_mode else "Vaša poruka")
        self._input.setPlaceholderText(
            "Unesite tekst…" if editor_mode else "Odaberite grupu slova…"
        )
        if self._view_mode in ("categories", "phrases"):
            self._keyboard_toggle_button.setText("Tastatura")
        elif self._symbols_mode:
            self._keyboard_toggle_button.setText("Grupe slova")
        else:
            self._keyboard_toggle_button.setText("Brojevi i znakovi")

    def _trigger_action(self, action: str) -> None:
        if self._active_dialog is not None and action not in self._dialog_actions:
            return
        button = self._action_buttons.get(action)
        if button is None or not button.isVisible() or not button.isEnabled():
            return
        command = action.removeprefix(SPEECH_WINDOW_ACTION_PREFIX)

        if command == "close":
            self.close()
        elif command == "clear":
            self._open_clear_dialog()
        elif command == "clear:cancel":
            self._close_dialog()
        elif command == "clear:confirm":
            self._input.clear()
            self._close_dialog()
            self._set_status("Tekst je obrisan.")
        elif command == "play":
            self._play()
        elif command == "categories":
            self._toggle_categories()
        elif command == "phrases":
            self._toggle_phrases()
        elif command == "space":
            self._append_text(" ")
        elif command == "backspace":
            self._backspace()
        elif command == "keyboard-toggle":
            self._toggle_keyboard_view()
        elif command == "letters:close":
            self._close_dialog()
        elif command.startswith("group:"):
            self._open_letter_dialog(int(command.split(":", 1)[1]))
        elif command.startswith("letter:"):
            _prefix, group_text, letter_text = command.split(":", 2)
            group_index = int(group_text)
            letter_index = int(letter_text)
            self._append_text(self._letter_groups[group_index][letter_index])
            self._close_dialog()
        elif command.startswith("symbol:"):
            self._append_text(SYMBOLS[int(command.split(":", 1)[1])])
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

    def _toggle_categories(self) -> None:
        if self._view_mode == "categories":
            self._show_group_level()
        else:
            self._restore_input_if_editing_phrase()
            self._show_category_level()

    def _toggle_phrases(self) -> None:
        if self._view_mode == "phrases":
            self._show_group_level()
        elif self._view_mode == "phrase_editor":
            self._restore_input_if_editing_phrase()
            self._view_mode = "keyboard"
            self._show_group_level()
        else:
            self._show_phrase_level()

    def _toggle_keyboard_view(self) -> None:
        if self._view_mode in ("categories", "phrases") or self._symbols_mode:
            self._show_group_level()
        else:
            self._show_symbols_level()

    def _start_phrase_editor(self) -> None:
        self._speech_input_text = self._input.text()
        self._input.clear()
        self._view_mode = "phrase_editor"
        self._symbols_mode = False
        self._show_group_level()
        self._view_title.setText("Dodaj novu frazu")
        self._update_view_controls()
        self._set_status("Sastavite novu frazu i odaberite Sačuvaj.")

    def _save_phrase_from_editor(self) -> None:
        phrase = " ".join(self._input.text().split())
        self._input.setText(self._speech_input_text)
        self._view_mode = "phrases"

        if not phrase:
            self._show_phrase_level()
            self._set_status("Fraza je prazna.")
            return
        if not self._phrase_exists(phrase):
            self._phrases.append(PhraseRecord(text=phrase))
            self._sort_phrases_by_usage()
            self._phrase_page = self._page_for_phrase(phrase)
            _save_phrases(self._phrases)
            status = "Fraza je sačuvana."
        else:
            status = "Fraza već postoji."
        self._show_phrase_level()
        self._set_status(status)

    def _cancel_phrase_editor(self) -> None:
        self._restore_input_if_editing_phrase()
        self._view_mode = "phrases"
        self._show_phrase_level()
        self._set_status("Dodavanje fraze je otkazano.")

    def _restore_input_if_editing_phrase(self) -> None:
        if self._view_mode == "phrase_editor":
            self._input.setText(self._speech_input_text)

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
        self._set_status("Fraza je dodana u poruku.")

    def _delete_phrase(self, index: int) -> None:
        if index < 0 or index >= len(self._phrases):
            return
        removed = self._phrases.pop(index)
        _save_phrases(self._phrases)
        self._clamp_phrase_page()
        logger.info("Deleted speech phrase: %s", removed.text)
        self._show_phrase_level()
        self._set_status("Fraza je obrisana.")

    def _change_phrase_page(self, delta: int) -> None:
        old_page = self._phrase_page
        self._phrase_page = max(0, min(self._phrase_page_count() - 1, self._phrase_page + delta))
        if self._phrase_page != old_page:
            self._show_phrase_level()

    def _visible_phrases(self) -> list[PhraseRecord]:
        start = self._phrase_page * PHRASES_PER_PAGE
        return self._phrases[start : start + PHRASES_PER_PAGE]

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
        self._input.setText(f"{self._input.text()}{value}")
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
        folded = text.casefold()
        for letter in MULTI_CHARACTER_LETTERS:
            if folded.endswith(letter.casefold()):
                self._input.setText(text[: -len(letter)])
                return
        self._input.setText(text[:-1])

    def _play(self) -> None:
        # Return in the input field can invoke this even when Izgovori is disabled.
        if self._view_mode == "phrase_editor" or self._active_dialog is not None:
            return
        text = self._input.text().strip()
        if not text:
            self._set_status("Prvo sastavite poruku.")
            return
        if self._speech.speak(text, self._speech_settings):
            self._set_status("Poruka se izgovara.")
        else:
            self._set_status("Odabrani glas nije dostupan.")

    def _set_status(self, text: str) -> None:
        if text:
            logger.info("Speech status: %s", text)
        self._status_label.setText(text)

    def _action(self, name: str) -> str:
        return f"{SPEECH_WINDOW_ACTION_PREFIX}{name}"


class _WrappedButton(QPushButton):
    """Keep long phrases and letter groups inside their allotted grid cell."""

    def paintEvent(self, event: QPaintEvent) -> None:
        option = QStyleOptionButton()
        self.initStyleOption(option)
        text = option.text
        option.text = ""
        painter = QStylePainter(self)
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)
        rect = self.style().subElementRect(QStyle.SubElement.SE_PushButtonContents, option, self)
        painter.drawItemText(
            rect,
            int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap),
            option.palette,
            self.isEnabled(),
            text,
            QPalette.ColorRole.ButtonText,
        )


def _group_letters(letters: list[str], letters_per_group: int) -> list[list[str]]:
    return [
        letters[index : index + letters_per_group]
        for index in range(0, len(letters), letters_per_group)
    ]


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
                    {"text": record.text, "uses": max(0, int(record.uses))}
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
