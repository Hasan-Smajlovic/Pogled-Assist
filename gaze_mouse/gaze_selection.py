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

    def update(
        self,
        target: object | None,
        now_ms: float,
        *,
        pause_ms: int,
        dwell_ms: int,
        restart: bool = False,
    ) -> GazeSelectionUpdate:
        if target is None:
            self.cancel()
            return GazeSelectionUpdate()

        if restart:
            self._blocked_target = None
            self._start(target, now_ms)
            return GazeSelectionUpdate()

        if self._blocked_target is not None:
            if target == self._blocked_target:
                return GazeSelectionUpdate()
            self._blocked_target = None

        if target != self._target:
            self._start(target, now_ms)
            return GazeSelectionUpdate()

        elapsed_ms = max(0.0, now_ms - self._started_ms)
        pause_ms = max(0, int(pause_ms))
        if elapsed_ms < pause_ms:
            return GazeSelectionUpdate()

        progress = min(
            1.0,
            (elapsed_ms - pause_ms) / max(1, int(dwell_ms)),
        )
        return GazeSelectionUpdate(progress=progress, ready=progress >= 1.0)

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

    def _start(self, target: object, now_ms: float) -> None:
        self._target = target
        self._started_ms = float(now_ms)

    def _clear_target(self) -> None:
        self._target = None
        self._started_ms = 0.0
