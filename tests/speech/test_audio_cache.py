from __future__ import annotations

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
        config = ElevenConfig("key", "different" if change == "voice" else "voice",
                              "eleven_v4" if change == "model" else "eleven_v3")
        cache.configure(config.audio_identity, set() if change == "delete" else {"Hvala!"})
    assert not cache.write(ticket, b"late audio")
    assert cache.read(cache.ticket("Hvala!")) is None
    assert list(cache.root.glob("*.audio")) == []


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
