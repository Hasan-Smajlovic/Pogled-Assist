"""Gaze-check measurements; no calibration or input side effects."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from itertools import pairwise
from statistics import median

from ..interaction.eye_tracking_policy import BOTH_EYES, eyes_usable

FRESH_SECONDS = 0.5
HISTORY_SECONDS = 10.0
SETTLE_SECONDS = 1.0
MEASURE_SECONDS = 2.0
TARGET_SECONDS = SETTLE_SECONDS + MEASURE_SECONDS
MIN_COVERAGE = 0.6
COVERAGE_INTERVAL_SECONDS = 0.1

Position = tuple[float, float, float]


def _fresh(sample, now: float) -> bool:
    return sample is not None and 0 <= now - sample[-1] < FRESH_SECONDS


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
    gaze_interruptions: int = 0
    position_supported: bool | None = None

    @property
    def stable(self) -> bool | None:
        if self.observed_seconds < 3.0:
            return None
        if self.left is None or self.right is None:
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

    def has_usable_gaze(self, policy: str, now: float) -> bool:
        if self.gaze is None or self.gaze_at is None:
            return False
        if not eyes_usable(policy, self.left, self.right):
            return False
        return 0 <= now - self.gaze_at < FRESH_SECONDS and all(
            math.isfinite(value) for value in self.gaze
        )


class CheckTelemetry:
    """Time-weighted availability over ten seconds, guarded by the provider lock."""

    def __init__(self) -> None:
        self.policy = BOTH_EYES
        self.eyes: tuple[bool, bool, float] | None = None
        self.positions: tuple[Position | None, Position | None, float] | None = None
        self.gaze: tuple[float, float, float] | None = None
        self.gaze_interruptions = 0
        self.position_supported: bool | None = None
        self._history: deque[tuple[float, bool]] = deque(maxlen=4096)

    def record_eyes(self, left: bool, right: bool, now: float) -> None:
        if self.eyes is not None and self.eyes[:2] != (left, right):
            self.gaze = None
        self._record_eye_history(left and right, now)
        self.eyes = left, right, now
        if not eyes_usable(self.policy, left, right):
            self.record_gaze_invalid()

    def _record_eye_history(self, both_valid: bool, now: float) -> None:
        if self.eyes is not None and now - self.eyes[2] >= FRESH_SECONDS:
            self._history.append((self.eyes[2] + FRESH_SECONDS, False))
        if not self._history or self._history[-1][1] != both_valid:
            self._history.append((now, both_valid))
        while len(self._history) > 1 and self._history[1][0] < now - HISTORY_SECONDS:
            self._history.popleft()

    def record_gaze_invalid(self) -> None:
        self.gaze = None
        # Preserve a loss even if a newer valid sample arrives before the Qt flush.
        self.gaze_interruptions += 1

    def record_gaze(self, x: float, y: float, now: float) -> None:
        if math.isfinite(x) and math.isfinite(y):
            self.gaze = x, y, now
        else:
            self.record_gaze_invalid()

    def snapshot(self, now: float) -> CheckSnapshot:
        eyes_fresh = _fresh(self.eyes, now)
        left, right = self.eyes[:2] if eyes_fresh else (None, None)
        left_position = right_position = None
        if _fresh(self.positions, now):
            # A valid eye origin does not require a valid gaze point.
            left_position, right_position = self.positions[:2]
        gaze = gaze_at = None
        if eyes_usable(self.policy, left, right) and _fresh(self.gaze, now):
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
            self.gaze_interruptions,
            self.position_supported,
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
    gaze_center: tuple[float, float] | None = None


class TrialGazeCoverage:
    """Coverage from validated gaze timestamps; a known loss breaks the interval."""

    def __init__(self, started_at: float) -> None:
        self.started_at = started_at
        self._last_sample_at: float | None = None
        self._previous_at: float | None = None
        self._covered_seconds = 0.0

    def add(self, at: float) -> None:
        if not math.isfinite(at) or at < self.started_at:
            return
        if self._last_sample_at is not None and at <= self._last_sample_at:
            return
        if self._previous_at is not None and at - self._previous_at < FRESH_SECONDS:
            self._covered_seconds += min(COVERAGE_INTERVAL_SECONDS, at - self._previous_at)
        self._last_sample_at = self._previous_at = at

    def interrupt(self) -> None:
        self._previous_at = None

    def sufficient(self, now: float) -> bool:
        return self.fraction(now) >= MIN_COVERAGE

    def fraction(self, now: float) -> float:
        elapsed = now - self.started_at
        return min(1.0, self._covered_seconds / elapsed) if elapsed > 0 else 0.0


class FixationCheck:
    """Five timed known targets. Raw out-of-screen gaze is never clamped."""

    def __init__(
        self,
        targets: list[tuple[str, float, float]],
        screen_size: tuple[int, int],
        radius: float,
        now: float,
        *,
        policy: str = BOTH_EYES,
    ) -> None:
        self.policy = policy
        self.targets = targets
        self.screen_size = screen_size
        self.radius = radius
        self.index = 0
        self.started_at = now
        self.results: list[FixationResult] = []
        self._samples: list[tuple[float, float]] = []
        self._last_sample_at: float | None = None
        self._previous_at: float | None = None
        self._covered_seconds = 0.0
        self._gaze_interruptions: int | None = None

    @property
    def finished(self) -> bool:
        return self.index >= len(self.targets)

    def add(self, snapshot: CheckSnapshot, now: float) -> None:
        if self.finished:
            return
        if snapshot.gaze_interruptions != self._gaze_interruptions:
            self.interrupt()
            self._gaze_interruptions = snapshot.gaze_interruptions
        if not snapshot.has_usable_gaze(self.policy, now):
            self.interrupt()
            return
        at = snapshot.gaze_at
        # Count only samples produced while this target is in its measure phase.
        if not self._sample_in_measurement(at, now):
            return
        self._last_sample_at = at
        if self._previous_at is not None:
            self._covered_seconds += min(COVERAGE_INTERVAL_SECONDS, at - self._previous_at)
        self._previous_at = at
        self._samples.append(snapshot.gaze)

    def _sample_in_measurement(self, at: float, now: float) -> bool:
        if not self.started_at + SETTLE_SECONDS <= at <= now:
            return False
        if at >= self.started_at + TARGET_SECONDS:
            return False
        return self._last_sample_at is None or at > self._last_sample_at

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
        if len(self._samples) < 12 or coverage < MIN_COVERAGE:
            return FixationResult(name, len(self._samples), coverage, None, None, None)
        width, height = self.screen_size
        points = [(x * (width - 1), y * (height - 1)) for x, y in self._samples]
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
            (center[0] / max(1, width - 1), center[1] / max(1, height - 1)),
        )
