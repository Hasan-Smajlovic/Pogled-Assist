from __future__ import annotations

import threading
from pathlib import Path

import pytest
from _speech_fakes import FakeCredentials, FakeElevenClient
from PySide6.QtCore import QThread

from pogled_assist.speech import speech_service
from pogled_assist.speech.audio_cache import AudioCache
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.speech.voice_state import VoiceError, VoiceState


@pytest.fixture
def service(monkeypatch, tmp_path):
    for name in ("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "ELEVENLABS_MODEL_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(speech_service, "find_espeak_ng", lambda: Path("fake-espeak.exe"))
    monkeypatch.setattr(speech_service, "find_edge_playback", lambda: Path("fake-edge.exe"))
    client = FakeElevenClient()
    instance = speech_service.SpeechService(
        credentials=FakeCredentials("synthetic-secret"), client=client,
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


def test_preparation_and_playback_delivery_use_qt_thread_and_preserve_selected_voice(service, qtbot):
    instance, client, played = service
    client.error = VoiceError("quota")
    instance._router.natural = lambda *_: b"natural audio"
    states, voices = [], []
    instance.playback_changed.connect(lambda request, state: states.append((request, state)))
    instance.voice_changed.connect(lambda request, state: voices.append(state))
    assert instance.speak("SYNTHETIC PRIVATE TEXT")
    request = instance.request_id
    qtbot.waitUntil(lambda: (request, "finished") in states)
    assert played[0][1] == b"natural audio"
    assert played[0][2] == instance.thread()
    assert voices[-1].voice == "human_like"
    assert instance.settings.voice_preset == "efendija"
    assert (request, "preparing") in states and (request, "speaking") in states


def test_stop_and_replacement_discard_late_network_audio_and_voice_events(service, qtbot):
    instance, client, played = service
    entered, release = threading.Event(), threading.Event()

    def blocked(*_args):
        entered.set()
        release.wait(3)
        return b"late audio"

    client.synthesize = blocked
    states, voices = [], []
    instance.playback_changed.connect(lambda request, state: states.append((request, state)))
    instance.voice_changed.connect(lambda request, state: voices.append(state))
    try:
        instance.speak("FIRST")
        first = instance.request_id
        assert entered.wait(1)
        instance.stop()
        instance._worker_voice.emit(first, VoiceState("human_like", "quota"))
        release.set()
        qtbot.wait(50)
        assert played == voices == []
        assert (first, "stopped") in states
        assert (first, "finished") not in states
    finally:
        release.set()


def test_arabic_keeps_hamed_and_never_contacts_elevenlabs(service, monkeypatch):
    instance, client, played = service
    commands = []
    monkeypatch.setattr(instance, "_start_process", lambda command, *_args, **_kw: commands.append(command) or True)
    assert instance.speak("سَلَامٌ", SpeechSettings(keyboard_script="arabic", voice_preset="efendija"))
    assert "ar-SA-HamedNeural" in commands[0]
    assert client.calls == played == []
    assert instance.settings.voice_preset == "efendija"


def test_paid_voice_test_emits_failure_instead_of_fallback_success(service, qtbot):
    instance, client, played = service
    client.error = VoiceError("quota")
    results = []
    instance.test_finished.connect(lambda request, message: results.append(message))
    instance.test_efendija()
    qtbot.waitUntil(lambda: bool(results))
    assert "nije uspjela" in results[0]
    assert "kredita" in results[0]
    assert played == []


def test_settings_and_http_failures_do_not_log_text_or_key(service, qtbot, caplog):
    instance, client, _played = service

    def fail(*_args):
        raise RuntimeError("SYNTHETIC PRIVATE TEXT synthetic-secret")

    client.synthesize = fail
    instance._router.natural = lambda *_: b"fallback"
    states = []
    instance.playback_changed.connect(lambda _request, state: states.append(state))
    instance.speak("SYNTHETIC PRIVATE TEXT")
    qtbot.waitUntil(lambda: "finished" in states)
    assert "SYNTHETIC PRIVATE TEXT" not in caplog.text
    assert "synthetic-secret" not in caplog.text
