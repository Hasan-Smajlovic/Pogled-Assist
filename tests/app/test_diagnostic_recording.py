from __future__ import annotations

import faulthandler
import hashlib
import json
import logging
import threading
import time
from zipfile import ZipFile

import pytest
from _clock import freeze_monotonic

from pogled_assist import build_info, logging_setup
from pogled_assist import diagnostic_recording as module
from pogled_assist.diagnostic_recording import RecordingStore, recording_context
from pogled_assist.log_transport import LogWriter
from pogled_assist.tracking.gaze_check_report import GazeCheckReport, identity


def wait_for(predicate):
    deadline = time.perf_counter() + 10
    while not predicate():
        assert time.perf_counter() < deadline, "Background recording did not acknowledge completion"
        threading.Event().wait(0.005)


@pytest.fixture
def writer(monkeypatch):
    monkeypatch.setattr(
        build_info,
        "_identity",
        {"app_version": "0.1.0", "build_revision": "a" * 40, "build_dirty": True},
    )
    value = LogWriter(capacity=24)
    yield value
    assert value.stop(timeout=10)


@pytest.fixture
def blocked_write(writer, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    write = module.RecordingSink.write

    def block(sink, event, *args, **kwargs):
        if event.name == "blocked":
            entered.set()
            release.wait()
        return write(sink, event, *args, **kwargs)

    monkeypatch.setattr(module.RecordingSink, "write", block)
    try:
        yield entered, release
    finally:
        # Unblock the sink before the writer fixture joins its thread.
        release.set()


def context():
    return recording_context(
        {
            "eye_tracking_policy": "any",
            "dwell_ms": 850,
            "selection_pause_ms": 250,
            "api_key": "PRIVATE-KEY",
            "text": "PRIVATE-MESSAGE",
        },
        {
            "backend": "mouse-simulation",
            "logical_screen": (0, 0, 1280, 720),
            "serial_number": "PRIVATE-SERIAL",
        },
        simulated=True,
    )


def finish(writer, folder, *, stop=True):
    if stop:
        writer.stop_recording()
    wait_for(lambda: not writer.recording_status()["busy"])
    store = RecordingStore(folder)
    return store.inspect(writer.recording_status()["id"])


def assert_recording_complete(item, expected):
    assert item["complete"] is expected
    assert item["analysis"]["complete"] is expected
    assert item["analysis"]["analysis"]["evidence_incomplete"] is (not expected)
    assert item["analysis"]["recording_health"] == item["health"]
    assert item["analysis"]["session_end_reason"] == item["reason"]


@pytest.mark.parametrize("normal", [False, True])
def test_manual_capture_is_independent_of_normal_logging_and_survives_toggles(
    writer, tmp_path, normal
):
    folder = tmp_path / "recordings"
    if normal:
        writer.start_segment(tmp_path / "logs/latest.txt", None, trace=False)
    key = writer.start_recording(folder, 2, context())
    assert key and writer.trace
    writer.event("native_gaze", {"x": 0.25}, trace=True)
    writer.disable()
    writer.event("after_disable", {"x": 0.5}, trace=True)
    writer.start_segment(tmp_path / "logs/latest.txt", None, trace=False)
    writer.event("after_enable", {}, trace=True)
    item = finish(writer, folder)
    assert item["id"] == key
    assert_recording_complete(item, True)
    assert item["reason"] == "manual" and item["context"]["build"]["build_dirty"]
    events = item["analysis"]["events"]
    assert all(events.get(name) == 1 for name in ("native_gaze", "after_disable", "after_enable"))
    assert events["session_start"] == events["session_end"] == 1
    assert not writer.trace


def test_explicit_recording_works_with_saved_logging_off_without_changing_it(monkeypatch, tmp_path):
    monkeypatch.setattr(logging_setup, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(logging_setup, "_writer", None)
    monkeypatch.setattr(logging_setup, "_queue_handler", None)
    latest = logging_setup.set_application_logging_enabled(False)
    try:
        value = logging_setup.recording_writer()
        folder = tmp_path / "recordings"
        value.start_recording(folder, 1, context())
        assert logging_setup.diagnostic_writer() is value
        value.event("native_gaze", {}, trace=True)
        finish(value, folder)
        assert logging_setup.diagnostic_writer() is None
        assert not latest.exists()
        assert not (tmp_path / "data/app_settings.json").exists()
    finally:
        logging_setup.shutdown_application_logging()
        logging.disable(logging.NOTSET)


def test_deadline_finishes_without_another_event_and_shutdown_is_interrupted(
    writer, tmp_path, monkeypatch
):
    now = freeze_monotonic(monkeypatch, 100)
    folder = tmp_path / "recordings"
    writer.start_recording(folder, 1, context())
    wait_for(lambda: writer.recording_status()["state"] == "recording")
    now[0] = 160
    with writer._condition:
        writer._condition.notify()
    item = finish(writer, folder, stop=False)
    assert item["reason"] == "time"
    assert_recording_complete(item, True)
    writer.start_recording(folder, 2, context())
    writer.stop_recording("shutdown")
    interrupted = finish(writer, folder, stop=False)
    assert interrupted["reason"] == "shutdown"
    assert interrupted["session_end_present"]
    assert_recording_complete(interrupted, False)


def test_recording_limit_is_separate_from_an_exhausted_normal_session(
    writer, tmp_path, monkeypatch
):
    from pogled_assist import log_transport

    monkeypatch.setattr(log_transport, "SESSION_BYTES", 9000)
    latest = tmp_path / "logs/latest.txt"
    writer.start_segment(latest, None, trace=True)
    writer.event("large", {"payload": "x" * 3000}, trace=True)
    wait_for(lambda: writer._active is not None and writer._json is None)
    folder = tmp_path / "recordings"
    writer.start_recording(folder, 2, context())
    writer.event("new_trace", {"x": 0.5}, trace=True)
    assert finish(writer, folder)["analysis"]["events"]["new_trace"] == 1
    monkeypatch.setattr(module, "RECORDING_BYTES", 10000)
    writer.start_recording(folder, 2, context())
    for _ in range(5):
        writer.event("large", {"payload": "x" * 2000}, trace=True)
    item = finish(writer, folder, stop=False)
    assert item["reason"] == "size"
    assert item["bytes"] <= 10000 and item["session_end_present"]
    assert_recording_complete(item, False)


def test_blocked_recording_does_not_block_producers_and_prevents_a_second_start(
    writer, tmp_path, blocked_write
):
    entered, release = blocked_write
    folder = tmp_path / "recordings"
    writer.start_recording(folder, 2, context())
    writer.event("blocked", {}, trace=True)
    assert entered.wait(10), "Recording writer did not reach the blocked sink"
    producer_done = threading.Event()

    def produce():
        for index in range(100):
            writer.event("native_gaze", {"index": index}, trace=True)
        writer.stop_recording()
        producer_done.set()

    thread = threading.Thread(target=produce, name="recording-producer")
    thread.start()
    try:
        # The sink stays blocked until release; this checks ordering, not throughput.
        if not producer_done.wait(10):
            faulthandler.dump_traceback()
            pytest.fail("Recording producer waited while the sink was blocked")
        assert writer.health()["queued"] <= writer.capacity
        assert writer.start_recording(folder, 1, context()) is None
        assert writer.recording_status()["state"] == "finishing"
    finally:
        release.set()
        thread.join(10)
        assert not thread.is_alive(), "Recording producer did not stop after releasing the sink"
    item = finish(writer, folder, stop=False)
    assert item["health"]["dropped"]["event"] > 0
    assert_recording_complete(item, False)
    writer.start_recording(folder, 1, context())
    fresh = finish(writer, folder)
    assert fresh["health"]["dropped"] == {}
    assert_recording_complete(fresh, True)


def test_write_error_and_bounded_snapshot_remain_explicit(writer, tmp_path, monkeypatch):
    folder = tmp_path / "recordings"
    original = module.RecordingSink.write

    def fail(sink, event, *args, **kwargs):
        if event.name == "disk-error":
            raise OSError("Synthetic private exception text")
        return original(sink, event, *args, **kwargs)

    monkeypatch.setattr(module.RecordingSink, "write", fail)
    writer.start_recording(folder, 1, context())
    writer.event("disk-error", {}, trace=True)
    item = finish(writer, folder, stop=False)
    assert item["reason"] == "writer_error" and item["health"]["writer_errors"] == 1
    assert_recording_complete(item, False)
    writer.start_recording(folder, 1, context())
    writer.event("oversized", {"values": "x" * 100000}, trace=True)
    item = finish(writer, folder)
    assert item["health"]["bounded_snapshots"] == 1
    assert_recording_complete(item, False)


def test_retention_restart_and_partial_recordings_do_not_touch_other_files(
    writer, tmp_path, monkeypatch
):
    monkeypatch.setattr(module, "MAX_RECORDINGS", 2)
    folder = tmp_path / "recordings"
    folder.mkdir()
    unrelated = folder / "manual.zip"
    unrelated.write_bytes(b"keep")
    ids = []
    for _ in range(3):
        ids.append(writer.start_recording(folder, 1, context()))
        finish(writer, folder)
    store = RecordingStore(folder)
    assert {item["id"] for item in store.load()} == set(ids[-2:])
    assert unrelated.read_bytes() == b"keep"
    key = ids[-1]
    metadata_path = folder / key / "recording.json"
    metadata = json.loads(metadata_path.read_bytes())
    metadata.update(state="recording", complete=True)
    module.atomic_bytes(metadata_path, module.json_bytes(metadata))
    trace = folder / key / "snimak.jsonl"
    lines = trace.read_text(encoding="utf-8").splitlines(keepends=True)
    trace.write_text("".join(lines[:-1]), encoding="utf-8")
    recovered = store.inspect(key)
    assert recovered["state"] == "interrupted" and recovered["reason"] == "missing_end"
    assert not recovered["complete"] and not recovered["session_end_present"]
    store.export(key, tmp_path / "partial.zip")
    other = folder / ("f" * 32)
    other.mkdir()
    (other / "recording.json").write_text("unsupported")
    assert any(item["state"] == "unreadable" for item in store.load())


@pytest.mark.parametrize(
    "field,invalid",
    [("bytes", 10**400), ("duration_seconds", 10**400), ("started_at", None)],
    ids=["overflowing-bytes", "overflowing-duration", "missing-start-time"],
)
def test_invalid_metadata_is_isolated_from_readable_history(writer, tmp_path, field, invalid):
    folder = tmp_path / "recordings"
    corrupt_id = writer.start_recording(folder, 1, context())
    finish(writer, folder)
    valid_id = writer.start_recording(folder, 1, context())
    finish(writer, folder)
    metadata_path = folder / corrupt_id / "recording.json"
    metadata = json.loads(metadata_path.read_bytes())
    metadata[field] = invalid
    module.atomic_bytes(metadata_path, module.json_bytes(metadata))

    store = RecordingStore(folder)
    entries = {item["id"]: item for item in store.recover_and_load()}
    assert entries[corrupt_id]["state"] == "unreadable"
    assert not entries[corrupt_id]["complete"]
    assert entries[valid_id]["complete"]
    destination = tmp_path / "existing.zip"
    destination.write_bytes(b"existing export")
    with pytest.raises(module.RecordingReadError):
        store.export(corrupt_id, destination)
    assert destination.read_bytes() == b"existing export"


@pytest.mark.parametrize("with_report", [False, True])
def test_export_manifest_checksums_privacy_and_exact_destination(writer, tmp_path, with_report):
    folder = tmp_path / "recordings"
    key = writer.start_recording(folder, 1, context())
    writer.record(logging.makeLogRecord({"msg": "PRIVATE-MESSAGE PRIVATE-KEY PRIVATE-SERIAL"}))
    writer.event("native_gaze", {"x": 0.5}, trace=True)
    item = finish(writer, folder)
    report = (
        GazeCheckReport(
            identity(),
            item["started_at"],
            item["started_at"],
            0,
            "interrupted",
            "Synthetic interruption",
            True,
            {"eye_tracking_policy": "hold"},
            {},
            [],
        )
        if with_report
        else None
    )
    destination = tmp_path / "chosen.name"  # Native Save As already confirmed this exact name.
    RecordingStore(folder).export(key, destination, report)
    assert not destination.with_suffix(".zip").exists()
    with ZipFile(destination) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["recording"]["id"] == key
        assert bool(manifest["selected_gaze_check"]) is with_report
        for entry in manifest["files"]:
            data = archive.read(entry["path"])
            assert (
                len(data) == entry["bytes"] and hashlib.sha256(data).hexdigest() == entry["sha256"]
            )
        payload = b"".join(archive.read(name) for name in archive.namelist())
        assert b"PRIVATE" not in payload
        if with_report:
            assert manifest["selected_gaze_check"]["simulated"] is True
            assert manifest["selected_gaze_check"]["eye_tracking_policy"] == "hold"
    assert item["complete"]


def test_failed_export_preserves_overwrite_target_and_cleans_temporary(
    writer, tmp_path, monkeypatch
):
    folder = tmp_path / "recordings"
    key = writer.start_recording(folder, 1, context())
    finish(writer, folder)
    destination = tmp_path / "previous.zip"
    destination.write_bytes(b"previous")

    def fail(*_args):
        raise OSError("Synthetic replace failure")

    monkeypatch.setattr(module.os, "replace", fail)
    with pytest.raises(OSError):
        RecordingStore(folder).export(key, destination)
    assert destination.read_bytes() == b"previous"
    assert not list(tmp_path.glob(".support-export-*"))


def test_source_build_identity_distinguishes_local_changes_and_frozen_unknown(
    monkeypatch, tmp_path
):
    from types import SimpleNamespace

    (tmp_path / "VERSION").write_text("0.1.0")
    monkeypatch.setattr(build_info, "_identity", None)
    outputs = iter(["b" * 40, " M source.py\n"])
    monkeypatch.setattr(
        build_info.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=next(outputs)),
    )
    assert build_info.resolve_build_identity(tmp_path) == {
        "app_version": "0.1.0",
        "build_revision": "b" * 40,
        "build_dirty": True,
    }
    monkeypatch.setattr(build_info.sys, "frozen", True, raising=False)
    assert build_info.resolve_build_identity(tmp_path)["build_revision"] is None
    (tmp_path / "BUILD_INFO.json").write_text(
        json.dumps({"app_version": "0.1.0", "build_revision": "c" * 40, "build_dirty": False})
    )
    assert build_info.resolve_build_identity(tmp_path)["build_dirty"] is False
    assert build_info.build_identity()["build_revision"] == "c" * 40


def test_manual_trace_preserves_ordinary_basic_accounting(writer, tmp_path, monkeypatch):
    from pogled_assist import diagnostics
    from pogled_assist.log_reader import summarize

    monkeypatch.setattr(diagnostics, "diagnostic_writer", lambda: writer)
    latest = tmp_path / "logs/latest.txt"
    writer.start_segment(latest, None, trace=False)
    folder = tmp_path / "recordings"
    writer.start_recording(folder, 1, context())
    metrics = diagnostics.StreamMetrics()
    for index in range(8):
        metrics.event("eye_gate_received", left_valid=True, right_valid=True, index=index)
    metrics.summary(force=True)
    item = finish(writer, folder)
    assert writer.stop()
    ordinary_path = next((latest.parent / "diagnostics").glob("*.jsonl"))
    ordinary = summarize(ordinary_path)
    assert ordinary["complete"]
    assert ordinary["events"]["eye_gate_received"] == 4
    assert ordinary["analysis"]["suppressed_events"] == {"suppressed:eye_gate_received": 4}
    assert not writer.health()["dropped"]
    assert item["complete"] and item["analysis"]["events"]["eye_gate_received"] == 8
    assert item["analysis"]["analysis"]["suppressed_events"] == {}


def test_recording_order_survives_ordinary_rotation_without_exceeding_queue_bound(
    writer, tmp_path, blocked_write
):
    entered, release = blocked_write
    latest = tmp_path / "logs/latest.txt"
    writer.start_segment(latest, None, trace=False)
    folder = tmp_path / "recordings"
    key = writer.start_recording(folder, 1, context())
    writer.event("blocked", {}, trace=True)
    assert entered.wait(10), "Recording writer did not reach the blocked sink"
    writer.event("before-summary", {})
    writer.event("stream_summary", {"counts": {}}, priority=True)
    writer.event("after-summary", {})
    writer.disable()
    assert writer.health()["queued"] <= writer.capacity
    release.set()
    finish(writer, folder)
    rows = [
        json.loads(line)
        for line in (folder / key / "snimak.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    events = [row["event"] for row in rows]
    assert (
        events.index("before-summary")
        < events.index("stream_summary")
        < events.index("after-summary")
    )
    assert writer.health()["dropped"].get("logging_disabled", 0) == 2
    assert writer.stop()
    from pogled_assist.log_reader import summarize

    ordinary = summarize(next((latest.parent / "diagnostics").glob("*.jsonl")))
    assert not ordinary["complete"]
    assert ordinary["logging_health_process_cumulative"]["dropped"]["logging_disabled"] == 2


def test_finishing_remains_published_until_final_file_work_acknowledges(
    writer, tmp_path, monkeypatch
):
    entered, release = threading.Event(), threading.Event()
    original = RecordingStore.prune

    def blocked(store, **kwargs):
        entered.set()
        release.wait()
        return original(store, **kwargs)

    monkeypatch.setattr(RecordingStore, "prune", blocked)
    folder = tmp_path / "recordings"
    writer.start_recording(folder, 1, context())
    writer.stop_recording()
    try:
        assert entered.wait(10), "Recording finalization did not reach retention cleanup"
        state = writer.recording_status()
        assert state["busy"] and state["state"] == "finishing" and not state["complete"]
        assert writer.start_recording(folder, 1, context()) is None
    finally:
        release.set()
    assert finish(writer, folder, stop=False)["complete"]


def test_restart_recovers_over_budget_crash_remnants_without_touching_active_capture(
    writer, tmp_path, monkeypatch
):
    folder = tmp_path / "recordings"
    monkeypatch.setattr(module, "MAX_RECORDINGS", 100)
    ids = []
    for _ in range(3):
        ids.append(writer.start_recording(folder, 1, context()))
        finish(writer, folder)
    metadata = folder / ids[-1] / "recording.json"
    value = json.loads(metadata.read_bytes())
    value.update(state="recording", reason=None, ended_at=None, complete=False)
    module.atomic_bytes(metadata, module.json_bytes(value))
    trace = folder / ids[-1] / "snimak.jsonl"
    trace.write_text(
        "\n".join(trace.read_text(encoding="utf-8").splitlines()[:-1]) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(module, "MAX_RECORDINGS", 2)
    active = writer.start_recording(folder, 1, context())
    wait_for(lambda: writer.recording_status()["state"] == "recording")
    store = RecordingStore(folder)
    rows = store.recover_and_load()
    assert len(rows) == 2 and active not in {row["id"] for row in rows}
    recovered = next(row for row in rows if row["id"] == ids[-1])
    assert recovered["state"] == "interrupted" and recovered["duration_seconds"] is None
    with pytest.raises(ValueError, match="active"):
        store.export(active, tmp_path / "active.zip")
    assert (folder / active / "snimak.jsonl").exists()
    finish(writer, folder)


def test_manual_shutdown_returns_without_waiting_for_a_blocked_file(
    writer, tmp_path, blocked_write
):
    entered, release = blocked_write
    folder = tmp_path / "recordings"
    writer.start_recording(folder, 1, context())
    writer.event("blocked", {}, trace=True)
    assert entered.wait(10), "Recording writer did not reach the blocked sink"
    assert not writer.stop(timeout=0.01)
    release.set()
    assert writer.stop()
    item = finish(writer, folder, stop=False)
    assert item["reason"] == "shutdown" and not item["complete"]
