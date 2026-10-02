from __future__ import annotations

import logging

import pytest
from _speech_fixtures import make_speech_window as make_speech_window, speech_focus as speech_focus
from _ui_fakes import FakeLibraryStore, FakeSpeech, click_speech_action
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLineEdit

from pogled_assist.ui.speech_window import SPEECH_WINDOW_ACTION_PREFIX


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
    qtbot.waitUntil(lambda: qapp.activeModalWidget() is window._dialogs.active)
    # The offscreen platform does not activate modal windows like Windows does.
    qapp.setActiveWindow(window._dialogs.active)
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
