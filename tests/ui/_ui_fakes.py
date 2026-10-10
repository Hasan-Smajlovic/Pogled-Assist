from __future__ import annotations

import copy
from dataclasses import replace

from PySide6.QtCore import QObject, Signal

from pogled_assist.speech.speech_library import SpeechLibrary, default_categories
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.ui.speech_window import SPEECH_WINDOW_ACTION_PREFIX


class FakeSpeech(QObject):
    playback_changed = Signal(int, str)

    def __init__(self):
        super().__init__()
        self.request_id = 0
        self._settings = SpeechSettings()
        self.requests = []
        self.stop_calls = 0

    @property
    def settings(self):
        return replace(self._settings)

    def speak(self, text, settings=None):
        self.request_id += 1
        self.requests.append((text, replace(settings) if settings is not None else self.settings))
        return True

    def stop(self):
        self.stop_calls += 1


class FakeAlarmSound(QObject):
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.start_calls = 0
        self.stop_calls = 0
        self.start_result = True
        self.last_error = None

    def start(self):
        self.start_calls += 1
        return self.start_result

    def stop(self):
        self.stop_calls += 1


class FakeLibraryStore:
    read_error = False

    def __init__(self, library=None):
        self.library = copy.deepcopy(library or SpeechLibrary(categories=default_categories()))
        self.saved = []
        self.fail_saves = False

    def load(self):
        return copy.deepcopy(self.library)

    def save(self, library):
        if self.fail_saves:
            return False
        self.library = copy.deepcopy(library)
        self.saved.append(copy.deepcopy(library))
        return True


def click_speech_action(qtbot, window, command):
    button = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}{command}"]
    qtbot.waitUntil(button.isVisible)
    button.click()


class FakeKeyboardInput:
    def __init__(self):
        self.typed = []
        self.pressed = []

    def foreground_window(self):
        return 50

    def belongs_to_current_process(self, _hwnd):
        return False

    def type_text(self, text):
        self.typed.append(text)

    def press_key(self, key):
        self.pressed.append(key)

    def is_window(self, _hwnd):
        return True

    def set_foreground_window(self, _hwnd):
        return True


class FakeControllerInput(FakeKeyboardInput):
    def __init__(self):
        super().__init__()
        self.clicks = []
        self.scrolls = []

    def click(self, x, y, **options):
        self.clicks.append((x, y, options))

    def click_current(self, **options):
        self.clicks.append((None, None, options))

    def scroll(self, units):
        self.scrolls.append(units)


class FakeAppBar:
    supported = False

    def register(self, *_args, **_kwargs):
        return False

    def unregister(self):
        return None

    def set_position(self, *_args):
        return None


class FakeHotbarInput(FakeControllerInput):
    def __init__(self):
        super().__init__()
        self.moves = []

    def move_to(self, x, y):
        self.moves.append((x, y))

    def cursor_position(self):
        return 600, 500


class FakeSpeechService(FakeSpeech):
    available = True

    def update_settings(self, settings):
        self._settings = replace(settings)

    def stop(self):
        return None
