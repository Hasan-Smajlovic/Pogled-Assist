"""Offline, bounded analysis of technical events; no Qt or tracker imports."""

from __future__ import annotations

import math
from collections import Counter, deque


def finite_number(value: object) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


class LatencySummary:
    """One-millisecond histogram; values above a minute retain their exact maximum."""

    def __init__(self) -> None:
        self.buckets: Counter = Counter()
        self.count = 0
        self.total = 0.0
        self.maximum = 0.0
        self.over_cap = 0

    def add(self, value: object) -> None:
        if not finite_number(value) or value < 0:
            return
        self.count += 1
        self.total += value
        self.maximum = max(self.maximum, value)
        self.over_cap += value > 60_000
        self.buckets[min(math.ceil(value), 60_000)] += 1

    def result(self) -> dict:
        def percentile(fraction: float) -> int | None:
            remaining = math.ceil(self.count * fraction)
            if not remaining:
                return None
            for upper_ms, count in sorted(self.buckets.items()):
                remaining -= count
                if remaining <= 0:
                    return upper_ms
            return None

        return {
            "count": self.count,
            "mean_ms": self.total / self.count if self.count else None,
            "p50_ms": percentile(0.5),
            "p95_ms": percentile(0.95),
            "p99_ms": percentile(0.99),
            "max_ms": self.maximum if self.count else None,
            "histogram_resolution_ms": 1,
            "percentile_cap_ms": 60_000,
            "over_cap_count": self.over_cap,
        }


class SessionAnalysis:
    """Associate nearby observations with ended attempts, without inferring intent."""

    def __init__(self) -> None:
        self.latencies = {
            name: LatencySummary()
            for name in (
                "provider_receive_to_emit",
                "heartbeat_lateness",
                "stream_interval_max_lateness",
            )
        }
        self.eye_seconds: Counter = Counter()
        self.suppressed: Counter = Counter()
        self.outcomes: Counter = Counter()
        self.attempts: deque = deque(maxlen=500)
        self.evidence: deque = deque(maxlen=2000)
        self.details_truncated = False

    def observe(self, item: dict) -> None:
        event, data = item["event"], item["data"]
        at = item.get("monotonic_s")
        if event in {"stream_summary", "selection_summary"}:
            counts = data.get("counts", {})
            if isinstance(counts, dict):
                for reason, count in counts.items():
                    if reason.startswith("suppressed:") and type(count) is int and count > 0:
                        self.suppressed[reason] += count
        if event == "stream_summary":
            durations = data.get("eye_state_seconds", {})
            if isinstance(durations, dict):
                for state, seconds in durations.items():
                    if finite_number(seconds) and seconds >= 0:
                        self.eye_seconds[state] += seconds
            self.latencies["stream_interval_max_lateness"].add(data.get("qt_timer_max_late_ms"))
        if event == "provider_gaze":
            self.latencies["provider_receive_to_emit"].add(data.get("age_ms"))
        if event == "ui_heartbeat":
            self.latencies["heartbeat_lateness"].add(data.get("qt_timer_late_ms"))
        if not finite_number(at):
            return
        evidence = None
        interval = 0.0
        if event == "eye_gate_applied" and (
            data.get("left_valid") is False or data.get("right_valid") is False
        ):
            evidence = "eye_gate_closed"
        elif event == "delivery_gap":
            evidence = "gaze_delivery_gap"
            gap = data.get("gap_ms")
            interval = gap / 1000 if finite_number(gap) and gap >= 0 else 0.0
        elif event == "provider_discard" and data.get("reason") == "delivery_stale":
            evidence = "stale_gaze_discarded"
        elif event in {"ui_heartbeat", "stream_summary"}:
            key = "qt_timer_late_ms" if event == "ui_heartbeat" else "qt_timer_max_late_ms"
            late, span = data.get(key), data.get("interval_s")
            if finite_number(late) and late >= 100:
                evidence = "qt_delay_at_least_100ms"
                interval = span if finite_number(span) and span >= 0 else 0.0
        if evidence:
            self.details_truncated |= len(self.evidence) == self.evidence.maxlen
            self.evidence.append((at - interval, at, evidence))
        if event == "selection_end":
            reason = data.get("reason")
            reason = reason if isinstance(reason, str) else None
            outcome = {
                "completed": "completed",
                "eye_gate_closed": "eye_gate_closed",
                "target_departure": "target_departure",
                "target_or_context_changed": "target_or_context_changed",
            }.get(reason, "other_or_unknown")
            self.outcomes[outcome] += 1
            elapsed = data.get("elapsed_ms")
            self.details_truncated |= len(self.attempts) == self.attempts.maxlen
            self.attempts.append(
                {
                    "monotonic_s": at,
                    "source": data.get("source")
                    if data.get("source")
                    in ("toolbar", "desktop", "quick_action", "speech", "keyboard", "gaze_check")
                    else "other",
                    "outcome": outcome,
                    "elapsed_ms": elapsed if finite_number(elapsed) and elapsed >= 0 else None,
                }
            )

    def result(self, *, complete: bool) -> dict:
        attempts = []
        for attempt in self.attempts:
            at = attempt["monotonic_s"]
            nearby = sorted(
                {name for start, end, name in self.evidence if start <= at + 0.1 and end >= at - 1}
            )
            attempts.append({**attempt, "nearby_observations": nearby})
        return {
            "latency": {name: summary.result() for name, summary in self.latencies.items()},
            "eye_state_seconds": dict(self.eye_seconds),
            "observed_selection_outcomes": dict(self.outcomes),
            "recent_selection_ends": attempts,
            "suppressed_events": dict(self.suppressed),
            "details_truncated": self.details_truncated,
            "evidence_incomplete": not complete or bool(self.suppressed) or self.details_truncated,
            "interpretation": (
                "Nearby observations overlap the preceding second or the next 100 ms; "
                "summary intervals are coarse and correlation does not establish cause. "
                "A completed dwell is not proof of a dispatched action or the intended target. "
                "Receive-to-emit age excludes tracker/IPC delay and UI handling; it requires trace. "
                "Timer percentiles describe recorded ticks or interval maxima, not all gaze samples. "
                "Missing observations are not evidence of uninterrupted tracking."
            ),
        }
