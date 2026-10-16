from __future__ import annotations

import os

import pytest

from pogled_assist.speech.audio_cache import AudioCache, cache_root
from pogled_assist.speech.elevenlabs import ElevenConfig


@pytest.fixture
def cache(tmp_path):
    cache = AudioCache(tmp_path / "audio")
    cache.configure(ElevenConfig("key", "voice").audio_identity, {"Trebam vode.", "Hvala!", "Čaj"})
    return cache


def test_only_whole_saved_text_is_eligible_and_punctuation_and_diacritics_matter(cache):
    assert cache.ticket("  TREBAM   VODE. ")
    assert cache.ticket("HVALA!")
    assert cache.ticket("trebam vode") is None
    assert cache.ticket("Trebam vode. Hvala!") is None
    assert cache.ticket("Caj") is None
    assert cache.ticket("Slobodno napisana poruka") is None


def test_saved_audio_survives_restart_and_contains_no_plain_text_index(cache):
    ticket = cache.ticket("Trebam vode.")
    assert cache.write(ticket, b"audio")
    reopened = AudioCache(cache.root)
    reopened.configure(ElevenConfig("another-key", "voice").audio_identity, {"Trebam vode."})
    assert reopened.read(reopened.ticket("TREBAM VODE.")) == b"audio"
    assert len(list(cache.root.iterdir())) == 1
    for path in cache.root.iterdir():
        assert "Trebam" not in path.name
        assert b"Trebam" not in path.read_bytes()


@pytest.mark.parametrize("change", ["clear", "delete", "voice", "model"])
def test_inflight_audio_cannot_restore_cleared_or_invalidated_files(cache, change):
    ticket = cache.ticket("Hvala!")
    assert cache.write(ticket, b"old audio")
    if change == "clear":
        assert cache.clear()
    else:
        config = ElevenConfig(
            "key",
            "different" if change == "voice" else "voice",
            "eleven_v3" if change == "model" else "eleven_v4",
        )
        cache.configure(config.audio_identity, set() if change == "delete" else {"Hvala!"})
    assert not cache.write(ticket, b"late audio")
    assert cache.read(cache.ticket("Hvala!")) is None
    if change in ("clear", "delete"):
        assert list(cache.root.glob("*.audio")) == []
    else:
        assert len(list(cache.root.glob("*.audio"))) == 1


def test_corrupt_audio_is_a_cache_miss(cache):
    ticket = cache.ticket("Čaj")
    cache.write(ticket, b"complete audio")
    path = next(cache.root.glob("*.audio"))
    path.write_bytes(path.read_bytes()[:-1])
    assert cache.read(ticket) is None
    assert not path.exists()


def test_disk_failure_does_not_escape_or_create_plaintext_fallback(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_bytes(b"not a directory")
    cache = AudioCache(blocked)
    cache.configure("voice", {"Saved text"})
    assert not cache.write(cache.ticket("Saved text"), b"audio")
    assert cache.read(cache.ticket("Saved text")) is None


def test_cache_is_outside_installation_data_and_version_history(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "profile"))
    assert cache_root() == tmp_path / "profile" / "PogledAssist" / "speech-audio"


def test_tuning_round_trip_reuses_previous_audio(cache):
    from dataclasses import replace

    config = ElevenConfig("key", "voice")
    cache.write(cache.ticket("Hvala!"), b"natural stability")
    cache.configure(replace(config, stability=100).audio_identity, {"Hvala!"})
    assert cache.read(cache.ticket("Hvala!")) is None
    cache.configure(config.audio_identity, {"Hvala!"})
    assert cache.read(cache.ticket("Hvala!")) == b"natural stability"


def test_library_read_error_disables_tickets_without_removing_audio(cache):
    config = ElevenConfig("key", "voice")
    old = cache.ticket("Hvala!")
    cache.write(old, b"saved")
    cache.configure(config.audio_identity, None)
    assert cache.ticket("Hvala!") is None
    assert not cache.write(old, b"late")
    assert len(list(cache.root.glob("*.audio"))) == 1
    cache.configure(config.audio_identity, {"Hvala!"})
    assert cache.read(cache.ticket("Hvala!")) == b"saved"


def test_deleting_entry_removes_all_tuning_versions(cache):
    from dataclasses import replace

    config = ElevenConfig("key", "voice")
    cache.write(cache.ticket("Hvala!"), b"first")
    cache.configure(replace(config, stability=100).audio_identity, {"Hvala!"})
    cache.write(cache.ticket("Hvala!"), b"second")
    cache.configure(config.audio_identity, set())
    assert list(cache.root.glob("*.audio")) == []


def test_size_limit_removes_least_recently_used_audio_even_after_restart(cache, monkeypatch):
    first, second = (cache.ticket(text) for text in ("Trebam vode.", "Hvala!"))
    assert cache.write(first, b"first")
    assert cache.write(second, b"other")
    first_path = cache.root / (first[1] + ".audio")
    second_path = cache.root / (second[1] + ".audio")
    os.utime(first_path, ns=(1_000_000_000, 1_000_000_000))
    os.utime(second_path, ns=(2_000_000_000, 2_000_000_000))
    limit = 2 * first_path.stat().st_size
    monkeypatch.setattr("pogled_assist.speech.audio_cache.MAX_CACHE_BYTES", limit)
    assert cache.read(first) == b"first"
    reopened = AudioCache(cache.root)
    reopened.configure(ElevenConfig("key", "voice").audio_identity, {"Trebam vode.", "Hvala!", "Čaj"})
    assert reopened.write(reopened.ticket("Čaj"), b"third")
    assert reopened.read(reopened.ticket("Trebam vode.")) == b"first"
    assert reopened.read(reopened.ticket("Hvala!")) is None
    assert reopened.read(reopened.ticket("Čaj")) == b"third"
    assert sum(path.stat().st_size for path in cache.root.glob("*.audio")) <= limit


def test_recency_write_failure_does_not_prevent_cached_playback(cache, monkeypatch):
    ticket = cache.ticket("Hvala!")
    cache.write(ticket, b"saved")

    def denied(*_args):
        raise PermissionError("synthetic filesystem error")

    monkeypatch.setattr("pogled_assist.speech.audio_cache.os.utime", denied)
    assert cache.read(ticket) == b"saved"
    assert len(list(cache.root.glob("*.audio"))) == 1


def test_cache_write_distinguishes_stale_ticket_from_unavailable_storage(cache):
    ticket = cache.ticket("Hvala!")
    cache.clear()
    assert cache.write(ticket, b"late") is None
    assert cache.write(None, b"private") is None
    unavailable = AudioCache(None)
    unavailable.configure("voice", {"Hvala!"})
    assert unavailable.write(unavailable.ticket("Hvala!"), b"saved") is False
