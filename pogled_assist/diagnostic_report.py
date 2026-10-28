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
        self.bridge_connections: deque = deque(maxlen=64)
        self.details_truncated = False

    def observe(self, item: dict) -> None:
        event, data = item["event"], item["data"]
        at = item.get("monotonic_s")
        self._observe_metrics(event, data)
        if not finite_number(at):
            return
        evidence, interval = _event_evidence(event, data)
        if evidence:
            self.details_truncated |= len(self.evidence) == self.evidence.maxlen
            self.evidence.append((at - interval, at, evidence))
        if event == "selection_end":
            self._observe_selection_end(at, data)
        if event == "bridge_connection":
            self._observe_bridge(at, data)

    def _observe_bridge(self, at: float, data: dict) -> None:
        self.details_truncated |= len(self.bridge_connections) == self.bridge_connections.maxlen
        self.bridge_connections.append(
            {
                "monotonic_s": at,
                "stream_generation": data.get("stream_generation")
                if type(data.get("stream_generation")) is int
                else None,
                "decision": data.get("decision")
                if isinstance(data.get("decision"), str)
                and data["decision"] in {"failure", "recovery", "shutdown"}
                else "unknown",
                "reason": data.get("reason")[:128] if isinstance(data.get("reason"), str) else None,
                "native_eye_age_ms": _nonnegative(data.get("native_eye_age_ms")),
                "process_state": data.get("process_state")
                if isinstance(data.get("process_state"), str)
                and data["process_state"] in {"running", "exited", "not_started"}
                else "unknown",
                "exit_code": data.get("exit_code") if type(data.get("exit_code")) is int else None,
                "shutdown_requested": data.get("shutdown_requested") is True,
            }
        )

    def _observe_metrics(self, event: str, data: dict) -> None:
        if event in {"stream_summary", "selection_summary"}:
            self._observe_suppressed(data.get("counts"))
        if event == "stream_summary":
            self._observe_eye_seconds(data.get("eye_state_seconds"))
            self.latencies["stream_interval_max_lateness"].add(data.get("qt_timer_max_late_ms"))
        if event == "provider_gaze":
            self.latencies["provider_receive_to_emit"].add(data.get("age_ms"))
        if event == "ui_heartbeat":
            self.latencies["heartbeat_lateness"].add(data.get("qt_timer_late_ms"))

    def _observe_suppressed(self, counts: object) -> None:
        if not isinstance(counts, dict):
            return
        for reason, count in counts.items():
            if type(count) is not int or count <= 0:
                continue
            if reason.startswith("suppressed:"):
                self.suppressed[reason] += count

    def _observe_eye_seconds(self, durations: object) -> None:
        if not isinstance(durations, dict):
            return
        for state, seconds in durations.items():
            if finite_number(seconds) and seconds >= 0:
                self.eye_seconds[state] += seconds

    def _observe_selection_end(self, at: float, data: dict) -> None:
        reason = data.get("reason")
        reason = reason if isinstance(reason, str) else None
        outcome = {
            "completed": "completed",
            "eye_gate_closed": "eye_gate_closed",
            "target_departure": "target_departure",
            "target_or_context_changed": "target_or_context_changed",
        }.get(reason, "other_or_unknown")
        self.outcomes[outcome] += 1
        source = data.get("source")
        if source not in ("toolbar", "desktop", "quick_action", "speech", "keyboard", "gaze_check"):
            source = "other"
        self.details_truncated |= len(self.attempts) == self.attempts.maxlen
        self.attempts.append(
            {
                "monotonic_s": at,
                "source": source,
                "outcome": outcome,
                "elapsed_ms": _nonnegative(data.get("elapsed_ms")),
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
            "bridge_connections": list(self.bridge_connections),
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


def _nonnegative(value: object, default=None):
    return value if finite_number(value) and value >= 0 else default


def _event_evidence(event: str, data: dict) -> tuple[str | None, float]:
    if event == "bridge_connection" and data.get("decision") in ("failure", "recovery"):
        return "bridge_" + data["decision"], 0.0
    if event == "eye_gate_applied":
        gate_open = data.get("application_gate_open")
        closed = (
            not gate_open
            if isinstance(gate_open, bool)
            else data.get("left_valid") is False or data.get("right_valid") is False
        )
        return ("eye_gate_closed" if closed else None), 0.0
    if event == "delivery_gap":
        return "gaze_delivery_gap", _nonnegative(data.get("gap_ms"), 0.0) / 1000
    if event == "provider_discard" and data.get("reason") == "delivery_stale":
        return "stale_gaze_discarded", 0.0
    if event in {"ui_heartbeat", "stream_summary"}:
        return _timer_evidence(event, data)
    return None, 0.0


def _timer_evidence(event: str, data: dict) -> tuple[str | None, float]:
    key = "qt_timer_late_ms" if event == "ui_heartbeat" else "qt_timer_max_late_ms"
    late = data.get(key)
    if finite_number(late) and late >= 100:
        return "qt_delay_at_least_100ms", _nonnegative(data.get("interval_s"), 0.0)
    return None, 0.0
