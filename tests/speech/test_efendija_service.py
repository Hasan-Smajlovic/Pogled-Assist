from __future__ import annotations

import threading
from dataclasses import replace

import pytest
from _speech_service_fakes import service as service

from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.speech.voice_state import VoiceError, VoiceState


@pytest.mark.parametrize("reason", ["quota", "offline"])
def test_passive_credit_refresh_never_resets_speech_cooldown(service, reason):
    instance, client, _ = service
    gate = instance._router.gate
    gate.failure(instance.account.config, reason, None)
    deadline = gate.retry_at
    instance.account._finish_subscription(instance.account._revision, client.balance, "")
    assert gate.retry_at == deadline


def test_preparation_and_playback_delivery_use_qt_thread_and_preserve_selected_voice(
    service, qtbot
):
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
    instance.set_saved_texts({"FIRST"})
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
        assert list(instance.audio_cache.root.glob("*.audio")) == []
        assert (first, "stopped") in states
        assert (first, "finished") not in states
    finally:
        release.set()


@pytest.mark.e2e
def test_immediate_replay_after_stop_uses_the_download_already_paid_for(service, qtbot, monkeypatch):
    instance, client, played = service
    instance.set_saved_texts({"SAČUVANA FRAZA."})
    original_play = instance._audio.play
    states = []
    instance.playback_changed.connect(lambda request, state: states.append((request, state)))

    def pause_first_playback(request, _data, result):
        monkeypatch.setattr(instance._audio, "play", original_play)
        result.started = True
        instance._audio.started.emit(request)

    monkeypatch.setattr(instance._audio, "play", pause_first_playback)
    assert instance.speak("SAČUVANA FRAZA.")
    first = instance.request_id
    qtbot.waitUntil(lambda: (first, "speaking") in states)
    instance.stop()
    client.error = VoiceError("quota")
    assert instance.speak("SAČUVANA FRAZA.")
    second = instance.request_id
    qtbot.waitUntil(lambda: (second, "finished") in states)
    assert len(client.calls) == 1
    assert played[-1][1] == client.audio
    assert instance.voice_state.cached
    assert (first, "finished") not in states


@pytest.mark.e2e
def test_cached_output_failure_does_not_regenerate_and_recovers_when_output_returns(
    service, qtbot, monkeypatch
):
    instance, client, _played = service
    instance.set_saved_texts({"SAČUVANA FRAZA."})
    states = []
    instance.playback_changed.connect(lambda request, state: states.append((request, state)))
    assert instance.speak("SAČUVANA FRAZA.")
    first = instance.request_id
    qtbot.waitUntil(lambda: (first, "finished") in states)
    original_play = instance._audio.play
    instance._router.natural = lambda *_: b"natural audio"

    def output_failed(request, data, result):
        if instance._audio_voice.cached:
            result.outcome = "failed"
            result.done.set()
        else:
            original_play(request, data, result)

    monkeypatch.setattr(instance._audio, "play", output_failed)
    assert instance.speak("SAČUVANA FRAZA.")
    second = instance.request_id
    qtbot.waitUntil(lambda: (second, "finished") in states)
    assert len(client.calls) == 1
    assert instance.voice_state.voice == "human_like"
    assert instance._router.gate.snapshot()[0] == ""
    monkeypatch.setattr(instance._audio, "play", original_play)
    client.error = VoiceError("offline")
    assert instance.speak("SAČUVANA FRAZA.")
    third = instance.request_id
    qtbot.waitUntil(lambda: (third, "finished") in states)
    assert len(client.calls) == 1
    assert instance.voice_state.cached


@pytest.mark.e2e
def test_storage_failure_reaches_voice_notice_after_successful_speech(service, qtbot):
    instance, _client, _played = service
    instance.set_saved_texts({"SAČUVANA FRAZA."})
    instance.audio_cache.root.write_bytes(b"not a directory")
    states = []
    instance.playback_changed.connect(lambda request, state: states.append((request, state)))
    assert instance.speak("SAČUVANA FRAZA.")
    request = instance.request_id
    qtbot.waitUntil(lambda: (request, "finished") in states)
    assert instance.voice_state.cache_failed
    assert instance.voice_state.notice[1:] == (
        "Zvuk nije sačuvan.",
        "Ponavljanje može trošiti kredite.",
    )


def test_arabic_keeps_hamed_and_never_contacts_elevenlabs(service, monkeypatch):
    instance, client, played = service
    commands = []
    monkeypatch.setattr(
        instance, "_start_process", lambda command, *_args, **_kw: commands.append(command) or True
    )
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
    assert not instance.voice_state.partial


@pytest.mark.parametrize(
    "change",
    [
        ("elevenlabs_model_id", "eleven_v3"),
        ("elevenlabs_stability", 30),
        ("elevenlabs_similarity", 95),
    ],
)
def test_model_or_tuning_change_cancels_request_before_native_stop_and_rejects_late_audio(
    service, qtbot, monkeypatch, change
):
    setting, value = change
    instance, client, played = service
    entered, release = threading.Event(), threading.Event()

    def blocked(*_args):
        entered.set()
        release.wait(3)
        return b"late old-model audio"

    client.synthesize = blocked
    try:
        assert instance.test_efendija()
        request, cancel = instance.request_id, instance._cancel
        assert entered.wait(1)

        def stop():
            assert cancel.is_set()
            assert instance.request_id != request and instance._cancel is None

        monkeypatch.setattr(instance._audio, "stop", stop)
        instance.update_settings(replace(instance.settings, **{setting: value}))
        release.set()
        qtbot.wait(50)
        assert played == []
        assert getattr(instance.settings, setting) == value
    finally:
        release.set()
        monkeypatch.undo()


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


def test_standard_speech_survives_changes_to_unused_elevenlabs_tuning(service):
    instance, _client, _played = service
    instance.update_settings(SpeechSettings())
    instance._cancel = threading.Event()
    instance.playback_state = "speaking"
    cancel = instance._cancel
    instance.update_settings(replace(instance.settings, elevenlabs_stability=100))
    assert not cancel.is_set()
    assert instance.playback_state == "speaking"


def test_explicit_credit_refresh_can_release_quota_gate(service, qtbot):
    instance, client, _played = service
    gate = instance._router.gate
    gate.failure(instance.account.config, "quota", None)
    instance.account.refresh_subscription(allow_recovery=True)
    qtbot.waitUntil(lambda: not instance.account.state.credits_busy)
    assert instance.account.state.subscription == client.balance
    assert gate.snapshot()[0] == "quota"
    assert gate.retry_at == 0


def test_zero_balance_check_does_not_release_quota_cooldown(service):
    from pogled_assist.speech.elevenlabs import Subscription

    instance, _client, _played = service
    gate = instance._router.gate
    config = instance.account.config
    gate.failure(config, "quota", None)
    deadline = gate.retry_at
    gate.checked(config, Subscription(100, 100))
    assert gate.retry_at == deadline
