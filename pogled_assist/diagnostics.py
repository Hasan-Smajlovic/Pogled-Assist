"""Observations at existing input boundaries, independent of gaze decisions."""

from __future__ import annotations

import time
import uuid
from collections import Counter

from .logging_setup import diagnostic_writer

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


def enabled() -> bool:
    return diagnostic_writer() is not None


def tracing() -> bool:
    writer = diagnostic_writer()
    return writer is not None and writer.trace


def emit(event: str, *, trace: bool = False, priority: bool = False, **fields) -> None:
    writer = diagnostic_writer()
    if writer is not None:
        try:
            writer.event(event, fields, trace=trace, priority=priority)
        except Exception:
            # An observation must never escape into the input or check callback.
            writer._failure()


def observation_failed() -> None:
    writer = diagnostic_writer()
    if writer is not None:
        writer._failure()


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

    def __init__(self) -> None:
        self._writer = None
        self.started = time.monotonic()
        self.counts: Counter = Counter()
        self.durations: Counter = Counter()
        self._states: dict[str, tuple[str, float, float]] = {}
        self._rates: dict[str, tuple[float, int]] = {}

    def _ready(self) -> bool:
        writer = diagnostic_writer()
        if writer is None:
            self._writer = None
            return False
        identity = (writer, writer._generation)
        if identity != self._writer:
            self._writer = identity
            self.started = time.monotonic()
            self.counts.clear()
            self.durations.clear()
            self._states.clear()
            self._rates.clear()
        return True

    def count(self, reason: str, amount: int = 1) -> None:
        if self._ready():
            self.counts[reason] += amount

    def eyes(self, stream: str, state: str, *, sampled: bool, stale_after: float | None) -> None:
        if not self._ready():
            return
        now = time.monotonic()
        self._accrue(stream, now)
        old = self._states.get(stream)
        fresh_at = now if sampled or old is None else old[2]
        expires = (
            float("inf") if stale_after is None else fresh_at + stale_after if sampled else fresh_at
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
        if not self._ready():
            return
        now = time.monotonic()
        start, count = self._rates.get(event, (now, 0))
        if now - start >= 1:
            start, count = now, 0
        self._rates[event] = start, count + 1
        if tracing() or count < 4:
            emit(event, trace=count >= 4, **fields)
        else:
            self.counts[f"suppressed:{event}"] += 1

    def summary(
        self,
        *,
        generation: int | None = None,
        backend: str | None = None,
        event_name: str = "stream_summary",
        **fields,
    ) -> bool:
        if not self._ready():
            return False
        now = time.monotonic()
        if now - self.started < 1:
            return False
        for stream in tuple(self._states):
            self._accrue(stream, now)
        if generation is not None:
            fields["stream_generation"] = generation
        if backend is not None:
            fields["backend"] = backend
        emit(
            event_name,
            priority=True,
            interval_s=now - self.started,
            counts=dict(self.counts),
            eye_state_seconds=dict(self.durations),
            **fields,
        )
        self.started = now
        self.counts.clear()
        self.durations.clear()
        return True


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
        self._rates = StreamMetrics()

    def observe(self, snapshot: dict, *, reason: str, pause_ms: int = 0, dwell_ms: int = 0) -> None:
        writer = diagnostic_writer()
        identity = (writer, writer._generation) if writer is not None else None
        if identity != self._writer:
            self._state = None
            self.attempt = None
            self._started_at = None
            self._writer = identity
        if writer is None:
            return
        target = self.context.token(snapshot["target"])
        phase = "repeat_locked" if snapshot["blocked"] else "idle"
        if snapshot["active"]:
            phase = (
                "edge_hold"
                if snapshot["held"]
                else "pause"
                if snapshot["credited_ms"] < pause_ms
                else "dwell"
            )
        state = (self.context.id, target, phase)
        previous = self._state
        self._rates.summary(
            event_name="selection_summary", source=self.source, context_id=self.context.id
        )
        if state == previous and not snapshot["active"] and reason != "sample":
            return
        if snapshot["active"] and (
            self.attempt is None or previous is None or previous[:2] != state[:2]
        ):
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
        if state != previous or reason != "sample":
            self._rates.event(
                "selection_state",
                source=self.source,
                context_id=self.context.id,
                attempt_id=self.attempt,
                target_id=target,
                phase=phase,
                reason=reason,
                credited_ms=snapshot["credited_ms"],
                elapsed_ms=max(0.0, time.monotonic() - self._started_at) * 1000
                if self._started_at is not None
                else None,
                pause_ms=pause_ms,
                dwell_ms=dwell_ms,
            )
        emit(
            "selection_sample",
            trace=True,
            source=self.source,
            context_id=self.context.id,
            attempt_id=self.attempt,
            target_id=target,
            phase=phase,
            reason=reason,
            credited_ms=snapshot["credited_ms"],
            pause_ms=pause_ms,
            dwell_ms=dwell_ms,
        )
        if not snapshot["active"] and self.attempt is not None:
            self._rates.event(
                "selection_end",
                source=self.source,
                context_id=self.context.id,
                attempt_id=self.attempt,
                reason=reason if reason != "sample" else "target_departure",
                credited_ms_before_end=self._credited_ms,
                elapsed_ms=max(0.0, time.monotonic() - self._started_at) * 1000
                if self._started_at is not None
                else None,
            )
            self.attempt = None
            self._started_at = None
        self._state = state
        self._credited_ms = snapshot["credited_ms"]
