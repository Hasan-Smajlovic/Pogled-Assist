"""Observations at existing input boundaries, independent of gaze decisions."""

from __future__ import annotations

import threading
import time
import uuid
import weakref
from collections import Counter

from .logging_setup import diagnostic_writer

_metrics = weakref.WeakSet()
_metrics_lock = threading.Lock()


SAFE_ACTIONS = frozenset(
    {
        "clear",
        "confirm:accept",
        "confirm:cancel",
        "exit:cancel",
        "exit:leave-speech",
        "exit:quit-app",
        "alarm:start",
        "alarm:stop",
        "sleep:start",
        "sleep:wake",
        "exit",
        "play",
        "settings",
        "speech",
        "keyboard",
        "controller",
        "left_click",
        "right_click",
        "double_left_click",
        "hide_hotbar",
        "show_hotbar",
        "quick_actions",
    }
)


def flush_summaries() -> None:
    """Queue partial intervals before the logging segment closes."""
    with _metrics_lock:
        metrics = tuple(_metrics)
    for item in metrics:
        try:
            item.summary(force=True)
        except Exception:
            observation_failed()


def enabled() -> bool:
    return diagnostic_writer() is not None


def tracing() -> bool:
    writer = diagnostic_writer()
    return writer is not None and writer.trace


def normal_tracing() -> bool:
    writer = diagnostic_writer()
    return writer is not None and getattr(writer, "normal_trace", writer.trace)


def emit(event: str, *, trace: bool = False, priority: bool = False, **fields) -> None:
    writer = diagnostic_writer()
    if writer is not None:
        try:
            writer.event(event, fields, trace=trace, priority=priority)
        except Exception:
            # An observation must never escape into the input or check callback.
            writer.observation_failed()


def observation_failed() -> None:
    writer = diagnostic_writer()
    if writer is not None:
        writer.observation_failed()


def safe_action(action: str | None) -> str | None:
    if action is None:
        return None
    command = action.removeprefix("speech_window:")
    return command if command in SAFE_ACTIONS else "content_target"


class TargetContext:
    """Opaque IDs live only for one displayed interaction context."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.id = uuid.uuid4().hex
        self._tokens: dict[str, str] = {}

    def token(self, action: str | None) -> str | None:
        if action is None:
            return None
        if not isinstance(action, str):
            return "unidentified_target"
        known = safe_action(action)
        if known != "content_target":
            return known
        if action not in self._tokens:
            # Random IDs do not encode a letter, index or order of selection.
            if len(self._tokens) >= 512:
                return "content_target"
            self._tokens[action] = uuid.uuid4().hex
        return self._tokens[action]


class StreamMetrics:
    """One-second summaries; stale last-known eye states earn no extra valid time."""

    def __init__(self, *, event_name: str = "stream_summary", **summary_fields) -> None:
        self._lock = threading.RLock()
        self._event_name = event_name
        self._summary_fields = summary_fields
        self._known_states: dict[str, str] = {}
        self._writer = None
        self.started = time.monotonic()
        self.counts: Counter = Counter()
        self.durations: Counter = Counter()
        self._states: dict[str, tuple[str, float, float]] = {}
        self._rates: dict[str, tuple[float, int]] = {}
        with _metrics_lock:
            _metrics.add(self)

    def _ready(self) -> bool:
        writer = diagnostic_writer()
        if writer is None:
            self._writer = None
            return False
        identity = (writer, getattr(writer, "observation_generation", writer._generation))
        if identity != self._writer:
            self._writer = identity
            self.started = time.monotonic()
            self.counts.clear()
            self.durations.clear()
            self._states.clear()
            # Applied gates remain known while logging is off. Native eye
            # samples must be received again before earning valid time.
            for stream, state in self._known_states.items():
                self._states[stream] = state, self.started, float("inf")
            self._rates.clear()
        return True

    def count(self, reason: str, amount: int = 1) -> None:
        with self._lock:
            if self._ready():
                self.counts[reason] += amount

    def eyes(self, stream: str, state: str, *, sampled: bool, stale_after: float | None) -> None:
        with self._lock:
            ready = self._ready()
            if stale_after is None:
                self._known_states[stream] = state
            if not ready:
                return
            now = time.monotonic()
            self._accrue(stream, now)
            old = self._states.get(stream)
            fresh_at = now if sampled or old is None else old[2]
            expires = (
                float("inf")
                if stale_after is None
                else fresh_at + stale_after
                if sampled
                else fresh_at
            )
            self._states[stream] = state, now, expires

    def _accrue(self, stream: str, now: float) -> None:
        previous = self._states.get(stream)
        if previous is None:
            return
        state, cursor, expires = previous
        valid_end = min(now, expires)
        self.durations[f"{stream}:{state}"] += max(0.0, valid_end - cursor)
        self.durations[f"{stream}:stale_unknown"] += max(0.0, now - max(cursor, expires))
        self._states[stream] = state, now, expires

    def event(self, event: str, **fields) -> None:
        with self._lock:
            if not self._ready():
                return
            now = time.monotonic()
            start, count = self._rates.get(event, (now, 0))
            if now - start >= 1:
                start, count = now, 0
            self._rates[event] = start, count + 1
            if count >= 4 and not normal_tracing():
                self.counts[f"suppressed:{event}"] += 1
            if tracing() or count < 4:
                emit(event, trace=count >= 4, **fields)

    def summary(self, *, force: bool = False, **fields) -> bool:
        with self._lock:
            self._update_summary_fields(fields)
            if not self._ready():
                return False
            now = time.monotonic()
            interval = max(0.0, now - self.started)
            if interval < 1 and not force:
                return False
            for stream in tuple(self._states):
                self._accrue(stream, now)
            if force and not self._has_observations():
                return False
            emit(
                self._event_name,
                priority=True,
                interval_s=interval,
                counts=dict(self.counts),
                eye_state_seconds=dict(self.durations),
                **self._summary_fields,
            )
            self.started = now
            self.counts.clear()
            self.durations.clear()
            return True

    def _has_observations(self) -> bool:
        return bool(self.counts) or any(self.durations.values())

    def _update_summary_fields(self, fields: dict) -> None:
        event_name = fields.pop("event_name", None)
        generation = fields.pop("generation", None)
        backend = fields.pop("backend", None)
        if event_name is not None:
            self._event_name = event_name
        if generation is not None:
            fields["stream_generation"] = generation
        if backend is not None:
            fields["backend"] = backend
        self._summary_fields.update(fields)


def eye_state(left: bool, right: bool) -> str:
    return (
        "both_valid"
        if left and right
        else "right_invalid"
        if left
        else "left_invalid"
        if right
        else "both_invalid"
    )


class SelectionObserver:
    def __init__(self, source: str) -> None:
        self.source = source
        self.context = TargetContext(source)
        self.attempt: str | None = None
        self._state = None
        self._writer = None
        self._started_at: float | None = None
        self._credited_ms = 0.0
        self._rates = StreamMetrics(
            event_name="selection_summary", source=source, context_id=self.context.id
        )

    def observe(self, snapshot: dict, *, reason: str, pause_ms: int = 0, dwell_ms: int = 0) -> None:
        if not self._ready():
            return
        target = self.context.token(snapshot["target"])
        phase = self._phase(snapshot, pause_ms)
        state = (self.context.id, target, phase)
        previous = self._state
        self._summarize_context()
        if self._skip_idle(snapshot, state, reason):
            return
        self._update_attempt(snapshot["active"], state)
        fields = {
            "source": self.source,
            "context_id": self.context.id,
            "attempt_id": self.attempt,
            "target_id": target,
            "phase": phase,
            "reason": reason,
            "credited_ms": snapshot["credited_ms"],
            "pause_ms": pause_ms,
            "dwell_ms": dwell_ms,
        }
        if state != previous or reason != "sample":
            self._rates.event("selection_state", elapsed_ms=self._elapsed_ms(), **fields)
        emit("selection_sample", trace=True, **fields)
        if not snapshot["active"]:
            self._end_attempt(reason)
        self._state = state
        self._credited_ms = snapshot["credited_ms"]
        if not snapshot["active"]:
            self._rates.summary(force=True)

    def _skip_idle(self, snapshot: dict, state: tuple, reason: str) -> bool:
        if snapshot["active"] or reason == "sample":
            return False
        return state == self._state

    def _summarize_context(self) -> None:
        if self._state is not None and self._state[0] != self.context.id:
            self._rates.summary(force=True)
        self._rates.summary(
            event_name="selection_summary", source=self.source, context_id=self.context.id
        )

    def _ready(self) -> bool:
        writer = diagnostic_writer()
        identity = (
            (writer, getattr(writer, "observation_generation", writer._generation))
            if writer is not None
            else None
        )
        if identity != self._writer:
            self._state = None
            self.attempt = None
            self._started_at = None
            self._writer = identity
        return writer is not None

    @staticmethod
    def _phase(snapshot: dict, pause_ms: int) -> str:
        if not snapshot["active"]:
            return "repeat_locked" if snapshot["blocked"] else "idle"
        if snapshot["held"]:
            return "edge_hold"
        return "pause" if snapshot["credited_ms"] < pause_ms else "dwell"

    def _elapsed_ms(self) -> float | None:
        if self._started_at is None:
            return None
        return max(0.0, time.monotonic() - self._started_at) * 1000

    def _update_attempt(self, active: bool, state: tuple) -> None:
        if not active:
            return
        previous = self._state
        same_target = previous is not None and previous[:2] == state[:2]
        if self.attempt is not None and same_target:
            return
        if self.attempt is not None:
            self._rates.event(
                "selection_end",
                source=self.source,
                context_id=previous[0],
                attempt_id=self.attempt,
                reason="target_or_context_changed",
                credited_ms_before_end=self._credited_ms,
            )
        self.attempt = uuid.uuid4().hex
        self._started_at = time.monotonic()

    def _end_attempt(self, reason: str) -> None:
        if self.attempt is None:
            return
        self._rates.event(
            "selection_end",
            source=self.source,
            context_id=self.context.id,
            attempt_id=self.attempt,
            reason=reason if reason != "sample" else "target_departure",
            credited_ms_before_end=self._credited_ms,
            elapsed_ms=self._elapsed_ms(),
        )
        self.attempt = None
        self._started_at = None
