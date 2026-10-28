"""Full-screen Bosnian speech keyboard."""

from __future__ import annotations

import copy
import logging
import math
from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication, QKeyEvent
from PySide6.QtWidgets import QDialog, QPushButton, QWidget

from .. import diagnostics
from ..keyboard_layouts import (
    ARABIC_SCRIPT,
    key_label,
    letters_for_script,
    other_script,
    switch_label,
    symbols_for_script,
)
from ..keyboard_layouts import BOSNIAN_LETTERS as BOSNIAN_LETTERS
from ..keyboard_layouts import group_keys as _group_letters
from ..logging_setup import get_project_root
from ..speech.alarm_sound import ALARM_UNAVAILABLE_MESSAGE, AlarmSound
from ..speech.speech_library import (
    CategoryRecord,
    PhraseRecord,
    SpeechLibraryStore,
    sorted_phrases,
    speech_library_store,
)
from ..speech.speech_service import SpeechService, SpeechSettings
from ..suggestions.composition import Composition
from ..suggestions.service import SuggestionService
from .speech_editor import EditorContext
from .speech_library_actions import ITEMS_PER_PAGE, SpeechLibraryActions
from .speech_playback_controls import SpeechPlaybackControls
from .speech_predictions import PredictionControls, SpeechPredictions
from .speech_surface import SPEECH_WINDOW_ACTION_PREFIX as SPEECH_WINDOW_ACTION_PREFIX
from .speech_surface import SpeechSurface

logger = logging.getLogger(__name__)

MULTI_CHARACTER_LETTERS = ("DŽ", "LJ", "NJ")
SYMBOLS = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "0", ".", "?")
PHRASE_BUTTON_MIN_HEIGHT = 64
GROUP_GRID_MAX_COLUMNS = 6
KEYS_PER_PAGE = 12


class SpeechWindow(SpeechPlaybackControls, SpeechLibraryActions, SpeechSurface):
    """Fullscreen speech entry surface with gaze-selectable buttons."""

    closed = Signal()
    quit_requested = Signal()
    keyboard_script_changed = Signal(str)

    @property
    def has_unsaved_input(self) -> bool:
        return bool(self._input.text().strip() or self._editor is not None)

    def __init__(
        self,
        speech: SpeechService,
        parent: QWidget | None = None,
        letters_per_group: int | None = None,
        library_store: SpeechLibraryStore | None = None,
        alarm_sound: AlarmSound | None = None,
        suggestions: SuggestionService | None = None,
    ) -> None:
        initial_settings = speech.settings
        if letters_per_group is not None:
            initial_settings = replace(
                initial_settings, letters_per_group=max(1, letters_per_group)
            )

        super().__init__(parent, initial_settings.keyboard_script)
        self._speech = speech
        self._playback_id: int | None = None
        self._speech.playback_changed.connect(self._playback_changed)
        self._speech.voice_changed.connect(self._voice_changed)
        self._speech_settings = initial_settings
        self._keyboard_page = 0
        self._active_group_index: int | None = None
        self._last_gaze_point: QPoint | None = None
        self._keyboard_departure_bounds: QRect | None = None
        self._letters_per_group = max(1, self._speech_settings.letters_per_group)
        self._letter_groups = _group_letters(
            letters_for_script(initial_settings.keyboard_script), self._letters_per_group
        )
        self._symbols = symbols_for_script(initial_settings.keyboard_script, SYMBOLS)
        self._symbol_groups = _group_letters(self._symbols, max(5, self._letters_per_group))
        self._library_store = library_store or speech_library_store(get_project_root())
        self._alarm_sound = alarm_sound or AlarmSound(self)
        self._alarm_sound.failed.connect(self._alarm_failed)
        self._library = self._library_store.load()
        self._sync_saved_audio()
        self._list_page = 0
        self._category_index: int | None = None
        self._deletion_mode = False
        self._editor: EditorContext | None = None
        self._confirm_action: Callable[[], None] | None = None
        self._view_mode = "keyboard"
        self._symbols_mode = False
        self._suggestions = suggestions or SuggestionService(self)
        self._composition = Composition(self._suggestions.store)
        self._conversation = self._composition
        self._updating_input = False
        self._predictions = SpeechPredictions(
            PredictionControls(
                self._input,
                self._prediction_label,
                self._prediction_buttons,
                self._undo_word_button,
            ),
            self._suggestions,
            self._suggestion_allowed,
            self._context_changed,
        )

        self.action_requested.connect(self._trigger_action)
        self.dialog_closed.connect(self._after_dialog_closed)
        self._input.returnPressed.connect(self._play)
        self._sync_script_controls()
        self._sync_voice_notice()
        self._input.textChanged.connect(self._text_changed)
        self._input.cursorPositionChanged.connect(self._refresh_suggestions)
        self._input.selectionChanged.connect(self._refresh_suggestions)
        self._show_group_level()
        self._predictions.show_status(self._suggestions.status)
        state = speech.playback_state
        if state in ("preparing", "speaking"):
            self._playback_id = speech.request_id
            self._playback_changed(speech.request_id, state)
        logger.info("Speech window initialized with %s letter groups.", len(self._letter_groups))

    def show_full_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())

        self._restore_message_if_editing()
        self._editor = None
        self._view_mode = "keyboard"
        self._category_index = None
        self._list_page = 0
        self._deletion_mode = False
        self._symbols_mode = False
        self._show_group_level()
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self._input.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        logger.info("Speech window shown full-screen.")

    def update_settings(self, settings: SpeechSettings) -> None:
        old_letters_per_group = self._letters_per_group
        old_script = self._speech_settings.keyboard_script
        self._speech_settings = replace(settings)
        self._letters_per_group = max(1, self._speech_settings.letters_per_group)
        if (
            self._letters_per_group != old_letters_per_group
            or old_script != settings.keyboard_script
        ):
            self._keyboard_page = 0
            self._close_dialog()
            self._letter_groups = _group_letters(
                letters_for_script(settings.keyboard_script), self._letters_per_group
            )
            self._symbols = symbols_for_script(settings.keyboard_script, SYMBOLS)
            self._symbol_groups = _group_letters(self._symbols, max(5, self._letters_per_group))
            if self._is_list_mode():
                self._show_list_level()
            elif self._symbols_mode:
                self._show_symbols_level()
            else:
                self._show_group_level()
            self._sync_script_controls()
            self._refresh_suggestions()

        logger.info("Speech window settings updated: %s", self._speech_settings)
        self._sync_voice_notice()

    def _sync_script_controls(self) -> None:
        arabic = self._speech_settings.keyboard_script == ARABIC_SCRIPT
        direction = Qt.RightToLeft if arabic else Qt.LeftToRight
        self._input.setLayoutDirection(direction)
        self._input.setAlignment((Qt.AlignRight | Qt.AlignAbsolute) if arabic else Qt.AlignCenter)
        self._script_button.setText(switch_label(self._speech_settings.keyboard_script))
        self._prediction_divider.setVisible(not arabic)
        for widget in [self._prediction_label, *self._prediction_buttons, self._undo_word_button]:
            widget.setVisible(not arabic)

    def _switch_keyboard_script(self) -> None:
        script = other_script(self._speech_settings.keyboard_script)
        self.update_settings(replace(self._speech_settings, keyboard_script=script))
        self.keyboard_script_changed.emit(script)

    def closeEvent(self, event: QCloseEvent) -> None:
        logger.info("Speech window close event received.")
        self._restore_message_if_editing()
        self._alarm_sound.stop()
        if self._dialogs.active is not None:
            self._dialogs.active.done(0)
        self._set_gaze_target_action(None)
        self.interaction_context_changed.emit()
        self.closed.emit()
        super().closeEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (
            event.key() == Qt.Key_Escape
            and self._active_group_index is not None
            and self._dialogs.active is None
        ):
            self._show_keyboard_groups()
            self._restore_input_focus()
            event.accept()
            return
        super().keyPressEvent(event)

    def action_at_global_point(self, point: QPoint) -> str | None:
        self._last_gaze_point = QPoint(point)
        if self._keyboard_departure_bounds is not None:
            if self._keyboard_departure_bounds.contains(point):
                return None
            self._keyboard_departure_bounds = None
        if not self._predictions.allows_gaze(point):
            return None
        actions = (
            self._dialogs.actions
            if self._dialogs.active is not None
            else self._action_buttons.keys()
        )
        return self._action_at_point(actions, point)

    def contains_global_point(self, point: QPoint) -> bool:
        if not self.isVisible():
            return False
        top_left = self.mapToGlobal(QPoint(0, 0))
        return QRect(top_left, self.size()).contains(point)

    def handle_gaze_action(self, action: str) -> None:
        if not action.startswith(SPEECH_WINDOW_ACTION_PREFIX):
            return
        if self._dialogs.active is not None and action not in self._dialogs.actions:
            return
        if action.startswith(self._action("suggestion:")):
            button = self._action_buttons.get(action)
            if not self._predictions.allows_action(button):
                return
        logger.info("Speech window gaze action requested: %s", diagnostics.safe_action(action))
        keyboard_actions = set(self._main_dynamic_actions)
        was_inline = self._active_group_index is not None
        self._trigger_action(action, source="gaze")
        if (
            (was_inline or self._active_group_index is not None)
            and keyboard_actions != self._main_dynamic_actions
            and self._last_gaze_point is not None
            and self._dialogs.active is None
        ):
            # A new key can appear under the gaze that selected its group.
            self._show_keyboard_buttons()
            replacement = self._action_at_point(self._main_dynamic_actions, self._last_gaze_point)
            self._keyboard_departure_bounds = (
                self.action_bounds(replacement) if replacement is not None else None
            )

    def _after_dialog_closed(self, dialog: QDialog) -> None:
        if dialog is self._dialogs.alarm:
            self._alarm_sound.stop()
        if dialog is self._dialogs.confirm:
            self._confirm_action = None

    def _show_group_level(self) -> None:
        self._active_group_index = None
        self._key_grid_host.setLayoutDirection(
            Qt.RightToLeft
            if self._speech_settings.keyboard_script == ARABIC_SCRIPT
            else Qt.LeftToRight
        )
        self._symbols_mode = False
        if self._editor is None:
            self._view_mode = "keyboard"
        self._clear_main_grid()
        self._view_title.setText(
            self._editor_title() if self._editor is not None else "Odaberite grupu slova"
        )

        visible = self._keyboard_items(self._letter_groups)
        group_count = min(KEYS_PER_PAGE, len(self._letter_groups))
        columns = _group_column_count(group_count)
        if self._speech_settings.keyboard_script == ARABIC_SCRIPT:
            columns = max(columns, math.ceil(group_count / 5))
        self._set_grid_stretch(group_count, columns)
        for position, (index, group) in enumerate(visible):
            action = self._action(f"group:{index}")
            button = self._make_dynamic_button(" ".join(group), action, "groupButton")
            self._key_grid.addWidget(button, position // columns, position % columns)

        self._update_view_controls()
        self._set_status("")
        self._context_changed()

    def _show_symbols_level(self) -> None:
        self._active_group_index = None
        self._key_grid_host.setLayoutDirection(
            Qt.RightToLeft
            if self._speech_settings.keyboard_script == ARABIC_SCRIPT
            else Qt.LeftToRight
        )
        if self._editor is None:
            self._view_mode = "keyboard"
        self._symbols_mode = True
        self._clear_main_grid()
        self._view_title.setText(
            self._editor_title() if self._editor is not None else "Brojevi i znakovi"
        )
        arabic = self._speech_settings.keyboard_script == ARABIC_SCRIPT
        keys = self._symbol_groups if arabic else self._symbols
        visible = self._keyboard_items(keys)
        count = min(KEYS_PER_PAGE, len(keys))
        columns = _group_column_count(count) if arabic else 4
        self._set_grid_stretch(count, columns)
        for position, (index, symbol) in enumerate(visible):
            action = self._action(f"symbol-group:{index}" if arabic else f"symbol:{index}")
            label = " ".join(key_label(key) for key in symbol) if arabic else symbol
            button = self._make_dynamic_button(
                label, action, "groupButton" if arabic else "symbolButton"
            )
            self._key_grid.addWidget(button, position // columns, position % columns)

        self._update_view_controls()
        self._set_status("")
        self._context_changed()

    def _show_list_level(self) -> None:
        self._active_group_index = None
        self._key_grid_host.setLayoutDirection(Qt.LeftToRight)
        self._symbols_mode = False
        self._clamp_list_page()
        self._clear_main_grid()
        self._view_title.setText(self._list_title())

        items = self._list_items()
        self._set_grid_stretch(ITEMS_PER_PAGE, 2)
        if not items:
            empty = QPushButton(
                "Biblioteka nije učitana. Odaberite Učitaj ponovo."
                if self._library_store.read_error
                else "Lista je prazna. Odaberite Dodaj za novi unos.",
                self._key_grid_host,
            )
            empty.setObjectName("phraseButton")
            empty.setEnabled(False)
            self._key_grid.addWidget(empty, 0, 0, 2, 2)
            self._set_status("")
        else:
            page_start = self._list_page * ITEMS_PER_PAGE
            visible_items = items[page_start : page_start + ITEMS_PER_PAGE]
            for position, item in enumerate(visible_items):
                index = page_start + position
                button = self._make_dynamic_button(
                    self._list_item_text(item),
                    self._action(f"list:select:{index}"),
                    "deleteItemButton" if self._deletion_mode else "phraseButton",
                )
                button.setMinimumHeight(PHRASE_BUTTON_MIN_HEIGHT)
                self._key_grid.addWidget(button, position // 2, position % 2)
            self._set_status("Odaberite stavku za brisanje." if self._deletion_mode else "")

        self._update_view_controls()
        self._context_changed()

    def _list_items(self) -> list[CategoryRecord] | list[str] | list[PhraseRecord]:
        if self._view_mode == "categories":
            return self._library.categories
        if self._view_mode == "answers":
            category = self._active_category()
            return category.answers if category is not None else []
        if self._view_mode == "phrases":
            return self._library.phrases
        return []

    def _list_title(self) -> str:
        if self._library_store.read_error:
            return "Biblioteka nije učitana"
        if self._view_mode == "phrases":
            return "Moje fraze"
        category = self._active_category()
        return (
            _uppercase(category.name) if self._view_mode == "answers" and category else "Kategorije"
        )

    def _list_item_text(self, item: CategoryRecord | PhraseRecord | str) -> str:
        if isinstance(item, CategoryRecord):
            suffix = "Obriši" if self._deletion_mode else f"Odgovori: {len(item.answers)}"
            return f"{_uppercase(item.name)}\n{suffix}"
        text = item.text if isinstance(item, PhraseRecord) else item
        text = _uppercase(text)
        return f"{text}\nObriši" if self._deletion_mode else text

    def _active_category(self) -> CategoryRecord | None:
        if self._category_index is None:
            return None
        if self._category_index < 0 or self._category_index >= len(self._library.categories):
            return None
        return self._library.categories[self._category_index]

    def _show_letter_group(self, group_index: int, *, symbols: bool = False) -> None:
        groups = self._symbol_groups if symbols else self._letter_groups
        if group_index < 0 or group_index >= len(groups):
            return
        self._active_group_index = group_index
        self._symbols_mode = symbols
        self._clear_main_grid()
        group = groups[group_index]
        title = "Odaberite znak" if symbols else "Odaberite slovo"
        self._view_title.setText(self._editor_title() if self._editor is not None else title)
        item_count = len(group) + 1
        columns = 3 if item_count <= 6 else 4
        if self._editor is not None and item_count == 13:
            columns = 5
        self._set_grid_stretch(item_count, columns)
        self._key_grid_host.setLayoutDirection(
            Qt.RightToLeft
            if self._speech_settings.keyboard_script == ARABIC_SCRIPT
            else Qt.LeftToRight
        )
        for index, letter in enumerate(group):
            action = self._action(
                f"symbol:{group_index * max(5, self._letters_per_group) + index}"
                if symbols
                else f"letter:{group_index}:{index}"
            )
            button = self._make_dynamic_button(
                key_label(letter),
                action,
                "letterButton",
            )
            self._key_grid.addWidget(button, index // columns, index % columns)

        back_action = self._action("letters:close")
        back = self._make_dynamic_button(
            "Nazad na grupe",
            back_action,
            "lettersBackButton",
        )
        back_index = len(group)
        self._key_grid.addWidget(back, back_index // columns, back_index % columns)
        self._update_view_controls()
        self._show_keyboard_buttons()
        self._context_changed()

    def _show_keyboard_buttons(self) -> None:
        for action in self._main_dynamic_actions:
            self._action_buttons[action].show()
        self._key_grid.activate()

    def _show_keyboard_groups(self) -> None:
        if self._symbols_mode:
            self._show_symbols_level()
        else:
            self._show_group_level()

    def _open_clear_dialog(self) -> None:
        if not self._input.text():
            self._set_status("Tekst je već prazan.")
            return
        copy_text = (
            "Obrisat će se samo novi unos. Vaša poruka za razgovor ostaje sačuvana."
            if self._editor is not None
            else "Cijela poruka bit će obrisana."
        )
        self._open_confirmation(
            "Obrisati sav tekst?",
            copy_text,
            "Obriši tekst",
            self._clear_input,
        )

    def _open_confirmation(
        self,
        title: str,
        copy_text: str,
        confirm_label: str,
        action: Callable[[], None],
    ) -> None:
        self._dialogs.confirm_title.setText(title)
        self._dialogs.confirm_copy.setText(copy_text)
        self._dialogs.confirm_button.setText(confirm_label)
        self._confirm_action = action
        self._dialogs.actions = {
            self._action("confirm:cancel"),
            self._action("confirm:accept"),
        }
        self._open_dialog(self._dialogs.confirm, 460)

    def _cancel_confirmation(self) -> None:
        self._confirm_action = None
        self._close_dialog()

    def _accept_confirmation(self) -> None:
        action = self._confirm_action
        self._confirm_action = None
        self._close_dialog()
        if action is not None:
            action()

    def _start_alarm(self) -> None:
        self._speech.stop()
        self._dialogs.alarm_copy.setText("Pokrećem zvučni signal…")
        self._dialogs.actions = {self._action("alarm:stop")}
        self._open_dialog(self._dialogs.alarm, 460)
        try:
            started = self._alarm_sound.start()
        except Exception:
            logger.exception("Alarm sound could not be started.")
            started = False
        if started:
            self._dialogs.alarm_copy.setText("Zvučni signal se ponavlja dok ga ne zaustavite.")
            self._set_status("Alarm je uključen.")
        else:
            self._alarm_failed(self._alarm_sound.last_error or ALARM_UNAVAILABLE_MESSAGE)

    def _alarm_failed(self, message: str) -> None:
        if self._dialogs.active is self._dialogs.alarm:
            self._dialogs.alarm_copy.setText(message)
        self._set_status(message)

    def _stop_alarm(self) -> None:
        self._alarm_sound.stop()
        if self._dialogs.active is self._dialogs.alarm:
            self._close_dialog()
        self._set_status("Alarm je zaustavljen.")

    def _start_sleep(self) -> None:
        self._speech.stop()
        self._dialogs.actions = {self._action("sleep:wake")}
        self._context_changed()
        self._dialogs.active = self._dialogs.sleep
        self._dialogs.backdrop.hide()
        self._position_sleep_dialog()
        self._dialogs.sleep.show()
        self._dialogs.sleep.raise_()
        self._dialogs.sleep.activateWindow()
        self._set_status("Odmor je uključen.")

    def _wake_from_sleep(self) -> None:
        if self._dialogs.active is self._dialogs.sleep:
            self._close_dialog()
        self._set_status("Možete nastaviti.")

    def _open_exit_dialog(self) -> None:
        self._dialogs.actions = {
            self._action("exit:cancel"),
            self._action("exit:leave-speech"),
            self._action("exit:quit-app"),
        }
        self._open_dialog(self._dialogs.exit, 460)

    def _leave_speech_mode(self) -> None:
        self._close_dialog()
        self._speech.stop()
        self.close()

    def _request_quit(self) -> None:
        self._close_dialog()
        self._alarm_sound.stop()
        self._speech.stop()
        self.quit_requested.emit()

    def _clear_input(self) -> None:
        self._input.clear()
        self._set_status("Tekst je obrisan.")

    def _update_view_controls(self) -> None:
        editor_mode = self._editor is not None
        list_mode = self._is_list_mode()
        category_mode = self._view_mode in ("categories", "answers")
        phrase_mode = self._view_mode == "phrases"
        self._categories_button.setChecked(category_mode)
        self._categories_button.setText("Tastatura" if category_mode else "Kategorije")
        self._phrases_button.setChecked(phrase_mode)
        self._phrases_button.setText("Tastatura" if phrase_mode else "Fraze")
        self._categories_button.setEnabled(not editor_mode)
        self._phrases_button.setEnabled(not editor_mode)
        self._play_button.setEnabled(not editor_mode or self._speech.is_busy)
        self._back_button.setVisible(self._view_mode == "answers" and not editor_mode)
        self._add_item_button.setVisible(list_mode and not self._library_store.read_error)
        self._retry_library_button.setVisible(list_mode and self._library_store.read_error)
        self._add_item_button.setText(
            {"phrases": "Dodaj frazu", "answers": "Dodaj odgovor"}.get(
                self._view_mode, "Dodaj kategoriju"
            )
        )
        self._delete_mode_button.setVisible(list_mode and not self._library_store.read_error)
        self._delete_mode_button.setChecked(self._deletion_mode)
        self._delete_mode_button.setText("Gotovo" if self._deletion_mode else "Obriši")
        self._delete_mode_button.setEnabled(bool(self._list_items()) or self._deletion_mode)
        self._save_item_button.setVisible(editor_mode)
        self._cancel_editor_button.setVisible(editor_mode)
        self._refresh_paging(list_mode)
        self._view_title.setVisible(list_mode or editor_mode)
        self._message_label.setText(self._editor_title() if editor_mode else "Vaša poruka")
        self._input.setPlaceholderText(
            "Unesite tekst…" if editor_mode else "Odaberite grupu slova…"
        )
        self._refresh_keyboard_toggle(list_mode)
        self._refresh_suggestions()

    def _refresh_keyboard_toggle(self, list_mode: bool) -> None:
        if list_mode:
            self._keyboard_toggle_button.setText("Tastatura")
        elif self._symbols_mode:
            self._keyboard_toggle_button.setText("Grupe slova")
        else:
            self._keyboard_toggle_button.setText("Brojevi i znakovi")

    def _is_list_mode(self) -> bool:
        return self._view_mode in ("categories", "answers", "phrases")

    def _editor_title(self) -> str:
        if self._editor is None:
            return "Vaša poruka"
        return {
            "category": "Nova kategorija",
            "answer": "Novi odgovor",
            "phrase": "Nova fraza",
        }[self._editor.kind]

    def _trigger_action(self, action: str, *, source: str = "button") -> None:
        if source == "button":
            self._keyboard_departure_bounds = None
        if self._available_button(action) is None:
            diagnostics.emit(
                "ui_action_rejected",
                context_id=self._diagnostic_context.id,
                target_id=self._diagnostic_context.token(action),
                source=source,
                reason="target_unavailable",
            )
            return
        diagnostics.invoke_action(
            lambda: self._dispatch_action(action, source=source),
            context=self._diagnostic_context,
            action=action,
            source=source,
        )

    def _dispatch_action(self, action: str, *, source: str) -> None:
        command = action.removeprefix(SPEECH_WINDOW_ACTION_PREFIX)
        handlers = {
            "clear": self._open_clear_dialog,
            "suggestion-undo": lambda: self._set_composed_text(self._composition.undo_selection()),
            "confirm:cancel": self._cancel_confirmation,
            "confirm:accept": self._accept_confirmation,
            "play": lambda: self._play(source=source),
            "list:retry": self._retry_library,
            "alarm:start": self._start_alarm,
            "alarm:stop": self._stop_alarm,
            "sleep:start": self._start_sleep,
            "sleep:wake": self._wake_from_sleep,
            "exit": self._open_exit_dialog,
            "exit:cancel": self._close_dialog,
            "exit:leave-speech": self._leave_speech_mode,
            "exit:quit-app": self._request_quit,
            "categories": self._toggle_categories,
            "phrases": self._toggle_phrases,
            "space": lambda: self._append_text(" "),
            "backspace": self._backspace,
            "keyboard-toggle": self._toggle_keyboard_view,
            "script-toggle": self._switch_keyboard_script,
            "letters:close": self._show_keyboard_groups,
            "list:add": self._start_editor,
            "editor:save": self._save_editor,
            "editor:cancel": self._cancel_editor,
            "list:back": self._show_categories_from_answers,
            "list:delete-mode": self._toggle_deletion_mode,
            "list:page:previous": lambda: self._change_page(-1),
            "list:page:next": lambda: self._change_page(1),
        }
        handler = handlers.get(command)
        if handler is not None:
            handler()
        else:
            self._trigger_indexed_action(command)
        self._restore_input_focus()

    def _trigger_indexed_action(self, command: str) -> None:
        kind, _, value = command.partition(":")
        if kind == "suggestion":
            self._select_suggestion(int(value))
        elif kind == "group":
            self._show_letter_group(int(value))
        elif kind == "letter":
            group_index, letter_index = (int(index) for index in value.split(":"))
            self._append_text(self._letter_groups[group_index][letter_index])
            self._show_group_level()
        elif kind == "symbol-group":
            self._show_letter_group(int(value), symbols=True)
        elif kind == "symbol":
            self._append_text(self._symbols[int(value)])
            if self._active_group_index is not None:
                self._show_symbols_level()
        elif command.startswith("list:select:"):
            self._select_list_item(int(command.rsplit(":", 1)[1]))

    def _toggle_categories(self) -> None:
        if self._view_mode in ("categories", "answers"):
            self._show_keyboard_from_list()
        else:
            self._view_mode = "categories"
            self._category_index = None
            self._list_page = 0
            self._deletion_mode = False
            self._show_list_level()

    def _toggle_phrases(self) -> None:
        if self._view_mode == "phrases":
            self._show_keyboard_from_list()
        else:
            self._view_mode = "phrases"
            self._category_index = None
            self._list_page = 0
            self._deletion_mode = False
            self._show_list_level()

    def _toggle_keyboard_view(self) -> None:
        self._keyboard_page = 0
        if self._is_list_mode():
            self._show_keyboard_from_list()
        elif self._symbols_mode:
            self._show_group_level()
        else:
            self._show_symbols_level()

    def _show_keyboard_from_list(self) -> None:
        self._view_mode = "keyboard"
        self._category_index = None
        self._list_page = 0
        self._deletion_mode = False
        self._show_group_level()

    def _show_categories_from_answers(self) -> None:
        if self._view_mode != "answers":
            return
        self._view_mode = "categories"
        self._category_index = None
        self._list_page = 0
        self._deletion_mode = False
        self._show_list_level()

    def _select_list_item(self, index: int) -> None:
        items = self._list_items()
        if index < 0 or index >= len(items):
            return
        if self._deletion_mode:
            self._confirm_item_deletion(index)
            return
        self._use_list_item(index, items[index])

    def _use_list_item(self, index: int, item: CategoryRecord | PhraseRecord | str) -> None:
        if self._view_mode == "categories" and isinstance(item, CategoryRecord):
            self._category_index = index
            self._view_mode = "answers"
            self._list_page = 0
            self._show_list_level()
            return
        if self._view_mode == "answers" and isinstance(item, str):
            self._append_phrase_to_input(item)
            self._set_status("Dodano u poruku. Odaberite Izgovori za čitanje.")
            return
        if self._view_mode == "phrases" and isinstance(item, PhraseRecord):
            self._select_phrase(item)

    def _select_phrase(self, phrase: PhraseRecord) -> None:
        self._append_phrase_to_input(phrase.text)
        candidate = copy.deepcopy(self._library)
        selected = next(
            (item for item in candidate.phrases if item.text.casefold() == phrase.text.casefold()),
            None,
        )
        if selected is None:
            return
        selected.uses += 1
        candidate.phrases = sorted_phrases(candidate.phrases)
        if not self._library_store.save(candidate):
            self._set_status("Dodano u poruku, ali broj korištenja nije sačuvan.")
            return
        self._library = candidate
        self._sync_saved_audio()
        self._list_page = self._page_for_saved_item("phrase", phrase.text)
        self._show_list_level()
        self._set_status("Fraza je dodana u poruku.")

    def _keyboard_items(self, keys):
        self._keyboard_pages = max(1, math.ceil(len(keys) / KEYS_PER_PAGE))
        self._keyboard_page = min(self._keyboard_page, self._keyboard_pages - 1)
        start = self._keyboard_page * KEYS_PER_PAGE
        return list(enumerate(keys))[start : start + KEYS_PER_PAGE]

    def _refresh_paging(self, list_mode: bool) -> None:
        count = self._list_page_count() if list_mode else self._keyboard_pages
        page = self._list_page if list_mode else self._keyboard_page
        visible = list_mode or (count > 1 and self._active_group_index is None)
        self._previous_page_button.setVisible(visible)
        self._next_page_button.setVisible(visible)
        self._page_label.setVisible(visible)
        self._previous_page_button.setEnabled(page > 0)
        self._next_page_button.setEnabled(page < count - 1)
        self._page_label.setText(f"{page + 1} / {count}")

    def _change_page(self, delta: int) -> None:
        if self._is_list_mode():
            self._change_list_page(delta)
            return
        self._keyboard_page = max(0, min(self._keyboard_pages - 1, self._keyboard_page + delta))
        if self._symbols_mode:
            self._show_symbols_level()
        else:
            self._show_group_level()

    def _change_list_page(self, delta: int) -> None:
        old_page = self._list_page
        self._list_page = max(0, min(self._list_page_count() - 1, self._list_page + delta))
        if self._list_page != old_page:
            self._show_list_level()

    def _list_page_count(self) -> int:
        return max(1, math.ceil(len(self._list_items()) / ITEMS_PER_PAGE))

    def _clamp_list_page(self) -> None:
        self._list_page = max(0, min(self._list_page, self._list_page_count() - 1))

    def _text_changed(self, text: str) -> None:
        if self._updating_input:
            return
        corrected = self._composition.edit(_uppercase(text))
        if corrected != text:
            self._updating_input = True
            self._correct_input_text(text, corrected)
            self._updating_input = False
        self._suggestions.persist()
        self._refresh_suggestions()

    def _suggestion_allowed(self) -> bool:
        # Qt exposes cursor offsets as UTF-16 code units, unlike Python string indexes.
        return (
            self._speech_settings.keyboard_script != ARABIC_SCRIPT
            and (self._editor is None or self._editor.kind != "category")
            and not self._input.hasSelectedText()
            and self._input.cursorPosition() == len(self._input.text().encode("utf-16-le")) // 2
        )

    def _refresh_suggestions(self, *_args) -> None:
        if self._updating_input:
            return
        self._predictions.refresh(
            can_undo=self._speech_settings.keyboard_script != ARABIC_SCRIPT
            and self._composition.undo is not None
        )

    def _select_suggestion(self, index: int) -> None:
        candidate = self._predictions.candidate(index)
        if candidate is not None:
            self._set_composed_text(self._composition.select(candidate))

    def _set_composed_text(self, text: str) -> None:
        self._updating_input = True
        self._input.setText(_uppercase(text))
        self._restore_input_focus()
        self._updating_input = False
        self._suggestions.persist()
        self._refresh_suggestions()

    def _append_text(self, value: str) -> None:
        self._input.setText(f"{self._input.text()}{_uppercase(value)}")
        self._restore_input_focus()

    def _append_phrase_to_input(self, phrase: str) -> None:
        current = self._input.text()
        if current and not current.endswith(" "):
            current = f"{current} "
        self._input.setText(f"{current}{_uppercase(phrase.strip())} ")
        self._restore_input_focus()

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

    def _retry_library(self) -> None:
        library = self._library_store.load()
        if self._library_store.read_error:
            self._sync_saved_audio()
            self._set_status("Učitavanje nije uspjelo. Biblioteka nije promijenjena.")
            return
        self._library = library
        self._sync_saved_audio()
        self._category_index = None
        self._list_page = 0
        self._deletion_mode = False
        if self._view_mode == "answers":
            self._view_mode = "categories"
        self._show_list_level()
        self._set_status("Biblioteka je učitana.")

    def _set_status(self, text: str) -> None:
        if text:
            logger.info("Speech status: %s", text)
        self._status_label.setText(text)


def _uppercase(text: str) -> str:
    return text.upper()


def _group_column_count(item_count: int) -> int:
    if item_count <= 1:
        return 1
    if item_count <= 8:
        return 2
    return min(GROUP_GRID_MAX_COLUMNS, math.ceil(item_count / 2))
