"""A real speech service with fake credentials, network and Qt audio output."""

from pathlib import Path

import pytest
from _speech_fakes import FakeCredentials, FakeElevenClient
from PySide6.QtCore import QThread

from pogled_assist.speech import speech_service
from pogled_assist.speech.audio_cache import AudioCache
from pogled_assist.speech.speech_service import SpeechSettings


@pytest.fixture
def service(monkeypatch, tmp_path):
    monkeypatch.setattr(speech_service, "find_espeak_ng", lambda: Path("fake-espeak.exe"))
    monkeypatch.setattr(speech_service, "find_edge_playback", lambda: Path("fake-edge.exe"))
    client = FakeElevenClient()
    instance = speech_service.SpeechService(
        credentials=FakeCredentials("synthetic-secret"),
        client=client,
        cache=AudioCache(tmp_path / "cache"),
    )
    instance.update_settings(SpeechSettings(voice_preset="efendija", elevenlabs_voice_id="voice"))
    played = []

    def play(request, data, result):
        played.append((request, data, QThread.currentThread()))
        result.started = True
        instance._audio.started.emit(request)
        result.outcome = "finished"
        result.done.set()

    monkeypatch.setattr(instance._audio, "play", play)
    yield instance, client, played
    instance.stop()
