from __future__ import annotations

import copy
from dataclasses import replace

from PySide6.QtCore import QObject, Signal

from pogled_assist.speech.speech_library import SpeechLibrary, default_categories
from pogled_assist.speech.speech_service import SpeechSettings


class FakeSpeech(QObject):
    playback_changed = Signal(int, str)

    def __init__(self, *, successful=True):
        super().__init__()
        self.request_id = 0
        self._settings = SpeechSettings()
        self.successful = successful
        self.requests = []
        self.stop_calls = 0

    @property
    def settings(self):
        return replace(self._settings)

    def speak(self, text, settings=None):
        self.request_id += 1
        self.requests.append((text, replace(settings) if settings is not None else self.settings))
        return self.successful

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
