"""Shared timing state for gaze-selectable targets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .. import diagnostics

DEFAULT_SELECTION_PAUSE_MS = 250
MIN_SELECTION_PAUSE_MS = 100
MAX_SELECTION_PAUSE_MS = 2000


@dataclass(frozen=True)
class GazeSelectionUpdate:
    """Result of advancing one gaze target through pause and dwell."""

    progress: float | None = None
    ready: bool = False


class GazeSelectionTimer:
    """Track pause, dwell progress, and leave-before-repeat for one interaction."""

    def __init__(self, diagnostic_source: str | None = None) -> None:
        self._target: object | None = None
        self._blocked_target: object | None = None
        self._started_ms = 0.0
        self._last_seen_ms = 0.0
        self._away_since_ms: float | None = None
        self._tracking_deadline_ms: float | None = None
        self._observer = (
            diagnostics.SelectionObserver(diagnostic_source) if diagnostic_source else None
        )
        self._pause_ms = 0
        self._dwell_ms = 0
        self._advancing = False
        self._context_getter: Callable[[object], diagnostics.TargetContext] | None = None

    def diagnostic_snapshot(self) -> dict:
        """Read timing state without advancing or resetting selection."""
        credited = (
            max(0.0, self._last_seen_ms - self._started_ms) if self._target is not None else 0.0
        )
        return {
            "target": self.target,
            "active": self._target is not None,
            "blocked": self.is_blocked,
            "held": self._away_since_ms is not None,
            "credited_ms": credited,
        }

    def set_diagnostic_context_getter(
        self, getter: Callable[[object], diagnostics.TargetContext]
    ) -> None:
        self._context_getter = getter

    def _observe(self, reason: str) -> None:
        if self._observer is not None and not self._advancing:
            try:
                snapshot = self.diagnostic_snapshot()
                self._observe_context(snapshot["target"])
                self._observer.observe(
                    snapshot,
                    reason=reason,
                    pause_ms=self._pause_ms,
                    dwell_ms=self._dwell_ms,
                )
            except Exception:
                # A failed observation must not prevent completion or cancellation.
                diagnostics.observation_failed()

    def _observe_context(self, target: object | None) -> None:
        if not diagnostics.enabled() or self._context_getter is None:
            return
        if target is not None:
            # Edge hold retains the selected target even when the raw hit moves.
            self._observer.context = self._context_getter(target)

    @property
    def target(self) -> object | None:
        """Include the repeat lock so a brief departure cannot unlock the target."""

        return self._target if self._target is not None else self._blocked_target

    @property
    def is_blocked(self) -> bool:
        return self._blocked_target is not None

    def update(
        self,
        target: object | None,
        now_ms: float,
        *,
        pause_ms: int,
        dwell_ms: int,
        restart: bool = False,
        can_hold: bool = False,
        hold_ms: int = 0,
    ) -> GazeSelectionUpdate:
        self._pause_ms = pause_ms
        self._dwell_ms = dwell_ms
        self._advancing = True
        try:
            result = self._advance(
                target,
                now_ms,
                restart=restart,
                edge_hold=(can_hold, hold_ms),
            )
        finally:
            self._advancing = False
        self._observe("sample")
        return result

    def _advance(
        self,
        target: object | None,
        now_ms: float,
        *,
        restart: bool,
        edge_hold: tuple[bool, int],
    ) -> GazeSelectionUpdate:
        """Hold only when the caller confirms that gaze is near the current target."""

        can_hold, hold_ms = edge_hold
        pause_ms = self._pause_ms
        dwell_ms = self._dwell_ms
        if self._tracking_deadline_ms is not None:
            resume = (
                now_ms < self._tracking_deadline_ms
                and target is not None
                and target == self._target
                and not restart
                and (self._away_since_ms is None or now_ms - self._away_since_ms < hold_ms)
            )
            self._tracking_deadline_ms = None
            if resume:
                self._started_ms += max(0.0, now_ms - self._last_seen_ms)
                self._last_seen_ms = now_ms
                self._away_since_ms = None
                progress = self._progress(now_ms, pause_ms, dwell_ms)
                return GazeSelectionUpdate(progress=progress.progress)
            self.pause(reason="tracking_hold_cancelled")
        if restart:
            self.cancel()
            if target is not None:
                self._start(target, now_ms)
            return GazeSelectionUpdate()

        if can_hold and self._holds(target, now_ms, hold_ms):
            progress = self._progress(self._last_seen_ms, pause_ms, dwell_ms)
            return GazeSelectionUpdate(progress=progress.progress)

        self._end_departure(target, now_ms, hold_ms)

        if target is None:
            self.cancel()
            return GazeSelectionUpdate()

        if target == self._blocked_target:
            return GazeSelectionUpdate()
        self._blocked_target = None

        if target != self._target:
            self._start(target, now_ms)
            return GazeSelectionUpdate()

        self._last_seen_ms = now_ms
        return self._progress(now_ms, pause_ms, dwell_ms)

    def complete(self) -> None:
        if self._target is not None:
            self._blocked_target = self._target
        self._clear_target()
        self._observe("completed")

    def cancel(self, *, require_leave: bool = False, reason: str = "cancelled") -> None:
        """Drop pending progress and optionally block the target until gaze leaves."""

        if require_leave:
            if self._target is not None:
                self._blocked_target = self._target
        else:
            self._blocked_target = None
        self._clear_target()
        self._observe(reason)

    def pause(self, *, reason: str = "paused") -> None:
        """Drop pending progress without treating invalid gaze as leaving the target."""

        self._clear_target()
        self._observe(reason)

    def hold_tracking(self, deadline_ms: float) -> None:
        if self._target is not None and self._tracking_deadline_ms is None:
            self._tracking_deadline_ms = deadline_ms
            self._observe("tracking_held")

    @property
    def tracking_held(self) -> bool:
        return self._tracking_deadline_ms is not None

    def _holds(self, target: object | None, now_ms: float, hold_ms: int) -> bool:
        if self.target is None or target == self.target or hold_ms <= 0:
            return False
        if self._away_since_ms is None:
            self._away_since_ms = now_ms
        return now_ms - self._away_since_ms < hold_ms

    def _end_departure(self, target: object | None, now_ms: float, hold_ms: int) -> None:
        if self._away_since_ms is None:
            return
        expired = now_ms - self._away_since_ms >= hold_ms
        if expired:
            # Departure can expire between samples, including on the return.
            self._blocked_target = None
        if target == self._target and target is not None:
            if expired:
                self._clear_target()
            else:
                # Exclude the interval up to the first returning sample.
                self._started_ms += max(0.0, now_ms - self._last_seen_ms)
        self._away_since_ms = None

    def _start(self, target: object, now_ms: float) -> None:
        self._target = target
        self._started_ms = float(now_ms)
        self._last_seen_ms = float(now_ms)
        self._away_since_ms = None

    def _clear_target(self) -> None:
        self._tracking_deadline_ms = None
        self._target = None
        self._started_ms = 0.0
        self._last_seen_ms = 0.0
        self._away_since_ms = None

    def _progress(self, now_ms: float, pause_ms: int, dwell_ms: int) -> GazeSelectionUpdate:
        if self._target is None:
            return GazeSelectionUpdate()
        elapsed_ms = max(0.0, now_ms - self._started_ms)
        pause_ms = max(0, int(pause_ms))
        if elapsed_ms < pause_ms:
            return GazeSelectionUpdate()
        progress = min(1.0, (elapsed_ms - pause_ms) / max(1, int(dwell_ms)))
        return GazeSelectionUpdate(progress=progress, ready=progress >= 1.0)
