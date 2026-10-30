from __future__ import annotations

import json
from dataclasses import replace
from zipfile import ZipFile

import pytest

from pogled_assist.tracking.gaze_check_report import (
    SCHEMA_VERSION,
    EyeTrackingSummary,
    GazeCheckReport,
    PrecisionRow,
    TrialAttempt,
    TrialRow,
    identity,
    report_text,
)
from pogled_assist.tracking.gaze_check_store import GazeCheckStore


def report():
    return GazeCheckReport(
        identity(),
        "2026-10-22T12:00:00+02:00",
        "2026-10-22T12:00:15+02:00",
        15,
        "completed",
        None,
        True,
        {"eye_tracking_policy": "any", "selection_pause_ms": 250, "dwell_ms": 850},
        {
            "app_version": "0.4.0",
            "backend": "mouse-simulation",
            "logical_screen": [-100, 20, 1280, 720],
        },
        [
            PrecisionRow("Sredina", (0.5, 0.5), "measured", 90, 0.9, 12, 8, True, (0.51, 0.5)),
            PrecisionRow("Gore lijevo", (0.04, 0.06)),
        ],
    )


def test_report_survives_restart_and_zip_matches_saved_aggregates(tmp_path):
    store = GazeCheckStore(tmp_path / "reports")
    original = report()
    original.trials.append(
        TrialAttempt(
            identity(),
            original.started_at,
            original.ended_at,
            4,
            "interrupted",
            "Zatvorena provjera",
            [
                TrialRow(0, (136, 64), "insufficient", False, 0.1, 2, 1, 2, 3),
                TrialRow(1, (96, 88)),
                TrialRow(2, (180, 72)),
            ],
            {"sdk_version": None},
        )
    )
    store.save(original)
    loaded = GazeCheckStore(store.directory).load()[0].report
    assert loaded.to_json() == original.to_json()
    destination = tmp_path / "manual.zip"
    store.export(loaded, destination)
    with ZipFile(destination) as archive:
        assert set(archive.namelist()) == {"rezultat.json", "izvjestaj.txt"}
        assert archive.read("rezultat.json") == original.to_json()
        text = archive.read("izvjestaj.txt").decode("utf-8")
    for expected in (
        f"ID: {original.id}",
        "Stanje: Završeno",
        "Simulacija: Da",
        "Sredina: Izmjereno",
        "Uzorci: 90; pokrivenost (0-1): 0.9",
        "Odstupanje (medijan px): 12; rasipanje (p90 px): 8; blizu: Da",
        "Gore lijevo: Nije izmjereno",
        f"PROBNI IZBOR · {original.trials[0].id} · Prekinuto",
        "Grupa 1: Premalo podataka",
        "Pogrešni: 1; poništeni: 2; izlasci: 3",
        "selection_pause_ms: 250",
        "dwell_ms: 850",
        "backend: mouse-simulation",
    ):
        assert expected in text


def test_failed_atomic_save_and_export_keep_existing_files_and_clean_temp(tmp_path, monkeypatch):
    from pogled_assist.tracking import gaze_check_store as module

    store = GazeCheckStore(tmp_path)
    value = report()
    store.save(value)
    saved = next(tmp_path.glob("*.json"))
    before = saved.read_bytes()
    destination = tmp_path / "manual.zip"
    destination.write_bytes(b"existing export")

    def fail(*_args):
        raise OSError("Synthetic rename failure")

    monkeypatch.setattr(module.os, "replace", fail)
    value.reason = "Synthetic newer data"
    with pytest.raises(OSError):
        store.save(value)
    with pytest.raises(OSError):
        store.export(value, destination)
    assert saved.read_bytes() == before
    assert destination.read_bytes() == b"existing export"
    assert set(path.name for path in tmp_path.iterdir()) == {saved.name, destination.name}


@pytest.mark.parametrize("count_limit,byte_limit", [(2, 10 * 1024 * 1024), (100, 2500)])
def test_retention_removes_oldest_only_after_success_and_preserves_other_files(
    tmp_path, monkeypatch, count_limit, byte_limit
):
    from pogled_assist.tracking import gaze_check_store as module

    monkeypatch.setattr(module, "MAX_REPORTS", count_limit)
    monkeypatch.setattr(module, "MAX_TOTAL_BYTES", byte_limit)
    store = GazeCheckStore(tmp_path)
    unrelated = tmp_path / "notes.json"
    unrelated.write_text("keep")
    bad = tmp_path / f"gaze-check-{identity()}.json"
    bad.write_text('{"schema_version": 999}')
    archive = tmp_path / "manual.zip"
    archive.write_bytes(b"keep")
    ids = []
    for day in (20, 21, 22):
        value = replace(report(), started_at=f"2026-10-{day}T12:00:00+02:00")
        ids.append(value.id)
        store.save(value)
    entries = [entry.report for entry in store.load() if entry.report]
    assert entries[0].id == ids[-1]
    assert len(entries) <= count_limit
    assert sum(len(entry.to_json()) for entry in entries) <= byte_limit
    assert ids[0] not in {entry.id for entry in entries}
    assert unrelated.read_text() == "keep" and archive.read_bytes() == b"keep"
    assert bad.exists()


@pytest.mark.parametrize(
    "mutation",
    ["version", "private", "nonfinite", "shape", "trial-private", "policy-list", "model-list"],
)
def test_unreadable_reports_stay_on_disk_and_load_as_errors(tmp_path, mutation):
    value = report()
    data = json.loads(value.to_json())
    if mutation == "version":
        data["schema_version"] = 999
    elif mutation == "private":
        data["environment"]["api_key"] = "synthetic-secret"
    elif mutation == "nonfinite":
        data["precision"][0]["coverage"] = float("nan")
    elif mutation == "shape":
        data["precision"][0] = {"name": []}
    elif mutation == "policy-list":
        data["settings"]["eye_tracking_policy"] = [0, 0, 0, 0]
    elif mutation == "model-list":
        data["environment"]["model"] = [0, 0, 0, 0]
    else:
        data["trials"] = [
            {
                "id": identity(),
                "started_at": value.started_at,
                "ended_at": value.ended_at,
                "duration_seconds": 1,
                "state": "completed",
                "reason": None,
                "rows": [],
                "environment": {"message": "Synthetic private text"},
            }
        ]
    path = tmp_path / f"gaze-check-{value.id}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    entry = GazeCheckStore(tmp_path).load()[0]
    assert entry.report is None and entry.error
    assert path.exists()


def test_more_than_100_trials_and_large_reports_remain_exportable(tmp_path, monkeypatch):
    from pogled_assist.tracking import gaze_check_store as module

    value = report()
    for _index in range(150):
        value.trials.append(
            TrialAttempt(
                identity(),
                value.started_at,
                value.ended_at,
                1,
                "completed",
                None,
                [TrialRow(i, (136, 64), "measured", True, 0.9, 1) for i in range(3)],
            )
        )
    assert len(value.to_json()) > 128 * 1024
    store = GazeCheckStore(tmp_path / "automatic")
    store.save(value)
    assert len(store.load()[0].report.trials) == 150
    monkeypatch.setattr(module, "MAX_TOTAL_BYTES", 1024)
    saved = store.directory / f"gaze-check-{value.id}.json"
    before = saved.read_bytes()
    with pytest.raises(ValueError):
        store.save(value)
    assert saved.read_bytes() == before
    destination = tmp_path / "all-attempts.zip"
    store.export(value, destination)
    with ZipFile(destination) as archive:
        assert len(json.loads(archive.read("rezultat.json"))["trials"]) == 150


@pytest.mark.parametrize(
    "counter,invalid",
    [
        ("wrong_selections", None),
        ("wrong_selections", -1),
        ("wrong_selections", 0.5),
        ("wrong_selections", True),
        ("wrong_selections", "0"),
        ("cancelled_selections", -1),
        ("departures", -1),
    ],
)
def test_corrupt_trial_counters_are_unreadable_instead_of_breaking_result_view(
    tmp_path, counter, invalid
):
    value = report()
    value.trials.append(
        TrialAttempt(
            identity(),
            value.started_at,
            value.ended_at,
            1,
            "completed",
            None,
            [TrialRow(index, (136, 64), "measured", True, 0.9, 1) for index in range(3)],
        )
    )
    data = json.loads(value.to_json())
    data["trials"][0]["rows"][0][counter] = invalid
    path = tmp_path / f"gaze-check-{value.id}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    entry = GazeCheckStore(tmp_path).load()[0]
    assert entry.report is None
    assert entry.error
    assert path.exists()


def word_report():
    value = report()
    value.precision_eyes = EyeTrackingSummary(15.2, 0.98, 0.97, 0.96, 2, 0.4)
    value.trials.append(
        TrialAttempt(
            identity(),
            value.started_at,
            value.ended_at,
            12,
            "completed",
            None,
            [TrialRow(index, (140, 120), "measured", True, 0.9, 1) for index in range(4)],
            word="VODA",
            eyes=EyeTrackingSummary(11.8, 0.99, 0.5, 0.5, 1, 0.0, True, 300, 0.95, 12.5),
        )
    )
    return value


def test_word_test_and_per_test_eye_tracking_survive_restart_and_export(tmp_path):
    store = GazeCheckStore(tmp_path / "reports")
    original = word_report()
    store.save(original)
    loaded = GazeCheckStore(store.directory).load()[0].report
    assert loaded.to_json() == original.to_json()
    assert json.loads(loaded.to_json())["schema_version"] == SCHEMA_VERSION == 2
    assert loaded.precision_eyes == original.precision_eyes
    assert loaded.trials[0].eyes == original.trials[0].eyes
    destination = tmp_path / "word.zip"
    store.export(loaded, destination)
    with ZipFile(destination) as archive:
        text = archive.read("izvjestaj.txt").decode("utf-8")
    for expected in (
        f"TEST RIJEČI · VODA · {original.trials[0].id} · Završeno",
        "Slovo 2 (O): Izmjereno",
        "Praćenje po oku (0-1) · lijevo: 0.980; desno: 0.970; oba: 0.960; izmjereno: 15.200 s",
        "Prekidi praćenja: 2; najduži: 0.400 s",
        "Prekidi praćenja: 1; najduži: 0.000 s",
        "Isto mjesto · podržano: Da; parovi: 300; unutar praga (0-1): 0.95",
    ):
        assert expected in text


def test_version_1_report_without_eye_tracking_still_loads(tmp_path):
    report_with_rows = report()
    report_with_rows.trials.append(
        TrialAttempt(
            identity(),
            report_with_rows.started_at,
            report_with_rows.ended_at,
            4,
            "completed",
            None,
            [TrialRow(index, (136, 64)) for index in range(3)],
        )
    )
    data = json.loads(report().to_json())
    data["schema_version"] = 1
    del data["precision_eyes"]
    data["trials"] = [
        {
            "id": identity(),
            "started_at": data["started_at"],
            "ended_at": data["ended_at"],
            "duration_seconds": 4,
            "state": "completed",
            "reason": None,
            "rows": json.loads(report_with_rows.to_json())["trials"][0]["rows"],
            "environment": {},
        }
    ]
    path = tmp_path / f"gaze-check-{data['id']}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    loaded = GazeCheckStore(tmp_path).load()[0].report
    assert loaded is not None
    assert loaded.precision_eyes is None
    assert (loaded.trials[0].word, loaded.trials[0].eyes) == (None, None)
    assert "Praćenje po oku: Nije dostupno" in report_text(loaded)


@pytest.mark.parametrize(
    "mutation", ["lowercase-word", "row-count", "negative-interruptions", "fraction", "agreement"]
)
def test_invalid_word_or_eye_tracking_values_are_unreadable(tmp_path, mutation):
    data = json.loads(word_report().to_json())
    trial = data["trials"][0]
    if mutation == "lowercase-word":
        trial["word"] = "voda"
    elif mutation == "row-count":
        trial["rows"].pop()
    elif mutation == "negative-interruptions":
        data["precision_eyes"]["interruptions"] = -1
    elif mutation == "fraction":
        trial["eyes"]["left"] = 1.5
    else:
        trial["eyes"]["agreement_supported"] = "yes"
    path = tmp_path / f"gaze-check-{data['id']}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    entry = GazeCheckStore(tmp_path).load()[0]
    assert entry.report is None and entry.error
    assert path.exists()
