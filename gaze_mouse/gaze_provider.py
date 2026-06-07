"""Tobii gaze data provider."""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication

from .tobii_stream_engine_bridge_backend import (
    TobiiStreamEngineBridgeBackend,
    TobiiStreamEngineBridgeError,
)
from .tobii_stream_engine import TobiiStreamEngineBackend, TobiiStreamEngineError


logger = logging.getLogger(__name__)

RETRY_INTERVAL_MS = 3000
NORMALIZED_COORDINATE_MARGIN = 0.5
GAZE_EMIT_INTERVAL_MS = 20
COALESCED_SAMPLE_LOG_INTERVAL = 3000


class TobiiGazeProvider(QObject):
    """Subscribe to Tobii gaze samples and emit normalized screen positions."""

    gaze_updated = Signal(float, float, object)
    eye_status_changed = Signal(bool, bool)
    status_changed = Signal(str)
    tracker_changed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tr: Any | None = None
        self._tracker: Any | None = None
        self._stream_engine: Any | None = None
        self._running = False
        self._start_requested = False
        self._backend_name = ""
        self._sample_count = 0
        self._sample_lock = threading.Lock()
        self._pending_gaze_sample: tuple[float, float, object] | None = None
        self._dropped_sample_count = 0
        self._last_reported_dropped_sample_count = 0
        self._last_eye_status: tuple[bool, bool] | None = None
        self._stream_eye_status_known = False
        self._stream_left_open = False
        self._stream_right_open = False
        self._screen_geometry = _primary_screen_geometry()
        self._emit_timer = QTimer(self)
        self._emit_timer.setInterval(GAZE_EMIT_INTERVAL_MS)
        self._emit_timer.timeout.connect(self._emit_latest_gaze_sample)
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._attempt_start)

    def start(self) -> None:
        if self._running:
            logger.info("Tobii gaze provider start skipped; provider is already running.")
            return

        self._start_requested = True
        self._sample_count = 0
        with self._sample_lock:
            self._pending_gaze_sample = None
            self._dropped_sample_count = 0
            self._last_reported_dropped_sample_count = 0
        self._stream_eye_status_known = False
        self._stream_left_open = False
        self._stream_right_open = False
        self._last_eye_status = None
        self._emit_eye_status(False, False, "startup")
        self._screen_geometry = _primary_screen_geometry()
        self._emit_timer.start()
        logger.info("Starting Tobii gaze provider.")
        self._attempt_start()

    def _attempt_start(self) -> None:
        if not self._start_requested or self._running:
            return

        if self._start_with_tobii_research():
            return

        if self._start_with_stream_engine():
            return

        self._schedule_retry("No Tobii eye tracker found. Retrying.")

    def _start_with_tobii_research(self) -> bool:
        try:
            import tobii_research as tr
        except ImportError:
            logger.exception("tobii-research import failed.")
            self.status_changed.emit(
                "Missing tobii-research. Trying Stream Engine."
            )
            return False

        try:
            logger.info("Scanning for Tobii eye trackers with tobii-research.")
            trackers = tr.find_all_eyetrackers()
        except Exception as exc:
            logger.exception("Tobii eye tracker scan failed.")
            self.status_changed.emit(f"Tobii Pro SDK scan failed: {exc}")
            return False

        if not trackers:
            logger.warning("No Tobii eye trackers were found through tobii-research.")
            self.status_changed.emit("No Tobii Pro SDK tracker found; trying Stream Engine.")
            return False

        self._tr = tr
        self._tracker = _choose_tracker(trackers)
        logger.info("Selected Tobii tracker: %s", _tracker_label(self._tracker))

        try:
            logger.info("Subscribing to Tobii gaze data.")
            self._tracker.subscribe_to(
                tr.EYETRACKER_GAZE_DATA,
                self._on_gaze_data,
                as_dictionary=True,
            )
        except Exception as exc:
            logger.exception("Tobii gaze subscription failed.")
            self.status_changed.emit(f"Tobii subscription failed: {exc}")
            self._tracker = None
            self._tr = None
            return False

        self._running = True
        self._backend_name = "tobii-research"
        label = _tracker_label(self._tracker)
        self.tracker_changed.emit(label)
        self.status_changed.emit(f"Tracking with {label}.")
        return True

    def _start_with_stream_engine(self) -> bool:
        logger.info("Trying Tobii Stream Engine fallback.")
        try:
            backend = TobiiStreamEngineBackend(
                self._on_stream_engine_gaze,
                self._on_stream_engine_eye_status,
            )
            backend.start()
        except TobiiStreamEngineError as exc:
            logger.warning("Tobii Stream Engine fallback did not start: %s", exc)
            self.status_changed.emit(f"Stream Engine unavailable: {exc}")
            return self._start_with_stream_engine_bridge(exc)
        except Exception as exc:
            logger.exception("Tobii Stream Engine fallback failed.")
            self.status_changed.emit(f"Stream Engine failed: {exc}")
            return self._start_with_stream_engine_bridge(exc)

        self._stream_engine = backend
        self._running = True
        self._backend_name = "stream-engine"
        label = backend.label
        self.tracker_changed.emit(label)
        self.status_changed.emit(f"Tracking with {label}.")
        return True

    def _start_with_stream_engine_bridge(self, direct_error: Exception) -> bool:
        logger.info(
            "Trying Tobii Stream Engine x86 bridge after direct backend failure: %s",
            direct_error,
        )
        self.status_changed.emit("Trying Tobii x86 bridge for 32-bit Core Software.")
        try:
            backend = TobiiStreamEngineBridgeBackend(
                self._on_stream_engine_gaze,
                self._on_stream_engine_eye_status,
            )
            backend.start()
        except TobiiStreamEngineBridgeError as exc:
            logger.warning("Tobii Stream Engine x86 bridge did not start: %s", exc)
            self.status_changed.emit(f"Tobii x86 bridge unavailable: {exc}")
            return False
        except Exception as exc:
            logger.exception("Tobii Stream Engine x86 bridge failed.")
            self.status_changed.emit(f"Tobii x86 bridge failed: {exc}")
            return False

        self._stream_engine = backend
        self._running = True
        self._backend_name = "stream-engine-x86-bridge"
        label = backend.label
        self.tracker_changed.emit(label)
        self.status_changed.emit(f"Tracking with {label}.")
        return True

    def _schedule_retry(self, message: str) -> None:
        if not self._start_requested:
            return

        logger.warning("%s Next scan in %.1f seconds.", message, RETRY_INTERVAL_MS / 1000)
        self.status_changed.emit(message)
        self.tracker_changed.emit("retrying")
        self._emit_eye_status(False, False, "retry")
        self._retry_timer.start(RETRY_INTERVAL_MS)

    def stop(self) -> None:
        self._start_requested = False
        self._retry_timer.stop()
        self._emit_timer.stop()
        self._clear_pending_gaze_sample()
        self._emit_eye_status(False, False, "stopped")

        if self._stream_engine is not None:
            self._stream_engine.stop()
            self._stream_engine = None
            self._running = False
            logger.info("Tobii gaze provider stopped.")
            return

        if not self._running or self._tracker is None or self._tr is None:
            logger.info("Tobii gaze provider stop skipped; provider is not running.")
            return

        try:
            logger.info("Unsubscribing from Tobii gaze data.")
            self._tracker.unsubscribe_from(
                self._tr.EYETRACKER_GAZE_DATA,
                self._on_gaze_data,
            )
        except Exception as exc:
            logger.exception("Tobii gaze unsubscribe failed.")
            self.status_changed.emit(f"Tobii unsubscribe failed: {exc}")
        finally:
            self._running = False
            self._backend_name = ""
            logger.info("Tobii gaze provider stopped.")

    def _on_gaze_data(self, gaze_data: dict[str, Any]) -> None:
        left = _valid_gaze_point(gaze_data, "left")
        right = _valid_gaze_point(gaze_data, "right")
        left_open = left is not None
        right_open = right is not None
        self._emit_eye_status(left_open, right_open, "tobii-research")

        if left is None or right is None:
            self._clear_pending_gaze_sample()
            return

        x = (left[0] + right[0]) / 2
        y = (left[1] + right[1]) / 2
        timestamp = gaze_data.get("system_time_stamp", time.monotonic_ns())
        self._queue_gaze_sample("tobii-research", x, y, timestamp)

    def _on_stream_engine_gaze(self, x: float, y: float, timestamp: int) -> None:
        if not self._stream_eye_status_known:
            self._emit_eye_status(False, False, "stream-engine")
            return

        if not (self._stream_left_open and self._stream_right_open):
            self._clear_pending_gaze_sample()
            return

        normalized_x, normalized_y = _normalize_stream_engine_point(x, y, self._screen_geometry)
        self._queue_gaze_sample("stream-engine", normalized_x, normalized_y, timestamp)

    def _on_stream_engine_eye_status(self, left_open: bool, right_open: bool, _timestamp: int) -> None:
        self._stream_eye_status_known = True
        self._stream_left_open = bool(left_open)
        self._stream_right_open = bool(right_open)
        if not (self._stream_left_open and self._stream_right_open):
            self._clear_pending_gaze_sample()
        self._emit_eye_status(self._stream_left_open, self._stream_right_open, "stream-engine")

    def _queue_gaze_sample(self, backend: str, x: float, y: float, timestamp: object) -> None:
        self._log_sample(backend, x, y, timestamp)
        with self._sample_lock:
            if self._pending_gaze_sample is not None:
                self._dropped_sample_count += 1
            self._pending_gaze_sample = (x, y, timestamp)

    def _emit_latest_gaze_sample(self) -> None:
        with self._sample_lock:
            sample = self._pending_gaze_sample
            self._pending_gaze_sample = None
            dropped_sample_count = self._dropped_sample_count

        if sample is None:
            return

        if (
            dropped_sample_count
            >= self._last_reported_dropped_sample_count + COALESCED_SAMPLE_LOG_INTERVAL
        ):
            logger.info(
                "Coalesced %s raw gaze samples to keep the UI responsive.",
                dropped_sample_count,
            )
            self._last_reported_dropped_sample_count = dropped_sample_count

        x, y, timestamp = sample
        self.gaze_updated.emit(x, y, timestamp)

    def _clear_pending_gaze_sample(self) -> None:
        with self._sample_lock:
            self._pending_gaze_sample = None

    def _log_sample(self, backend: str, x: float, y: float, timestamp: object) -> None:
        self._sample_count += 1
        if self._sample_count == 1 or self._sample_count % 300 == 0:
            logger.info(
                "Gaze provider sample #%s from %s: x=%.4f y=%.4f timestamp=%s",
                self._sample_count,
                backend,
                x,
                y,
                timestamp,
            )

    def _emit_eye_status(self, left_open: bool, right_open: bool, backend: str) -> None:
        status = (bool(left_open), bool(right_open))
        if status == self._last_eye_status:
            return

        self._last_eye_status = status
        logger.info(
            "Eye status from %s changed: left_open=%s right_open=%s.",
            backend,
            status[0],
            status[1],
        )
        self.eye_status_changed.emit(status[0], status[1])


def _valid_gaze_point(
    gaze_data: dict[str, Any],
    eye: str,
) -> tuple[float, float] | None:
    validity = gaze_data.get(f"{eye}_gaze_point_validity")
    if validity not in (1, True):
        return None

    point = gaze_data.get(f"{eye}_gaze_point_on_display_area")
    if point is None or len(point) != 2:
        return None

    x = float(point[0])
    y = float(point[1])
    if not math.isfinite(x) or not math.isfinite(y):
        return None

    return x, y


def _choose_tracker(trackers: tuple[Any, ...]) -> Any:
    for tracker in trackers:
        label = _tracker_label(tracker).lower()
        if "4c" in label:
            return tracker
    return trackers[0]


def _tracker_label(tracker: Any) -> str:
    parts = [
        getattr(tracker, "model", ""),
        getattr(tracker, "device_name", ""),
        getattr(tracker, "serial_number", ""),
    ]
    label = " ".join(str(part) for part in parts if part)
    return label or "Tobii eye tracker"


ScreenGeometry = tuple[int, int, int, int]


def _primary_screen_geometry() -> ScreenGeometry | None:
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return None

    geometry = screen.geometry()
    return geometry.left(), geometry.top(), geometry.width(), geometry.height()


def _normalize_stream_engine_point(
    x: float,
    y: float,
    screen_geometry: ScreenGeometry | None,
) -> tuple[float, float]:
    if _looks_like_normalized_display_point(x, y):
        return _clamp(x, 0.0, 1.0), _clamp(y, 0.0, 1.0)

    if screen_geometry is None:
        return _clamp(x, 0.0, 1.0), _clamp(y, 0.0, 1.0)

    left, top, width, height = screen_geometry
    normalized_x = (x - left) / max(1, width - 1)
    normalized_y = (y - top) / max(1, height - 1)
    return _clamp(normalized_x, 0.0, 1.0), _clamp(normalized_y, 0.0, 1.0)


def _looks_like_normalized_display_point(x: float, y: float) -> bool:
    return (
        -NORMALIZED_COORDINATE_MARGIN <= x <= 1.0 + NORMALIZED_COORDINATE_MARGIN
        and -NORMALIZED_COORDINATE_MARGIN <= y <= 1.0 + NORMALIZED_COORDINATE_MARGIN
    )


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))
