from __future__ import annotations

import json
import logging
import sys

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
