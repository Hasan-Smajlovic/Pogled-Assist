from __future__ import annotations

from dataclasses import replace

import pytest
from _speech_fixtures import make_speech_window as make_speech_window
from _ui_fakes import FakeLibraryStore, FakeSpeech, click_speech_action
from PySide6.QtCore import QPoint, QRect, Qt

from pogled_assist.keyboard_layouts import ARABIC_LETTERS, ARABIC_MARKS
from pogled_assist.speech.speech_library import CategoryRecord, PhraseRecord, SpeechLibrary
from pogled_assist.ui.speech_window import BOSNIAN_LETTERS, SPEECH_WINDOW_ACTION_PREFIX


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
    dialog = window._dialogs.letter
    assert dialog.width() <= 1280 and dialog.height() <= 720
    rects = []
    for action in window._dialogs.letter_actions:
        button = window._action_buttons[action]
        rect = QRect(button.mapTo(dialog, QPoint(0, 0)), button.size())
        assert dialog.rect().contains(rect)
        assert all(not rect.intersects(previous) for previous in rects)
        rects.append(rect)
