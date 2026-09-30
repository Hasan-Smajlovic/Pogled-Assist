"""Shared timing state for gaze-selectable targets."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_SELECTION_PAUSE_MS = 500
MIN_SELECTION_PAUSE_MS = 100
MAX_SELECTION_PAUSE_MS = 2000


@dataclass(frozen=True)
class GazeSelectionUpdate:
    """Result of advancing one gaze target through pause and dwell."""

    progress: float | None = None
    ready: bool = False


class GazeSelectionTimer:
    """Track pause, dwell progress, and leave-before-repeat for one interaction."""

    def __init__(self) -> None:
        self._target: object | None = None
        self._blocked_target: object | None = None
        self._started_ms = 0.0
        self._last_seen_ms = 0.0
        self._away_since_ms: float | None = None

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
        """Hold only when the caller confirms that gaze is near the current target."""

        if restart:
            self.cancel()
            if target is not None:
                self._start(target, now_ms)
            return GazeSelectionUpdate()

        if self.target is not None and target != self.target and can_hold and hold_ms > 0:
            if self._away_since_ms is None:
                self._away_since_ms = now_ms
            if now_ms - self._away_since_ms < hold_ms:
                progress = self._progress(self._last_seen_ms, pause_ms, dwell_ms)
                return GazeSelectionUpdate(progress=progress.progress)

        if self._away_since_ms is not None:
            if target == self._target and target is not None:
                if now_ms - self._away_since_ms < hold_ms:
                    # Exclude the interval up to the first returning sample.
                    self._started_ms += max(0.0, now_ms - self._last_seen_ms)
                else:
                    self._clear_target()
            self._away_since_ms = None

        if target is None:
            self.cancel()
            return GazeSelectionUpdate()

        if self._blocked_target is not None:
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

    def cancel(self, *, require_leave: bool = False) -> None:
        """Drop pending progress and optionally block the target until gaze leaves."""

        if require_leave:
            if self._target is not None:
                self._blocked_target = self._target
        else:
            self._blocked_target = None
        self._clear_target()

    def pause(self) -> None:
        """Drop pending progress without treating invalid gaze as leaving the target."""

        self._clear_target()

    def _start(self, target: object, now_ms: float) -> None:
        self._target = target
        self._started_ms = float(now_ms)
        self._last_seen_ms = float(now_ms)
        self._away_since_ms = None

    def _clear_target(self) -> None:
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
