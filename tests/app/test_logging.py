from __future__ import annotations

import json
import logging
import sys
import threading

from pogled_assist import logging_setup


def test_stream_to_logger_buffers_lines_and_exposes_file_interface():
    records = []

    class ListHandler(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    class Fallback:
        def fileno(self):
            return 7

    logger = logging.getLogger("test.stream")
    logger.handlers = [ListHandler()]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    stream = logging_setup.StreamToLogger(logger, logging.INFO, Fallback())

    assert stream.write("first\npartial") == len("first\npartial")
    stream.flush()

    assert records == ["first", "partial"]
    assert stream.fileno() == 7
    assert stream.encoding == "utf-8"
    assert stream.errors == "replace"
    assert stream.isatty() is False
    assert stream.writable() is True


def test_logging_setting_and_archive_helpers(monkeypatch, tmp_path):
    monkeypatch.setattr(logging_setup, "get_project_root", lambda: tmp_path)
    settings = tmp_path / "data" / "app_settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"gaze": {"logging_enabled": "off"}}), encoding="utf-8")
    assert logging_setup._read_logging_enabled_setting() is False

    latest = tmp_path / "logs" / "latest.txt"
    latest.parent.mkdir()
    latest.write_text("old log", encoding="utf-8")
    archived = logging_setup._archive_latest_log(latest)
    assert archived is not None
    assert archived.read_text(encoding="utf-8") == "old log"
    assert latest.read_text(encoding="utf-8") == "old log"


def test_setup_application_logging_handles_missing_standard_streams(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "__stdout__", None)
    monkeypatch.setattr(sys, "__stderr__", None)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(logging_setup, "get_project_root", lambda: tmp_path)

    try:
        latest_log = logging_setup.setup_application_logging()
        root_logger = logging.getLogger()
        stream_handlers = [
            handler
            for handler in root_logger.handlers
            if isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, logging.FileHandler)
        ]
        assert not stream_handlers

        print("hello from stdout")
        sys.stderr.write("hello from stderr\n")
        logging.shutdown()

        content = latest_log.read_text(encoding="utf-8")
        assert "Logging initialized." in content
        assert "hello from stdout" in content
        assert "hello from stderr" in content
    finally:
        logging_setup._restore_standard_streams()
        logging_setup._clear_root_handlers()


def test_stream_to_logger_reentrancy_protection():
    calls = []

    class ReentrantLogger:
        def log(self, level, message):
            calls.append((level, message))
            stream.write("recursive message\n")

    logger = ReentrantLogger()
    stream = logging_setup.StreamToLogger(logger, logging.INFO, fallback_stream=None)
    stream.write("initial message\n")

    assert calls == [(logging.INFO, "initial message")]


def test_concurrent_stream_writes_never_write_to_the_fallback():
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    calls = []
    fallback_calls = []

    class Logger:
        def log(self, _level, text):
            if text == "worker message":
                entered.set()
                release.wait(5)
            calls.append(text)

    class Fallback:
        def write(self, text):
            fallback_calls.append(text)

        def flush(self):
            fallback_calls.append("flush")

    stream = logging_setup.StreamToLogger(Logger(), logging.INFO, Fallback())
    worker = threading.Thread(target=lambda: stream.write("worker message\n"))

    def write_ui_message():
        stream.write("UI message\n")
        stream.flush()
        returned.set()

    ui = threading.Thread(target=write_ui_message)
    try:
        worker.start()
        assert entered.wait(1)
        ui.start()
        assert returned.wait(0.5), "a competing log call must not wait for the first producer"
        assert calls == ["UI message"]
        assert fallback_calls == []
    finally:
        release.set()
        worker.join(2)
        if ui.ident is not None:
            ui.join(2)
    assert sorted(calls) == ["UI message", "worker message"]


def test_stream_without_newlines_has_a_bounded_buffer_and_keeps_all_text():
    calls = []

    class Logger:
        def log(self, _level, text):
            calls.append(text)

    stream = logging_setup.StreamToLogger(Logger(), logging.INFO, None)
    text = "x" * 100_000
    assert stream.write(text) == len(text)
    assert len(stream._buffer) < logging_setup.MAX_STREAM_CHARS
    stream.flush()
    assert "".join(calls) == text
    assert all(len(line) <= logging_setup.MAX_STREAM_CHARS for line in calls)


def test_recursive_stream_loss_is_counted_without_console_io(monkeypatch):
    from pogled_assist.log_transport import LogWriter

    writer = LogWriter()
    writer.start_segment(None, None, trace=False)
    monkeypatch.setattr(logging_setup, "_writer", writer)

    class Logger:
        def log(self, _level, _text):
            stream.write("recursive output\n")

    stream = logging_setup.StreamToLogger(Logger(), logging.INFO, None)
    try:
        stream.write("initial message\n")
        assert writer.health()["dropped"]["stream_recursive"] == 1
    finally:
        assert writer.stop()
