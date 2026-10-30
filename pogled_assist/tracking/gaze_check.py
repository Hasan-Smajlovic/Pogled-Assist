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
EYE_LOW_FRACTION = 0.85
EYE_GAP_FRACTION = 0.2
AGREEMENT_MIN_FRACTION = 0.8
MIN_AGREEMENT_SAMPLES = 12

Position = tuple[float, float, float]
Point = tuple[float, float]
# Left and right gaze points on the display area, normalized, and their time.
EyeGazePair = tuple[float, float, float, float, float]


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
    # Cumulative time-weighted availability since the telemetry started.
    measured_at: float | None = None
    telemetry_started_at: float | None = None
    left_seconds: float = 0.0
    right_seconds: float = 0.0
    both_seconds: float = 0.0
    # Per-eye gaze points exist only where the backend reports them separately.
    eye_gaze_supported: bool | None = None
    eye_gaze_pairs: tuple[EyeGazePair, ...] = ()

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
        self.eye_gaze_supported: bool | None = None
        self.started_at: float | None = None
        self._history: deque[tuple[float, bool]] = deque(maxlen=4096)
        self._eye_seconds = (0.0, 0.0, 0.0)
        self._eye_gaze_pairs: deque[EyeGazePair] = deque(maxlen=4096)

    def record_eyes(self, left: bool, right: bool, now: float) -> None:
        if self.eyes is not None and self.eyes[:2] != (left, right):
            self.gaze = None
        self._record_eye_history(left and right, now)
        self._eye_seconds = self._eye_seconds_at(now)
        if self.started_at is None:
            self.started_at = now
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

    def _eye_seconds_at(self, now: float) -> tuple[float, float, float]:
        """Add the last report's time, which ends after FRESH_SECONDS without a sample."""
        if self.eyes is None:
            return self._eye_seconds
        left, right, at = self.eyes
        duration = max(0.0, min(now - at, FRESH_SECONDS))
        total_left, total_right, total_both = self._eye_seconds
        return (
            total_left + duration * left,
            total_right + duration * right,
            total_both + duration * (left and right),
        )

    def record_eye_gaze(self, left: Point | None, right: Point | None, now: float) -> None:
        """Record per-eye gaze for the check only; input keeps the combined point."""
        self.eye_gaze_supported = True
        if left is None or right is None:
            return
        if not all(math.isfinite(value) for value in (*left, *right)):
            return
        self._eye_gaze_pairs.append((*left, *right, now))
        while self._eye_gaze_pairs and self._eye_gaze_pairs[0][-1] < now - HISTORY_SECONDS:
            self._eye_gaze_pairs.popleft()

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
        left_seconds, right_seconds, both_seconds = self._eye_seconds_at(now)
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
            measured_at=None if self.started_at is None else now,
            telemetry_started_at=self.started_at,
            left_seconds=left_seconds,
            right_seconds=right_seconds,
            both_seconds=both_seconds,
            eye_gaze_supported=self.eye_gaze_supported,
            eye_gaze_pairs=tuple(pair for pair in self._eye_gaze_pairs if pair[-1] <= now),
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


@dataclass(frozen=True)
class EyeTrackingResult:
    """Per-eye tracking availability, interruptions and left/right gaze agreement."""

    observed_seconds: float
    left: float
    right: float
    both: float
    agreement_supported: bool | None
    agreement_samples: int
    median_separation: float | None
    agreement_fraction: float | None
    threshold: float
    completed: bool
    # Losses of the gaze the selected eye-tracking policy accepts, blinks included.
    interruptions: int = 0
    longest_interruption: float = 0.0


class EyeTrackingRun:
    """Availability measured from cumulative telemetry, for a run or a rolling window.

    Time without a snapshot, including a telemetry restart, counts as not tracked.
    """

    def __init__(
        self,
        screen_size: tuple[int, int],
        threshold: float,
        now: float,
        duration: float | None = None,
        *,
        policy: str = BOTH_EYES,
        window: float | None = None,
    ) -> None:
        self.screen_size = screen_size
        self.threshold = threshold
        self.started_at = now
        self.duration = duration
        self.policy = policy
        self.window = window
        self._closed = (0.0, 0.0, 0.0)
        self._origin: float | None = None
        self._base = self._last = (0.0, 0.0, 0.0)
        self._totals: deque[tuple[float, tuple[float, float, float]]] = deque(
            [(now, (0.0, 0.0, 0.0))]
        )
        self._agreement_supported: bool | None = None
        self._last_pair_at = now
        self._separations: deque[tuple[float, float]] = deque()
        self._losses: deque[list[float | None]] = deque()
        self._usable: bool | None = None
        self._last_at = now
        self._gaze_interruptions: int | None = None

    @property
    def deadline(self) -> float:
        return math.inf if self.duration is None else self.started_at + self.duration

    def finished(self, now: float) -> bool:
        return now >= self.deadline

    def add(self, snapshot: CheckSnapshot) -> None:
        if snapshot.eye_gaze_supported is not None:
            self._agreement_supported = snapshot.eye_gaze_supported
        at, origin = snapshot.measured_at, snapshot.telemetry_started_at
        if at is None or origin is None or not self.started_at <= at <= self.deadline:
            return
        totals = (snapshot.left_seconds, snapshot.right_seconds, snapshot.both_seconds)
        if origin != self._origin:
            self._closed = self._valid_seconds()
            self._origin = origin
            # Telemetry that began during the run has measured all of its time.
            self._base = (0.0, 0.0, 0.0) if origin >= self.started_at else totals
        self._last = totals
        if self.window is not None:
            self._totals.append((at, self._valid_seconds()))
        self._record_loss(snapshot, at)
        self._add_pairs(snapshot.eye_gaze_pairs)
        self._prune(at)

    def _valid_seconds(self) -> tuple[float, float, float]:
        return tuple(
            closed + max(0.0, last - base)
            for closed, last, base in zip(self._closed, self._last, self._base, strict=True)
        )

    def _record_loss(self, snapshot: CheckSnapshot, at: float) -> None:
        if at < self._last_at:
            return
        # Invalid gaze while the eyes stay valid is one continuous loss, not a counter tick each.
        usable = snapshot.has_usable_gaze(self.policy, at)
        ongoing = self._losses[-1] if self._losses and self._losses[-1][1] is None else None
        if ongoing is None and at - self._last_at >= FRESH_SECONDS:
            # No report for FRESH_SECONDS is a loss even when the next one is valid.
            ongoing = [self._last_at + FRESH_SECONDS if self._usable else self._last_at, None]
            self._losses.append(ongoing)
        counted = self._gaze_interruptions
        self._gaze_interruptions = snapshot.gaze_interruptions
        if usable:
            if ongoing is not None:
                ongoing[1] = at
            elif counted is not None and snapshot.gaze_interruptions != counted:
                # A loss shorter than the snapshot interval is known only from the counter.
                self._losses.append([at, at])
        elif ongoing is None:
            self._losses.append([at, None])
        self._usable = usable
        self._last_at = at

    def _add_pairs(self, pairs: tuple[EyeGazePair, ...]) -> None:
        width, height = self.screen_size
        for left_x, left_y, right_x, right_y, at in pairs:
            if not self._last_pair_at < at <= self.deadline:
                continue
            self._last_pair_at = at
            separation = math.hypot(
                (left_x - right_x) * (width - 1), (left_y - right_y) * (height - 1)
            )
            self._separations.append((at, separation))

    def _prune(self, now: float) -> None:
        if self.window is None:
            return
        start = now - self.window
        while len(self._totals) > 1 and self._totals[1][0] <= start:
            self._totals.popleft()
        while self._separations and self._separations[0][0] < start:
            self._separations.popleft()
        while self._losses and self._losses[0][1] is not None and self._losses[0][1] < start:
            self._losses.popleft()

    def _interval(self, now: float) -> tuple[float, float]:
        end = min(now, self.deadline)
        start = self.started_at if self.window is None else max(self.started_at, end - self.window)
        return start, end

    def _fractions(self, start: float, end: float) -> tuple[float, tuple[float, ...]]:
        base_at, base = self._totals[0]
        for at, totals in self._totals:
            if at > start:
                break
            # The newest total at the window start; a run counts from zero.
            base_at, base = at, totals
        observed = max(0.0, end - base_at)
        current = self._valid_seconds()
        return observed, tuple(
            min(1.0, max(0.0, total - before) / observed) if observed > 0 else 0.0
            for total, before in zip(current, base, strict=True)
        )

    def _interruptions(self, start: float, end: float) -> tuple[int, float]:
        losses = [list(loss) for loss in self._losses]
        ongoing = losses and losses[-1][1] is None
        if not ongoing and end - self._last_at >= FRESH_SECONDS:
            losses.append([self._last_at + FRESH_SECONDS if self._usable else self._last_at, None])
        count, longest = 0, 0.0
        for loss_start, loss_end in losses:
            loss_end = end if loss_end is None else loss_end
            if loss_end < start or loss_start > end:
                continue
            count += 1
            longest = max(longest, min(end, loss_end) - max(start, loss_start))
        return count, longest

    def result(self, now: float) -> EyeTrackingResult:
        start, end = self._interval(now)
        observed, (left, right, both) = self._fractions(start, end)
        if self.window is None:
            observed = max(0.0, end - self.started_at)
        separations = [value for at, value in self._separations if start <= at <= end]
        median_separation = agreement = None
        if self._agreement_supported and len(separations) >= MIN_AGREEMENT_SAMPLES:
            median_separation = median(separations)
            agreement = sum(value <= self.threshold for value in separations) / len(separations)
        interruptions, longest = self._interruptions(start, end)
        return EyeTrackingResult(
            observed,
            left,
            right,
            both,
            self._agreement_supported,
            len(separations),
            median_separation,
            agreement,
            self.threshold,
            self.finished(now),
            interruptions,
            longest,
        )
