from __future__ import annotations

import threading

import pytest
from _speech_fakes import FakeElevenClient

from pogled_assist.speech.audio_cache import AudioCache
from pogled_assist.speech.audio_playback import PlaybackResult
from pogled_assist.speech.elevenlabs import ElevenConfig, Subscription
from pogled_assist.speech.voice_router import VoiceRouter
from pogled_assist.speech.voice_state import EFENDIJA, NATURAL, STANDARD, SpeechCancelled, VoiceError


@pytest.fixture
def route(tmp_path):
    config = ElevenConfig("synthetic-key", "synthetic-voice")
    cache = AudioCache(tmp_path / "cache")
    cache.configure(config.audio_identity, {"SAČUVANA FRAZA."})
    client = FakeElevenClient()
    router = VoiceRouter(cache, client)
    router.gate.configure(config.fingerprint)
    natural_calls, played, notices = [], [], []

    def natural(text, *_args):
        natural_calls.append(text)
        return b"natural audio"

    def play(data, voice):
        played.append((data, voice))
        return PlaybackResult(started=True, outcome="finished")

    router.natural = natural
    return router, config, client, natural_calls, played, notices, play


@pytest.mark.parametrize("reason", ["quota", "invalid_key", "permission", "configuration", "offline", "timeout", "rate_limit"])
def test_preparation_error_uses_natural_for_same_text_without_changing_selection(route, reason):
    router, config, client, natural, played, notices, play = route
    client.error = VoiceError(reason)
    outcome = router.run("MOJA PORUKA.", config, threading.Event(), play, notices.append)
    assert outcome == "finished"
    assert natural == ["MOJA PORUKA."]
    assert len(client.calls) == 1
    assert played[0][1].voice == NATURAL
    assert played[0][1].reason == reason
    assert config.voice == "synthetic-voice"


def test_natural_failure_reaches_standard_with_truthful_notice(route):
    router, config, client, _natural, played, notices, play = route
    client.error = VoiceError("offline")

    def fail(*_args):
        raise VoiceError("offline")

    router.natural = fail
    assert router.run("PORUKA", config, threading.Event(), play, notices.append) == "standard"
    assert played == []
    assert notices[-1].voice == STANDARD
    assert notices[-1].notice[2] == "Koristi se Standardni glas."


def test_deadlines_are_five_seconds_then_three_and_are_not_restarted(route):
    router, config, _client, _natural, _played, notices, play = route
    limits = []

    class TimedOut:
        def run(self, operation, cancel, timeout):
            limits.append(timeout)
            raise VoiceError("timeout")

    router.network = router.natural_network = TimedOut()
    assert router.run("PORUKA", config, threading.Event(), play, notices.append) == "standard"
    assert 0 < limits[0] <= 5
    assert limits[1] == 3


def test_whole_saved_phrase_is_cached_only_after_success_and_repeats_offline(route):
    router, config, client, natural, played, notices, play = route
    assert router.run("sačuvana  fraza.", config, threading.Event(), play, notices.append) == "finished"
    assert client.calls[0][2] == "SAČUVANA FRAZA."
    client.error = VoiceError("quota")
    router.run("SAČUVANA FRAZA.", config, threading.Event(), play, notices.append)
    assert len(client.calls) == 1
    assert natural == []
    assert played[-1][1].cached


def test_free_form_text_never_creates_cache_file(route):
    router, config, _client, _natural, _played, notices, play = route
    router.run("PRIVATNA PORUKA", config, threading.Event(), play, notices.append)
    assert not router.cache.root.exists()


@pytest.mark.parametrize("provider", [EFENDIJA, NATURAL])
def test_partial_playback_never_repeats_message_on_another_provider(route, provider):
    router, config, client, natural, _played, notices, _play = route
    if provider == NATURAL:
        client.error = VoiceError("offline")
    calls = []

    def broken(_data, voice):
        calls.append(voice.voice)
        return PlaybackResult(started=True, outcome="failed")

    assert router.run("PORUKA", config, threading.Event(), broken, notices.append) == "failed"
    assert calls == [provider]
    assert notices[-1].partial
    assert natural == (["PORUKA"] if provider == NATURAL else [])


def test_audio_error_before_playback_can_fall_back(route):
    router, config, _client, _natural, _played, notices, _play = route
    calls = []

    def play(_data, voice):
        calls.append(voice.voice)
        return PlaybackResult(started=voice.voice == NATURAL,
                              outcome="failed" if voice.voice == EFENDIJA else "finished")

    assert router.run("PORUKA", config, threading.Event(), play, notices.append) == "finished"
    assert calls == [EFENDIJA, NATURAL]


def test_quota_cooldown_skips_paid_requests_until_balance_increases(route):
    router, config, client, natural, played, notices, play = route
    client.error = VoiceError("quota")
    client.balance = Subscription(100, 100, 2000000000)
    router.run("PORUKA", config, threading.Event(), play, notices.append)
    retry_at = router.gate.retry_at
    client.error = None
    router.run("DRUGA PORUKA", config, threading.Event(), play, notices.append)
    assert len(client.calls) == 1
    assert router.gate.retry_at == retry_at
    router.gate.retry_at = 0
    router.run("TREĆA PORUKA", config, threading.Event(), play, notices.append)
    assert len(client.calls) == 1
    assert natural == ["PORUKA", "DRUGA PORUKA", "TREĆA PORUKA"]
    client.balance = Subscription(100, 200, 2000000000)
    router.gate.retry_at = 0
    router.run("ČETVRTA PORUKA", config, threading.Event(), play, notices.append)
    assert len(client.calls) == 2
    assert played[-1][1].voice == EFENDIJA
    assert notices[-1].recovered
    assert router.gate.reason == ""


def test_free_check_allows_retry_but_does_not_claim_audio_recovery(route):
    router, config, client, _natural, _played, notices, play = route
    client.error = VoiceError("invalid_key")
    router.run("PORUKA", config, threading.Event(), play, notices.append)
    router.gate.checked(config, client.balance)
    assert router.gate.reason == "invalid_key"
    assert router.gate.retry_at == 0
    assert not any(notice.recovered for notice in notices)


def test_cached_clip_does_not_claim_online_recovery(route):
    router, config, client, _natural, played, notices, play = route
    router.run("SAČUVANA FRAZA.", config, threading.Event(), play, notices.append)
    router.gate.failure(config, "offline", None)
    notices.clear()
    client.error = VoiceError("offline")
    router.run("SAČUVANA FRAZA.", config, threading.Event(), play, notices.append)
    assert played[-1][1].cached
    assert router.gate.reason == "offline"
    assert not any(notice.recovered for notice in notices)


def test_explicit_voice_test_never_passes_using_cache_or_fallback(route):
    router, config, client, natural, played, notices, play = route
    router.cache.write(router.cache.ticket("SAČUVANA FRAZA."), b"old audio")
    client.error = VoiceError("quota")
    with pytest.raises(VoiceError, match="quota"):
        router.run("SAČUVANA FRAZA.", config, threading.Event(), play, notices.append, test=True)
    assert len(client.calls) == 1
    assert played == natural == []


def test_stop_during_generation_drops_audio_and_does_not_start_fallback(route):
    router, config, client, natural, played, notices, play = route
    cancel = threading.Event()

    def stopped(*_args):
        cancel.set()
        return b"late audio"

    client.synthesize = stopped
    with pytest.raises(SpeechCancelled):
        router.run("PORUKA", config, cancel, play, notices.append)
    assert played == natural == notices == []


def test_confirmed_quota_error_falls_back_without_waiting_for_another_http_call(route):
    router, config, client, natural, _played, notices, play = route
    client.error = VoiceError("quota")

    def unexpected_check(*_args):
        pytest.fail("A confirmed error must fall back immediately")

    client.subscription = unexpected_check
    assert router.run("PORUKA", config, threading.Event(), play, notices.append) == "finished"
    assert natural == ["PORUKA"]


def test_failed_audio_cache_write_does_not_turn_successful_speech_into_failure(route, monkeypatch):
    router, config, _client, _natural, _played, notices, play = route
    monkeypatch.setattr(router.cache, "write", lambda *_: False)
    assert router.run("SAČUVANA FRAZA.", config, threading.Event(), play, notices.append) == "finished"
