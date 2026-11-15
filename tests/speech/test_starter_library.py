from __future__ import annotations

import json
import os
from pathlib import Path

from pogled_assist.speech.speech_library import CategoryRecord, PhraseRecord, SpeechLibraryStore


def test_new_library_contains_the_reviewed_categories_and_five_conversation_phrases(tmp_path):
    library = SpeechLibraryStore(tmp_path / "library.json").load()

    assert [category.name for category in library.categories] == [
        "Trebam",
        "Brzi odgovor",
        "Kako se osjećam",
        "Ljudi",
        "Selami i dove",
        "Namaz i ibadet",
        "Kur'an i čitanje",
    ]
    assert library.categories[3].answers[-2:] == ["Kako su naši?", "Prenesi im selam."]
    assert library.categories[4].answers == [
        "Selam alejkum.",
        "Alejkumu selam.",
        "Allah razi olsun.",
        "Neka vam Allah podari svako dobro.",
    ]
    assert library.categories[5].answers == [
        "Je li vrijeme za namaz?",
        "Želim klanjati.",
        "Pomozi mi da uzmem abdest.",
        "Okreni me prema kibli.",
    ]
    assert library.categories[6].answers == [
        "Želim slušati učenje Kur'ana.",
        "Pročitaj mi prijevod ovog ajeta.",
        "Otvori tefsir.",
        "Pročitaj mi još jednom.",
    ]
    assert library.phrases == [
        PhraseRecord("Drago mi je što ste došli."),
        PhraseRecord("Molim vas ponovite."),
        PhraseRecord("Molim vas sačekajte da napišem."),
        PhraseRecord("Nisam to htio reći."),
        PhraseRecord("Razgovarat ćemo kasnije."),
    ]


def write_old_library(path):
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "categories": [
                    {"name": "Moje", "answers": ["Moj odgovor"]},
                    {"name": "LJUDI", "answers": ["Moja porodica", "KAKO  SU NAŠI?"]},
                    {"name": "SELAMI I DOVE", "answers": ["SELAM ALEJKUM.", "Moj selam"]},
                ],
                "phrases": [
                    {"text": "Moja fraza", "uses": 11},
                    {"text": "MOLIM VAS PONOVITE.", "uses": 7},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_existing_library_is_extended_once_without_replacing_personal_content(tmp_path):
    primary, legacy = tmp_path / "library.json", tmp_path / "phrases.json"
    write_old_library(primary)
    store = SpeechLibraryStore(primary, legacy_path=legacy)

    library = store.load()

    assert [category.name for category in library.categories] == [
        "Moje",
        "LJUDI",
        "SELAMI I DOVE",
        "Namaz i ibadet",
        "Kur'an i čitanje",
    ]
    assert library.categories[0] == CategoryRecord("Moje", ["Moj odgovor"])
    assert library.categories[1].answers == ["Moja porodica", "KAKO SU NAŠI?", "Prenesi im selam."]
    assert library.categories[2].answers == [
        "SELAM ALEJKUM.",
        "Moj selam",
        "Alejkumu selam.",
        "Allah razi olsun.",
        "Neka vam Allah podari svako dobro.",
    ]
    assert library.phrases[:2] == [
        PhraseRecord("Moja fraza", 11),
        PhraseRecord("MOLIM VAS PONOVITE.", 7),
    ]
    assert [phrase.text for phrase in library.phrases[2:]] == [
        "Drago mi je što ste došli.",
        "Molim vas sačekajte da napišem.",
        "Nisam to htio reći.",
        "Razgovarat ćemo kasnije.",
    ]
    assert (
        json.loads(legacy.read_text(encoding="utf-8"))
        == json.loads(primary.read_text(encoding="utf-8"))["phrases"]
    )
    first_save = primary.read_bytes()
    assert SpeechLibraryStore(primary, legacy_path=legacy).load() == library
    assert primary.read_bytes() == first_save

    library.categories.pop()
    library.categories[1].answers.remove("Prenesi im selam.")
    library.phrases.pop()
    assert store.save(library)
    assert SpeechLibraryStore(primary, legacy_path=legacy).load() == library


def test_failed_starter_update_preserves_both_files_and_can_be_retried(tmp_path, monkeypatch):
    primary, legacy = tmp_path / "library.json", tmp_path / "phrases.json"
    write_old_library(primary)
    before = primary.read_bytes()
    replace = Path.replace

    def fail_legacy_replace(source, target):
        if target == legacy:
            raise PermissionError("Synthetic locked rollback file")
        return replace(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", fail_legacy_replace)
        SpeechLibraryStore(primary, legacy_path=legacy).load()
    assert primary.read_bytes() == before
    assert not legacy.exists()

    library = SpeechLibraryStore(primary, legacy_path=legacy).load()
    assert library.categories[-1].name == "Kur'an i čitanje"
    assert library.phrases[0] == PhraseRecord("Moja fraza", 11)
    assert SpeechLibraryStore(primary, legacy_path=legacy).load() == library


def test_content_update_does_not_recreate_removed_original_categories(tmp_path):
    primary = tmp_path / "library.json"
    primary.write_text('{"version":2,"categories":[],"phrases":[]}', encoding="utf-8")
    store = SpeechLibraryStore(primary)

    library = store.load()

    assert [category.name for category in library.categories] == [
        "Selami i dove",
        "Namaz i ibadet",
        "Kur'an i čitanje",
    ]
    assert library.phrases[0] == PhraseRecord("Drago mi je što ste došli.")
    assert store.load() == library


def test_newer_rollback_phrases_do_not_reset_a_saved_content_revision(tmp_path):
    primary, legacy = tmp_path / "library.json", tmp_path / "phrases.json"
    primary.write_text(
        json.dumps(
            {
                "version": 2,
                "starter_revision": 7,
                "categories": [{"name": "Moje", "answers": ["Moj odgovor"]}],
                "phrases": [{"text": "Prije", "uses": 5}],
            }
        ),
        encoding="utf-8",
    )
    legacy.write_text('[{"text":"Poslije","uses":8}]', encoding="utf-8")
    newer = primary.stat().st_mtime_ns + 1_000_000_000
    os.utime(legacy, ns=(newer, newer))
    store = SpeechLibraryStore(primary, legacy_path=legacy)

    library = store.load()

    assert library.categories == [CategoryRecord("Moje", ["Moj odgovor"])]
    assert library.phrases == [PhraseRecord("Poslije", 8)]
    assert json.loads(primary.read_text(encoding="utf-8"))["starter_revision"] == 7
    assert store.load() == library


def test_unreadable_rollback_file_blocks_the_content_update_until_reloaded(tmp_path):
    primary, legacy = tmp_path / "library.json", tmp_path / "phrases.json"
    write_old_library(primary)
    before = primary.read_bytes()
    legacy.write_text("{broken", encoding="utf-8")
    store = SpeechLibraryStore(primary, legacy_path=legacy)

    library = store.load()

    assert store.read_error
    assert library.categories[0] == CategoryRecord("Moje", ["Moj odgovor"])
    assert [category.name for category in library.categories] == ["Moje", "LJUDI", "SELAMI I DOVE"]
    assert primary.read_bytes() == before
    assert legacy.read_text(encoding="utf-8") == "{broken"
    assert not store.save(library)

    legacy.write_text(json.dumps(json.loads(before)["phrases"]), encoding="utf-8")
    recovered = store.load()
    assert not store.read_error
    assert recovered.categories[-1].name == "Kur'an i čitanje"
    assert recovered.phrases[0] == PhraseRecord("Moja fraza", 11)
    assert store.load() == recovered
