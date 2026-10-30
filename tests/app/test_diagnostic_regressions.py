"""Cross-destination regressions from the continuous diagnostics review."""

import json
import sys
from queue import Empty, Queue
from threading import Event, Thread
from zipfile import ZipFile

import pytest
from _clock import freeze_monotonic
from PySide6.QtCore import QObject, Signal

from pogled_assist import diagnostics, logging_setup
from pogled_assist.diagnostic_recording import RecordingStore, recording_context
from pogled_assist.interaction.gaze_selection import GazeSelectionTimer
from pogled_assist.log_reader import summarize
from pogled_assist.log_transport import LogWriter
from pogled_assist.ui.diagnostic_recordings import DiagnosticRecordings


def record(path, session, event, at, **data):
    item = dict(
        schema_version=1,
        process_instance="process",
        session_id=session,
        event=event,
        monotonic_s=at,
        data=data,
    )
    with path.open("a") as stream:
        stream.write(json.dumps(item) + "\n")


def test_full_stream_summary_survives_both_destinations(tmp_path, monkeypatch):
    now = freeze_monotonic(monkeypatch, 100)
    writer = LogWriter()
    monkeypatch.setattr(logging_setup, "_writer", writer)
    root = tmp_path / "logs"
    writer.start_segment(root / "latest.txt", None, trace=False)
    folder = root / "recordings"
    key = writer.start_recording(folder, 1, recording_context({}, {}, simulated=True))
    metrics = diagnostics.StreamMetrics()
    counts = {
        name: index + 1
        for index, name in enumerate(
            (
                "native_gaze_callback",
                "native_eye_callback",
                "eye_position_callback",
                "provider_queued",
                "provider_emitted",
                "provider_replaced",
                "rejected:right_invalid",
                "suppressed:eye_gate_received",
            )
        )
    }
    metadata = {
        name: "v" * 256 for name in ("sdk_version", "model", "firmware_version", "architecture")
    }
    durations = {}
    try:
        for name, count in counts.items():
            metrics.count(name, count)
        for stream, states in (
            ("native", ("both_valid", "left_invalid", "right_invalid", "both_invalid")),
            ("application_gate", ("open", "closed")),
        ):
            for state in states:
                metrics.eyes(
                    stream, state, sampled=True, stale_after=0.5 if stream == "native" else None
                )
                now[0] += 0.1
                durations[f"{stream}:{state}"] = pytest.approx(0.1)
            durations[f"{stream}:stale_unknown"] = 0
        # Native state continues accruing while the application gate is sampled.
        durations["native:both_invalid"] = pytest.approx(0.3)
        metrics.summary(
            force=True,
            generation=1,
            backend="stream_engine",
            backend_metadata=metadata,
            qt_timer_max_late_ms=12.0,
            check_active=False,
            eye_age_ms=123.0,
        )
        writer.stop_recording()
    finally:
        assert writer.stop()
    ordinary = next((root / "diagnostics").glob("*.jsonl"))
    manual = folder / key / "snimak.jsonl"
    for path in (ordinary, manual):
        events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        summary = next(item["data"] for item in events if item["event"] == "stream_summary")
        assert not summary.get("_snapshot_truncated")
        assert summary["cumulative_counts"] == counts
        assert summary["counts"] == {
            k: v for k, v in counts.items() if path == ordinary or not k.startswith("suppressed:")
        }
        assert summary["eye_state_seconds"] == durations
        assert summary["backend_metadata"] == metadata
        assert summary["eye_age_ms"] == 123.0
        assert len(summary["observation_start_sessions"]) == 2
        assert summarize(path)["complete"]


@pytest.mark.parametrize("drop_baseline", [False, True])
def test_large_cumulative_summary_keeps_manual_baseline_and_rotated_context(
    qapp, tmp_path, monkeypatch, drop_baseline
):
    from pogled_assist import diagnostic_recording, log_transport

    monkeypatch.setattr(log_transport, "SEGMENT_BYTES", 2000)
    monkeypatch.setattr(diagnostic_recording, "SEGMENT_BYTES", 2000)
    freeze_monotonic(monkeypatch, 100)
    writer = LogWriter()
    monkeypatch.setattr(logging_setup, "_writer", writer)
    root = tmp_path / "logs"
    writer.start_segment(root / "latest.txt", None, trace=False)
    folder = root / "recordings"
    store = RecordingStore(folder)
    recordings = DiagnosticRecordings(store, qapp, writer=lambda: writer)
    monkeypatch.setattr(recordings, "_schedule_maintenance", lambda: None)
    metrics = diagnostics.StreamMetrics(event_name="selection_summary", source="toolbar")
    reasons = (
        "target_departure",
        "restart",
        "target_changed",
        "settings_changed",
        "invalid_gaze",
        "both_eyes_invalid",
        "stale_eye_data",
        "eligible_eye_changed",
        "eye_gate_closed",
        "tracking_hold_expired",
        "stale_gaze",
        "gaze_freshness_expired",
        "interaction_context_changed",
        "input_suspended",
        "geometry_changed",
        "tracking_pause_unfinished",
        "edge_hold_expired",
    )
    room = writer._queue_has_room
    try:
        for reason in reasons:
            metrics.event("selection_end", reason=reason)
            metrics.summary(force=True)
        assert len(metrics._total_counts) == 34
        metrics.event("selection_end", reason="completed")
        if drop_baseline:
            monkeypatch.setattr(writer, "_queue_has_room", lambda *_args: False)
        assert recordings.start(1, recording_context({}, {}, simulated=True))
        key = writer._recording.id
        monkeypatch.setattr(writer, "_queue_has_room", room)
        metrics.event("selection_end", reason="completed")
        metrics.summary(force=True)
        # A new ordinary destination replays the captured counter position.
        writer.start_segment(root / "latest.txt", None, trace=False)
        metrics.event("selection_end", reason="completed")
        recordings.stop()
    finally:
        monkeypatch.setattr(writer, "_queue_has_room", room)
        recordings.shutdown()
        recordings.deleteLater()
        assert writer.stop()
    manual = store.inspect(key)["analysis"]["analysis"]
    assert manual["reason_totals_from_counters"] == {
        "outcome:completed": 2,
        "reason:selection_end:completed": 2,
    }
    merged = summarize(root)["analysis"]
    expected = {
        f"{prefix}{reason}": 1
        for reason in reasons
        for prefix in ("outcome:", "reason:selection_end:")
    }
    expected.update({"outcome:completed": 3, "reason:selection_end:completed": 3})
    assert merged["reason_totals_from_counters"] == expected
    assert not manual["partial_counter_streams"]
    assert writer.health()["bounded_snapshots"] == 0
    assert list((root / "diagnostics").glob("*.part-*.jsonl"))
    assert list((folder / key).glob("snimak-*.jsonl"))
    large_contexts = 0
    for path in root.rglob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            fields = item["data"]
            if item["event"] == "segment_context":
                fields = fields.get("snapshot", {}).get("data", {})
                if len(fields.get("cumulative_counts", {})) > 32:
                    large_contexts += 1
            assert not fields.get("_snapshot_truncated")
    assert large_contexts > 0
    destination = tmp_path / "support.zip"
    store.export(key, destination)
    with ZipFile(destination) as archive:
        assert '"outcome:completed": 2' in archive.read("sazetak.txt").decode()


def test_overlapping_sessions_are_merged_in_observation_order(tmp_path):
    ordinary, manual = tmp_path / "ordinary.jsonl", tmp_path / "manual.jsonl"
    record(ordinary, "ordinary", "session_start", 0)
    record(
        ordinary,
        "ordinary",
        "selection_state",
        1,
        attempt_id="a",
        attempt_started=True,
        observation_id="start",
    )
    for index in (1, 3):
        record(
            ordinary,
            "ordinary",
            "selection_summary",
            index,
            observation_id=f"sum{index}",
            observation_stream_id="stream",
            interval_index=index,
            cumulative_counts={"outcome:completed": index},
        )
    record(
        ordinary,
        "ordinary",
        "selection_end",
        4,
        attempt_id="a",
        reason="completed",
        observation_id="end",
        coverage="observed_start",
    )
    record(ordinary, "ordinary", "session_end", 6)
    record(manual, "manual", "session_start", 1.5)
    record(
        manual,
        "manual",
        "segment_context",
        1.5,
        snapshot={"event": "selection_state", "data": {"attempt_id": "a"}},
    )
    record(
        manual,
        "manual",
        "selection_summary",
        2,
        observation_id="sum2",
        observation_stream_id="stream",
        interval_index=2,
        cumulative_counts={"outcome:completed": 2},
    )
    record(
        manual,
        "manual",
        "selection_end",
        4,
        attempt_id="a",
        reason="completed",
        observation_id="end",
        coverage="observed_start",
    )
    record(manual, "manual", "session_end", 5)
    result = summarize(tmp_path)
    assert result["deduplicated_observations"] == 1
    assert result["analysis"]["partial_selection_attempts"] == 0
    assert result["analysis"]["missing_counter_intervals"] == 0
    assert result["analysis"]["reason_totals_from_counters"] == {"outcome:completed": 3}


@pytest.mark.parametrize(
    "field,invalid",
    [
        ("attempt_id", []),
        ("surface", []),
        ("coverage", []),
        ("outcome", []),
        ("observation_start_sessions", {}),
        ("observation_start_sessions", [[]]),
        ("observation_start_sessions", ["a", "b", "c"]),
    ],
)
def test_malformed_optional_field_keeps_other_evidence(tmp_path, field, invalid):
    path = tmp_path / "stream.jsonl"
    record(path, "s", "session_start", 0)
    record(path, "s", "selection_state", 1, attempt_id="known", attempt_started=True)
    record(
        path,
        "s",
        "selection_hold_end" if field == "outcome" else "selection_end",
        2,
        **{field: invalid, "reason": "completed"},
    )
    record(path, "s", "session_end", 3)
    result = summarize(path)
    assert not result["complete"]
    assert result["parse_warnings"][0]["reason"] == "invalid_diagnostic_fields"
    assert result["session_end_present"]


def test_qt_slot_failure_is_not_reported_as_handler_returned(monkeypatch):
    class Emitter(QObject):
        fired = Signal()

    events, errors = [], []
    monkeypatch.setattr(diagnostics, "enabled", lambda: True)
    monkeypatch.setattr(diagnostics, "emit", lambda event, **fields: events.append((event, fields)))
    monkeypatch.setattr(sys, "excepthook", lambda *args: errors.append(args))

    def fail():
        raise RuntimeError("Synthetic handler failure")

    emitter = Emitter()
    emitter.fired.connect(lambda: diagnostics.invoke_action(fail))
    diagnostics.invoke_action(emitter.fired.emit)
    assert len(errors) == 1
    assert [fields["outcome"] for event, fields in events if event == "ui_action_returned"] == [
        "handler_failed"
    ]


def test_shutdown_can_race_with_worker_taking_the_last_job(qapp, tmp_path):
    taken = Event()

    class RacingQueue(Queue):
        def empty(self):
            result = super().empty()
            if not result:
                worker = Thread(target=lambda: (self.get(), taken.set()))
                worker.start()
                assert taken.wait(1)
                worker.join()
            return result

        def get_nowait(self):
            # Model the worker winning between the old empty()/get_nowait() calls.
            if not taken.is_set():
                self.empty()
            return super().get_nowait()

    recordings = DiagnosticRecordings(RecordingStore(tmp_path), qapp, writer=lambda: None)
    recordings._queue = RacingQueue()
    recordings._queue.put(("maintenance", "", None))
    try:
        recordings.shutdown()
    except Empty:
        pytest.fail("Shutdown let the queue race escape into Qt closeEvent")
    finally:
        recordings.deleteLater()


def test_enabling_ordinary_during_manual_replays_context(tmp_path, monkeypatch):
    writer = LogWriter()
    monkeypatch.setattr(logging_setup, "_writer", writer)
    writer.start_recording(tmp_path / "recordings", 1, recording_context({}, {}, simulated=True))
    timer = GazeSelectionTimer("toolbar")
    timer.update("speech", 0, pause_ms=250, dwell_ms=1000)
    timer.update("speech", 400, pause_ms=250, dwell_ms=1000)
    writer.start_segment(tmp_path / "logs/latest.txt", None, trace=False)
    timer.complete()
    writer.stop_recording()
    assert writer.stop()
    result = summarize(tmp_path / "logs/diagnostics")
    assert result["analysis"]["settings_intervals"]
    assert result["analysis"]["recent_selection_ends"][0]["coverage"] == "partial_start"


def test_edge_hold_expiry_during_tracking_keeps_its_actual_reason(monkeypatch):
    events = []
    monkeypatch.setattr(diagnostics, "enabled", lambda: True)
    from types import SimpleNamespace

    writer = SimpleNamespace(
        _generation=1, trace=False, event=lambda event, fields, **kw: events.append((event, fields))
    )
    monkeypatch.setattr(diagnostics, "diagnostic_writer", lambda: writer)
    timer = GazeSelectionTimer("toolbar")
    timer.update("speech", 0, pause_ms=250, dwell_ms=1000)
    timer.update("speech", 400, pause_ms=250, dwell_ms=1000)
    timer.update(None, 410, pause_ms=250, dwell_ms=1000, can_hold=True, hold_ms=100)
    timer.hold_tracking(700, 900, eyes=(False, True))
    timer.update("speech", 550, pause_ms=250, dwell_ms=1000, can_hold=True, hold_ms=100)
    assert (
        next(fields["reason"] for event, fields in events if event == "selection_end")
        == "edge_hold_expired"
    )


@pytest.mark.parametrize("missing", ["first", "middle", "last"])
def test_missing_segment_is_partial_and_still_exportable(tmp_path, monkeypatch, missing):
    from pogled_assist import diagnostic_recording

    monkeypatch.setattr(diagnostic_recording, "SEGMENT_BYTES", 2500)
    writer = LogWriter()
    folder = tmp_path / "recordings"
    key = writer.start_recording(folder, 1, recording_context({}, {}, simulated=True))
    for index in range(20):
        writer.event("synthetic", {"index": index, "padding": "x" * 600})
    writer.stop_recording()
    assert writer.stop()
    traces = sorted(
        (folder / key).glob("snimak*.jsonl"), key=lambda path: path.name != "snimak.jsonl"
    )
    target = {
        "first": traces[0],
        "middle": folder / key / "snimak-000001.jsonl",
        "last": max(traces, key=lambda path: path.name if "-" in path.stem else ""),
    }[missing]
    missing_index = 0 if target.name == "snimak.jsonl" else int(target.stem.split("-")[-1])
    target.unlink()
    store = RecordingStore(folder)
    entry = store.load()[0]
    assert not entry["complete"]
    assert entry["state"] == "interrupted"
    destination = tmp_path / "partial.zip"
    store.export(key, destination)
    with ZipFile(destination) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["recording"]["segment_gaps"] == [missing_index]
        assert f"Nedostajući segmenti: [{missing_index}]" in archive.read("sazetak.txt").decode()


def test_manual_context_keeps_all_geometry_chunks(tmp_path, qtbot):
    writer = LogWriter()
    writer.start_segment(tmp_path / "logs/latest.txt", None, trace=True)
    qtbot.waitUntil(lambda: ("runtime", None) in writer._context_snapshots)
    for index in range(3):
        writer.event(
            "target_geometry",
            {
                "context_id": "context",
                "kind": "speech",
                "targets": [{"target_id": f"target-{index}", "rect": [0, 0, 40, 40]}],
            },
            trace=True,
        )
    key = writer.start_recording(
        tmp_path / "recordings", 1, recording_context({}, {}, simulated=True)
    )
    writer.stop_recording()
    assert writer.stop()
    rows = [
        json.loads(line)
        for line in (tmp_path / "recordings" / key / "snimak.jsonl").read_text().splitlines()
    ]
    targets = [
        target["target_id"]
        for row in rows
        if row["event"] == "segment_context"
        for target in row["data"].get("snapshot", {}).get("data", {}).get("targets", [])
    ]
    assert targets == ["target-0", "target-1", "target-2"]
    assert any(row["data"].get("snapshot", {}).get("event") == "runtime" for row in rows)


def test_reader_separates_holds_started_before_recording(tmp_path):
    path = tmp_path / "manual.jsonl"
    record(path, "manual", "session_start", 10)
    record(
        path,
        "manual",
        "selection_hold_end",
        11,
        outcome="resumed",
        duration_ms=2000,
        hold_started_monotonic_s=9,
    )
    record(
        path,
        "manual",
        "selection_hold_end",
        12,
        outcome="expired",
        duration_ms=500,
        hold_started_monotonic_s=11.5,
    )
    record(path, "manual", "session_end", 13)
    analysis = summarize(path)["analysis"]
    assert analysis["hold_outcomes"] == {"expired": 1}
    assert analysis["hold_coverage"] == {"partial_start": 1, "observed_start": 1}
    assert analysis["partial_hold_outcomes"] == {"resumed": 1}
    assert analysis["partial_hold_duration"]["max_ms"] == 2000


def test_recorded_hold_coverage_and_support_summary(tmp_path, monkeypatch):
    now = freeze_monotonic(monkeypatch, 100)
    writer = LogWriter()
    monkeypatch.setattr(logging_setup, "_writer", writer)
    writer.start_segment(tmp_path / "logs/latest.txt", None, trace=False)
    timer = GazeSelectionTimer("toolbar")
    timer.update("speech", 0, pause_ms=250, dwell_ms=1000)
    timer.update("speech", 400, pause_ms=250, dwell_ms=1000)
    timer.hold_tracking(700, 900, eyes=(False, True))
    now[0] = 110
    folder = tmp_path / "recordings"
    key = writer.start_recording(folder, 1, recording_context({}, {}, simulated=True))
    now[0] = 111
    timer.update("speech", 500, pause_ms=250, dwell_ms=1000)
    timer.complete()
    writer.stop_recording()
    assert writer.stop()
    store = RecordingStore(folder)
    analysis = store.inspect(key)["analysis"]["analysis"]
    assert analysis["partial_hold_outcomes"] == {"resumed": 1}
    assert analysis["hold_outcomes"] == {}
    assert analysis["partial_hold_duration"]["max_ms"] == 11000
    destination = tmp_path / "support.zip"
    store.export(key, destination)
    with ZipFile(destination) as archive:
        summary = archive.read("sazetak.txt").decode()
    for label in (
        "Ishodi po površini",
        "Intervali postavki",
        "Kašnjenja (ms)",
        "Djelimično zabilježena zadržavanja",
        "Odbačeni napredak (ms)",
        "Nedostajući intervali brojača",
    ):
        assert label in summary


@pytest.mark.parametrize("drop_before", [False, True])
@pytest.mark.parametrize("drop_during", [False, True])
def test_manual_counter_baseline_excludes_prior_activity_and_recovers_lost_intervals(
    qapp, tmp_path, monkeypatch, drop_before, drop_during
):
    freeze_monotonic(monkeypatch, 100)
    writer = LogWriter()
    monkeypatch.setattr(logging_setup, "_writer", writer)
    root = tmp_path / "logs"
    writer.start_segment(root / "latest.txt", None, trace=False)
    store = RecordingStore(root / "recordings")
    recordings = DiagnosticRecordings(store, qapp, writer=lambda: writer)
    monkeypatch.setattr(recordings, "_schedule_maintenance", lambda: None)
    metrics = diagnostics.StreamMetrics(event_name="selection_summary", source="toolbar")
    room = writer._queue_has_room
    try:
        for _ in range(3):
            metrics.event("selection_end", reason="target_departure")
        metrics.summary(force=True)
        metrics.event("selection_end", reason="target_departure")
        if drop_before:
            monkeypatch.setattr(writer, "_queue_has_room", lambda *_args: False)
        assert recordings.start(1, recording_context({}, {}, simulated=True))
        key = writer._recording.id
        monkeypatch.setattr(writer, "_queue_has_room", room)
        metrics.event("selection_end", reason="completed")
        if drop_during:
            monkeypatch.setattr(writer, "_queue_has_room", lambda *_args: False)
        metrics.summary(force=True)
        monkeypatch.setattr(writer, "_queue_has_room", room)
        metrics.event("selection_end", reason="completed")
        recordings.stop()
    finally:
        monkeypatch.setattr(writer, "_queue_has_room", room)
        recordings.shutdown()
        recordings.deleteLater()
        assert writer.stop()
    analysis = store.inspect(key)["analysis"]["analysis"]
    assert analysis["reason_totals_from_counters"] == {
        "outcome:completed": 2,
        "reason:selection_end:completed": 2,
    }
    assert analysis["missing_counter_intervals"] == int(drop_during)
    destination = tmp_path / "support.zip"
    store.export(key, destination)
    with ZipFile(destination) as archive:
        summary = archive.read("sazetak.txt").decode()
        counter_line = next(line for line in summary.splitlines() if line.startswith("Razlozi iz"))
        assert "target_departure" not in counter_line
        assert '"outcome:completed": 2' in counter_line
    merged = summarize(root)["analysis"]
    assert merged["reason_totals_from_counters"]["outcome:target_departure"] == 4
    assert merged["reason_totals_from_counters"]["outcome:completed"] == 2


@pytest.mark.parametrize("manual_covers_start", [False, True])
def test_dropped_initial_intervals_use_the_streams_actual_destinations(
    tmp_path, monkeypatch, manual_covers_start
):
    freeze_monotonic(monkeypatch, 100)
    writer = LogWriter()
    monkeypatch.setattr(logging_setup, "_writer", writer)
    root = tmp_path / "logs"
    writer.start_segment(root / "latest.txt", None, trace=False)
    folder = root / "recordings"
    room = writer._queue_has_room
    try:
        if manual_covers_start:
            key = writer.start_recording(folder, 1, recording_context({}, {}, simulated=True))
        metrics = diagnostics.StreamMetrics(event_name="selection_summary", source="toolbar")
        for _ in range(2):
            metrics.event("selection_end", reason="completed")
            metrics.event("selection_end", reason="completed")
            monkeypatch.setattr(writer, "_queue_has_room", lambda *_args: False)
            metrics.summary(force=True)
            monkeypatch.setattr(writer, "_queue_has_room", room)
        if not manual_covers_start:
            key = writer.start_recording(folder, 1, recording_context({}, {}, simulated=True))
        metrics.event("selection_end", reason="completed")
        metrics.event("selection_end", reason="completed")
        metrics.summary(force=True)
        writer.stop_recording()
    finally:
        monkeypatch.setattr(writer, "_queue_has_room", room)
        assert writer.stop()
    manual = RecordingStore(folder).inspect(key)["analysis"]["analysis"]
    assert manual["reason_totals_from_counters"]["outcome:completed"] == (
        6 if manual_covers_start else 2
    )
    assert manual["missing_counter_intervals"] == (2 if manual_covers_start else 0)
    merged = summarize(root)["analysis"]
    assert merged["reason_totals_from_counters"]["outcome:completed"] == 6
    assert merged["missing_counter_intervals"] == 2


@pytest.mark.parametrize("include_origin", [False, True])
def test_unrelated_old_session_cannot_extend_counter_coverage(tmp_path, include_origin):
    old, manual = tmp_path / "old.jsonl", tmp_path / "manual.jsonl"
    record(old, "old", "session_start", 0)
    record(old, "old", "session_end", 1)
    if include_origin:
        origin = tmp_path / "origin.jsonl"
        record(origin, "origin", "session_start", 2)
        record(origin, "origin", "session_end", 12)
    fields = dict(
        observation_stream_id="stream",
        observation_start_sessions=["origin"],
        observation_started_monotonic_s=2.5,
    )
    record(manual, "manual", "session_start", 10)
    record(
        manual,
        "manual",
        "segment_context",
        10,
        snapshot={
            "event": "selection_summary",
            "data": {**fields, "interval_index": 2, "cumulative_counts": {"outcome:completed": 4}},
        },
    )
    record(
        manual,
        "manual",
        "selection_summary",
        11,
        **fields,
        interval_index=3,
        counts={"outcome:completed": 2},
        cumulative_counts={"outcome:completed": 6},
    )
    record(manual, "manual", "session_end", 12)
    assert summarize(manual)["analysis"]["reason_totals_from_counters"] == {"outcome:completed": 2}
    merged = summarize(tmp_path)["analysis"]
    assert merged["reason_totals_from_counters"] == {
        "outcome:completed": 6 if include_origin else 2
    }
    assert merged["missing_counter_intervals"] == (2 if include_origin else 0)
