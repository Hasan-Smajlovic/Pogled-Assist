from __future__ import annotations

import copy
from pathlib import Path

import pytest

from pogled_assist.speech.speech_library import (
    CategoryRecord,
    PhraseRecord,
    SpeechLibrary,
    SpeechLibraryStore,
)


@pytest.mark.parametrize("failed_file", ["primary", "legacy"])
def test_unreadable_library_cannot_be_overwritten_even_after_access_returns(
    tmp_path, monkeypatch, failed_file
):
    primary, legacy = tmp_path / "library.json", tmp_path / "phrases.json"
    original = SpeechLibrary(
        [CategoryRecord("Synthetic custom", ["Synthetic answer"])],
        [PhraseRecord("Synthetic phrase", 7)],
    )
    assert SpeechLibraryStore(primary, legacy_path=legacy).save(original)
    before = {path: path.read_bytes() for path in (primary, legacy)}
    target = primary if failed_file == "primary" else legacy
    read_text = Path.read_text

    def unavailable(path, *args, **kwargs):
        if path == target:
            raise PermissionError("Synthetic read failure")
        return read_text(path, *args, **kwargs)

    store = SpeechLibraryStore(primary, legacy_path=legacy)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", unavailable)
        fallback = store.load()
    assert store.read_error
    candidate = copy.deepcopy(fallback)
    candidate.phrases.append(PhraseRecord("Synthetic new entry"))
    assert not store.save(candidate)
    assert {path: path.read_bytes() for path in before} == before
    recovered = store.load()
    assert not store.read_error
    assert recovered == original
    recovered.phrases[0].uses += 1
    assert store.save(recovered)
    assert store.load().categories == original.categories


@pytest.mark.parametrize("content", ["{broken", "null", "42"])
def test_corrupt_primary_is_not_replaced_by_legacy_or_defaults(tmp_path, content):
    primary, legacy = tmp_path / "library.json", tmp_path / "phrases.json"
    primary.write_text(content, encoding="utf-8")
    legacy.write_text('[{"text":"Synthetic phrase","uses":2}]', encoding="utf-8")
    before = legacy.read_bytes()
    store = SpeechLibraryStore(primary, legacy_path=legacy)
    fallback = store.load()
    fallback.phrases[0].uses += 1
    assert not store.save(fallback)
    assert primary.read_text(encoding="utf-8") == content
    assert legacy.read_bytes() == before


def test_missing_primary_does_not_allow_overwriting_unreadable_legacy(tmp_path):
    primary, legacy = tmp_path / "library.json", tmp_path / "phrases.json"
    legacy.write_text("{broken", encoding="utf-8")
    store = SpeechLibraryStore(primary, legacy_path=legacy)
    fallback = store.load()
    assert store.read_error
    assert not store.save(fallback)
    assert not primary.exists()
    assert legacy.read_text(encoding="utf-8") == "{broken"
