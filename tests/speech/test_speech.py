from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from pogled_assist.speech.alarm_sound import (
    ALARM_FREQUENCY_HZ,
    ALARM_TONE_DURATION_MS,
    ALARM_UNAVAILABLE_MESSAGE,
    AlarmSound,
)
from pogled_assist.speech.speech_library import (
    CategoryRecord,
    PhraseRecord,
    SpeechLibrary,
    SpeechLibraryStore,
    default_categories,
    parse_phrase_record,
    sorted_phrases,
)
from pogled_assist.speech.speech_service import (
    EDGE_PLAYBACK_PITCH,
    EDGE_PLAYBACK_RATE,
    EDGE_PLAYBACK_VOICE,
    VOICE_PRESET_HUMAN_LIKE,
    SpeechService,
    SpeechSettings,
    _application_root,
    _candidate_paths,
    _edge_playback_candidate_paths,
    _voice_output_mentions_bosnian,
)
from pogled_assist.tracking.tobii_stream_engine import APP_ROOT_ENV
from pogled_assist.ui.speech_window import _group_letters


def test_alarm_sound_repeats_in_background_until_stopped(qtbot):
    first_tone = threading.Event()
    calls = []

    def beep(frequency, duration):
        calls.append((frequency, duration))
        first_tone.set()

    alarm = AlarmSound(beep=beep)

    assert alarm.start() is True
    assert first_tone.wait(timeout=1)
    qtbot.waitUntil(lambda: alarm.is_playing)
    alarm.stop()

    assert calls[0] == (ALARM_FREQUENCY_HZ, ALARM_TONE_DURATION_MS)
    assert alarm.is_playing is False
    assert alarm.last_error is None


def test_alarm_sound_reports_playback_failure(qtbot):
    attempted = threading.Event()

    def failing_beep(_frequency, _duration):
        attempted.set()
        raise RuntimeError("audio device unavailable")

    alarm = AlarmSound(beep=failing_beep)

    assert alarm.start() is True
    assert attempted.wait(timeout=1)
    qtbot.waitUntil(lambda: alarm.last_error is not None)
    alarm.stop()

    assert alarm.is_playing is False
    assert alarm.last_error == ALARM_UNAVAILABLE_MESSAGE


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
    monkeypatch.setattr(
        "pogled_assist.speech.speech_service.shutil.which", lambda _name: str(espeak)
    )

    espeak_candidates = _candidate_paths()
    edge_candidates = _edge_playback_candidate_paths()

    assert espeak_candidates[0] == espeak
    assert espeak_candidates.count(espeak) == 1
    assert edge_candidates[0] == edge


def test_packaged_speech_candidates_use_the_installed_application_root(monkeypatch, tmp_path):
    espeak = tmp_path / "tools" / "espeak-ng" / "bin" / "espeak-ng.exe"
    edge = tmp_path / ".venv" / "Scripts" / "edge-playback.exe"
    espeak.parent.mkdir(parents=True)
    edge.parent.mkdir(parents=True)
    espeak.touch()
    edge.touch()
    monkeypatch.setenv(APP_ROOT_ENV, str(tmp_path))
    monkeypatch.delenv("ESPEAK_NG_EXE", raising=False)
    monkeypatch.delenv("EDGE_PLAYBACK_EXE", raising=False)
    monkeypatch.setattr("pogled_assist.speech.speech_service.shutil.which", lambda _name: None)

    assert _application_root() == tmp_path
    assert espeak in _candidate_paths()
    assert edge in _edge_playback_candidate_paths()


def test_speech_service_builds_espeak_command(monkeypatch, tmp_path):
    executable = tmp_path / "espeak-ng.exe"
    monkeypatch.setattr("pogled_assist.speech.speech_service.find_espeak_ng", lambda: executable)
    monkeypatch.setattr("pogled_assist.speech.speech_service.find_edge_playback", lambda: None)
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
    monkeypatch.setattr("pogled_assist.speech.speech_service.find_espeak_ng", lambda: None)
    monkeypatch.setattr(
        "pogled_assist.speech.speech_service.find_edge_playback", lambda: executable
    )
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
    monkeypatch.setattr("pogled_assist.speech.speech_service.find_espeak_ng", lambda: None)
    monkeypatch.setattr("pogled_assist.speech.speech_service.find_edge_playback", lambda: None)
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
    path = tmp_path / "speech_library.json"
    legacy_path = tmp_path / "speech_phrases.json"
    legacy_path.write_text(
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
    store = SpeechLibraryStore(path, legacy_path=legacy_path)

    loaded = store.load()

    assert loaded.categories == default_categories()
    assert loaded.phrases == [PhraseRecord("Dobar dan", 4), PhraseRecord("Želim pomoć", 0)]
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
    assert json.loads(legacy_path.read_text(encoding="utf-8")) == saved["phrases"]


def test_speech_library_migrates_current_v2_file_without_losing_categories(tmp_path):
    path = tmp_path / "speech_library.json"
    legacy_path = tmp_path / "speech_phrases.json"
    legacy_path.write_text(
        json.dumps(
            {
                "version": 2,
                "categories": [{"name": "Moje", "answers": ["Jedan", "Dva"]}],
                "phrases": [{"text": "Hvala", "uses": 3}],
            }
        ),
        encoding="utf-8",
    )
    store = SpeechLibraryStore(path, legacy_path=legacy_path)

    loaded = store.load()

    assert loaded == SpeechLibrary(
        categories=[CategoryRecord("Moje", ["Jedan", "Dva"])],
        phrases=[PhraseRecord("Hvala", 3)],
    )
    assert json.loads(path.read_text(encoding="utf-8"))["categories"] == [
        {"name": "Moje", "answers": ["Jedan", "Dva"]}
    ]
    assert json.loads(legacy_path.read_text(encoding="utf-8")) == [{"text": "Hvala", "uses": 3}]


def test_speech_library_imports_phrase_changes_made_during_rollback(tmp_path):
    path = tmp_path / "speech_library.json"
    legacy_path = tmp_path / "speech_phrases.json"
    store = SpeechLibraryStore(path, legacy_path=legacy_path)
    library = SpeechLibrary(
        categories=[CategoryRecord("Moje", ["Odgovor ostaje"])],
        phrases=[PhraseRecord("Prije rollbacka", 1)],
    )
    assert store.save(library) is True

    legacy_path.write_text(
        json.dumps([{"text": "Dodano u staroj verziji", "uses": 2}]),
        encoding="utf-8",
    )
    newer = path.stat().st_mtime_ns + 1_000_000_000
    os.utime(legacy_path, ns=(newer, newer))

    loaded = store.load()

    assert loaded.categories == [CategoryRecord("Moje", ["Odgovor ostaje"])]
    assert loaded.phrases == [PhraseRecord("Dodano u staroj verziji", 2)]
    assert json.loads(path.read_text(encoding="utf-8"))["phrases"] == [
        {"text": "Dodano u staroj verziji", "uses": 2}
    ]


def test_speech_library_imports_v2_rollback_phrases_without_losing_categories(tmp_path):
    path = tmp_path / "speech_library.json"
    legacy_path = tmp_path / "speech_phrases.json"
    store = SpeechLibraryStore(path, legacy_path=legacy_path)
    assert store.save(
        SpeechLibrary(
            categories=[CategoryRecord("Prije", ["Stari odgovor"])],
            phrases=[PhraseRecord("Stara fraza", 1)],
        )
    )

    rollback_store = SpeechLibraryStore(legacy_path)
    rollback_library = rollback_store.load()
    assert rollback_library.categories == default_categories()
    rollback_library.phrases = [PhraseRecord("Nova fraza", 4)]
    assert rollback_store.save(rollback_library)
    newer = path.stat().st_mtime_ns + 1_000_000_000
    os.utime(legacy_path, ns=(newer, newer))

    loaded = store.load()

    assert loaded == SpeechLibrary(
        categories=[CategoryRecord("Prije", ["Stari odgovor"])],
        phrases=[PhraseRecord("Nova fraza", 4)],
    )
    assert json.loads(path.read_text(encoding="utf-8"))["categories"] == [
        {"name": "Prije", "answers": ["Stari odgovor"]}
    ]
    assert json.loads(legacy_path.read_text(encoding="utf-8")) == [
        {"text": "Nova fraza", "uses": 4}
    ]


def test_speech_library_restores_both_files_when_legacy_write_fails(monkeypatch, tmp_path):
    path = tmp_path / "speech_library.json"
    legacy_path = tmp_path / "speech_phrases.json"
    store = SpeechLibraryStore(path, legacy_path=legacy_path)
    original = SpeechLibrary(
        categories=[CategoryRecord("Sačuvano", ["Odgovor"])],
        phrases=[PhraseRecord("Fraza", 1)],
    )
    assert store.save(original)
    original_path_content = path.read_bytes()
    original_legacy_content = legacy_path.read_bytes()
    replace = Path.replace

    def fail_legacy_replace(source, target):
        if source == legacy_path.with_suffix(legacy_path.suffix + ".tmp"):
            raise OSError("legacy file is locked")
        return replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_legacy_replace)

    assert store.save(SpeechLibrary(categories=[], phrases=[])) is False
    assert path.read_bytes() == original_path_content
    assert legacy_path.read_bytes() == original_legacy_content


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
