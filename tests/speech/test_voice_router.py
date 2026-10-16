from __future__ import annotations

import threading

import pytest
from _speech_fakes import FakeElevenClient

from pogled_assist.speech.audio_cache import AudioCache
from pogled_assist.speech.audio_playback import PlaybackResult
from pogled_assist.speech.elevenlabs import ElevenConfig, Subscription
from pogled_assist.speech.voice_router import Playback, VoiceRouter
from pogled_assist.speech.voice_state import (
    EFENDIJA,
    NATURAL,
    STANDARD,
    SpeechCancelled,
    VoiceError,
)


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


@pytest.mark.parametrize(
    "reason",
    ["quota", "invalid_key", "permission", "configuration", "offline", "timeout", "rate_limit"],
)
def test_preparation_error_uses_natural_for_same_text_without_changing_selection(route, reason):
    router, config, client, natural, played, notices, play = route
    client.error = VoiceError(reason)
    outcome = router.run('MOJA PORUKA.', config, Playback(threading.Event(), play, notices.append))
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
    assert router.run('PORUKA', config, Playback(threading.Event(), play, notices.append)) == "standard"
    assert played == []
    assert notices[-1].voice == STANDARD
    assert notices[-1].notice[2] == "Koristi se Standardni glas."


def test_preparation_has_thirty_seconds_then_three_for_fallback(route):
    router, config, _client, _natural, _played, notices, play = route
    limits = []

    class TimedOut:
        def run(self, operation, cancel, timeout):
            limits.append(timeout)
            raise VoiceError("timeout")

    router.network = router.natural_network = TimedOut()
    assert router.run('PORUKA', config, Playback(threading.Event(), play, notices.append)) == "standard"
    assert 29 < limits[0] <= 30
    assert limits[1] == 3


def test_slow_valid_synthesis_is_not_discarded_after_five_seconds(route, monkeypatch):
    router, config, client, natural, played, notices, play = route
    clock = [100.0]
    monkeypatch.setattr("pogled_assist.speech.voice_router.time.monotonic", lambda: clock[0])

    def synthesize(config, text, cancel, deadline):
        client.calls.append(("synthesize", config, text))
        clock[0] += 8
        if clock[0] >= deadline:
            raise VoiceError("timeout")
        return b"slow valid audio"

    client.synthesize = synthesize
    assert router.run('PORUKA', config, Playback(threading.Event(), play, notices.append)) == "finished"
    assert len(client.calls) == 1 and natural == []
    assert played[0][0] == b"slow valid audio" and played[0][1].voice == EFENDIJA


def test_whole_saved_phrase_reuses_downloaded_audio_offline(route):
    router, config, client, natural, played, notices, play = route
    assert (
        router.run('sačuvana  fraza.', config, Playback(threading.Event(), play, notices.append))
        == "finished"
    )
    assert client.calls[0][2] == "SAČUVANA FRAZA."
    client.error = VoiceError("quota")
    router.run('SAČUVANA FRAZA.', config, Playback(threading.Event(), play, notices.append))
    assert len(client.calls) == 1
    assert natural == []
    assert played[-1][1].cached


def test_free_form_text_never_creates_cache_file(route):
    router, config, _client, _natural, _played, notices, play = route
    router.run('PRIVATNA PORUKA', config, Playback(threading.Event(), play, notices.append))
    assert not router.cache.root.exists()
    assert not any(notice.cache_failed for notice in notices)


@pytest.mark.parametrize("started", [False, True])
def test_cached_output_failure_preserves_audio_without_another_paid_request(route, started):
    router, config, client, natural, _played, notices, play = route
    playback = Playback(threading.Event(), play, notices.append)
    router.run('SAČUVANA FRAZA.', config, playback)
    ticket = router.cache.ticket('SAČUVANA FRAZA.')
    audio = router.cache.read(ticket)

    def broken(_data, voice):
        return PlaybackResult(started=started, outcome="failed") if voice.cached else play(_data, voice)

    outcome = router.run(
        'SAČUVANA FRAZA.', config, Playback(threading.Event(), broken, notices.append)
    )
    assert outcome == ("failed" if started else "finished")
    assert router.cache.read(ticket) == audio
    assert len(client.calls) == 1
    assert natural == ([] if started else ['SAČUVANA FRAZA.'])
    assert router.gate.snapshot()[0] == ""
    client.error = VoiceError("offline")
    assert router.run('SAČUVANA FRAZA.', config, playback) == "finished"
    assert len(client.calls) == 1


@pytest.mark.parametrize("started", [False, True])
def test_unreadable_cached_media_is_discarded_without_repeating_partial_speech(route, started):
    router, config, client, natural, _played, notices, play = route
    ticket = router.cache.ticket('SAČUVANA FRAZA.')
    router.cache.write(ticket, b"unreadable media with valid checksum")

    def unreadable(data, voice):
        if voice.cached:
            return PlaybackResult(started=started, outcome="failed", invalid_audio=True)
        return play(data, voice)

    outcome = router.run(
        'SAČUVANA FRAZA.', config, Playback(threading.Event(), unreadable, notices.append)
    )
    assert outcome == ("failed" if started else "finished")
    assert len(client.calls) == (0 if started else 1)
    assert natural == []
    assert router.cache.read(ticket) == (None if started else client.audio)


@pytest.mark.parametrize("started", [False, True])
def test_stop_after_download_keeps_saved_audio_for_the_next_request(route, started):
    router, config, client, natural, _played, notices, play = route
    cancel = threading.Event()

    def stop(_data, _voice):
        cancel.set()
        return PlaybackResult(started=started, outcome="stopped")

    with pytest.raises(SpeechCancelled):
        router.run('SAČUVANA FRAZA.', config, Playback(cancel, stop, notices.append))
    assert notices == natural == []
    client.error = VoiceError("quota")
    assert router.run(
        'SAČUVANA FRAZA.', config, Playback(threading.Event(), play, notices.append)
    ) == "finished"
    assert len(client.calls) == 1
    assert natural == []


def test_unreadable_new_audio_is_not_saved(route):
    router, config, _client, _natural, _played, notices, play = route

    def unreadable(data, voice):
        if voice.voice == EFENDIJA:
            return PlaybackResult(outcome="failed", invalid_audio=True)
        return play(data, voice)

    assert router.run(
        'SAČUVANA FRAZA.', config, Playback(threading.Event(), unreadable, notices.append)
    ) == "finished"
    assert router.cache.read(router.cache.ticket('SAČUVANA FRAZA.')) is None


@pytest.mark.parametrize("change", ["clear", "delete", "disable", "voice"])
def test_stop_cannot_restore_audio_invalidated_during_playback(route, change):
    router, config, _client, _natural, _played, notices, _play = route
    cancel = threading.Event()

    def stop(_data, _voice):
        if change == "clear":
            router.cache.clear()
        else:
            identity = "another voice" if change == "voice" else config.audio_identity
            texts = {'SAČUVANA FRAZA.'}
            if change == "disable":
                texts = None
            elif change == "delete":
                texts = set()
            router.cache.configure(identity, texts)
        cancel.set()
        return PlaybackResult(started=True, outcome="stopped")

    with pytest.raises(SpeechCancelled):
        router.run('SAČUVANA FRAZA.', config, Playback(cancel, stop, notices.append))
    assert list(router.cache.root.glob("*.audio")) == []
    assert notices == []


@pytest.mark.parametrize("provider", [EFENDIJA, NATURAL])
def test_partial_playback_never_repeats_message_on_another_provider(route, provider):
    router, config, client, natural, _played, notices, _play = route
    if provider == NATURAL:
        client.error = VoiceError("offline")
    calls = []

    def broken(_data, voice):
        calls.append(voice.voice)
        return PlaybackResult(started=True, outcome="failed")

    assert router.run('PORUKA', config, Playback(threading.Event(), broken, notices.append)) == "failed"
    assert calls == [provider]
    assert notices[-1].partial
    assert natural == (["PORUKA"] if provider == NATURAL else [])


def test_audio_error_before_playback_can_fall_back(route):
    router, config, _client, _natural, _played, notices, _play = route
    calls = []

    def play(_data, voice):
        calls.append(voice.voice)
        return PlaybackResult(
            started=voice.voice == NATURAL,
            outcome="failed" if voice.voice == EFENDIJA else "finished",
        )

    assert router.run('PORUKA', config, Playback(threading.Event(), play, notices.append)) == "finished"
    assert calls == [EFENDIJA, NATURAL]


def test_quota_cooldown_skips_paid_requests_then_retries_user_message(route):
    router, config, client, natural, played, notices, play = route
    client.error = VoiceError("quota")
    client.balance = Subscription(100, 100, 2000000000)
    router.run('PORUKA', config, Playback(threading.Event(), play, notices.append))
    retry_at = router.gate.retry_at
    client.error = None
    router.run('DRUGA PORUKA', config, Playback(threading.Event(), play, notices.append))
    assert len(client.calls) == 1
    assert router.gate.retry_at == retry_at
    router.gate.retry_at = 0
    router.run('TREĆA PORUKA', config, Playback(threading.Event(), play, notices.append))
    assert len(client.calls) == 2
    assert natural == ["PORUKA", "DRUGA PORUKA"]
    assert played[-1][1].voice == EFENDIJA
    assert notices[-1].recovered
    assert router.gate.reason == ""


def test_free_check_allows_retry_but_does_not_claim_audio_recovery(route):
    router, config, client, _natural, _played, notices, play = route
    client.error = VoiceError("invalid_key")
    router.run('PORUKA', config, Playback(threading.Event(), play, notices.append))
    router.gate.checked(config, client.balance)
    assert router.gate.reason == "invalid_key"
    assert router.gate.retry_at == 0
    assert not any(notice.recovered for notice in notices)


def test_cached_clip_does_not_claim_online_recovery(route):
    router, config, client, _natural, played, notices, play = route
    router.run('SAČUVANA FRAZA.', config, Playback(threading.Event(), play, notices.append))
    router.gate.failure(config, "offline", None)
    notices.clear()
    client.error = VoiceError("offline")
    router.run('SAČUVANA FRAZA.', config, Playback(threading.Event(), play, notices.append))
    assert played[-1][1].cached
    assert router.gate.reason == "offline"
    assert not any(notice.recovered for notice in notices)


def test_explicit_voice_test_never_passes_using_cache_or_fallback(route):
    router, config, client, natural, played, notices, play = route
    router.cache.write(router.cache.ticket("SAČUVANA FRAZA."), b"old audio")
    client.error = VoiceError("quota")
    with pytest.raises(VoiceError, match="quota"):
        router.run('SAČUVANA FRAZA.', config, Playback(threading.Event(), play, notices.append), test=True)
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
        router.run('SAČUVANA FRAZA.', config, Playback(cancel, play, notices.append))
    assert played == natural == notices == []
    assert list(router.cache.root.glob("*.audio")) == []


def test_confirmed_quota_error_falls_back_without_waiting_for_another_http_call(route):
    router, config, client, natural, _played, notices, play = route
    client.error = VoiceError("quota")

    def unexpected_check(*_args):
        pytest.fail("A confirmed error must fall back immediately")

    client.subscription = unexpected_check
    assert router.run('PORUKA', config, Playback(threading.Event(), play, notices.append)) == "finished"
    assert natural == ["PORUKA"]


def test_disk_failure_warns_without_turning_successful_speech_into_failure(route):
    router, config, _client, _natural, _played, notices, play = route
    router.cache.root.write_bytes(b"not a directory")
    router.gate.failure(config, "offline", None)
    router.gate.retry_at = 0
    assert (
        router.run('SAČUVANA FRAZA.', config, Playback(threading.Event(), play, notices.append)) == "finished"
    )
    assert notices[-1].cache_failed
    assert notices[-1].notice == (
        "warning", "Zvuk nije sačuvan.", "Ponavljanje može trošiti kredite."
    )
    assert not notices[-1].recovered
    assert router.gate.snapshot()[0] == ""


def test_stale_cache_ticket_does_not_report_a_storage_failure(route):
    router, config, _client, _natural, _played, notices, play = route

    def clear_and_play(data, voice):
        router.cache.clear()
        return play(data, voice)

    assert router.run(
        'SAČUVANA FRAZA.', config, Playback(threading.Event(), clear_and_play, notices.append)
    ) == "finished"
    assert not notices[-1].cache_failed
    assert list(router.cache.root.glob("*.audio")) == []


def test_quota_recovers_without_optional_subscription_permission(route):
    router, config, client, natural, played, notices, play = route
    client.error = VoiceError("quota")
    router.run('PORUKA', config, Playback(threading.Event(), play, notices.append))
    client.error = None

    def denied(*_args):
        raise VoiceError("permission")

    client.subscription = denied
    router.run('DRUGA PORUKA', config, Playback(threading.Event(), play, notices.append))
    assert len(client.calls) == 1
    router.gate.retry_at = 0
    router.run('TREĆA PORUKA', config, Playback(threading.Event(), play, notices.append))
    assert len(client.calls) == 2
    assert natural == ["PORUKA", "DRUGA PORUKA"]
    assert played[-1][1].voice == EFENDIJA
    assert notices[-1].recovered


def test_key_quota_can_recover_with_unchanged_positive_account_balance(route):
    router, config, client, _natural, played, notices, play = route
    client.balance = Subscription(10, 100, None)
    router.gate.failure(config, "quota", client.balance)
    router.gate.retry_at = 0
    router.run('PORUKA', config, Playback(threading.Event(), play, notices.append))
    assert len(client.calls) == 1
    assert played[-1][1].voice == EFENDIJA
    assert notices[-1].recovered


@pytest.mark.parametrize("reason", ["busy", "too_long"])
def test_request_failure_does_not_cool_down_healthy_voice(route, reason):
    router, config, client, _natural, _played, notices, play = route
    client.error = VoiceError(reason)
    router.run('PORUKA', config, Playback(threading.Event(), play, notices.append))
    assert router.gate.snapshot()[0] == ""
    client.error = None
    router.run('KRATKO', config, Playback(threading.Event(), play, notices.append))
    assert len(client.calls) == 2


@pytest.mark.parametrize("reason", ["timeout", "offline", "permission"])
def test_optional_balance_failure_cannot_block_quota_recovery(route, reason):
    router, config, client, _natural, _played, notices, play = route
    router.gate.failure(config, "quota", Subscription(100, 100))
    router.gate.retry_at = 0

    def unavailable(*_):
        raise VoiceError(reason)

    client.subscription = unavailable
    router.run('PORUKA', config, Playback(threading.Event(), play, notices.append))
    assert len(client.calls) == 1
    assert notices[-1].recovered
