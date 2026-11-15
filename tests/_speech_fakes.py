from __future__ import annotations

import copy
import faulthandler
from contextlib import contextmanager
from dataclasses import replace
from threading import Thread

from PySide6.QtCore import QCoreApplication, QObject, Signal

from pogled_assist.keyboard_layouts import LETTER_GROUPS_LAYOUT
from pogled_assist.speech.audio_cache import AudioCache
from pogled_assist.speech.eleven_account import ElevenAccount
from pogled_assist.speech.elevenlabs import AccountOptions, Subscription
from pogled_assist.speech.speech_library import SpeechLibrary, default_categories
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.speech.voice_state import ACTIVE_PLAYBACK_STATES, VOICE_TEST_TEXT, VoiceState


@contextmanager
def speech_workers(monkeypatch):
    """Join real speech workers while their Qt owners are still alive.

    Exiting restores the previous thread factory, so an enclosing fixture context
    tracks the workers started after a nested context closes.
    """
    from pogled_assist.speech import eleven_account, eleven_transport, speech_service

    workers = []

    def thread(*args, **kwargs):
        worker = Thread(*args, **kwargs)
        workers.append(worker)
        return worker

    with monkeypatch.context() as patch:
        for module in (eleven_account, eleven_transport, speech_service):
            patch.setattr(module, "Thread", thread)
        try:
            yield workers
        finally:
            for worker in workers:
                if worker.ident is not None:
                    worker.join(10)
            alive = [worker.name for worker in workers if worker.is_alive()]
            if alive:
                faulthandler.dump_traceback()
            assert not alive, f"Speech workers did not stop: {alive}"


def wait_for_speech_workers(qtbot, workers):
    """Wait until started workers exit, then deliver the Qt results they queued."""
    assert workers, "No speech worker was started."
    qtbot.waitUntil(lambda: not any(worker.is_alive() for worker in workers))
    QCoreApplication.processEvents()


class FakeCredentials:
    def __init__(self, key=""):
        self.key = key

    def read(self):
        return self.key

    def write(self, key):
        self.key = key

    def delete(self):
        self.key = ""


class FakeElevenClient:
    def __init__(self):
        self.calls = []
        self.audio = b"synthetic mp3"
        self.error = None
        self.balance = Subscription(10, 100, 2000000000)

    def synthesize(self, config, text, cancel, deadline):
        self.calls.append((config.voice, config.model, text))
        if self.error:
            raise self.error
        return self.audio

    def subscription(self, *_args):
        return self.balance

    def options(self, *_args):
        return AccountOptions(
            (("synthetic-voice", "Probni glas"),),
            (("eleven_v4", "Eleven v4"),),
            None,
        )


def grouped_fake_speech(**options):
    """Speech whose Latin letters use the Settings group layout instead of the alphabet."""
    speech = FakeSpeech(**options)
    speech._settings = replace(speech._settings, letter_layout=LETTER_GROUPS_LAYOUT)
    return speech


class FakeSpeech(QObject):
    playback_changed = Signal(int, str)
    voice_changed = Signal(int, object)
    test_finished = Signal(int, str)

    def __init__(self, *, successful=True):
        super().__init__()
        self.request_id = 0
        self.playback_state = "stopped"
        self._settings = SpeechSettings()
        self.successful = successful
        self.requests = []
        self.stop_calls = 0
        self.voice_state = VoiceState()
        self.saved_texts = set()
        self.audio_cache = AudioCache(None)
        self.account = ElevenAccount(self, store=FakeCredentials(), client=FakeElevenClient())
        self.account.configure(self.settings)
        self.playback_changed.connect(self._set_playback_state)

    def _set_playback_state(self, _request_id, state):
        self.playback_state = state

    def set_saved_texts(self, texts):
        self.saved_texts = set(texts) if texts is not None else None

    def test_efendija(self):
        return self.speak(VOICE_TEST_TEXT)

    def publish_voice(self, state):
        self.voice_state = replace(state, recovered=False)
        self.voice_changed.emit(self.request_id, state)

    @property
    def is_busy(self):
        return self.playback_state in ACTIVE_PLAYBACK_STATES

    @property
    def settings(self):
        return replace(self._settings)

    def speak(self, text, settings=None):
        self.request_id += 1
        self.requests.append((text, replace(settings) if settings is not None else self.settings))
        self.playback_state = "preparing" if self.successful else "failed"
        return self.successful

    def stop(self):
        self.stop_calls += 1
        self.playback_state = "stopped"
        self.playback_changed.emit(self.request_id, "stopped")


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
