from __future__ import annotations

import pytest
from _ui_fakes import FakeAlarmSound, FakeLibraryStore, FakeSpeech

from pogled_assist.ui.speech_window import SpeechWindow


@pytest.fixture
def make_speech_window(qtbot):
    def create(speech, **options):
        window = SpeechWindow(speech, **options)
        qtbot.addWidget(window)
        return window

    return create


@pytest.fixture
def speech_focus(qtbot, qapp, make_speech_window):
    window = make_speech_window(
        FakeSpeech(), library_store=FakeLibraryStore(), alarm_sound=FakeAlarmSound()
    )
    window.show_full_screen()
    window.activateWindow()
    qtbot.waitUntil(lambda: qapp.focusWidget() is window._input)
    return qapp, window
