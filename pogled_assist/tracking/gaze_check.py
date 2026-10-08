"""Ephemeral gaze-check measurements; no calibration or input side effects."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from itertools import pairwise
from statistics import median

FRESH_SECONDS = 0.5
HISTORY_SECONDS = 10.0
SETTLE_SECONDS = 1.0
MEASURE_SECONDS = 2.0
TARGET_SECONDS = SETTLE_SECONDS + MEASURE_SECONDS

Position = tuple[float, float, float]


@dataclass(frozen=True)
class CheckSnapshot:
    left: bool | None = None
    right: bool | None = None
    left_position: Position | None = None
    right_position: Position | None = None
    gaze: tuple[float, float] | None = None
    gaze_at: float | None = None
    observed_seconds: float = 0.0
    available_fraction: float = 0.0
    longest_loss_seconds: float = 0.0

    @property
    def stable(self) -> bool | None:
        if self.observed_seconds < 3.0 or self.left is None or self.right is None:
            return None
        return self.available_fraction >= 0.85 and self.longest_loss_seconds <= 0.5

    def in_box(self, axes: tuple[int, ...]) -> bool | None:
        if self.left_position is None or self.right_position is None:
            return None
        return all(
            0.0 <= position[axis] <= 1.0
            for position in (self.left_position, self.right_position)
            for axis in axes
        )


class CheckTelemetry:
    """Time-weighted availability over ten seconds, guarded by the provider lock."""

    def __init__(self) -> None:
        self.eyes: tuple[bool, bool, float] | None = None
        self.positions: tuple[Position | None, Position | None, float] | None = None
        self.gaze: tuple[float, float, float] | None = None
        self._history: deque[tuple[float, bool]] = deque(maxlen=4096)

    def record_eyes(self, left: bool, right: bool, now: float) -> None:
        if self.eyes is not None and now - self.eyes[2] >= FRESH_SECONDS:
            self._history.append((self.eyes[2] + FRESH_SECONDS, False))
        self.eyes = left, right, now
        if not self._history or self._history[-1][1] != (left and right):
            self._history.append((now, left and right))
        while len(self._history) > 1 and self._history[1][0] < now - HISTORY_SECONDS:
            self._history.popleft()
        if not (left and right):
            self.gaze = None

    def record_gaze(self, x: float, y: float, now: float) -> None:
        if math.isfinite(x) and math.isfinite(y):
            self.gaze = x, y, now

    def snapshot(self, now: float) -> CheckSnapshot:
        eyes_fresh = self.eyes is not None and 0 <= now - self.eyes[2] < FRESH_SECONDS
        left, right = self.eyes[:2] if eyes_fresh else (None, None)
        left_position = right_position = None
        if self.positions is not None and 0 <= now - self.positions[2] < FRESH_SECONDS:
            # A valid eye origin does not require a valid gaze point.
            left_position, right_position = self.positions[:2]
        gaze = gaze_at = None
        if left and right and self.gaze is not None and 0 <= now - self.gaze[2] < FRESH_SECONDS:
            gaze, gaze_at = self.gaze[:2], self.gaze[2]
        observed, fraction, longest = self._availability(now)
        return CheckSnapshot(
            left,
            right,
            left_position,
            right_position,
            gaze,
            gaze_at,
            observed,
            fraction,
            longest,
        )

    def _availability(self, now: float) -> tuple[float, float, float]:
        if not self._history or self.eyes is None:
            return 0.0, 0.0, 0.0
        start = max(now - HISTORY_SECONDS, self._history[0][0])
        observed = max(0.0, now - start)
        events = list(self._history)
        if now - self.eyes[2] >= FRESH_SECONDS:
            events.append((self.eyes[2] + FRESH_SECONDS, False))
        events.append((now, False))
        available = loss = longest = 0.0
        for (at, valid), (end, _) in pairwise(events):
            duration = max(0.0, min(now, end) - max(start, at))
            if valid:
                available += duration
                loss = 0.0
            else:
                loss += duration
                longest = max(longest, loss)
        return observed, available / observed if observed else 0.0, longest


@dataclass(frozen=True)
class FixationResult:
    name: str
    samples: int
    coverage: float
    median_error: float | None
    spread: float | None
    near: bool | None


class FixationCheck:
    """Five timed known targets. Raw out-of-screen gaze is never clamped."""

    def __init__(
        self,
        targets: list[tuple[str, float, float]],
        screen_size: tuple[int, int],
        radius: float,
        now: float,
    ) -> None:
        self.targets = targets
        self.screen_size = screen_size
        self.radius = radius
        self.index = 0
        self.started_at = now
        self.results: list[FixationResult] = []
        self._samples: list[tuple[float, float, float]] = []
        self._last_sample_at: float | None = None
        self._previous_at: float | None = None
        self._covered_seconds = 0.0

    @property
    def finished(self) -> bool:
        return self.index >= len(self.targets)

    def add(self, snapshot: CheckSnapshot, now: float) -> None:
        if self.finished:
            return
        if (
            snapshot.gaze is None
            or snapshot.gaze_at is None
            or not (snapshot.left and snapshot.right)
            or not 0 <= now - snapshot.gaze_at < FRESH_SECONDS
            or not all(math.isfinite(value) for value in snapshot.gaze)
        ):
            self.interrupt()
            return
        at = snapshot.gaze_at
        # Count only samples produced while this target is in its measure phase.
        if not (
            self.started_at + SETTLE_SECONDS <= at <= now
            and at < self.started_at + TARGET_SECONDS
            and (self._last_sample_at is None or at > self._last_sample_at)
        ):
            return
        self._last_sample_at = at
        if self._previous_at is not None:
            self._covered_seconds += min(0.1, at - self._previous_at)
        self._previous_at = at
        x, y = snapshot.gaze
        self._samples.append((at, x, y))

    def interrupt(self) -> None:
        """Do not bridge a known tracking loss, including coalesced eye events."""
        self._previous_at = None

    def advance(self, now: float) -> bool:
        if self.finished or now - self.started_at < TARGET_SECONDS:
            return False
        self.results.append(self._result())
        self.index += 1
        self.started_at = now
        self._samples.clear()
        self._last_sample_at = None
        self._previous_at = None
        self._covered_seconds = 0.0
        return True

    def _result(self) -> FixationResult:
        name, target_x, target_y = self.targets[self.index]
        coverage = self._covered_seconds / MEASURE_SECONDS
        if len(self._samples) < 12 or coverage < 0.6:
            return FixationResult(name, len(self._samples), coverage, None, None, None)
        width, height = self.screen_size
        points = [(x * (width - 1), y * (height - 1)) for _, x, y in self._samples]
        target = target_x * (width - 1), target_y * (height - 1)
        center = median(x for x, _ in points), median(y for _, y in points)
        errors = sorted(math.dist(point, target) for point in points)
        spread = sorted(math.dist(point, center) for point in points)
        p90 = math.ceil(0.9 * len(points)) - 1
        return FixationResult(
            name,
            len(points),
            min(1.0, coverage),
            median(errors),
            spread[p90],
            errors[p90] <= self.radius,
        )
