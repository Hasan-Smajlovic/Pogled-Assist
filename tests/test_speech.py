from __future__ import annotations

import json
import os

import pytest

from gaze_mouse.speech_library import (
    CategoryRecord,
    PhraseRecord,
    SpeechLibrary,
    SpeechLibraryStore,
    default_categories,
    parse_phrase_record,
    sorted_phrases,
)
from gaze_mouse.speech_service import (
    EDGE_PLAYBACK_PITCH,
    EDGE_PLAYBACK_RATE,
    EDGE_PLAYBACK_VOICE,
    VOICE_PRESET_HUMAN_LIKE,
    SpeechService,
    SpeechSettings,
    _candidate_paths,
    _edge_playback_candidate_paths,
    _voice_output_mentions_bosnian,
)
from gaze_mouse.speech_window import _group_letters


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        (" 5  bs  M bosnian", True),
        ("Languages: Bosnian\n", True),
        ("en-us English", False),
        ("bsh unrelated", False),
    ],
)
def test_voice_output_detection(output, expected):
    assert _voice_output_mentions_bosnian(output) is expected


def test_executable_candidates_prefer_environment_and_remove_duplicates(monkeypatch, tmp_path):
    espeak = tmp_path / "espeak-ng.exe"
    edge = tmp_path / "edge-playback.exe"
    monkeypatch.setenv("ESPEAK_NG_EXE", str(espeak))
    monkeypatch.setenv("EDGE_PLAYBACK_EXE", str(edge))
    monkeypatch.setattr("gaze_mouse.speech_service.shutil.which", lambda _name: str(espeak))

    espeak_candidates = _candidate_paths()
    edge_candidates = _edge_playback_candidate_paths()

    assert espeak_candidates[0] == espeak
    assert espeak_candidates.count(espeak) == 1
    assert edge_candidates[0] == edge


def test_speech_service_builds_espeak_command(monkeypatch, tmp_path):
    executable = tmp_path / "espeak-ng.exe"
    monkeypatch.setattr("gaze_mouse.speech_service.find_espeak_ng", lambda: executable)
    monkeypatch.setattr("gaze_mouse.speech_service.find_edge_playback", lambda: None)
    service = SpeechService()
    calls = []
    monkeypatch.setattr(
        service, "_start_process", lambda command, engine: calls.append((command, engine)) or True
    )

    result = service.speak(
        "  Dobar dan  ", SpeechSettings(language="bs", speed=170, pitch=45, amplitude=130)
    )

    assert result is True
    assert calls == [
        (
            [str(executable), "-v", "bs", "-s", "170", "-p", "45", "-a", "130", "Dobar dan"],
            "espeak-ng",
        )
    ]


def test_speech_service_builds_human_voice_command(monkeypatch, tmp_path):
    executable = tmp_path / "edge-playback.exe"
    existing_path = str(tmp_path / "existing-bin")
    monkeypatch.setenv("PATH", existing_path)
    monkeypatch.setattr("gaze_mouse.speech_service.find_espeak_ng", lambda: None)
    monkeypatch.setattr("gaze_mouse.speech_service.find_edge_playback", lambda: executable)
    service = SpeechService()
    calls = []
    monkeypatch.setattr(
        service,
        "_start_process",
        lambda command, engine, **kwargs: calls.append((command, engine, kwargs)) or True,
    )

    result = service.speak("Zdravo", SpeechSettings(voice_preset=VOICE_PRESET_HUMAN_LIKE))

    assert result is True
    assert len(calls) == 1
    command, engine, kwargs = calls[0]
    assert command == [
        str(executable),
        "--voice",
        EDGE_PLAYBACK_VOICE,
        f"--rate={EDGE_PLAYBACK_RATE}",
        f"--pitch={EDGE_PLAYBACK_PITCH}",
        "--text",
        "Zdravo",
    ]
    assert engine == "edge-playback"
    environment = kwargs["environment"]
    path_key = next(key for key in environment if key.casefold() == "path")
    assert environment[path_key] == os.pathsep.join((str(executable.parent), existing_path))


def test_speech_service_rejects_empty_or_missing_engine(monkeypatch):
    monkeypatch.setattr("gaze_mouse.speech_service.find_espeak_ng", lambda: None)
    monkeypatch.setattr("gaze_mouse.speech_service.find_edge_playback", lambda: None)
    service = SpeechService()

    assert service.speak("   ") is False
    assert service.speak("Zdravo") is False
    assert service.speak("Zdravo", SpeechSettings(voice_preset=VOICE_PRESET_HUMAN_LIKE)) is False


def test_grouping_letters_splits_and_keeps_remainder():
    assert _group_letters(["A", "B", "C", "D", "E"], 2) == [["A", "B"], ["C", "D"], ["E"]]


def test_default_speech_categories_match_the_design_reference():
    categories = default_categories()

    assert [category.name for category in categories] == [
        "Trebam",
        "Brzi odgovor",
        "Kako se osjećam",
        "Ljudi",
    ]
    assert categories[0].answers == [
        "Trebam vode",
        "Namjesti mi jastuk",
        "Trebam lijek",
        "Pomozi mi da se okrenem",
        "Hladno mi je",
        "Trebam u toalet",
    ]
    assert all(len(category.answers) == 6 for category in categories)


def test_phrase_parsing_and_sorting_are_stable():
    assert parse_phrase_record({"phrase": "  Dobar   dan ", "count": "3"}) == ("Dobar dan", 3)
    assert parse_phrase_record({"text": "Test", "uses": -2}) == ("Test", 0)
    assert parse_phrase_record(None) == ("", 0)

    records = [PhraseRecord("Zdravo", 1), PhraseRecord("abc", 3), PhraseRecord("ABC", 2)]
    assert sorted_phrases(records) == [records[1], records[2], records[0]]


def test_speech_library_migrates_legacy_phrases_and_round_trips_utf8(tmp_path):
    path = tmp_path / "speech_phrases.json"
    path.write_text(
        json.dumps(
            [
                {"text": "Dobar dan", "uses": 1},
                {"phrase": "Dobar   dan", "count": 4},
                "Želim pomoć",
                {"text": "", "uses": 99},
            ]
        ),
        encoding="utf-8",
    )
    store = SpeechLibraryStore(path)

    loaded = store.load()

    assert loaded.categories == default_categories()
    assert loaded.phrases == [PhraseRecord("Dobar dan", 4), PhraseRecord("Želim pomoć", 0)]
    assert store.save(loaded) is True
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["version"] == 2
    assert saved["categories"][0] == {
        "name": "Trebam",
        "answers": [
            "Trebam vode",
            "Namjesti mi jastuk",
            "Trebam lijek",
            "Pomozi mi da se okrenem",
            "Hladno mi je",
            "Trebam u toalet",
        ],
    }
    assert saved["phrases"] == [
        {"text": "Dobar dan", "uses": 4},
        {"text": "Želim pomoć", "uses": 0},
    ]


def test_speech_library_preserves_saved_empty_categories_and_new_items(tmp_path):
    path = tmp_path / "speech_phrases.json"
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "categories": [
                    {"name": "Moje", "answers": ["Prvi odgovor", "prvi  odgovor", "Drugi"]},
                ],
                "phrases": [{"text": "Hvala", "uses": 2}],
            }
        ),
        encoding="utf-8",
    )
    store = SpeechLibraryStore(path)

    assert store.load() == SpeechLibrary(
        categories=[CategoryRecord("Moje", ["Prvi odgovor", "Drugi"])],
        phrases=[PhraseRecord("Hvala", 2)],
    )

    path.write_text(
        json.dumps({"version": 2, "categories": [], "phrases": []}),
        encoding="utf-8",
    )
    assert store.load() == SpeechLibrary()


def test_speech_library_load_recovers_from_bad_data_and_save_reports_failure(tmp_path):
    path = tmp_path / "speech_phrases.json"
    path.write_text("{", encoding="utf-8")
    assert SpeechLibraryStore(path).load() == SpeechLibrary(categories=default_categories())

    blocked_parent = tmp_path / "blocked"
    blocked_parent.write_text("not a directory", encoding="utf-8")
    assert SpeechLibraryStore(blocked_parent / "speech_phrases.json").save(SpeechLibrary()) is False
