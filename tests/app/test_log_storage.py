"""Continuous files, shared retention and offline copies use synthetic data."""

import json
import logging
import os
import threading
import time
import tracemalloc
from zipfile import ZipFile

import pytest

from pogled_assist import diagnostic_recording as recording
from pogled_assist import log_transport
from pogled_assist.log_reader import summarize


def wait_for(predicate):
    deadline = time.perf_counter() + 10
    while not predicate():
        assert time.perf_counter() < deadline
        threading.Event().wait(0.005)


def context():
    return recording.recording_context({}, {}, simulated=True)


def test_rotation_continues_ordinary_and_manual_without_changing_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr(log_transport, "SEGMENT_BYTES", 4096)
    monkeypatch.setattr(recording, "SEGMENT_BYTES", 4096)
    writer = log_transport.LogWriter(capacity=1024)
    root = tmp_path / "logs"
    writer.start_segment(root / "latest.txt", None, trace=False)
    key = writer.start_recording(root / "recordings", 1, context())
    deadline = writer._recording.deadline
    try:
        for _ in range(90):
            writer.event("selection_end", {"reason": "test", "padding": "x" * 150}, priority=True)
            writer.record(logging.makeLogRecord({"msg": "x" * 180, "levelno": 20}))
        wait_for(lambda: not writer._queue)
        assert writer._recording.deadline == deadline
        writer.stop_recording()
        wait_for(lambda: not writer.recording_status()["busy"])
    finally:
        assert writer.stop()
    assert len(list((root / "diagnostics").glob("*.jsonl"))) > 2
    assert len(list(root.glob("*.txt"))) > 2
    assert len(list((root / "recordings" / key).glob("*.jsonl"))) > 2
    report = summarize(root)
    assert report["events"]["selection_end"] == 90
    assert report["deduplicated_observations"] >= 90
    item = recording.RecordingStore(root / "recordings").inspect(key)
    assert item["complete"]
    destination = tmp_path / "support.zip"
    recording.RecordingStore(root / "recordings").export(key, destination)
    with ZipFile(destination) as archive:
        assert len([n for n in archive.namelist() if n.endswith(".jsonl")]) > 2


def test_shared_budget_deletes_oldest_ordinary_and_protects_exports(tmp_path, monkeypatch):
    root = tmp_path / "logs"
    folder = root / "diagnostics"
    folder.mkdir(parents=True)
    old = folder / ("a" * 32 + ".jsonl")
    newer = folder / ("b" * 32 + ".jsonl")
    old.write_text("{}\n" * 80)
    newer.write_text("{}\n" * 80)
    unknown = folder / "unrelated.jsonl"
    unknown.write_text("keep")
    store = recording.RecordingStore(root / "recordings")
    monkeypatch.setattr(recording, "disk_free", lambda _root: 20_000_000_000)
    store.reserve_path(old)
    state = store.maintain(budget_bytes=300)
    assert old.exists() and not newer.exists() and unknown.exists()
    assert state["usage_bytes"] == old.stat().st_size
    store.release_path(old)
    state = store.maintain(budget_bytes=0)
    assert not old.exists()
    assert state["pruned_items"] >= 1


def test_writer_finish_does_not_wait_for_store_inspection_lock(tmp_path):
    writer = log_transport.LogWriter()
    try:
        writer.start_recording(tmp_path / "recordings", 1, context())
        wait_for(lambda: writer.recording_status()["state"] == "recording")
        with recording._STORE_LOCK:
            writer.stop_recording()
            wait_for(lambda: not writer.recording_status()["busy"])
    finally:
        assert writer.stop()


def test_low_space_cleanup_uses_hysteresis_and_preserves_exclusions(tmp_path, monkeypatch):
    root = tmp_path / "logs"
    root.mkdir()
    old = root / "20261001_120000_123456.txt"
    old.write_bytes(b"old")
    support = root / "support.zip"
    support.write_bytes(b"zip")
    report = root / "gaze-check"
    report.mkdir()
    (report / "report.json").write_bytes(b"check")
    free = [recording.LOW_SPACE_BYTES - 1]
    monkeypatch.setattr(recording, "disk_free", lambda _root: free[0])
    store = recording.RecordingStore(root / "recordings")
    state = store.maintain()
    assert not old.exists() and support.read_bytes() == b"zip"
    assert (report / "report.json").exists()
    assert state["low_space"]
    free[0] = (recording.LOW_SPACE_BYTES + recording.RECOVERY_SPACE_BYTES) // 2
    assert store.maintain()["low_space"]
    free[0] = recording.RECOVERY_SPACE_BYTES
    assert not store.maintain()["low_space"]


def test_failed_rotation_preserves_source_and_reports_live_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(log_transport, "SEGMENT_BYTES", 800)
    writer = log_transport.LogWriter()
    latest = tmp_path / "logs/latest.txt"
    writer.start_segment(latest, None, trace=False)
    writer.record(logging.makeLogRecord({"msg": "original", "levelno": 20}))
    wait_for(lambda: writer._output._file is not None)

    def fail(*_args):
        raise OSError("synthetic move failure")

    monkeypatch.setattr(os, "replace", fail)
    for _ in range(10):
        writer.record(logging.makeLogRecord({"msg": "x" * 180, "levelno": 20}))
    assert writer.stop()
    assert "original" in latest.read_text()
    assert any(
        item["channel"] == "text_rotation" for item in writer.persistence_status()["failures"]
    )


def test_failed_deletion_reports_real_usage_and_preserves_unsafe_paths(tmp_path, monkeypatch):
    root = tmp_path / "logs"
    root.mkdir()
    old = root / "20261001_120000_123456.txt"
    old.write_bytes(b"keep")
    store = recording.RecordingStore(root / "recordings")
    unlink = type(old).unlink

    def fail(path, *args, **kwargs):
        if path == old:
            raise PermissionError("synthetic deletion failure")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(type(old), "unlink", fail)
    state = store.maintain(budget_bytes=0)
    assert old.exists() and state["usage_bytes"] == 4
    assert state["state"] == "cleanup_failed"


def test_failed_deletions_still_bound_the_work_in_one_maintenance_pass(tmp_path, monkeypatch):
    root = tmp_path / "logs"
    root.mkdir()
    for index in range(130):
        (root / f"20261001_120000_{index:06}.txt").write_bytes(b"keep")
    attempts = []
    unlink = type(root).unlink

    def fail(path, *args, **kwargs):
        if path.parent == root:
            attempts.append(path.name)
            raise PermissionError("Synthetic deletion failure")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(type(root), "unlink", fail)
    monkeypatch.setattr(recording, "disk_free", lambda _root: 20_000_000_000)
    state = recording.RecordingStore(root / "recordings").maintain(budget_bytes=0)
    assert len(attempts) == 128
    assert state["usage_bytes"] == 130 * 4
    assert state["state"] == "cleanup_failed"


def test_cleanup_rechecks_reparse_points_before_deletion(tmp_path, monkeypatch):
    root = tmp_path / "logs"
    root.mkdir()
    path = root / "20261001_120000_123456.txt"
    path.write_bytes(b"preserve")
    safe = recording._safe_storage_path
    calls = [0]

    def changed(candidate):
        if candidate == path:
            calls[0] += 1
            if calls[0] > 1:
                return False
        return safe(candidate)

    monkeypatch.setattr(recording, "_safe_storage_path", changed)
    recording.RecordingStore(root / "recordings").maintain(budget_bytes=0)
    assert path.read_bytes() == b"preserve"


def test_reader_marks_missing_segments_without_claiming_pruning(tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    base = dict(schema_version=1, session_id="session", process_instance="process", data={})
    (folder / "session.jsonl").write_text(json.dumps({**base, "event": "session_start"}) + "\n")
    (folder / "session.part-000002.jsonl").write_text(
        json.dumps({**base, "event": "session_end"}) + "\n"
    )
    result = summarize(folder)
    assert not result["complete"]
    assert result["parse_warnings"][0]["reason"] == "missing_or_duplicate_segments_unknown_cause"
    assert result["lifecycle_complete"]


def test_reader_bounds_malformed_record_details_and_does_not_mix_process_clocks(tmp_path):
    for process in ("p1", "p2"):
        base = dict(
            schema_version=1, session_id=process, process_instance=process, monotonic_s=1, data={}
        )
        (tmp_path / f"{process}.jsonl").write_text(
            json.dumps({**base, "event": "session_start"})
            + "\n"
            + "invalid\n" * 500
            + json.dumps({**base, "event": "session_end"})
            + "\n"
        )
    result = summarize(tmp_path)
    assert len(result["processes"]) == 2 and not result["complete"]
    assert all(
        len(item["parse_warnings"]) == 200 and item["warnings_truncated"]
        for item in result["sessions"]
    )


def test_recording_above_former_size_cap_exports_with_bounded_memory(tmp_path, monkeypatch):
    from pogled_assist import build_info

    root = tmp_path / "recordings"
    item_context = context()
    item_context["build"] = build_info.resolve_build_identity()
    item = recording.Recording("c" * 32, root, 0, time.time(), 10, item_context)
    sink = recording.RecordingSink(item, "synthetic-process")
    event = recording.RecordingEvent("synthetic", {"padding": "x" * 3000}, 1, time.time())
    for _ in range(11000):
        assert sink.write(event)
    assert item.bytes_written > 32 * 1024 * 1024
    item.end_present = sink.write(
        recording.RecordingEvent(
            "session_end", {"reason": "manual", "recording_health": item.health()}, 2, time.time()
        ),
        footer=True,
    )
    sink.close()
    item.complete, item.state, item.reason = True, "completed", "manual"
    recording.atomic_bytes(root / item.id / "recording.json", recording.json_bytes(item.snapshot()))
    store = recording.RecordingStore(root)
    # Routine history does not parse payloads, even for a recording over 32 MiB.
    with monkeypatch.context() as patch:
        patch.setattr(recording, "summarize", lambda _path: pytest.fail("history parsed payload"))
        assert store.load()[0]["bytes"] == item.bytes_written
    tracemalloc.start()
    try:
        store.export(item.id, tmp_path / "large.zip")
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 8 * 1024 * 1024
    with ZipFile(tmp_path / "large.zip") as archive:
        assert len([n for n in archive.namelist() if n.endswith(".jsonl")]) >= 3
