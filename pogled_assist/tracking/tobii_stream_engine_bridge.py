"""Subprocess entry point for reading 32-bit Tobii Stream Engine gaze data."""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from typing import Any

from pogled_assist.log_transport import LogWriter, QueueLogHandler
from pogled_assist.tracking.tobii_stream_engine import TobiiStreamEngineBackend

logger = logging.getLogger(__name__)
_running = True
_output_lock = threading.Lock()


def main() -> int:
    writer = LogWriter(capacity=128)
    writer.start_segment(None, sys.stderr, trace=False)
    handler = QueueLogHandler(writer)
    root = logging.getLogger()
    previous_handlers, previous_level = root.handlers[:], root.level
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    try:
        return _run_bridge()
    finally:
        handler.close()
        root.handlers = previous_handlers
        root.setLevel(previous_level)


def _run_bridge() -> int:
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

    logger.info("Starting Tobii Stream Engine bridge with Python: %s", sys.executable)
    logger.info("Bridge pointer size: %s-bit", 8 * _pointer_size())

    if _pointer_size() != 4:
        _emit("error", message="Tobii bridge must run with 32-bit Python.")
        return 2

    if "--check" in sys.argv[1:]:
        if sys.version_info[:2] != (3, 10):
            _emit("error", message="Tobii bridge requires Python 3.10.")
            return 2
        _emit("checked", python_bits=32)
        return 0

    _install_signal_handlers()
    backend = TobiiStreamEngineBackend(_emit_gaze, _emit_eye_status)
    backend.eye_position_callback = _emit_eye_position
    backend.gaze_invalid_callback = _emit_gaze_invalid
    try:
        backend.start()
        _emit(
            "started",
            label=backend.label,
            dll_path=backend.dll_path,
            eye_position_supported=backend.eye_position_supported,
            diagnostic_metadata=getattr(backend, "diagnostic_metadata", {}),
        )
        while _running:
            time.sleep(0.25)
    except KeyboardInterrupt:
        logger.info("Tobii Stream Engine bridge interrupted.")
    except Exception as exc:
        logger.exception("Tobii Stream Engine bridge failed.")
        _emit("error", message=str(exc))
        return 3
    finally:
        backend.stop()

    _emit("stopped")
    return 0


def _emit_gaze(x: float, y: float, timestamp: int) -> None:
    _emit("gaze", x=x, y=y, timestamp=timestamp)


def _emit_eye_status(left_open: bool, right_open: bool, timestamp: int) -> None:
    _emit(
        "eyes",
        left_open=bool(left_open),
        right_open=bool(right_open),
        timestamp=timestamp,
    )


def _emit_eye_position(left: object, right: object, timestamp: int) -> None:
    _emit("eye_position", left=left, right=right, timestamp=timestamp)


def _emit_gaze_invalid(timestamp: int) -> None:
    _emit("gaze_invalid", timestamp=timestamp)


def _emit(message_type: str, **payload: Any) -> None:
    message = {"type": message_type, **payload}
    line = json.dumps(message, separators=(",", ":")) + "\n"
    # Startup and SDK callbacks run on different threads. Keep the JSON, newline,
    # and flush together so stdout remains a stream of complete JSON lines.
    with _output_lock:
        sys.stdout.write(line)
        sys.stdout.flush()


def _pointer_size() -> int:
    return int(((sys.maxsize > 2**32) and 8) or 4)


def _install_signal_handlers() -> None:
    def stop(_signum: int, _frame: object) -> None:
        global _running
        _running = False

    for signal_name in ("SIGINT", "SIGTERM"):
        signal_value = getattr(signal, signal_name, None)
        if signal_value is not None:
            signal.signal(signal_value, stop)


if __name__ == "__main__":
    raise SystemExit(main())
