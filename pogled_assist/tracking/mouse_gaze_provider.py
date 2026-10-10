"""Development-only gaze provider driven by the mouse cursor."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QPoint, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication

from .gaze_check import CheckSnapshot, CheckTelemetry
from .status import TrackingState, TrackingStatus

logger = logging.getLogger(__name__)

MOUSE_GAZE_INTERVAL_MS = 20


class MouseGazeProvider(QObject):
    """Emit gaze samples from the mouse cursor for source-development testing."""

    gaze_updated = Signal(float, float, object)
    eye_status_changed = Signal(bool, bool)
    status_changed = Signal(str)
    tracker_changed = Signal(str)
    tracking_status_changed = Signal(object)
    diagnostics_updated = Signal(object)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        cursor_position: Callable[[], QPoint] | None = None,
    ) -> None:
        super().__init__(parent)
        self._cursor_position = cursor_position or QCursor.pos
        self._running = False
        self._check_telemetry = CheckTelemetry()
        self._check_active = False
        self._screen_geometry: tuple[int, int, int, int] | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(MOUSE_GAZE_INTERVAL_MS)
        self._timer.timeout.connect(self._emit_cursor_sample)

    def start(self) -> None:
        if self._running:
            return

        self._screen_geometry = _primary_screen_geometry()
        if self._screen_geometry is None:
            self.tracking_status_changed.emit(TrackingStatus(TrackingState.UNAVAILABLE))
            self.status_changed.emit("Simulacija pogleda nije dostupna jer nema glavnog ekrana.")
            return

        self._running = True
        self._check_telemetry = CheckTelemetry()
        self.tracking_status_changed.emit(TrackingStatus(TrackingState.SIMULATING))
        self.tracker_changed.emit("Simulator pogleda mišem")
        self.eye_status_changed.emit(True, True)
        self.status_changed.emit("Praćenje simulacijom miša je aktivno.")
        self._emit_cursor_sample()
        self._timer.start()
        logger.info("Mouse gaze simulator started.")

    def stop(self) -> None:
        self._timer.stop()
        if not self._running:
            return

        self._running = False
        self._check_telemetry = CheckTelemetry()
        self.diagnostics_updated.emit(CheckSnapshot())
        self.tracking_status_changed.emit(TrackingStatus(TrackingState.STOPPED))
        self.eye_status_changed.emit(False, False)
        logger.info("Mouse gaze simulator stopped.")

    def _emit_cursor_sample(self) -> None:
        if not self._running or self._screen_geometry is None:
            return

        point = self._cursor_position()
        x, y = _normalize_cursor_position(point, self._screen_geometry)
        now = time.monotonic()
        if self._check_active:
            self._check_telemetry.record_eyes(True, True, now)
            self._check_telemetry.record_gaze(x, y, now)
            self.diagnostics_updated.emit(self.check_snapshot())
        self.gaze_updated.emit(x, y, time.monotonic_ns())

    def check_snapshot(self) -> CheckSnapshot:
        return self._check_telemetry.snapshot(time.monotonic())

    def set_check_active(self, active: bool) -> None:
        self._check_active = bool(active)
        self._check_telemetry = CheckTelemetry()


def _primary_screen_geometry() -> tuple[int, int, int, int] | None:
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return None

    geometry = screen.geometry()
    return geometry.left(), geometry.top(), geometry.width(), geometry.height()


def _normalize_cursor_position(
    point: QPoint,
    geometry: tuple[int, int, int, int],
) -> tuple[float, float]:
    left, top, width, height = geometry
    x = (point.x() - left) / max(1, width - 1)
    y = (point.y() - top) / max(1, height - 1)
    return _clamp(x), _clamp(y)


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
