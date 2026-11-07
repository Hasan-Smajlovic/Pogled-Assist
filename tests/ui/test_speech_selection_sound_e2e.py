from __future__ import annotations

from dataclasses import replace

import pytest
from _speech_fixtures import make_speech_window as make_speech_window
from _ui_fakes import FakeAlarmSound, FakeLibraryStore, FakeSelectionSound, FakeSpeech

from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.ui.speech_window import BOSNIAN_LETTERS

pytestmark = pytest.mark.e2e


def _open_speech(qtbot, make_speech_window, **settings):
    speech = FakeSpeech()
    speech._settings = SpeechSettings(**settings)
    sound = FakeSelectionSound()
    alarm = FakeAlarmSound()
    window = make_speech_window(
        speech, library_store=FakeLibraryStore(), alarm_sound=alarm, selection_sound=sound
    )
    window.resize(1280, 720)
    window.show()
    qtbot.waitUntil(window.isVisible)
    return window, sound, alarm


def _gaze_letter(window, letter):
    window.handle_gaze_action(window._action(f"letter:{BOSNIAN_LETTERS.index(letter)}"))


def test_each_completed_gaze_selection_ticks_once_after_the_text_changes(qtbot, make_speech_window):
    window, sound, _alarm = _open_speech(qtbot, make_speech_window)
    heard = []
    sound.play = lambda level: heard.append((level, window._input.text()))

    _gaze_letter(window, "DŽ")
    window.handle_gaze_action(window._action("space"))
    _gaze_letter(window, "A")
    window.handle_gaze_action(window._action("backspace"))

    assert window._input.text() == "DŽ "
    assert heard == [("quiet", "DŽ"), ("quiet", "DŽ "), ("quiet", "DŽ A"), ("quiet", "DŽ ")]


def test_tick_follows_the_current_setting_and_groups_tick_per_selection(qtbot, make_speech_window):
    window, sound, _alarm = _open_speech(qtbot, make_speech_window, letter_layout="groups")
    window.handle_gaze_action(window._action("group:0"))
    window.update_settings(replace(window._speech_settings, selection_sound="loud"))
    window.handle_gaze_action(window._action("letter:0:0"))
    window.update_settings(replace(window._speech_settings, selection_sound="off"))
    window.handle_gaze_action(window._action("space"))

    assert window._input.text() == "A "
    # SelectionSound stays silent for "off"; the window always reports the saved level.
    assert sound.levels == ["quiet", "loud", "off"]


def test_mouse_clicks_and_rejected_gaze_actions_stay_silent(qtbot, make_speech_window):
    window, sound, _alarm = _open_speech(qtbot, make_speech_window)
    window._action_buttons[window._action(f"letter:{BOSNIAN_LETTERS.index('B')}")].click()
    # The alphabet has no "back to groups" key, so this gaze action is rejected.
    window.handle_gaze_action(window._action("letters:close"))
    window.handle_gaze_action("not-a-speech-action")

    assert window._input.text() == "B"
    assert sound.levels == []


def test_speaking_and_the_alarm_are_their_own_confirmation(qtbot, make_speech_window):
    window, sound, alarm = _open_speech(qtbot, make_speech_window)
    _gaze_letter(window, "E")
    window.handle_gaze_action(window._action("play"))
    window.handle_gaze_action(window._action("alarm:start"))
    # While the alarm dialog is open, letters are blocked and stay silent.
    _gaze_letter(window, "F")
    window.handle_gaze_action(window._action("alarm:stop"))

    assert window._input.text() == "E"
    assert alarm.start_calls == 1 and alarm.stop_calls
    assert window._dialogs.active is None
    assert sound.levels == ["quiet"]
