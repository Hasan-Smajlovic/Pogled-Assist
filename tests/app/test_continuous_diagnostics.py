"""Evidence must follow real timer boundaries, independent of destinations."""

from types import SimpleNamespace

import pytest

from pogled_assist import diagnostics
from pogled_assist.interaction.gaze_selection import GazeSelectionTimer


@pytest.fixture
def observations(monkeypatch):
    events = []
    writer = SimpleNamespace(
        _generation=1,
        observation_generation=1,
        trace=False,
        event=lambda name, data, **kw: events.append((name, data)),
    )
    monkeypatch.setattr(diagnostics, "diagnostic_writer", lambda: writer)
    return writer, events


@pytest.mark.parametrize("restart", [True, False])
def test_same_target_timer_reset_ends_the_old_attempt(observations, restart):
    _writer, events = observations
    timer = GazeSelectionTimer("toolbar")
    timer.update("speech", 0, pause_ms=250, dwell_ms=1000)
    timer.update("speech", 400, pause_ms=250, dwell_ms=1000)
    old = timer._observer.attempt
    if restart:
        timer.update("speech", 600, pause_ms=250, dwell_ms=1000, restart=True)
    else:
        timer.update(None, 410, pause_ms=250, dwell_ms=1000, can_hold=True, hold_ms=100)
        timer.update("speech", 550, pause_ms=250, dwell_ms=1000, can_hold=True, hold_ms=100)
    ends = [data for name, data in events if name == "selection_end"]
    assert len(ends) == 1
    assert ends[0]["attempt_id"] == old
    assert ends[0]["credited_ms_before_end"] == 400
    assert ends[0]["reason"] == ("restart" if restart else "edge_hold_expired")
    assert timer._observer.attempt != old


def test_basic_burst_keeps_all_terminal_reasons_before_queue_admission(observations):
    _writer, events = observations
    timer = GazeSelectionTimer("toolbar")
    for index in range(20):
        timer.update("speech", index * 10, pause_ms=250, dwell_ms=1000)
        timer.pause(reason="stale_gaze")
    assert len([1 for name, _ in events if name == "selection_end"]) == 20
    assert timer._observer._rates.counts["outcome:stale_gaze"] == 20


def test_completed_pause_transition_retains_attempt_and_records_discard(observations):
    _writer, events = observations
    timer = GazeSelectionTimer("toolbar")
    timer.update("speech", 0, pause_ms=250, dwell_ms=1000)
    timer.update("speech", 400, pause_ms=250, dwell_ms=1000)
    attempt = timer._observer.attempt
    timer.hold_tracking(500, 700)
    assert timer.retain_completed_pause()
    assert timer._observer.attempt == attempt
    assert not any(name == "selection_end" for name, _ in events)
    changes = [data for name, data in events if name == "selection_credit_discarded"]
    assert changes[-1]["discarded_ms"] == 150
    timer.pause(reason="tracking_hold_expired")
    outcomes = [data for name, data in events if name == "selection_hold_end"]
    assert outcomes[-1]["outcome"] == "expired"
    assert outcomes[-1]["attempt_id"] == attempt


def test_action_link_retains_origin_when_handler_replaces_context(observations):
    _writer, events = observations
    timer = GazeSelectionTimer("toolbar")
    context = diagnostics.TargetContext("speech")
    timer.set_diagnostic_context_getter(lambda _target: context)
    timer.update("speech_window:group:2", 0, pause_ms=100, dwell_ms=100)
    timer.update("speech_window:group:2", 200, pause_ms=100, dwell_ms=100)
    attempt = timer._observer.attempt
    timer.complete()
    diagnostics.invoke_action(
        lambda: setattr(timer._observer, "context", diagnostics.TargetContext("speech")),
        context=context,
        action="speech_window:group:2",
        source="gaze",
        selection=timer,
    )
    actions = [data for name, data in events if name.startswith("ui_action_")]
    assert len(actions) == 2
    assert actions[0]["action_id"] == actions[1]["action_id"]
    assert all(
        data["attempt_id"] == attempt and data["context_id"] == context.id for data in actions
    )
    assert all(data["role"] == "group" for data in actions)
    assert "group:2" not in str(events)


def test_manual_start_stop_does_not_split_an_ordinary_attempt(tmp_path, monkeypatch):
    from pogled_assist import logging_setup
    from pogled_assist.diagnostic_recording import recording_context
    from pogled_assist.log_transport import LogWriter

    writer = LogWriter()
    writer.start_segment(tmp_path / "logs/latest.txt", None, trace=False)
    monkeypatch.setattr(logging_setup, "_writer", writer)
    timer = GazeSelectionTimer("toolbar")
    try:
        timer.update("speech", 0, pause_ms=250, dwell_ms=1000)
        attempt = timer._observer.attempt
        writer.start_recording(
            tmp_path / "recordings", 1, recording_context({}, {}, simulated=True)
        )
        timer.update("speech", 400, pause_ms=250, dwell_ms=1000)
        assert timer._observer.attempt == attempt
        writer.stop_recording()
        timer.update("speech", 500, pause_ms=250, dwell_ms=1000)
        assert timer._observer.attempt == attempt
        timer.complete()
    finally:
        assert writer.stop()


def test_dropped_summary_keeps_cumulative_reason_counts_and_marks_missing_interval(monkeypatch):
    now = [0.0]
    events = []
    accepts = [False]
    writer = SimpleNamespace(
        _generation=1,
        trace=False,
        event=lambda name, data, **_kw: events.append((name, data)) or accepts[0],
    )
    monkeypatch.setattr(diagnostics, "diagnostic_writer", lambda: writer)
    monkeypatch.setattr(diagnostics, "time", SimpleNamespace(monotonic=lambda: now[0]))
    metrics = diagnostics.StreamMetrics(event_name="selection_summary")
    for _ in range(8):
        metrics.event("selection_end", reason="stale_gaze")
    now[0] = 1
    metrics.summary()
    accepts[0] = True
    for _ in range(3):
        metrics.event("selection_end", reason="stale_gaze")
    now[0] = 2
    metrics.summary()
    summary = events[-1][1]
    assert summary["counts"]["outcome:stale_gaze"] == 3
    assert summary["cumulative_counts"]["outcome:stale_gaze"] == 11
    assert summary["previous_intervals_dropped"] == 1
    assert summary["interval_index"] == 2
