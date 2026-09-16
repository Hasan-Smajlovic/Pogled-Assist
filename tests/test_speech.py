from __future__ import annotations

import json

import pytest

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
from gaze_mouse.speech_window import (
    PhraseRecord,
    _grid_column_count,
    _group_letters,
    _load_phrases,
    _parse_phrase_record,
    _save_phrases,
    _sorted_phrase_records,
)


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
    monkeypatch.setattr("gaze_mouse.speech_service.find_espeak_ng", lambda: None)
    monkeypatch.setattr("gaze_mouse.speech_service.find_edge_playback", lambda: executable)
    service = SpeechService()
    calls = []
    monkeypatch.setattr(
        service, "_start_process", lambda command, engine: calls.append((command, engine)) or True
    )

    result = service.speak("Zdravo", SpeechSettings(voice_preset=VOICE_PRESET_HUMAN_LIKE))

    assert result is True
    assert calls == [
        (
            [
                str(executable),
                "--voice",
                EDGE_PLAYBACK_VOICE,
                f"--rate={EDGE_PLAYBACK_RATE}",
                f"--pitch={EDGE_PLAYBACK_PITCH}",
                "--text",
                "Zdravo",
            ],
            "edge-playback",
        )
    ]


def test_speech_service_rejects_empty_or_missing_engine(monkeypatch):
    monkeypatch.setattr("gaze_mouse.speech_service.find_espeak_ng", lambda: None)
    monkeypatch.setattr("gaze_mouse.speech_service.find_edge_playback", lambda: None)
    service = SpeechService()

    assert service.speak("   ") is False
    assert service.speak("Zdravo") is False
    assert service.speak("Zdravo", SpeechSettings(voice_preset=VOICE_PRESET_HUMAN_LIKE)) is False


def test_grouping_and_grid_columns_cover_short_and_long_layouts():
    assert _group_letters(["A", "B", "C", "D", "E"], 2) == [["A", "B"], ["C", "D"], ["E"]]
    assert _grid_column_count(0, max_columns=6, preferred_min_columns=3, max_rows=8) == 1
    assert _grid_column_count(4, max_columns=6, preferred_min_columns=3, max_rows=8) == 3
    assert _grid_column_count(30, max_columns=6, preferred_min_columns=3, max_rows=8) == 4


def test_phrase_parsing_and_sorting_are_stable():
    assert _parse_phrase_record({"phrase": "  Dobar   dan ", "count": "3"}) == ("Dobar dan", 3)
    assert _parse_phrase_record({"text": "Test", "uses": -2}) == ("Test", 0)
    assert _parse_phrase_record(None) == ("None", 0)

    records = [PhraseRecord("Zdravo", 1), PhraseRecord("abc", 3), PhraseRecord("ABC", 2)]
    assert _sorted_phrase_records(records) == [records[1], records[2], records[0]]


def test_phrase_storage_deduplicates_and_round_trips_utf8(monkeypatch, tmp_path):
    path = tmp_path / "speech_phrases.json"
    monkeypatch.setattr("gaze_mouse.speech_window._phrases_path", lambda: path)
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

    loaded = _load_phrases()

    assert loaded == [PhraseRecord("Dobar dan", 4), PhraseRecord("Želim pomoć", 0)]
    _save_phrases(loaded)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == [
        {"text": "Dobar dan", "uses": 4},
        {"text": "Želim pomoć", "uses": 0},
    ]


def test_phrase_load_handles_wrong_shape_and_bad_json(monkeypatch, tmp_path):
    path = tmp_path / "speech_phrases.json"
    monkeypatch.setattr("gaze_mouse.speech_window._phrases_path", lambda: path)
    path.write_text("{}", encoding="utf-8")
    assert _load_phrases() == []
    path.write_text("{", encoding="utf-8")
    assert _load_phrases() == []
