"""Eye eligibility and bounded interruptions, independent of target selection."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

BOTH_EYES = "both"
BRIEF_INTERRUPTION = "hold"
ANY_EYE = "any"
EYE_TRACKING_POLICIES = (BOTH_EYES, BRIEF_INTERRUPTION, ANY_EYE)
EYE_TRACKING_POLICY_CHOICES = (
    (BOTH_EYES, "Oba oka"),
    (BRIEF_INTERRUPTION, "Oba oka uz kratke prekide"),
    (ANY_EYE, "Jedno oko je dovoljno (probno)"),
)
GAZE_FRESH_SECONDS = 0.5
COMPLETED_PAUSE_RETENTION_MS = 500


def valid_policy(value: object) -> str:
    return value if isinstance(value, str) and value in EYE_TRACKING_POLICIES else BOTH_EYES


def eyes_usable(policy: str, left: object, right: object) -> bool:
    eyes = (left is True, right is True)
    return any(eyes) if policy == ANY_EYE else all(eyes)


def policy_description(policy: str, hold_ms: int) -> str:
    if policy == BRIEF_INTERRUPTION:
        return (
            f"Čuva sav napredak do {hold_ms} ms. "
            + (
                "Zatim do ukupno 500 ms čuva samo završenu početnu pauzu. "
                if hold_ms < COMPLETED_PAUSE_RETENTION_MS
                else ""
            )
            + "Nastavak traži oba oka i svjež pogled na isti cilj."
        )
    if policy == ANY_EYE:
        return "Probno: jedno oko je dovoljno uz svjež validan pogled. Bez podataka nema odabira."
    return "Odabir zahtijeva oba oka. Gubitak jednog oka poništava napredak."


@dataclass(frozen=True)
class EyeState:
    left: bool
    right: bool
    received_at: float


class EyeTrackingGate(QObject):
    """Notify owners to freeze or cancel; a fresh sample alone permits resumption."""

    interrupted = Signal()
    hold_started = Signal(float, float)
    pause_retained = Signal()
    hold_finished = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.policy = BOTH_EYES
        self.hold_ms = 150
        self.eyes = (False, False)
        self._sole_eye: tuple[bool, bool] | None = None
        self._last_gaze_at: float | None = None
        self._hold_until: float | None = None
        self._full_hold_until: float | None = None
        self._loss_at: float | None = None
        self._pause_only = False
        self._deadline = QTimer(self)
        self._deadline.setSingleShot(True)
        self._deadline.timeout.connect(self._expire)
        self._freshness = QTimer(self)
        self._freshness.setSingleShot(True)
        self._freshness.timeout.connect(self._expire_gaze)

    @property
    def holding(self) -> bool:
        return self._hold_until is not None

    def configure(self, policy: str, hold_ms: int) -> None:
        policy = valid_policy(policy)
        if (policy, hold_ms) != (self.policy, self.hold_ms):
            self.cancel()
        self.policy, self.hold_ms = policy, hold_ms

    def cancel(self) -> None:
        self._deadline.stop()
        self._freshness.stop()
        self._hold_until = None
        self._full_hold_until = None
        self._loss_at = None
        self._pause_only = False
        self._last_gaze_at = None
        self._sole_eye = None
        self.interrupted.emit()

    def invalidate_gaze(self, received_at: float | None = None) -> None:
        # A later eye loss in the Qt queue must not hide earlier invalid gaze.
        now = time.monotonic()
        at = now if received_at is None else received_at
        if self._hold_until is None or now >= self._hold_until or at < self._loss_at:
            self.cancel()

    def update_eyes(self, left: bool, right: bool, received_at: float | None = None) -> None:
        now = time.monotonic()
        at = now if received_at is None else received_at
        previous = self.eyes
        self.eyes = (bool(left), bool(right))
        if not any(self.eyes) or not self._eyes_are_fresh(at, now):
            self.cancel()
            return
        if all(self.eyes):
            return
        if self._sole_eye is not None and self._sole_eye != self.eyes:
            self.cancel()
        self._sole_eye = self.eyes
        if self.policy == ANY_EYE:
            return
        if self._can_hold(previous, at):
            self._start_hold(at, now)
        elif not self.holding:
            self.cancel()

    @staticmethod
    def _eyes_are_fresh(at: float, now: float) -> bool:
        return math.isfinite(at) and now - at < GAZE_FRESH_SECONDS

    def _can_hold(self, previous: tuple[bool, bool], at: float) -> bool:
        if self.policy != BRIEF_INTERRUPTION or self.holding:
            return False
        if not all(previous) or self._last_gaze_at is None:
            return False
        return at - self._last_gaze_at < GAZE_FRESH_SECONDS

    def _start_hold(self, at: float, now: float) -> None:
        self._loss_at = at
        self._full_hold_until = at + self.hold_ms / 1000
        self._hold_until = at + COMPLETED_PAUSE_RETENTION_MS / 1000
        self._pause_only = False
        if now >= self._hold_until:
            self.cancel()
            return
        self._freshness.stop()
        self.hold_started.emit(self._full_hold_until * 1000, self._hold_until * 1000)
        self._expire()

    def sample(self, received_at: float | None = None) -> bool:
        now = time.monotonic()
        at = now if received_at is None else received_at
        if not math.isfinite(at) or not 0 <= now - at < GAZE_FRESH_SECONDS:
            self.cancel()
            return False
        if not eyes_usable(self.policy, *self.eyes):
            return False
        if self._hold_until is not None:
            self._resume_hold(now)
        self._last_gaze_at = at
        if all(self.eyes):
            self._sole_eye = None
        self._freshness.start(max(1, math.ceil((at + GAZE_FRESH_SECONDS - now) * 1000)))
        return True

    def _resume_hold(self, now: float) -> None:
        if now >= self._hold_until or now - self._last_gaze_at >= GAZE_FRESH_SECONDS:
            self.cancel()
            return
        self._expire()
        self._hold_until = None
        self._full_hold_until = None
        self._loss_at = None
        self._pause_only = False
        self._deadline.stop()
        self.hold_finished.emit()

    def _expire(self) -> None:
        if self._hold_until is not None:
            now = time.monotonic()
            remaining = self._hold_until - now
            if remaining > 0:
                if now >= self._full_hold_until and not self._pause_only:
                    self._pause_only = True
                    self.pause_retained.emit()
                if not self._pause_only:
                    remaining = min(remaining, self._full_hold_until - now)
                self._deadline.start(max(1, math.ceil(remaining * 1000)))
            else:
                self.cancel()

    def _expire_gaze(self) -> None:
        if self.holding:
            return
        if self._last_gaze_at is not None:
            remaining = self._last_gaze_at + GAZE_FRESH_SECONDS - time.monotonic()
            if remaining > 0:
                self._freshness.start(max(1, math.ceil(remaining * 1000)))
            else:
                self.cancel()
