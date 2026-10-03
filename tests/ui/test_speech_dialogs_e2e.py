from __future__ import annotations

import pytest
from _speech_fixtures import make_speech_window as make_speech_window
from _ui_fakes import FakeAlarmSound, FakeLibraryStore, FakeSpeech, click_speech_action
from PySide6.QtCore import QPoint, QRect, Qt

from pogled_assist.speech.speech_library import PhraseRecord, SpeechLibrary, default_categories
from pogled_assist.ui.speech_window import BOSNIAN_LETTERS, SPEECH_WINDOW_ACTION_PREFIX


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
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.letter)
    assert window._dialogs.backdrop.isVisible()

    qtbot.mouseClick(window._play_button, Qt.LeftButton)
    qtbot.mouseClick(window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}space"], Qt.LeftButton)
    assert speech.requests == []
    assert window._input.text() == ""

    letter_action = f"{SPEECH_WINDOW_ACTION_PREFIX}letter:1:1"
    letter = window._action_buttons[letter_action]
    qtbot.waitUntil(letter.isVisible)
    qtbot.mouseClick(letter, Qt.LeftButton)
    qtbot.waitUntil(lambda: window._dialogs.active is None)
    assert window._input.text() == "DŽ"
    assert not window._dialogs.backdrop.isVisible()

    gaze_group_action = f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"
    group = window._action_buttons[gaze_group_action]
    group_center = group.mapToGlobal(group.rect().center())
    assert window.action_at_global_point(group_center) == gaze_group_action
    window.handle_gaze_action(gaze_group_action)
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.letter)

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
    qtbot.waitUntil(lambda: window._dialogs.active is None)
    assert window._input.text() == "DŽA"


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
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.alarm)

    assert speech.stop_calls == 1
    assert alarm.start_calls == 1
    assert window._dialogs.alarm_copy.text() == "Zvučni signal se ponavlja dok ga ne zaustavite."
    space_center = window._space_button.mapToGlobal(window._space_button.rect().center())
    assert window.action_at_global_point(space_center) is None
    assert window._input.text() == "PORUKA OSTAJE"

    window.handle_gaze_action(stop_action)
    qtbot.waitUntil(lambda: window._dialogs.active is None)
    assert alarm.stop_calls >= 1
    assert window._input.text() == "PORUKA OSTAJE"

    window.handle_gaze_action(alarm_action)
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.alarm)
    window._action_buttons[stop_action].click()
    qtbot.waitUntil(lambda: window._dialogs.active is None)

    alarm.start_result = False
    alarm.last_error = "Audio uređaj nije dostupan."
    window._action_buttons[alarm_action].click()
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.alarm)
    assert window._dialogs.alarm_copy.text() == "Audio uređaj nije dostupan."
    assert window._status_label.text() == "Audio uređaj nije dostupan."

    alarm.failed.emit("Zvuk je prekinut.")
    assert window._dialogs.alarm_copy.text() == "Zvuk je prekinut."
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
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.sleep)

    assert speech.stop_calls == 1
    assert window._dialogs.sleep.geometry() == QRect(
        window.mapToGlobal(QPoint(0, 0)), window.size()
    )
    assert window._dialogs.sleep.isVisible()
    assert window._input.text() == "NEDOVRŠENA FRAZA"
    assert window._editor is editor
    assert window._list_page == 1
    assert window._view_mode == "editor"
    assert editor is not None and editor.message == "RAZGOVOR"
    space_center = window._space_button.mapToGlobal(window._space_button.rect().center())
    assert window.action_at_global_point(space_center) is None

    qtbot.mouseClick(window._dialogs.wake_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window._dialogs.active is None)
    assert window._input.text() == "NEDOVRŠENA FRAZA"
    assert window._editor is editor
    assert window._list_page == 1

    window._action_buttons[sleep_action].click()
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.sleep)
    wake_center = window._dialogs.wake_button.mapToGlobal(
        window._dialogs.wake_button.rect().center()
    )
    assert window.action_at_global_point(wake_center) == wake_action
    window.handle_gaze_action(wake_action)
    qtbot.waitUntil(lambda: window._dialogs.active is None)
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
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.exit)

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
    qtbot.waitUntil(lambda: window._dialogs.active is None)
    assert (
        window._input.text(),
        window._view_mode,
        window._category_index,
        window._list_page,
    ) == preserved_state
    assert quit_requests == []

    window.handle_gaze_action(exit_action)
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.exit)
    qtbot.mouseClick(leave_button, Qt.LeftButton)
    qtbot.waitUntil(window.isHidden)

    assert quit_requests == []
    assert speech.stop_calls == 1
    assert alarm.stop_calls >= 1

    window.show_full_screen()
    qtbot.waitUntil(window.isVisible)
    assert window._input.text() == "PORUKA"
    window.handle_gaze_action(exit_action)
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.exit)
    window.handle_gaze_action(quit_action)

    assert quit_requests == [True]
    assert speech.stop_calls == 2
    assert alarm.stop_calls >= 1
