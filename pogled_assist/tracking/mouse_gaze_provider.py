"""Development-only gaze provider driven by the mouse cursor."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QPoint, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication

from ..interaction.eye_tracking_policy import BOTH_EYES, EyeState, eyes_usable, valid_policy
from .gaze_check import CheckSnapshot, CheckTelemetry
from .status import GAZE_DELIVERY_GAP_SECONDS, TrackingState, TrackingStatus

logger = logging.getLogger(__name__)

MOUSE_GAZE_INTERVAL_MS = 20


class MouseGazeProvider(QObject):
    """Emit gaze samples from the mouse cursor for source-development testing."""

    gaze_updated = Signal(float, float, object)
    eye_status_changed = Signal(bool, bool)
    eye_state_changed = Signal(object)
    continuity_lost = Signal()
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
        self._eye_tracking_policy = BOTH_EYES
        self._eyes = (True, True)
        self._connected = True
        self._paused = False
        self._last_gaze_at: float | None = None
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
        self._eyes = (True, True)
        self._connected = True
        self._paused = False
        self._last_gaze_at = None
        self._check_telemetry = CheckTelemetry()
        self._check_telemetry.policy = self._eye_tracking_policy
        self.tracker_changed.emit("Simulator pogleda mišem")
        self._publish_state()
        self._emit_cursor_sample()
        self._timer.start()
        logger.info("Mouse gaze simulator started.")

    def check_environment(self) -> dict:
        return {"backend": "mouse-simulation", "model": None, "sdk_version": None}

    @property
    def gaze_received_at(self) -> float | None:
        return self._last_gaze_at

    def stop(self) -> None:
        self._timer.stop()
        if not self._running:
            return

        self._running = False
        self._check_telemetry = CheckTelemetry()
        self.diagnostics_updated.emit(CheckSnapshot())
        self.tracking_status_changed.emit(TrackingStatus(TrackingState.STOPPED))
        self.eye_status_changed.emit(False, False)
        self.eye_state_changed.emit(EyeState(False, False, time.monotonic()))
        logger.info("Mouse gaze simulator stopped.")

    def toggle_left_eye(self) -> None:
        if self._running:
            self._eyes = (not self._eyes[0], self._eyes[1])
            self._publish_state()

    def toggle_right_eye(self) -> None:
        if self._running:
            self._eyes = (self._eyes[0], not self._eyes[1])
            self._publish_state()

    def toggle_gaze(self) -> None:
        if self._running:
            self._paused = not self._paused
            self._publish_state()

    def toggle_connection(self) -> None:
        if self._running:
            self._connected = not self._connected
            self._publish_state()

    def reset(self) -> None:
        if not self._running:
            return
        self.eye_status_changed.emit(False, False)
        self.continuity_lost.emit()
        self._eyes = (True, True)
        self._connected = True
        self._paused = False
        self._last_gaze_at = None
        if self._check_active:
            self._check_telemetry.record_gaze_invalid()
        self._publish_state()

    def _publish_state(self) -> None:
        if not self._connected:
            detail = "Veza je prekinuta"
        elif not all(self._eyes):
            detail = (
                f"Lijevo {'✓' if self._eyes[0] else '—'}   Desno {'✓' if self._eyes[1] else '—'}"
            )
        elif self._paused:
            detail = "Isporuka pogleda pauzirana"
        else:
            detail = ""
        eyes = self._eyes if self._connected else (False, False)
        if self._check_active:
            self._check_telemetry.record_eyes(*eyes, now=time.monotonic())
        self.tracking_status_changed.emit(TrackingStatus(TrackingState.SIMULATING, detail))
        self.eye_status_changed.emit(*eyes)
        self.eye_state_changed.emit(EyeState(*eyes, time.monotonic()))
        self.status_changed.emit(
            f"Simulacija: {detail}." if detail else "Praćenje simulacijom miša je aktivno."
        )
        if self._check_active:
            self.diagnostics_updated.emit(self.check_snapshot())

    def _emit_cursor_sample(self) -> None:
        if not self._running or self._screen_geometry is None:
            return

        now = time.monotonic()
        eyes = self._eyes if self._connected else (False, False)
        if self._check_active:
            self._check_telemetry.record_eyes(*eyes, now=now)
        if eyes_usable(self._eye_tracking_policy, *eyes) and not self._paused:
            if (
                self._last_gaze_at is not None
                and now - self._last_gaze_at >= GAZE_DELIVERY_GAP_SECONDS
            ):
                # Match the provider's gate pulse so waiting time cannot finish a dwell.
                self.eye_status_changed.emit(False, False)
                self.eye_status_changed.emit(*eyes)
                self.continuity_lost.emit()
            point = self._cursor_position()
            x, y = _normalize_cursor_position(point, self._screen_geometry)
            self._last_gaze_at = now
            if self._check_active:
                self._check_telemetry.record_gaze(x, y, now)
            timestamp = time.monotonic_ns()
            self.gaze_updated.emit(x, y, timestamp)
        if self._check_active:
            self.diagnostics_updated.emit(self.check_snapshot())

    def check_snapshot(self) -> CheckSnapshot:
        return self._check_telemetry.snapshot(time.monotonic())

    def set_check_active(self, active: bool) -> None:
        self._check_active = bool(active)
        self._check_telemetry = CheckTelemetry()
        self._check_telemetry.policy = self._eye_tracking_policy

    def set_eye_tracking_policy(self, policy: str) -> None:
        policy = valid_policy(policy)
        if policy != self._eye_tracking_policy:
            self._eye_tracking_policy = policy
            self._check_telemetry.policy = policy
            self._check_telemetry.record_gaze_invalid()
            self._last_gaze_at = None
            self.continuity_lost.emit()


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
