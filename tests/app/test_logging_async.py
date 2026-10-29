from __future__ import annotations

import faulthandler
import json
import logging
import os
import threading
import time
from pathlib import Path

import pytest

from pogled_assist import logging_setup
from pogled_assist.log_transport import LogWriter, bounded_copy


def read_events(latest):
    return [
        json.loads(line)
        for file in (latest.parent / "diagnostics").glob("*.jsonl")
        for line in file.read_text().splitlines()
    ]


@pytest.mark.parametrize("failed_channel", ["text", "json", "both"])
def test_initial_directory_failure_recovers_outputs_and_retention_reservations(
    tmp_path, monkeypatch, qtbot, failed_channel
):
    from pogled_assist import log_reservations

    latest = tmp_path / "logs/latest.txt"
    latest.parent.mkdir()
    folders = {
        "text": {latest.parent},
        "json": {latest.parent / "diagnostics"},
        "both": {latest.parent, latest.parent / "diagnostics"},
    }[failed_channel]
    denied = threading.Event()
    denied.set()
    mkdir = Path.mkdir

    def fail_directory(path, *args, **kwargs):
        if denied.is_set() and path in folders:
            raise OSError("Synthetic directory failure")
        return mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_directory)
    writer = LogWriter()
    try:
        writer.start_segment(latest, None, trace=False)
        expected = {"text", "json"} if failed_channel == "both" else {failed_channel}
        qtbot.waitUntil(
            lambda: expected.issubset(
                gap["channel"] for gap in writer.persistence_status()["failures"]
            )
        )
        denied.clear()
        qtbot.waitUntil(
            lambda: writer._output._file is not None and writer._output._json is not None,
            timeout=5000,
        )
        assert writer.event("after_storage_recovery", {}, priority=True)
        writer.record(logging.makeLogRecord({"msg": "after storage recovery", "levelno": 20}))
        qtbot.waitUntil(lambda: not writer.persistence_status()["failures"])
        paths = (writer._output._text_path, writer._output._json_path)
        assert all(path is not None for path in paths)
        assert all(
            log_reservations._RESERVATIONS.get(log_reservations._path_key(path)) == 1
            for path in paths
        )
        gaps = writer.persistence_status()["gaps"]
        assert all(gap["recovered_at"] is not None for gap in gaps)
    finally:
        denied.clear()
        assert writer.stop()
    assert "after storage recovery" in latest.read_text()
    names = [item["event"] for item in read_events(latest)]
    assert "after_storage_recovery" in names
    if failed_channel in {"json", "both"}:
        assert "persistence_recovered" in names
    assert all(
        log_reservations._path_key(path) not in log_reservations._RESERVATIONS for path in paths
    )


def test_blocked_console_does_not_block_log_producer(monkeypatch, tmp_path):
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    armed = threading.Event()

    class Console:
        def write(self, text):
            if armed.is_set():
                entered.set()
                release.wait()
            return len(text)

        def flush(self):
            pass

    monkeypatch.setattr(logging_setup.sys, "__stdout__", Console())
    monkeypatch.setattr(logging_setup, "get_project_root", lambda: tmp_path)
    logging_setup.setup_application_logging()
    armed.set()

    def produce():
        logging.getLogger("test.input").info("tracking continues")
        finished.set()

    producer = threading.Thread(target=produce)
    try:
        producer.start()
        assert entered.wait(10), "the real console sink must be blocked"
        if not finished.wait(10):
            faulthandler.dump_traceback()
            pytest.fail("Input waited while the console sink was blocked")
    finally:
        release.set()
        producer.join(10)
        logging_setup._restore_standard_streams()
        logging_setup._clear_root_handlers()
        assert not producer.is_alive(), "Log producer did not stop after releasing the sink"


def test_blocked_file_overflow_is_bounded_and_shutdown_has_a_deadline(tmp_path, monkeypatch):
    from pathlib import Path

    entered, release = threading.Event(), threading.Event()
    real_open = Path.open

    class File:
        def __init__(self, stream):
            self.stream = stream

        def write(self, text):
            if "block-file" in text:
                entered.set()
                release.wait()
            return self.stream.write(text)

        def flush(self):
            self.stream.flush()

        def close(self):
            self.stream.close()

    def open_file(path, *args, **kwargs):
        stream = real_open(path, *args, **kwargs)
        return File(stream) if path.name == "latest.txt" else stream

    monkeypatch.setattr(Path, "open", open_file)
    writer = LogWriter(capacity=12)
    latest = tmp_path / "logs/latest.txt"
    writer.start_segment(latest, None, trace=True)
    writer.record(logging.makeLogRecord({"msg": "block-file", "args": (), "levelno": 20}))
    try:
        assert entered.wait(10), "File writer did not reach the blocked sink"
        for index in range(2000):
            writer.event("native_gaze", {"sample": index}, trace=True)
        health = writer.health()
        assert health["queued"] <= 12
        assert health["dropped"]["event"] >= 1990
        assert writer.event("stream_summary", {}, priority=True)
        assert not writer.stop(timeout=0.01)
    finally:
        release.set()
        assert writer.stop(timeout=2)
    events = read_events(latest)
    assert any(item["event"] == "session_end" for item in events)
    summary = next(item for item in events if item["event"] == "stream_summary")
    assert summary["logging_health"]["dropped"]["event"] >= 1990


def test_queued_data_is_a_bounded_copy_without_arbitrary_object_formatting():
    class Hostile:
        def __repr__(self):
            raise AssertionError("producer must not format live objects")

    data = {"mutable": [1, 2], "huge": "x" * 1000000, "live": Hostile()}
    snapshot = bounded_copy(data)
    data["mutable"].append(3)
    assert snapshot["mutable"] == (1, 2)
    assert len(snapshot["huge"]) < 8192
    assert len(repr(snapshot)) < 8192


def test_runtime_segments_archive_on_writer_and_discard_disabled_backlog(tmp_path):
    entered, release = threading.Event(), threading.Event()

    class Console:
        def write(self, text):
            entered.set()
            release.wait()

        def flush(self):
            pass

    latest = tmp_path / "logs/latest.txt"
    writer = LogWriter()
    writer.start_segment(latest, Console(), trace=False)
    writer.record(logging.makeLogRecord({"msg": "first segment", "args": (), "levelno": 20}))
    try:
        assert entered.wait(10), "Segment writer did not reach the blocked sink"
        writer.event("must_be_discarded", {})
        writer.disable()
        writer.start_segment(latest, None, trace=False)
        writer.event("new_segment", {})
    finally:
        release.set()
        assert writer.stop()
    assert "first segment" in next(latest.parent.glob("2*.txt")).read_text()
    assert "first segment" not in latest.read_text()
    events = read_events(latest)
    assert not any(item["event"] == "must_be_discarded" for item in events)
    assert len({item["session_id"] for item in events}) == 2
    assert any(item["event"] == "new_segment" for item in events)


def test_writer_io_errors_do_not_escape_or_recurse(tmp_path, monkeypatch):
    from pathlib import Path

    def fail(*_args, **_kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(Path, "open", fail)
    writer = LogWriter()
    writer.start_segment(tmp_path / "logs/latest.txt", None, trace=True)
    for _ in range(100):
        writer.event("native_gaze", {})
    assert writer.stop()
    assert writer.health()["writer_errors"] >= 1


def test_archive_failure_preserves_old_log_and_keeps_structured_logging(tmp_path, monkeypatch):

    def fail(*_args, **_kwargs):
        raise OSError("archive unavailable")

    latest = tmp_path / "logs/latest.txt"
    latest.parent.mkdir()
    latest.write_text("only copy of the previous session\n", encoding="utf-8")
    monkeypatch.setattr(os, "replace", fail)
    writer = LogWriter()
    writer.start_segment(latest, None, trace=False)
    writer.event("new_session_observation", {})
    assert writer.stop()
    assert latest.read_text().startswith("only copy of the previous session\n")
    events = read_events(latest)
    assert any(item["event"] == "new_session_observation" for item in events)
    end = next(item for item in events if item["event"] == "session_end")
    assert end["logging_health"]["writer_errors"] >= 1


def test_snapshot_crossing_a_logging_toggle_cannot_enter_the_new_session(tmp_path, monkeypatch):
    from pogled_assist import log_transport

    latest = tmp_path / "logs/latest.txt"
    writer = LogWriter()
    writer.start_segment(latest, None, trace=False)
    real_copy = log_transport.bounded_copy

    def toggle_during_copy(fields):
        snapshot = real_copy(fields)
        writer.disable()
        monkeypatch.setattr(log_transport, "bounded_copy", real_copy)
        writer.start_segment(latest, None, trace=False)
        return snapshot

    monkeypatch.setattr(log_transport, "bounded_copy", toggle_during_copy)
    assert not writer.event("old_observation", {})
    assert writer.event("new_observation", {})
    assert writer.stop()
    events = read_events(latest)
    assert not any(item["event"] == "old_observation" for item in events)
    assert any(item["event"] == "new_observation" for item in events)
    assert writer.health()["dropped"]["old_segment"] == 1


def test_bounded_payloads_report_truncation_in_session_health(tmp_path):
    latest = tmp_path / "logs/latest.txt"
    writer = LogWriter()
    writer.start_segment(latest, None, trace=True)
    writer.event("oversized", {"values": "x" * 100000}, trace=True)
    assert writer.stop()
    events = read_events(latest)
    oversized = next(item for item in events if item["event"] == "oversized")
    assert oversized["data"]["_snapshot_truncated"]
    assert isinstance(oversized["data"]["values"], str)
    end = next(item for item in events if item["event"] == "session_end")
    assert end["logging_health"]["bounded_snapshots"] == 1


def test_trace_limit_survives_rotation_while_basic_logging_continues(tmp_path, monkeypatch):
    from pogled_assist import log_transport

    monkeypatch.setattr(log_transport, "TRACE_BYTES", 100)
    monkeypatch.setattr(log_transport, "SEGMENT_BYTES", 16000)
    latest = tmp_path / "logs/latest.txt"
    writer = LogWriter()
    writer.start_segment(latest, None, trace=True)
    for _ in range(15):
        writer.event("native_gaze", {"values": "x" * 1000}, trace=True)
    for _ in range(15):
        writer.event("basic", {"values": "x" * 1000})
    assert writer.stop()
    names = [record["event"] for record in read_events(latest)]
    assert "trace_limit" in names
    assert "session_limit" not in names
    assert "segment_context" in names
    assert len(list((latest.parent / "diagnostics").glob("*.jsonl"))) > 1
    assert names.count("native_gaze") == 1
    assert "basic" in names


def test_trace_expires_even_while_writer_cannot_run(tmp_path):
    writer = LogWriter()
    writer.start_segment(tmp_path / "logs/latest.txt", None, trace=True)
    writer._trace_until = time.monotonic() - 1
    assert not writer.trace
    assert not writer.event("native_gaze", {}, trace=True)
    assert writer.event("stream_summary", {}, priority=True)
    assert writer.stop()


def test_logging_disabled_overrides_trace_and_creates_no_files(monkeypatch, tmp_path):
    monkeypatch.setenv("POGLED_ASSIST_GAZE_DIAGNOSTICS", "trace")
    monkeypatch.setattr(logging_setup, "get_project_root", lambda: tmp_path)
    try:
        logging_setup.set_application_logging_enabled(False)
        assert logging_setup.diagnostic_writer() is None
        assert not (tmp_path / "logs").exists()
    finally:
        logging.disable(logging.NOTSET)
        logging_setup._clear_root_handlers()


def test_unhandled_exception_captures_type_and_stack_without_locals(monkeypatch, tmp_path):
    monkeypatch.setattr(logging_setup, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(logging_setup.sys, "__stdout__", None)
    try:
        latest = logging_setup.setup_application_logging()
        try:
            raise ValueError("private composed message")
        except ValueError:
            logging_setup._log_unhandled_exception(*logging_setup.sys.exc_info())
        logging_setup.shutdown_application_logging()
        content = latest.read_text()
        assert "ValueError" in content
        assert "test_unhandled_exception" in content
        assert "private composed message" not in content
    finally:
        logging_setup._restore_standard_streams()
        logging_setup._clear_root_handlers()


def test_old_trace_limit_cannot_disable_a_new_trace_session(tmp_path, monkeypatch):
    from pogled_assist import log_transport

    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr(log_transport, "TRACE_BYTES", 10)
    from pogled_assist.log_output import OrdinaryOutput

    real_write = OrdinaryOutput._write_event

    def wait_before_limit(self, sequence, data):
        if data[0] == "old_trigger":
            entered.set()
            release.wait()
        real_write(self, sequence, data)

    monkeypatch.setattr(OrdinaryOutput, "_write_event", wait_before_limit)
    writer = LogWriter()
    latest = tmp_path / "logs/latest.txt"
    writer.start_segment(latest, None, trace=True)
    writer.event("old_trace", {}, trace=True)
    writer.event("old_trigger", {}, trace=True)
    try:
        assert entered.wait(10), "Trace writer did not reach the blocked event"
        writer.disable()
        writer.start_segment(latest, None, trace=True)
        assert writer.event("new_trace", {}, trace=True)
    finally:
        release.set()
        assert writer.stop()
    events = read_events(latest)
    old = next(item for item in events if item["event"] == "old_trace")
    new = next(item for item in events if item["event"] == "new_trace")
    assert old["session_id"] != new["session_id"]


def test_geometry_batch_keeps_field_names_and_all_four_target_rectangles():
    targets = [
        {
            "target_id": str(index) * 32,
            "logical_bounds": (400, 250, 480, 200),
            "visible": True,
            "enabled": True,
        }
        for index in range(4)
    ]
    snapshot = bounded_copy({"context_id": "x" * 32, "kind": "letter", "targets": targets})
    assert not snapshot.get("_snapshot_truncated")
    assert len(snapshot["targets"]) == 4
    assert all(target["logical_bounds"] == (400, 250, 480, 200) for target in snapshot["targets"])


def test_closing_summaries_share_the_queue_bound_across_rapid_toggles(tmp_path):
    entered, release = threading.Event(), threading.Event()

    class Console:
        def write(self, _text):
            entered.set()
            release.wait()

        def flush(self):
            pass

    writer = LogWriter(capacity=8)
    latest = tmp_path / "logs/latest.txt"
    writer.start_segment(latest, Console(), trace=False)
    writer.record(logging.makeLogRecord({"msg": "blocked", "args": (), "levelno": 20}))
    try:
        assert entered.wait(10), "Summary writer did not reach the blocked sink"
        for index in range(20):
            writer.event("stream_summary", {"counts": {"sample": index}}, priority=True)
            writer.disable()
            assert writer.health()["queued"] <= writer.capacity
            writer.start_segment(latest, None, trace=False)
            assert writer.health()["queued"] <= writer.capacity
        assert writer.health()["dropped"], "bounded overflow must be reported"
    finally:
        release.set()
        assert writer.stop()
    assert writer.health()["queued"] == 0
    assert writer.health()["writer_errors"] == 0
    events = read_events(latest)
    assert any(event["event"] == "stream_summary" for event in events)
    sessions_with_summaries = {
        event["session_id"] for event in events if event["event"] == "stream_summary"
    }
    for session in sessions_with_summaries:
        names = [event["event"] for event in events if event["session_id"] == session]
        assert names.count("session_start") == names.count("session_end") == 1
