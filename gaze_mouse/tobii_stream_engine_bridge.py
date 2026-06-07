"""Subprocess entry point for reading 32-bit Tobii Stream Engine gaze data."""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from typing import Any

from gaze_mouse.tobii_stream_engine import TobiiStreamEngineBackend


logger = logging.getLogger(__name__)
_running = True


def main() -> int:
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    logger.info("Starting Tobii Stream Engine bridge with Python: %s", sys.executable)
    logger.info("Bridge pointer size: %s-bit", 8 * _pointer_size())

    if _pointer_size() != 4:
        _emit("error", message="Tobii bridge must run with 32-bit Python.")
        return 2

    _install_signal_handlers()
    backend = TobiiStreamEngineBackend(_emit_gaze, _emit_eye_status)
    try:
        backend.start()
        _emit("started", label=backend.label, dll_path=backend.dll_path)
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


def _emit(message_type: str, **payload: Any) -> None:
    message = {"type": message_type, **payload}
    print(json.dumps(message, separators=(",", ":")), flush=True)


def _pointer_size() -> int:
    return int((sys.maxsize > 2**32) and 8 or 4)


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
