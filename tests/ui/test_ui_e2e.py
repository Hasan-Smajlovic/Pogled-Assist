from __future__ import annotations

import pytest
from _speech_fixtures import make_speech_window as make_speech_window
from _ui_fakes import FakeLibraryStore, FakeSpeech
from PySide6.QtCore import QPoint, QRect, Qt

from pogled_assist.ui.speech_window import SPEECH_WINDOW_ACTION_PREFIX


@pytest.mark.e2e
def test_twelve_letter_dialog_fits_150_percent_display_and_accepts_gaze(qtbot, make_speech_window):
    window = make_speech_window(
        FakeSpeech(), letters_per_group=12, library_store=FakeLibraryStore()
    )
    window.resize(1280, 720)
    window.show()
    qtbot.waitUntil(window.isVisible)

    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"].click()
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.letter)
    dialog = window._dialogs.letter
    assert dialog.height() <= window.height() - 64
    assert dialog.width() <= window.width() - 64

    bounds = dialog.rect()
    for action in window._dialogs.letter_actions:
        button = window._action_buttons[action]
        rect = QRect(button.mapTo(dialog, QPoint(0, 0)), button.size())
        assert bounds.contains(rect), action
        assert button.width() >= 140, action
        assert button.height() >= 110, action
        assert window.action_at_global_point(button.mapToGlobal(button.rect().center())) == action

    last_letter = f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:11"
    window.handle_gaze_action(last_letter)
    qtbot.waitUntil(lambda: window._dialogs.active is None)
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
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.confirm)
    qtbot.mouseClick(
        window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:cancel"], Qt.LeftButton
    )
    qtbot.waitUntil(lambda: window._dialogs.active is None)
    assert window._input.text() == "TREBAM POMOĆ"

    qtbot.mouseClick(window._clear_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.confirm)
    qtbot.mouseClick(
        window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:accept"], Qt.LeftButton
    )
    qtbot.waitUntil(lambda: window._dialogs.active is None)
    assert window._input.text() == ""

    qtbot.mouseClick(window._clear_button, Qt.LeftButton)
    assert window._dialogs.active is None


@pytest.mark.e2e
def test_library_retry_is_gaze_selectable_and_preserves_the_message(
    qtbot, make_speech_window, tmp_path, monkeypatch
):
    from pathlib import Path

    from pogled_assist.speech.speech_library import (
        CategoryRecord,
        PhraseRecord,
        SpeechLibrary,
        SpeechLibraryStore,
    )

    primary, legacy = tmp_path / "library.json", tmp_path / "phrases.json"
    original = SpeechLibrary(
        [CategoryRecord("Synthetic custom", ["Synthetic answer"])],
        [PhraseRecord("Synthetic phrase", 5)],
    )
    assert SpeechLibraryStore(primary, legacy_path=legacy).save(original)
    before = primary.read_bytes()
    read_text = Path.read_text

    def unavailable(path, *args, **kwargs):
        if path == primary:
            raise PermissionError("Synthetic failure")
        return read_text(path, *args, **kwargs)

    store = SpeechLibraryStore(primary, legacy_path=legacy)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", unavailable)
        window = make_speech_window(FakeSpeech(), library_store=store)
    window.resize(1280, 720)
    window.show()
    window._view_mode = "phrases"
    window._show_list_level()
    qtbot.wait(1)
    window._input.setText("SYNTHETIC MESSAGE")
    window.handle_gaze_action(f"{SPEECH_WINDOW_ACTION_PREFIX}list:select:0")
    message = window._input.text()
    assert "SYNTHETIC PHRASE" in message
    assert primary.read_bytes() == before
    assert window._add_item_button.isHidden()
    assert window._delete_mode_button.isHidden()
    retry = window._retry_library_button
    assert retry.isVisible() and retry.height() >= 80
    assert window.rect().contains(QRect(retry.mapTo(window, QPoint()), retry.size()))
    assert (
        window.action_at_global_point(retry.mapToGlobal(retry.rect().center()))
        == f"{SPEECH_WINDOW_ACTION_PREFIX}list:retry"
    )
    window.handle_gaze_action(f"{SPEECH_WINDOW_ACTION_PREFIX}list:retry")
    assert not store.read_error
    assert window._library == original
    assert window._input.text() == message
    assert retry.isHidden()
    assert window._add_item_button.isVisible()


@pytest.mark.e2e
def test_speech_lifecycle_updates_status_and_ignores_previous_request(qtbot, make_speech_window):
    speech = FakeSpeech()
    window = make_speech_window(speech, library_store=FakeLibraryStore())
    window.show()
    window._input.setText("SYNTHETIC MESSAGE")
    window._play_button.click()
    first = speech.request_id
    assert window._status_label.text() == "Pokrećem govor."
    speech.playback_changed.emit(first, "speaking")
    assert window._status_label.text() == "Poruka se izgovara."
    speech.playback_changed.emit(first, "failed")
    assert window._status_label.text() == "Govor nije uspio. Pokušajte ponovo."
    assert window._input.text() == "SYNTHETIC MESSAGE"
    window._play_button.click()
    second = speech.request_id
    speech.playback_changed.emit(first, "finished")
    assert window._status_label.text() == "Pokrećem govor."
    speech.playback_changed.emit(second, "finished")
    assert window._status_label.text() == "Čitanje je završeno."
