from __future__ import annotations

import pytest
from _speech_fixtures import make_speech_window as make_speech_window
from _ui_fakes import FakeLibraryStore, FakeSpeech, click_speech_action
from PySide6.QtCore import QPoint, QRect

from pogled_assist.keyboard_layouts import ALL_LETTERS_LAYOUT, LETTER_GROUPS_LAYOUT
from pogled_assist.speech.speech_library import (
    CategoryRecord,
    PhraseRecord,
    SpeechLibrary,
    default_categories,
)
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.ui.speech_window import SPEECH_WINDOW_ACTION_PREFIX


@pytest.mark.e2e
def test_speech_keyboard_entry_playback_and_phrase_workflow(qtbot, make_speech_window):
    store = FakeLibraryStore()
    speech = FakeSpeech()
    window = make_speech_window(speech, library_store=store)
    window.show()

    for command in ("letter:6", "space", "letter:0"):
        click_speech_action(qtbot, window, command)
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
    assert window._list_heading.text() == "Kategorije"
    assert window._list_page_label.isHidden()
    category_button = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}list:select:0"]
    assert category_button.text() == "TREBAM\u00a0\u203a\n6 odgovora"
    assert not window._back_button.isVisible()
    click_speech_action(qtbot, window, "list:select:0")
    assert window._view_mode == "answers"
    assert window._list_heading.text() == "Kategorije \u203a TREBAM"
    assert window._back_button.isVisible()
    assert window._back_button.text() == "\u2039 Kategorije"
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
    # Nine entries fit on one page, so the seventh answer stays on the first.
    assert window._list_page == 0
    assert window._list_page_label.isHidden()
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
    assert window._list_page == 0
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
        window._list_previous_button,
        window._list_next_button,
    )
    assert all(button.width() >= 100 for button in list_controls)
    assert all(button.height() >= 72 for button in list_controls)
    alarm = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}alarm:start"]
    assert window._key_grid_host.width() >= alarm.width() * 2
    assert f"{SPEECH_WINDOW_ACTION_PREFIX}close" not in window._action_buttons

    window._input.setText("Poruka")
    window._clear_button.click()
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.confirm)

    cancel = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:cancel"]
    confirm = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:accept"]
    assert window._dialogs.confirm.width() >= 900
    assert window._dialogs.confirm.height() >= 440
    assert cancel.height() >= 128
    assert confirm.height() >= 128


@pytest.mark.e2e
def test_speech_add_and_cancel_category_answer_and_phrase_editors(qtbot, make_speech_window):
    phrases = [PhraseRecord(f"Fraza {index}") for index in range(10)]
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

    window._list_previous_button.click()
    click_speech_action(qtbot, window, "list:select:0")
    window._add_item_button.click()
    window._input.setText("Odbačeni odgovor")
    window._cancel_editor_button.click()
    assert "ODBAČENI ODGOVOR" not in store.library.categories[0].answers
    assert window._view_mode == "answers"
    assert window._input.text() == "RAZGOVOR"

    window._phrases_button.click()
    window._list_next_button.click()
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
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.confirm)
    assert "svi njeni odgovori" in window._dialogs.confirm_copy.text()
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:cancel"].click()
    qtbot.waitUntil(lambda: window._dialogs.active is None)
    assert len(store.library.categories) == 4

    click_speech_action(qtbot, window, "list:select:0")
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:accept"].click()
    qtbot.waitUntil(lambda: window._dialogs.active is None)
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
    qtbot.waitUntil(lambda: window._dialogs.active is None)
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
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.confirm)
    assert "samo novi unos" in window._dialogs.confirm_copy.text()
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:accept"].click()
    assert window._input.text() == ""
    window._cancel_editor_button.click()
    assert window._input.text() == "PORUKA OSTAJE"

    window._delete_mode_button.click()
    click_speech_action(qtbot, window, "list:select:0")
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:accept"].click()
    qtbot.waitUntil(lambda: window._dialogs.active is None)
    assert store.library.phrases == []
    window._delete_mode_button.click()

    store.fail_saves = True
    window._add_item_button.click()
    window._input.setText("Neuspjela fraza")
    window._save_item_button.click()
    assert window._editor is not None
    assert window._input.text() == "NEUSPJELA FRAZA"
    assert window._status_label.text() == "Čuvanje nije uspjelo. Novi unos nije sačuvan."
    assert all(item.text != "NEUSPJELA FRAZA" for item in store.library.phrases)


def _window_rect(window, widget) -> QRect:
    return QRect(widget.mapTo(window, QPoint()), widget.size())


def _card_rows(window) -> list[list[QRect]]:
    cards = sorted(
        (
            _window_rect(window, window._action_buttons[action])
            for action in window._main_dynamic_actions
        ),
        key=lambda rect: (rect.top(), rect.left()),
    )
    rows: dict[int, list[QRect]] = {}
    for rect in cards:
        rows.setdefault(rect.top(), []).append(rect)
    return list(rows.values())


@pytest.mark.e2e
@pytest.mark.parametrize("layout", [ALL_LETTERS_LAYOUT, LETTER_GROUPS_LAYOUT])
def test_lists_show_nine_cards_level_with_the_side_controls(qtbot, make_speech_window, layout):
    speech = FakeSpeech()
    # Letter groups widen the system column, leaving the least room for cards and the strip.
    speech._settings = SpeechSettings(letter_layout=layout)
    phrases = [PhraseRecord(f"Fraza broj {index}", 20 - index) for index in range(11)]
    store = FakeLibraryStore(SpeechLibrary(categories=default_categories(), phrases=phrases))
    window = make_speech_window(speech, library_store=store)
    window.resize(1280, 720)
    window.show()
    alphabet_key_height = None
    if layout == ALL_LETTERS_LAYOUT:
        letter = window._action_buttons[window._action("letter:0")]
        qtbot.waitUntil(letter.isVisible)
        alphabet_key_height = letter.height()

    window._phrases_button.click()
    qtbot.waitUntil(lambda: [len(row) for row in _card_rows(window)] == [3, 3, 3])
    rows = _card_rows(window)
    assert window._list_heading.text() == "Moje fraze"
    assert window._list_page_label.text() == "\u00b7 stranica 1 od 2"
    assert window._list_page_label.isVisible()
    assert not window._view_title.isVisible()
    assert window._next_page_button.isHidden()
    strip = (window._add_item_button, window._list_previous_button)
    # Leaving, editing and paging rows share the card rows' top and bottom edges.
    for row, button in zip(rows[1:], strip, strict=True):
        rect = _window_rect(window, button)
        assert (rect.top(), rect.bottom()) == (row[0].top(), row[0].bottom())
    assert not window._back_button.isVisible()
    assert not window._list_back_line.isVisible()
    cards = [rect for row in rows for rect in row]
    assert min(rect.height() for rect in cards) >= 100
    assert min(rect.width() for rect in cards) >= (250 if layout == ALL_LETTERS_LAYOUT else 200)
    if alphabet_key_height is not None:
        assert min(rect.height() for rect in cards) >= alphabet_key_height - 1
    controls = (
        window._add_item_button,
        window._delete_mode_button,
        window._list_previous_button,
        window._list_next_button,
    )
    for button in controls:
        rect = _window_rect(window, button)
        assert window.rect().contains(rect)
        assert rect.width() >= 100 and rect.height() >= 72
    assert (window.width(), window.height()) == (1280, 720)

    window._list_next_button.click()
    qtbot.waitUntil(lambda: len(_card_rows(window)) == 1)
    assert window._list_page_label.text() == "\u00b7 stranica 2 od 2"
    assert not window._list_next_button.isEnabled()
    rect = _window_rect(window, window._list_previous_button)
    # A short page keeps its empty rows, so the strip does not move.
    assert rect.bottom() == rows[2][0].bottom()

    window._categories_button.click()
    click_speech_action(qtbot, window, "list:select:0")
    qtbot.waitUntil(lambda: [len(row) for row in _card_rows(window)] == [3, 3])
    answer_rows = _card_rows(window)
    back = _window_rect(window, window._back_button)
    assert (back.top(), back.bottom()) == (answer_rows[0][0].top(), answer_rows[0][0].bottom())
    assert _window_rect(window, window._add_item_button).top() == answer_rows[1][0].top()
    assert window._list_back_line.isVisible()
    assert window._list_page_label.isHidden()


@pytest.mark.e2e
def test_category_cards_open_answers_and_name_their_count(qtbot, make_speech_window):
    counts = (0, 1, 2, 5, 11, 21)
    categories = [
        CategoryRecord(f"Kategorija {count}", [f"Odgovor {index}" for index in range(count)])
        for count in counts
    ]
    store = FakeLibraryStore(SpeechLibrary(categories=categories))
    window = make_speech_window(FakeSpeech(), library_store=store)
    window.resize(1280, 720)
    window.show()

    window._categories_button.click()
    texts = [
        window._action_buttons[window._action(f"list:select:{index}")].text()
        for index in range(len(counts))
    ]
    assert [text.partition("\n")[2] for text in texts] == [
        "Nema odgovora",
        "1 odgovor",
        "2 odgovora",
        "5 odgovora",
        "11 odgovora",
        "21 odgovor",
    ]
    category = window._action_buttons[window._action("list:select:0")]
    assert category.objectName() == "categoryButton"
    assert texts[0].partition("\n")[0] == "KATEGORIJA 0\u00a0\u203a"

    window._delete_mode_button.click()
    deleting = window._action_buttons[window._action("list:select:0")]
    assert deleting.objectName() == "deleteItemButton"
    assert deleting.text() == "KATEGORIJA 0\nObriši"
    window._delete_mode_button.click()

    click_speech_action(qtbot, window, "list:select:4")
    answer = window._action_buttons[window._action("list:select:0")]
    assert answer.objectName() == "phraseButton"
    assert window._list_heading.text() == "Kategorije \u203a KATEGORIJA 11"
    assert window._list_page_label.text() == "\u00b7 stranica 1 od 2"
    window._back_button.click()
    assert window._view_mode == "categories"
    assert window._list_heading.text() == "Kategorije"
