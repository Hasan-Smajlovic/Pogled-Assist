from types import SimpleNamespace

import pytest
from _clock import freeze_monotonic

from pogled_assist.interaction.mouse_controller import GazeSettings
from pogled_assist.tracking.gaze_check import FixationResult
from pogled_assist.tracking.gaze_check_report import GazeCheckReport, TrialRow
from pogled_assist.tracking.gaze_check_session import GazeCheckSession

TARGETS = (("Centar", 0.5, 0.5), ("Lijevo", 0.1, 0.5))


def test_precision_attempt_keeps_unmeasured_targets_and_freezes_context(monkeypatch):
    now = freeze_monotonic(monkeypatch, 10.0)
    settings = GazeSettings(eye_tracking_policy="any")
    session = GazeCheckSession(settings, TARGETS, simulated=True)
    settings.eye_tracking_policy = "both"
    session.begin()
    session.set_environment({"backend": "simulator", "typed_text": "private"})
    attempt_id = session.attempt_id
    now[0] = 12.0
    measurement = SimpleNamespace(
        targets=TARGETS,
        results=[FixationResult("Centar", 10, 0.8, 12, 8, True, (0.5, 0.5))],
    )
    report = session.finish_precision(measurement, None, "window_closed")
    assert report.id == attempt_id
    assert report.duration_seconds == 2.0
    assert report.state == "interrupted"
    assert report.reason == "window_closed"
    assert report.simulated
    assert report.settings["eye_tracking_policy"] == "any"
    assert report.environment == {"backend": "simulator"}
    assert [row.state for row in report.precision] == ["measured", "unmeasured"]
    assert session.attempt_id is None
    session.environment["backend"] = "another backend"
    assert report.environment["backend"] == "simulator"
    assert GazeCheckReport.from_json(report.to_json()).to_json() == report.to_json()
    with pytest.raises(RuntimeError, match="already finished"):
        session.finish_precision(measurement, None)


def test_repeated_word_attempts_share_precision_and_keep_separate_context(monkeypatch):
    now = freeze_monotonic(monkeypatch, 10.0)
    session = GazeCheckSession(GazeSettings(), TARGETS)
    session.begin()
    precision = session.finish_precision(None, None)
    precision_id = precision.id
    attempt_ids = []
    for backend in ("first", "second"):
        session.begin()
        attempt_ids.append(session.attempt_id)
        session.set_environment({"backend": backend})
        now[0] += 1.0
        rows = [TrialRow(index, (100, 80)) for index in range(4)]
        report = session.finish_trial(rows, word="VODA", eyes=None)
        rows.clear()
        assert report is precision
        assert report.id == precision_id
    assert len(set([*attempt_ids, precision_id])) == 3
    assert [trial.id for trial in report.trials] == attempt_ids
    assert [trial.environment["backend"] for trial in report.trials] == ["first", "second"]
    assert all(len(trial.rows) == 4 for trial in report.trials)
    assert GazeCheckReport.from_json(report.to_json()).to_json() == report.to_json()


def test_word_attempt_without_precision_preserves_missing_measurements(monkeypatch):
    freeze_monotonic(monkeypatch, 10.0)
    session = GazeCheckSession(GazeSettings(), TARGETS)
    session.begin()
    report = session.finish_trial(
        [TrialRow(index, (100, 80)) for index in range(4)],
        word="VODA",
        eyes=None,
        reason="tracking_lost",
    )
    assert report.state == "interrupted"
    assert report.reason == "Preciznost nije pokrenuta"
    assert all(row.state == "unmeasured" for row in report.precision)
    assert report.trials[0].reason == "tracking_lost"
    assert GazeCheckReport.from_json(report.to_json()).to_json() == report.to_json()
