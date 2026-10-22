"""Application logging setup."""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import sys
import threading
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from types import TracebackType

from .log_transport import LogWriter, QueueLogHandler

LOGGER_NAME = "pogled_assist"
LOG_DIR_NAME = "logs"
LATEST_LOG_NAME = "latest.txt"
LOG_ROOT_ENV = "POGLED_ASSIST_LOG_ROOT"
SETTINGS_FILE = "app_settings.json"
MAX_STREAM_CHARS = 2048

_qt_message_handler = None
_writer: LogWriter | None = None
_queue_handler: QueueLogHandler | None = None


class StreamToLogger:
    """File-like stream that sends stdout/stderr writes into logging."""

    def __init__(
        self,
        logger: logging.Logger,
        level: int,
        fallback_stream,
    ) -> None:
        self._logger = logger
        self._level = level
        self._fallback_stream = fallback_stream
        self._buffer = ""
        self._buffer_lock = threading.Lock()
        self._local = threading.local()

    def write(self, message: object) -> int:
        text = str(message)
        if not text:
            return 0

        if getattr(self._local, "in_write", False):
            self._note_drop("stream_recursive")
            return len(text)

        self._local.in_write = True
        try:
            for start in range(0, len(text), MAX_STREAM_CHARS):
                # Never hold the buffer lock while a logging handler runs.
                # Another producer can proceed even if that handler stalls.
                if not self._buffer_lock.acquire(blocking=False):
                    self._note_drop("stream_buffer_busy")
                    continue
                try:
                    parts = (self._buffer + text[start : start + MAX_STREAM_CHARS]).split("\n")
                    self._buffer = parts.pop()
                    if len(self._buffer) >= MAX_STREAM_CHARS:
                        parts.append(self._buffer[:MAX_STREAM_CHARS])
                        self._buffer = self._buffer[MAX_STREAM_CHARS:]
                finally:
                    self._buffer_lock.release()
                for line in parts:
                    self._write_line(line)
        finally:
            self._local.in_write = False
        return len(text)

    def flush(self) -> None:
        if getattr(self._local, "in_write", False):
            return
        if not self._buffer_lock.acquire(blocking=False):
            self._note_drop("stream_buffer_busy")
            return
        try:
            line = self._buffer
            self._buffer = ""
        finally:
            self._buffer_lock.release()
        self._local.in_write = True
        try:
            self._write_line(line)
        finally:
            self._local.in_write = False

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        try:
            if self._fallback_stream is not None:
                return self._fallback_stream.fileno()
        except Exception:
            pass
        return -1

    @property
    def encoding(self) -> str:
        return "utf-8"

    @property
    def errors(self) -> str:
        return "replace"

    def writable(self) -> bool:
        return True

    def close(self) -> None:
        self.flush()

    def _write_line(self, line: str) -> None:
        if line.strip():
            line = line.rstrip()
            for start in range(0, len(line), MAX_STREAM_CHARS):
                self._logger.log(self._level, line[start : start + MAX_STREAM_CHARS])

    def _note_drop(self, reason: str) -> None:
        writer = diagnostic_writer()
        if writer is not None:
            writer.note_drop(reason)


def setup_application_logging() -> Path:
    """Create a fresh latest log file and route app output into it."""

    return set_application_logging_enabled(_read_logging_enabled_setting())


def set_application_logging_enabled(enabled: bool) -> Path:
    """Apply runtime logging state and return the latest-log path."""

    global _writer, _queue_handler

    project_root = get_project_root()
    log_dir = project_root / LOG_DIR_NAME
    latest_log = log_dir / LATEST_LOG_NAME

    _flush_diagnostic_summaries()

    if not enabled:
        if _writer is not None:
            _writer.disable()
        _disable_python_logging()
        return latest_log

    logging.disable(logging.NOTSET)
    _restore_standard_streams()
    _clear_root_handlers(stop_writer=False)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    console_stream = sys.__stdout__ if sys.__stdout__ is not None else sys.__stderr__
    if _writer is None or _writer.finished:
        _writer = LogWriter()
        _queue_handler = QueueLogHandler(_writer)
    _writer.start_segment(
        latest_log,
        console_stream,
        trace=os.environ.get("POGLED_ASSIST_GAZE_DIAGNOSTICS", "").lower() == "trace",
    )
    root_logger.addHandler(_queue_handler)

    logging.captureWarnings(True)
    sys.excepthook = _log_unhandled_exception
    sys.stdout = StreamToLogger(logging.getLogger("stdout"), logging.INFO, sys.__stdout__)
    sys.stderr = StreamToLogger(logging.getLogger("stderr"), logging.ERROR, sys.__stderr__)

    logger = logging.getLogger(LOGGER_NAME)
    logger.info("Logging initialized.")
    logger.info("Project root: %s", project_root)
    logger.info("Latest log: %s", latest_log)
    logger.info("Python executable: %s", sys.executable)
    logger.info("Python version: %s", sys.version.replace("\n", " "))
    logger.info("Platform: %s", platform.platform())

    return latest_log


def _disable_python_logging() -> None:
    _restore_standard_streams()
    _clear_root_handlers(stop_writer=False)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.CRITICAL + 1)
    root_logger.addHandler(logging.NullHandler())
    logging.captureWarnings(False)
    logging.disable(logging.CRITICAL)
    sys.excepthook = sys.__excepthook__


def _clear_root_handlers(*, stop_writer: bool = True) -> None:
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        if isinstance(handler, QueueLogHandler):
            continue
        with suppress(Exception):
            handler.flush()
        with suppress(Exception):
            handler.close()
    if stop_writer:
        shutdown_application_logging()


def diagnostic_writer() -> LogWriter | None:
    return _writer if _writer is not None and _writer.enabled else None


def recording_writer() -> LogWriter:
    """Share the persistent transport without enabling normal logging or changing settings."""
    global _writer, _queue_handler
    if _writer is None or _writer.finished:
        _writer = LogWriter()
        _queue_handler = QueueLogHandler(_writer)
    return _writer


def shutdown_application_logging() -> None:
    global _writer, _queue_handler
    _flush_diagnostic_summaries()
    if _queue_handler is not None:
        _queue_handler.close()
    if _writer is None or _writer.finished:
        _writer = None
        _queue_handler = None


def _flush_diagnostic_summaries() -> None:
    if diagnostic_writer() is None:
        return
    # Import here because observations use this module to find the writer.
    from .diagnostics import flush_summaries

    try:
        flush_summaries()
    except Exception:
        diagnostic = diagnostic_writer()
        if diagnostic is not None:
            diagnostic._failure()


def _restore_standard_streams() -> None:
    for name, original in (("stdout", sys.__stdout__), ("stderr", sys.__stderr__)):
        current = getattr(sys, name)
        if isinstance(current, StreamToLogger):
            with suppress(Exception):
                current.flush()
            setattr(sys, name, original)


def _read_logging_enabled_setting() -> bool:
    path = get_project_root() / "data" / SETTINGS_FILE
    if not path.exists():
        return True

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return True

    if not isinstance(data, dict):
        return True

    gaze_settings = data.get("gaze", {})
    if not isinstance(gaze_settings, dict):
        return True

    return _coerce_bool(gaze_settings.get("logging_enabled", True), True)


def install_qt_message_handler() -> None:
    """Route Qt diagnostic messages into the same Python log file."""

    global _qt_message_handler

    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except Exception:
        logging.getLogger(LOGGER_NAME).exception("Could not import Qt message handler.")
        return

    logger = logging.getLogger("qt")

    def handler(message_type, context, message: str) -> None:
        level = logging.INFO
        if message_type == QtMsgType.QtWarningMsg:
            level = logging.WARNING
        elif message_type in (
            QtMsgType.QtCriticalMsg,
            QtMsgType.QtFatalMsg,
        ):
            level = logging.ERROR

        location = ""
        if context.file:
            location = f" ({context.file}:{context.line})"
        logger.log(level, "%s%s", message, location)

    _qt_message_handler = handler
    qInstallMessageHandler(_qt_message_handler)
    logging.getLogger(LOGGER_NAME).info("Qt message logging installed.")


def get_project_root() -> Path:
    """Return the directory used for runtime logs."""

    configured_log_root = os.environ.get(LOG_ROOT_ENV, "").strip()
    if configured_log_root:
        return Path(configured_log_root).expanduser()

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _archive_latest_log(latest_log: Path) -> Path | None:
    if not latest_log.exists():
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    archived_log = latest_log.with_name(f"{timestamp}.txt")
    shutil.copy2(latest_log, archived_log)
    return archived_log


def _log_unhandled_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback: TracebackType | None,
) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logging.getLogger(LOGGER_NAME).critical(
        "Unhandled exception",
        exc_info=(exc_type, exc_value, exc_traceback),
    )


def _coerce_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default
