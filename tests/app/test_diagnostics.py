from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from pogled_assist import diagnostics
from pogled_assist.log_reader import summarize


def test_native_state_expires_without_extending_a_silent_valid_tail(monkeypatch):
    now = [10.0]
    events = []
    writer = SimpleNamespace(
        _generation=1, trace=False, event=lambda name, data, **_kwargs: events.append((name, data))
    )
    monkeypatch.setattr(diagnostics, "diagnostic_writer", lambda: writer)
    monkeypatch.setattr(diagnostics.time, "monotonic", lambda: now[0])
    metrics = diagnostics.StreamMetrics()
    metrics.eyes("native", "both_valid", sampled=True, stale_after=0.5)
    metrics.eyes("application_gate", "open", sampled=True, stale_after=None)
    now[0] = 12
    metrics.summary(generation=1, backend="fake")
    summary = events[-1][1]
    assert summary["interval_s"] == 2
    assert summary["eye_state_seconds"]["native:both_valid"] == pytest.approx(0.5)
    assert summary["eye_state_seconds"]["native:stale_unknown"] == pytest.approx(1.5)
    assert summary["eye_state_seconds"]["application_gate:open"] == 2


def test_rate_limited_event_counts_are_visible_and_reset_on_segment(monkeypatch):
    now = [10.0]
    events = []
    writer = SimpleNamespace(
        _generation=1, trace=False, event=lambda name, data, **_kwargs: events.append((name, data))
    )
    monkeypatch.setattr(diagnostics, "diagnostic_writer", lambda: writer)
    monkeypatch.setattr(diagnostics.time, "monotonic", lambda: now[0])
    metrics = diagnostics.StreamMetrics()
    for _ in range(40):
        metrics.event("eye_gate_received")
    now[0] = 11
    metrics.summary(generation=1, backend="fake")
    assert len([name for name, _ in events if name == "eye_gate_received"]) == 4
    assert events[-1][1]["counts"]["suppressed:eye_gate_received"] == 36
    writer._generation += 1
    metrics.count("new_segment")
    now[0] = 12
    metrics.summary(generation=2, backend="fake")
    assert events[-1][1]["counts"] == {"new_segment": 1}


def test_content_targets_use_context_local_ids_and_never_labels():
    first = diagnostics.TargetContext("letter")
    second = diagnostics.TargetContext("letter")
    action = "speech_window:letter:4:2"
    assert first.token(action) == first.token(action)
    assert first.token(action) != second.token(action)
    assert action not in first.token(action)
    assert diagnostics.safe_action(action) == "content_target"
    assert first.token("speech_window:confirm:accept") == "confirm:accept"


def test_observer_failure_does_not_change_selection_results_or_repeat_lock(monkeypatch):
    from pogled_assist.interaction.gaze_selection import GazeSelectionTimer

    failures = []

    def fail(*_args, **_kwargs):
        raise RuntimeError("broken diagnostic observer")

    timer = GazeSelectionTimer("toolbar")
    monkeypatch.setattr(timer._observer, "observe", fail)
    monkeypatch.setattr(diagnostics, "observation_failed", lambda: failures.append(True))
    timer.update("clear", 0, pause_ms=500, dwell_ms=1600)
    update = timer.update("clear", 2100, pause_ms=500, dwell_ms=1600)
    assert update.ready
    timer.complete()
    assert timer.is_blocked
    timer.pause(reason="eye_loss")
    assert timer.is_blocked
    timer.cancel()
    assert not timer.is_blocked
    assert len(failures) == 5


def test_selection_observer_keeps_elapsed_time_separate_and_restarts_with_logging(monkeypatch):
    now = [10.0]
    events = []
    writer = SimpleNamespace(
        _generation=1, trace=False, event=lambda name, data, **_kwargs: events.append((name, data))
    )
    monkeypatch.setattr(diagnostics, "diagnostic_writer", lambda: writer)
    monkeypatch.setattr(diagnostics.time, "monotonic", lambda: now[0])
    observer = diagnostics.SelectionObserver("toolbar")
    active = {
        "target": "clear",
        "active": True,
        "blocked": False,
        "held": False,
        "credited_ms": 100,
    }
    observer.observe(active, reason="sample", pause_ms=500, dwell_ms=1600)
    attempt = observer.attempt
    now[0] = 12
    observer.observe(
        {**active, "target": None, "active": False, "credited_ms": 0}, reason="eye_gate_closed"
    )
    end = next(data for name, data in events if name == "selection_end")
    assert end["credited_ms_before_end"] == 100
    assert end["elapsed_ms"] == 2000
    now[0] = 13
    observer.observe(active, reason="sample")
    attempt = observer.attempt
    writer._generation += 1
    observer.observe(active, reason="sample")
    assert observer.attempt != attempt


def test_offline_reader_marks_partial_line_and_missing_end(tmp_path):
    path = tmp_path / "session.jsonl"
    item = {"schema_version": 1, "session_id": "fake", "event": "session_start", "data": {}}
    path.write_text(json.dumps(item) + '\n{"partial":', encoding="utf-8")
    result = summarize(path)
    assert result["session_start_present"]
    assert not result["session_end_present"]
    assert not result["complete"]
    assert result["parse_warnings"] == [{"line": 2, "reason": "partial_last_line"}]


def test_offline_reader_does_not_sum_cumulative_writer_loss_twice(tmp_path):
    path = tmp_path / "session.jsonl"
    records = [
        {
            "schema_version": 1,
            "session_id": "fake",
            "event": name,
            "data": {},
            "logging_health": {"dropped": {"event": 3}},
        }
        for name in ("session_start", "ui_heartbeat", "session_end")
    ]
    path.write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")
    result = summarize(path)
    assert result["lifecycle_complete"]
    assert not result["complete"]
    assert result["logging_health_process_cumulative"]["dropped"]["event"] == 3


def test_application_gate_duration_waits_for_the_qt_delivery(monkeypatch, qtbot):
    import threading

    from pogled_assist.tracking.gaze_provider import TobiiGazeProvider

    writer = SimpleNamespace(_generation=1, trace=False, event=lambda *_args, **_kwargs: None)
    monkeypatch.setattr(diagnostics, "diagnostic_writer", lambda: writer)
    provider = TobiiGazeProvider()
    _gaze, eyes = provider._new_stream_callbacks()
    eyes(True, True, 1)
    assert provider._delivered_eye_status == (True, True)
    worker = threading.Thread(target=lambda: eyes(False, True, 2))
    worker.start()
    worker.join(1)
    assert not worker.is_alive()
    assert provider._last_eye_status == (False, True)
    assert provider._delivered_eye_status == (True, True)
    assert provider._metrics._states["application_gate"][0] == "open"
    provider._flush_eye_status()
    assert provider._delivered_eye_status == (False, True)
    assert provider._metrics._states["application_gate"][0] == "closed"
    provider.stop()
