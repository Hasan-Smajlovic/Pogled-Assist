from __future__ import annotations

import logging
from dataclasses import replace

import pytest
from _ui_fakes import FakeAlarmSound, FakeLibraryStore, FakeSpeech, click_speech_action
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QLineEdit

from pogled_assist.keyboard_layouts import ARABIC_LETTERS, ARABIC_MARKS
from pogled_assist.speech.speech_library import (
    CategoryRecord,
    PhraseRecord,
    SpeechLibrary,
    default_categories,
)
from pogled_assist.ui.speech_window import (
    BOSNIAN_LETTERS,
    SPEECH_WINDOW_ACTION_PREFIX,
    SpeechWindow,
)


@pytest.fixture
def make_speech_window(qtbot):
    def create(speech, **options):
        window = SpeechWindow(speech, **options)
        qtbot.addWidget(window)
        return window

    return create


@pytest.mark.parametrize("source", ["gaze", "button", "keyboard"])
def test_speech_playback_logs_input_source_without_message(
    qtbot, caplog, source, make_speech_window
):
    speech = FakeSpeech()
    window = make_speech_window(speech, library_store=FakeLibraryStore())
    window.show()
    window._input.setText("SYNTHETIC PRIVATE MESSAGE")
    with caplog.at_level(logging.INFO):
        if source == "gaze":
            window.handle_gaze_action(f"{SPEECH_WINDOW_ACTION_PREFIX}play")
        elif source == "button":
            qtbot.mouseClick(window._play_button, Qt.LeftButton)
        else:
            qtbot.keyClick(window._input, Qt.Key_Return)
    assert len(speech.requests) == 1
    assert f"Speech playback requested: source={source}." in caplog.text
    assert "SYNTHETIC PRIVATE MESSAGE" not in caplog.text


@pytest.fixture
def speech_focus(qtbot, qapp, make_speech_window):
    window = make_speech_window(
        FakeSpeech(), library_store=FakeLibraryStore(), alarm_sound=FakeAlarmSound()
    )
    window.show_full_screen()
    qapp.setActiveWindow(window)
    qtbot.waitUntil(lambda: qapp.focusWidget() is window._input)
    return qapp, window


@pytest.mark.e2e
def test_speech_can_type_on_open_and_reopen_without_selecting_input(qtbot, speech_focus):
    qapp, window = speech_focus
    qtbot.keyClicks(qapp.focusWidget(), "a")
    assert window._input.text() == "A"
    window.close()
    window.show_full_screen()
    qapp.setActiveWindow(window)
    qtbot.waitUntil(lambda: qapp.focusWidget() is window._input)
    qtbot.keyClicks(qapp.focusWidget(), "b")
    assert window._input.text() == "AB"


@pytest.mark.e2e
@pytest.mark.parametrize("selection_length", [0, 3])
def test_speech_restores_focus_on_return_without_changing_caret_or_selection(
    qtbot, speech_focus, selection_length
):
    qapp, window = speech_focus
    window._input.setText("ABCDEFGHIJ")
    if selection_length:
        window._input.setSelection(2, selection_length)
    else:
        window._input.setCursorPosition(2)
    cursor = window._input.cursorPosition()
    selected = window._input.selectedText()
    if not selection_length:
        # Exercise returning with a previously misplaced focus widget.
        window._play_button.setFocus()

    other = QLineEdit()
    qtbot.addWidget(other)
    other.show()
    qapp.setActiveWindow(other)
    other.setFocus()
    qapp.processEvents()
    assert qapp.focusWidget() is other
    qtbot.keyClicks(qapp.focusWidget(), "z")
    assert other.text() == "z"
    assert window._input.text() == "ABCDEFGHIJ"

    qapp.setActiveWindow(window)
    qtbot.waitUntil(lambda: qapp.focusWidget() is window._input, timeout=500)
    assert window._input.cursorPosition() == cursor
    assert window._input.selectedText() == selected
    qtbot.keyClicks(qapp.focusWidget(), "x")
    assert window._input.text() == "ABX" + "ABCDEFGHIJ"[2 + selection_length :]


@pytest.mark.e2e
@pytest.mark.parametrize("selection_length", [3, -3])
def test_speech_control_click_keeps_selection_and_its_direction(
    qtbot, speech_focus, selection_length
):
    qapp, window = speech_focus
    window._input.setText("ABCDEFGHIJ")
    window._input.setSelection(2 if selection_length > 0 else 5, selection_length)
    cursor = window._input.cursorPosition()
    qtbot.mouseClick(window._categories_button, Qt.LeftButton)
    assert qapp.focusWidget() is window._input
    assert window._input.selectedText() == "CDE"
    assert window._input.cursorPosition() == cursor
    qtbot.keyClicks(qapp.focusWidget(), "x")
    assert window._input.text() == "ABXFGHIJ"


@pytest.mark.e2e
@pytest.mark.parametrize("source", ["mouse", "gaze"])
@pytest.mark.parametrize(
    "command", ["play", "categories", "phrases", "keyboard-toggle", "backspace"]
)
def test_speech_controls_leave_message_ready_for_typing(qtbot, speech_focus, source, command):
    qapp, window = speech_focus
    window._input.setText("PORUKA")
    action = f"{SPEECH_WINDOW_ACTION_PREFIX}{command}"
    if source == "mouse":
        qtbot.mouseClick(window._action_buttons[action], Qt.LeftButton)
    else:
        window.handle_gaze_action(action)
    qtbot.waitUntil(lambda: qapp.focusWidget() is window._input, timeout=500)
    previous = window._input.text()
    qtbot.keyClicks(qapp.focusWidget(), "x")
    assert window._input.text() == previous + "X"


@pytest.mark.e2e
@pytest.mark.parametrize(
    "commands",
    [
        pytest.param(("group:0", "letters:close"), id="group:0-letters:close"),
        pytest.param(("group:0", "letter:0:0"), id="group:0-letter:0:0"),
        pytest.param(("clear", "confirm:cancel"), id="clear-confirm:cancel"),
        pytest.param(("clear", "confirm:accept"), id="clear-confirm:accept"),
        pytest.param(("alarm:start", "alarm:stop"), id="alarm:start-alarm:stop"),
        pytest.param(("sleep:start", "sleep:wake"), id="sleep:start-sleep:wake"),
        pytest.param(("exit", "exit:cancel"), id="exit-exit:cancel"),
    ],
)
@pytest.mark.parametrize("source", ["mouse", "gaze"])
def test_speech_dialogs_block_background_typing_and_restore_input_on_close(
    qtbot, speech_focus, commands, source
):
    qapp, window = speech_focus
    open_command, close_command = commands
    window._input.setText("PORUKA")
    open_action = f"{SPEECH_WINDOW_ACTION_PREFIX}{open_command}"
    if source == "mouse":
        qtbot.mouseClick(window._action_buttons[open_action], Qt.LeftButton)
    else:
        window.handle_gaze_action(open_action)
    qtbot.waitUntil(lambda: qapp.activeModalWidget() is window._active_dialog)
    # The offscreen platform does not activate modal windows like Windows does.
    qapp.setActiveWindow(window._active_dialog)
    assert qapp.focusWidget() is not window._input
    qtbot.keyClicks(qapp.focusWidget(), "x")
    assert window._input.text() == "PORUKA"
    action = f"{SPEECH_WINDOW_ACTION_PREFIX}{close_command}"
    if source == "mouse":
        qtbot.mouseClick(window._action_buttons[action], Qt.LeftButton)
    else:
        window.handle_gaze_action(action)
    qapp.setActiveWindow(window)
    qtbot.waitUntil(lambda: qapp.focusWidget() is window._input, timeout=500)
    previous = window._input.text()
    qtbot.keyClicks(qapp.focusWidget(), "y")
    assert window._input.text() == previous + "Y"


@pytest.mark.e2e
@pytest.mark.parametrize("kind", ["category", "answer", "phrase"])
@pytest.mark.parametrize("finish", ["save", "cancel", "failure"])
def test_speech_editor_focus_keeps_draft_separate_from_conversation(
    qtbot, speech_focus, kind, finish
):
    qapp, window = speech_focus
    window._input.setText("PORUKA")
    if kind == "phrase":
        window._phrases_button.click()
    else:
        window._categories_button.click()
    if kind == "answer":
        click_speech_action(qtbot, window, "list:select:0")
    qtbot.mouseClick(window._add_item_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: qapp.focusWidget() is window._input, timeout=500)
    qtbot.keyClicks(qapp.focusWidget(), "novi unos")
    assert window._editor.message == "PORUKA"
    assert window._input.text() == "NOVI UNOS"
    if finish == "failure":
        window._library_store.fail_saves = True
    button = window._cancel_editor_button if finish == "cancel" else window._save_item_button
    qtbot.mouseClick(button, Qt.LeftButton)
    qtbot.waitUntil(lambda: qapp.focusWidget() is window._input, timeout=500)
    if finish == "failure":
        assert window._editor is not None
        assert window._editor.message == "PORUKA"
        assert window._input.text() == "NOVI UNOS"
    else:
        assert window._editor is None
        assert window._input.text() == "PORUKA"
    previous = window._input.text()
    qtbot.keyClicks(qapp.focusWidget(), "x")
    assert window._input.text() == previous + "X"


@pytest.mark.e2e
def test_speech_keeps_typing_focus_when_tab_is_pressed(qtbot, speech_focus):
    qapp, window = speech_focus
    qtbot.keyClick(qapp.focusWidget(), Qt.Key_Tab)
    assert qapp.focusWidget() is window._input
    qtbot.keyClicks(qapp.focusWidget(), "a")
    assert window._input.text() == "A"


@pytest.mark.e2e
def test_speech_queued_focus_return_cannot_take_focus_from_another_window(qtbot, speech_focus):
    qapp, window = speech_focus
    other = QLineEdit()
    qtbot.addWidget(other)
    other.show()
    qapp.setActiveWindow(other)
    other.setFocus()
    qapp.setActiveWindow(window)
    # Leave Speech before its deferred activation work reaches the event loop.
    qapp.setActiveWindow(other)
    other.setFocus()
    qapp.processEvents()
    assert qapp.activeWindow() is other
    assert qapp.focusWidget() is other
    qtbot.keyClicks(qapp.focusWidget(), "x")
    assert other.text() == "x"
    assert window._input.text() == ""


@pytest.mark.e2e
def test_arabic_speech_keys_marks_switching_and_stale_predictions(qtbot, make_speech_window):
    from scripts.ui.capture_ui import PreviewSuggestionService

    suggestions = PreviewSuggestionService()
    requests = []
    suggestions.request = lambda *args: requests.append(args)
    speech = FakeSpeech()
    store = FakeLibraryStore()
    window = make_speech_window(speech, library_store=store, suggestions=suggestions)
    window.resize(1280, 720)
    window.show()
    window._input.setText("SELAM ")
    previous_request = requests[-1]
    window._script_button.click()
    assert window._input.text() == "SELAM "
    assert window._input.layoutDirection() == Qt.RightToLeft
    assert [letter for group in window._letter_groups for letter in group] == ARABIC_LETTERS
    assert not window._prediction_label.isVisible()
    count = len(requests)
    click_speech_action(qtbot, window, "group:0")
    click_speech_action(qtbot, window, "letter:0:1")
    assert window._input.text() == "SELAM ب"
    window._show_symbols_level()
    for mark in ARABIC_MARKS:
        index = window._symbols.index(mark)
        click_speech_action(qtbot, window, f"symbol-group:{index // 5}")
        button = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}symbol:{index}"]
        assert button.text() == "◌" + mark
        button.click()
        assert window._input.text() == "SELAM ب" + mark
        window._backspace()
        assert window._input.text() == "SELAM ب"
    assert len(requests) == count
    suggestions.predictions_ready.emit(previous_request[0], previous_request[1], ["ZASTARJELO"])
    assert all(not button.isEnabled() for button in window._prediction_buttons)
    window._play_button.click()
    assert speech.requests[-1][0] == "SELAM ب"
    assert speech.requests[-1][1].keyboard_script == "arabic"
    window._script_button.click()
    assert window._input.text() == "SELAM ب"
    assert window._input.layoutDirection() == Qt.LeftToRight
    assert window._prediction_label.isVisible()
    assert len(requests) > count
    assert [letter for group in window._letter_groups for letter in group] == BOSNIAN_LETTERS
    assert store.saved == []


@pytest.mark.e2e
def test_arabic_phrase_editor_survives_switch_and_preserves_library(qtbot, make_speech_window):
    store = FakeLibraryStore(
        SpeechLibrary(
            categories=[CategoryRecord("Moje", ["ODGOVOR"])],
            phrases=[PhraseRecord("STARA FRAZA", 3)],
        )
    )
    window = make_speech_window(FakeSpeech(), library_store=store)
    window.show()
    window._input.setText("PORUKA ZA RAZGOVOR")
    window._phrases_button.click()
    window._add_item_button.click()
    window._script_button.click()
    window._input.setText("سَلَامٌ")
    window._script_button.click()
    assert window._input.text() == "سَلَامٌ"
    window._save_item_button.click()
    assert window._input.text() == "PORUKA ZA RAZGOVOR"
    assert store.library.categories == [CategoryRecord("Moje", ["ODGOVOR"])]
    assert PhraseRecord("STARA FRAZA", 3) in store.library.phrases
    assert PhraseRecord("سَلَامٌ", 0) in store.library.phrases


@pytest.mark.e2e
@pytest.mark.parametrize("letters_per_group", [1, 5, 12])
def test_arabic_speech_groups_and_dialog_fit_150_percent(
    qtbot, letters_per_group, make_speech_window
):
    from scripts.ui.capture_ui import PreviewSuggestionService

    window = make_speech_window(
        FakeSpeech(),
        letters_per_group=letters_per_group,
        library_store=FakeLibraryStore(),
        suggestions=PreviewSuggestionService(),
    )
    window.update_settings(replace(window._speech_settings, keyboard_script="arabic"))
    window.resize(1280, 720)
    window.show()
    qtbot.wait(1)
    assert window.width() <= 1280 and window.height() <= 720
    window._input.setText("سَلَامٌ")
    qtbot.wait(1)
    assert window._input.cursorRect().x() > window._input.width() // 2
    for action, button in window._action_buttons.items():
        if "group:" in action:
            assert window.rect().contains(QRect(button.mapTo(window, QPoint(0, 0)), button.size()))
            assert button.height() >= 72
    window._open_letter_dialog(0)
    qtbot.wait(1)
    dialog = window._letter_dialog
    assert dialog.width() <= 1280 and dialog.height() <= 720
    rects = []
    for action in window._letter_dialog_actions:
        button = window._action_buttons[action]
        rect = QRect(button.mapTo(dialog, QPoint(0, 0)), button.size())
        assert dialog.rect().contains(rect)
        assert all(not rect.intersects(previous) for previous in rects)
        rects.append(rect)


@pytest.mark.e2e
def test_speech_keyboard_entry_playback_and_phrase_workflow(qtbot, make_speech_window):
    store = FakeLibraryStore()
    speech = FakeSpeech()
    window = make_speech_window(speech, library_store=store)
    window.show()

    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:1"].click()
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}letter:1:1"].click()
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}space"].click()
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"].click()
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:0"].click()
    window._play_button.click()

    assert window._input.text() == "DŽ A"
    assert speech.requests[0][0] == "DŽ A"

    window._phrases_button.click()
    window._add_item_button.click()
    window._input.setText("  Trebam   pomoć ")
    window._save_item_button.click()

    assert store.saved[-1].phrases == [PhraseRecord("TREBAM POMOĆ", 0)]
    assert window._input.text() == "DŽ A"

    phrase_button = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}list:select:0"]
    qtbot.waitUntil(phrase_button.isVisible)
    phrase_button.click()
    assert window._input.text() == "DŽ A TREBAM POMOĆ "
    assert store.saved[-1].phrases == [PhraseRecord("TREBAM POMOĆ", 1)]


@pytest.mark.e2e
def test_speech_message_does_not_silently_truncate_long_saved_phrases(qtbot, make_speech_window):
    long_phrase = "Vrlo duga poruka " * 30
    store = FakeLibraryStore(
        SpeechLibrary(categories=default_categories(), phrases=[PhraseRecord(long_phrase)])
    )
    window = make_speech_window(FakeSpeech(), library_store=store)
    window.show()
    window._input.setText("Početak")

    window._append_phrase_to_input(long_phrase)

    assert window._input.text() == f"POČETAK {long_phrase.strip().upper()} "


@pytest.mark.e2e
def test_speech_categories_answers_and_shared_editor_preserve_message(qtbot, make_speech_window):
    store = FakeLibraryStore()
    window = make_speech_window(FakeSpeech(), library_store=store)
    window.show()
    window._input.setText("Moja poruka")

    window._categories_button.click()
    assert window._view_mode == "categories"
    assert window._categories_button.text() == "Tastatura"
    assert window._page_label.text() == "1 / 1"
    category_button = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}list:select:0"]
    assert category_button.text().startswith("TREBAM\n")
    click_speech_action(qtbot, window, "list:select:0")
    assert window._view_mode == "answers"
    assert window._view_title.text() == "TREBAM"
    assert window._back_button.isVisible()
    answer_button = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}list:select:0"]
    assert answer_button.text() == "TREBAM VODE"

    click_speech_action(qtbot, window, "list:select:0")
    assert window._input.text() == "MOJA PORUKA TREBAM VODE "

    window._add_item_button.click()
    assert window._editor.kind == "answer"
    assert window._input.text() == ""
    assert not window._categories_button.isEnabled()
    assert not window._phrases_button.isEnabled()
    window._input.setText("Sedmi odgovor")
    window._save_item_button.click()

    assert window._view_mode == "answers"
    assert window._list_page == 1
    assert window._page_label.text() == "2 / 2"
    assert window._input.text() == "MOJA PORUKA TREBAM VODE "
    assert store.library.categories[0].answers[-1] == "SEDMI ODGOVOR"

    window._add_item_button.click()
    window._input.setText("   ")
    window._save_item_button.click()
    assert window._editor is not None
    assert window._input.text() == "   "
    assert window._status_label.text() == "Prvo unesite tekst."

    window._input.setText("sedmi   odgovor")
    window._save_item_button.click()
    assert window._editor is not None
    assert window._input.text() == "SEDMI   ODGOVOR"
    assert "već postoji" in window._status_label.text()
    window._cancel_editor_button.click()
    assert window._view_mode == "answers"
    assert window._list_page == 1
    assert window._input.text() == "MOJA PORUKA TREBAM VODE "


@pytest.mark.e2e
def test_speech_list_and_dialog_controls_are_large_gaze_targets(qtbot, make_speech_window):
    window = make_speech_window(FakeSpeech(), library_store=FakeLibraryStore())
    window.resize(1440, 900)
    window.show()
    qtbot.waitUntil(window.isVisible)

    window._categories_button.click()
    qtbot.waitUntil(window._add_item_button.isVisible)

    list_controls = (
        window._add_item_button,
        window._delete_mode_button,
        window._previous_page_button,
        window._next_page_button,
    )
    assert all(button.width() >= 160 for button in list_controls)
    assert all(button.height() >= 80 for button in list_controls)
    alarm = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}alarm:start"]
    assert window._key_grid_host.width() >= alarm.width() * 2
    assert f"{SPEECH_WINDOW_ACTION_PREFIX}close" not in window._action_buttons

    window._input.setText("Poruka")
    window._clear_button.click()
    qtbot.waitUntil(lambda: window._active_dialog is window._confirm_dialog)

    cancel = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:cancel"]
    confirm = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:accept"]
    assert window._confirm_dialog.width() >= 900
    assert window._confirm_dialog.height() >= 440
    assert cancel.height() >= 128
    assert confirm.height() >= 128


@pytest.mark.e2e
def test_speech_add_and_cancel_category_answer_and_phrase_editors(qtbot, make_speech_window):
    phrases = [PhraseRecord(f"Fraza {index}") for index in range(7)]
    store = FakeLibraryStore(SpeechLibrary(categories=default_categories(), phrases=phrases))
    window = make_speech_window(FakeSpeech(), library_store=store)
    window.show()
    window._input.setText("Razgovor")

    window._categories_button.click()
    window._add_item_button.click()
    window._input.setText("Nova kategorija")
    window._save_item_button.click()
    assert store.library.categories[-1] == CategoryRecord("NOVA KATEGORIJA")
    assert window._input.text() == "RAZGOVOR"

    window._add_item_button.click()
    window._input.setText("Odbačena kategorija")
    window._cancel_editor_button.click()
    assert all(item.name != "ODBAČENA KATEGORIJA" for item in store.library.categories)
    assert window._input.text() == "RAZGOVOR"

    click_speech_action(qtbot, window, "list:select:0")
    window._add_item_button.click()
    window._input.setText("Odbačeni odgovor")
    window._cancel_editor_button.click()
    assert "ODBAČENI ODGOVOR" not in store.library.categories[0].answers
    assert window._view_mode == "answers"
    assert window._input.text() == "RAZGOVOR"

    window._phrases_button.click()
    window._next_page_button.click()
    assert window._list_page == 1
    window._add_item_button.click()
    window._input.setText("ZZZ nova fraza")
    window._save_item_button.click()
    assert any(item.text == "ZZZ NOVA FRAZA" for item in store.library.phrases)
    assert window._list_page == 1
    assert window._input.text() == "RAZGOVOR"

    window._add_item_button.click()
    window._input.setText("Odbačena fraza")
    window._cancel_editor_button.click()
    assert all(item.text != "ODBAČENA FRAZA" for item in store.library.phrases)
    assert window._view_mode == "phrases"
    assert window._list_page == 1
    assert window._input.text() == "RAZGOVOR"


@pytest.mark.e2e
def test_speech_deletion_confirmation_clear_and_save_failures(qtbot, make_speech_window):
    store = FakeLibraryStore(
        SpeechLibrary(
            categories=default_categories(),
            phrases=[PhraseRecord("Sačuvana fraza", 3)],
        )
    )
    window = make_speech_window(FakeSpeech(), library_store=store)
    window.show()
    window._input.setText("Poruka ostaje")

    window._categories_button.click()
    window._delete_mode_button.click()
    click_speech_action(qtbot, window, "list:select:0")
    qtbot.waitUntil(lambda: window._active_dialog is window._confirm_dialog)
    assert "svi njeni odgovori" in window._confirm_copy.text()
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:cancel"].click()
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert len(store.library.categories) == 4

    click_speech_action(qtbot, window, "list:select:0")
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:accept"].click()
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert [category.name for category in store.library.categories] == [
        "Brzi odgovor",
        "Kako se osjećam",
        "Ljudi",
    ]
    assert window._deletion_mode is True

    window._delete_mode_button.click()
    click_speech_action(qtbot, window, "list:select:0")
    window._delete_mode_button.click()
    click_speech_action(qtbot, window, "list:select:0")
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:accept"].click()
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert store.library.categories[0].answers == [
        "Ne",
        "Možda",
        "Hvala",
        "Molim te",
        "Nisam razumio",
    ]

    window._phrases_button.click()
    window._add_item_button.click()
    window._input.setText("Privremeni unos")
    window._clear_button.click()
    qtbot.waitUntil(lambda: window._active_dialog is window._confirm_dialog)
    assert "samo novi unos" in window._confirm_copy.text()
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:accept"].click()
    assert window._input.text() == ""
    window._cancel_editor_button.click()
    assert window._input.text() == "PORUKA OSTAJE"

    window._delete_mode_button.click()
    click_speech_action(qtbot, window, "list:select:0")
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:accept"].click()
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert store.library.phrases == []
    window._delete_mode_button.click()

    store.fail_saves = True
    window._add_item_button.click()
    window._input.setText("Neuspjela fraza")
    window._save_item_button.click()
    assert window._editor is not None
    assert window._input.text() == "NEUSPJELA FRAZA"
    assert window._status_label.text() == "Spremanje nije uspjelo. Novi unos nije sačuvan."
    assert all(item.text != "NEUSPJELA FRAZA" for item in store.library.phrases)


@pytest.mark.e2e
def test_speech_modal_blocks_background_and_supports_gaze(qtbot, make_speech_window):
    speech = FakeSpeech()
    window = make_speech_window(speech, library_store=FakeLibraryStore())
    window.show()
    qtbot.waitUntil(window.isVisible)

    assert len(window._letter_groups) == 6
    assert all(len(group) == 5 for group in window._letter_groups)
    assert [letter for group in window._letter_groups for letter in group] == BOSNIAN_LETTERS

    group_action = f"{SPEECH_WINDOW_ACTION_PREFIX}group:1"
    qtbot.mouseClick(window._action_buttons[group_action], Qt.LeftButton)
    qtbot.waitUntil(lambda: window._active_dialog is window._letter_dialog)
    assert window._modal_backdrop.isVisible()

    qtbot.mouseClick(window._play_button, Qt.LeftButton)
    qtbot.mouseClick(window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}space"], Qt.LeftButton)
    assert speech.requests == []
    assert window._input.text() == ""

    letter_action = f"{SPEECH_WINDOW_ACTION_PREFIX}letter:1:1"
    letter = window._action_buttons[letter_action]
    qtbot.waitUntil(letter.isVisible)
    qtbot.mouseClick(letter, Qt.LeftButton)
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert window._input.text() == "DŽ"
    assert not window._modal_backdrop.isVisible()

    gaze_group_action = f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"
    group = window._action_buttons[gaze_group_action]
    group_center = group.mapToGlobal(group.rect().center())
    assert window.action_at_global_point(group_center) == gaze_group_action
    window.handle_gaze_action(gaze_group_action)
    qtbot.waitUntil(lambda: window._active_dialog is window._letter_dialog)

    space_center = window._space_button.mapToGlobal(window._space_button.rect().center())
    assert window.action_at_global_point(space_center) is None
    window.handle_gaze_action(f"{SPEECH_WINDOW_ACTION_PREFIX}space")
    assert window._input.text() == "DŽ"

    gaze_letter_action = f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:0"
    gaze_letter = window._action_buttons[gaze_letter_action]
    qtbot.waitUntil(gaze_letter.isVisible)
    letter_center = gaze_letter.mapToGlobal(gaze_letter.rect().center())
    assert window.action_at_global_point(letter_center) == gaze_letter_action
    window.handle_gaze_action(gaze_letter_action)
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert window._input.text() == "DŽA"


@pytest.mark.e2e
def test_twelve_letter_dialog_fits_150_percent_display_and_accepts_gaze(qtbot, make_speech_window):
    window = make_speech_window(FakeSpeech(), letters_per_group=12, library_store=FakeLibraryStore())
    window.resize(1280, 720)
    window.show()
    qtbot.waitUntil(window.isVisible)

    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"].click()
    qtbot.waitUntil(lambda: window._active_dialog is window._letter_dialog)
    dialog = window._letter_dialog
    assert dialog.height() <= window.height() - 64
    assert dialog.width() <= window.width() - 64

    bounds = dialog.rect()
    for action in window._letter_dialog_actions:
        button = window._action_buttons[action]
        rect = QRect(button.mapTo(dialog, QPoint(0, 0)), button.size())
        assert bounds.contains(rect), action
        assert button.width() >= 140, action
        assert button.height() >= 110, action
        assert window.action_at_global_point(button.mapToGlobal(button.rect().center())) == action

    last_letter = f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:11"
    window.handle_gaze_action(last_letter)
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert window._input.text() == window._letter_groups[0][-1]


@pytest.mark.e2e
def test_single_letter_groups_fit_150_percent_display(qtbot, make_speech_window):
    window = make_speech_window(FakeSpeech(), letters_per_group=1, library_store=FakeLibraryStore())
    window.resize(1280, 720)
    window.show()
    qtbot.waitUntil(window.isVisible)

    assert window.size().width() <= 1280
    assert window.size().height() <= 720
    bounds = QRect(0, 0, 1280, 720)
    group_actions = [
        f"{SPEECH_WINDOW_ACTION_PREFIX}group:{index}" for index in range(len(window._letter_groups))
    ]
    for action in (*group_actions, f"{SPEECH_WINDOW_ACTION_PREFIX}keyboard-toggle"):
        button = window._action_buttons[action]
        rect = QRect(button.mapTo(window, QPoint(0, 0)), button.size())
        assert bounds.contains(rect), action
        assert button.height() >= 72, action


@pytest.mark.e2e
def test_speech_symbols_backspace_clear_and_play(qtbot, make_speech_window):
    speech = FakeSpeech()
    window = make_speech_window(speech, library_store=FakeLibraryStore())
    window.show()
    qtbot.waitUntil(window.isVisible)

    qtbot.mouseClick(window._keyboard_toggle_button, Qt.LeftButton)
    assert window._symbols_mode is True
    symbol = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}symbol:0"]
    qtbot.waitUntil(symbol.isVisible)
    qtbot.mouseClick(symbol, Qt.LeftButton)
    assert window._input.text() == "1"

    qtbot.mouseClick(window._keyboard_toggle_button, Qt.LeftButton)
    assert window._symbols_mode is False
    assert f"{SPEECH_WINDOW_ACTION_PREFIX}group:0" in window._action_buttons

    for value in ("DŽ", "LJ", "NJ", "dž", "lj", "nj"):
        window._input.setText(value)
        qtbot.mouseClick(window._backspace_button, Qt.LeftButton)
        assert window._input.text() == ""

    window._input.setText("Trebam pomoć")
    qtbot.mouseClick(window._play_button, Qt.LeftButton)
    assert speech.requests[-1][0] == "TREBAM POMOĆ"
    assert window._input.text() == "TREBAM POMOĆ"

    qtbot.mouseClick(window._clear_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window._active_dialog is window._confirm_dialog)
    qtbot.mouseClick(
        window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:cancel"], Qt.LeftButton
    )
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert window._input.text() == "TREBAM POMOĆ"

    qtbot.mouseClick(window._clear_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window._active_dialog is window._confirm_dialog)
    qtbot.mouseClick(
        window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:accept"], Qt.LeftButton
    )
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert window._input.text() == ""

    qtbot.mouseClick(window._clear_button, Qt.LeftButton)
    assert window._active_dialog is None


@pytest.mark.e2e
def test_speech_alarm_stops_speech_blocks_background_and_reports_failure(qtbot, make_speech_window):
    speech = FakeSpeech()
    alarm = FakeAlarmSound()
    window = make_speech_window(speech, library_store=FakeLibraryStore(), alarm_sound=alarm)
    window.resize(1280, 720)
    window.show()
    window._input.setText("Poruka ostaje")

    alarm_action = f"{SPEECH_WINDOW_ACTION_PREFIX}alarm:start"
    stop_action = f"{SPEECH_WINDOW_ACTION_PREFIX}alarm:stop"
    window._action_buttons[alarm_action].click()
    qtbot.waitUntil(lambda: window._active_dialog is window._alarm_dialog)

    assert speech.stop_calls == 1
    assert alarm.start_calls == 1
    assert window._alarm_copy.text() == "Zvučni signal se ponavlja dok ga ne zaustavite."
    space_center = window._space_button.mapToGlobal(window._space_button.rect().center())
    assert window.action_at_global_point(space_center) is None
    assert window._input.text() == "PORUKA OSTAJE"

    window.handle_gaze_action(stop_action)
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert alarm.stop_calls >= 1
    assert window._input.text() == "PORUKA OSTAJE"

    window.handle_gaze_action(alarm_action)
    qtbot.waitUntil(lambda: window._active_dialog is window._alarm_dialog)
    window._action_buttons[stop_action].click()
    qtbot.waitUntil(lambda: window._active_dialog is None)

    alarm.start_result = False
    alarm.last_error = "Audio uređaj nije dostupan."
    window._action_buttons[alarm_action].click()
    qtbot.waitUntil(lambda: window._active_dialog is window._alarm_dialog)
    assert window._alarm_copy.text() == "Audio uređaj nije dostupan."
    assert window._status_label.text() == "Audio uređaj nije dostupan."

    alarm.failed.emit("Zvuk je prekinut.")
    assert window._alarm_copy.text() == "Zvuk je prekinut."
    window._action_buttons[stop_action].click()


@pytest.mark.e2e
def test_speech_sleep_preserves_unfinished_entry_and_supports_mouse_and_gaze(
    qtbot, make_speech_window
):
    phrases = [PhraseRecord(f"Fraza {index}") for index in range(7)]
    speech = FakeSpeech()
    window = make_speech_window(
        speech,
        library_store=FakeLibraryStore(
            SpeechLibrary(categories=default_categories(), phrases=phrases)
        ),
        alarm_sound=FakeAlarmSound(),
    )
    window.resize(1280, 720)
    window.show()
    window._input.setText("Razgovor")
    window._phrases_button.click()
    window._next_page_button.click()
    window._add_item_button.click()
    window._input.setText("Nedovršena fraza")
    editor = window._editor

    sleep_action = f"{SPEECH_WINDOW_ACTION_PREFIX}sleep:start"
    wake_action = f"{SPEECH_WINDOW_ACTION_PREFIX}sleep:wake"
    window.handle_gaze_action(sleep_action)
    qtbot.waitUntil(lambda: window._active_dialog is window._sleep_dialog)

    assert speech.stop_calls == 1
    assert window._sleep_dialog.geometry() == QRect(window.mapToGlobal(QPoint(0, 0)), window.size())
    assert window._sleep_dialog.isVisible()
    assert window._input.text() == "NEDOVRŠENA FRAZA"
    assert window._editor is editor
    assert window._list_page == 1
    assert window._view_mode == "editor"
    assert editor is not None and editor.message == "RAZGOVOR"
    space_center = window._space_button.mapToGlobal(window._space_button.rect().center())
    assert window.action_at_global_point(space_center) is None

    qtbot.mouseClick(window._wake_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert window._input.text() == "NEDOVRŠENA FRAZA"
    assert window._editor is editor
    assert window._list_page == 1

    window._action_buttons[sleep_action].click()
    qtbot.waitUntil(lambda: window._active_dialog is window._sleep_dialog)
    wake_center = window._wake_button.mapToGlobal(window._wake_button.rect().center())
    assert window.action_at_global_point(wake_center) == wake_action
    window.handle_gaze_action(wake_action)
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert window._input.text() == "NEDOVRŠENA FRAZA"
    assert window._editor is editor


@pytest.mark.e2e
def test_speech_exit_offers_cancel_leave_speech_and_normal_app_shutdown(qtbot, make_speech_window):
    speech = FakeSpeech()
    alarm = FakeAlarmSound()
    window = make_speech_window(speech, library_store=FakeLibraryStore(), alarm_sound=alarm)
    window.resize(1280, 720)
    window.show()
    window._input.setText("Poruka")
    window._categories_button.click()
    click_speech_action(qtbot, window, "list:select:0")
    preserved_state = (
        window._input.text(),
        window._view_mode,
        window._category_index,
        window._list_page,
    )
    quit_requests = []
    window.quit_requested.connect(lambda: quit_requests.append(True))

    exit_action = f"{SPEECH_WINDOW_ACTION_PREFIX}exit"
    cancel_action = f"{SPEECH_WINDOW_ACTION_PREFIX}exit:cancel"
    leave_action = f"{SPEECH_WINDOW_ACTION_PREFIX}exit:leave-speech"
    quit_action = f"{SPEECH_WINDOW_ACTION_PREFIX}exit:quit-app"
    window._action_buttons[exit_action].click()
    qtbot.waitUntil(lambda: window._active_dialog is window._exit_dialog)

    cancel_button = window._action_buttons[cancel_action]
    leave_button = window._action_buttons[leave_action]
    quit_button = window._action_buttons[quit_action]
    cancel_rect = QRect(cancel_button.mapToGlobal(QPoint(0, 0)), cancel_button.size())
    leave_rect = QRect(leave_button.mapToGlobal(QPoint(0, 0)), leave_button.size())
    quit_rect = QRect(quit_button.mapToGlobal(QPoint(0, 0)), quit_button.size())
    assert leave_button.text() == "Izađi"
    assert quit_button.text() == "Ugasi aplikaciju"
    assert all(button.height() >= 128 for button in (cancel_button, leave_button, quit_button))
    assert not cancel_rect.intersects(leave_rect)
    assert not cancel_rect.intersects(quit_rect)
    assert not leave_rect.intersects(quit_rect)
    window.handle_gaze_action(cancel_action)
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert (
        window._input.text(),
        window._view_mode,
        window._category_index,
        window._list_page,
    ) == preserved_state
    assert quit_requests == []

    window.handle_gaze_action(exit_action)
    qtbot.waitUntil(lambda: window._active_dialog is window._exit_dialog)
    qtbot.mouseClick(leave_button, Qt.LeftButton)
    qtbot.waitUntil(window.isHidden)

    assert quit_requests == []
    assert speech.stop_calls == 1
    assert alarm.stop_calls >= 1

    window.show_full_screen()
    qtbot.waitUntil(window.isVisible)
    assert window._input.text() == "PORUKA"
    window.handle_gaze_action(exit_action)
    qtbot.waitUntil(lambda: window._active_dialog is window._exit_dialog)
    window.handle_gaze_action(quit_action)

    assert quit_requests == [True]
    assert speech.stop_calls == 2
    assert alarm.stop_calls >= 1
