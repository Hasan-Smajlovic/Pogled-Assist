"""Observations at existing input boundaries, independent of gaze decisions."""

from __future__ import annotations

import threading
import time
import uuid
import weakref
from collections import Counter
from contextvars import ContextVar

from .logging_setup import diagnostic_writer

_metrics = weakref.WeakSet()
_metrics_lock = threading.Lock()
_action_origin = ContextVar("diagnostic_action", default=None)
ESSENTIAL_EVENTS = frozenset(
    {
        "selection_end",
        "selection_state",
        "selection_hold_end",
        "selection_credit_discarded",
        "ui_action_requested",
        "ui_action_returned",
        "ui_action_rejected",
    }
)


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


def emit(event: str, *, trace: bool = False, priority: bool = False, **fields) -> bool:
    writer = diagnostic_writer()
    if writer is not None:
        try:
            return writer.event(event, fields, trace=trace, priority=priority) is not False
        except Exception:
            # An observation must never escape into the input or check callback.
            writer.observation_failed()
    return False


def observation_failed() -> None:
    writer = diagnostic_writer()
    if writer is not None:
        writer.observation_failed()


def safe_action(action: str | None) -> str | None:
    if action is None:
        return None
    if not isinstance(action, str):
        return "content_target"
    command = action.removeprefix("speech_window:")
    return command if command in SAFE_ACTIONS else "content_target"


class TargetContext:
    """Opaque IDs live only for one displayed interaction context."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.id = uuid.uuid4().hex
        self._tokens: dict[object, str] = {}

    def token(self, action: str | None) -> str | None:
        if action is None:
            return None
        known = safe_action(action)
        if known != "content_target":
            return known
        if action not in self._tokens:
            # Random IDs do not encode a letter, index or order of selection.
            if len(self._tokens) >= 512:
                return "content_target"
            self._tokens[action] = uuid.uuid4().hex
        return self._tokens[action]


def control_role(action: object) -> str:
    if not isinstance(action, str):
        return "control"
    command = (
        action.removeprefix("speech_window:")
        .removeprefix("keyboard_window:")
        .removeprefix("controller_window:")
    )
    kind = command.partition(":")[0]
    kind = kind.removeprefix("keyboard_")
    if kind in {"group", "letter", "confirm", "suggestion", "key", "phrase", "category", "answer"}:
        return kind
    return "control" if safe_action(action) != "content_target" else "content_control"


def invoke_action(callback, *, context=None, action=None, source="unknown", selection=None):
    """Keep dispatch identity alive while a synchronous handler replaces its controls."""
    if not enabled():
        return callback()
    dispatch = _action_origin.get()
    if dispatch is not None:
        return _call_handler(callback, dispatch)
    origin = getattr(getattr(selection, "_observer", None), "completed", None)
    fields = dict(origin or {}) if source == "gaze" else {}
    if not fields:
        context = context or TargetContext("action")
        fields = dict(
            context_id=context.id,
            target_id=context.token(action),
            surface=context.kind,
            role=control_role(action),
            attempt_id=None,
        )
    fields.update(action_id=uuid.uuid4().hex, origin=source, source=source)
    dispatch = {"outcome": "handler_returned"}
    token = _action_origin.set(dispatch)
    emit("ui_action_requested", priority=True, **fields)
    try:
        return _call_handler(callback, dispatch)
    finally:
        emit("ui_action_returned", priority=True, **dispatch, **fields)
        _action_origin.reset(token)


def _call_handler(callback, dispatch):
    try:
        return callback()
    except BaseException:
        # Qt reports slot exceptions through sys.excepthook and returns from emit().
        # Remember the failure at the handler boundary before Qt intercepts it.
        dispatch["outcome"] = "handler_failed"
        raise


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
        self._last_events = {}
        self._total_counts = Counter()
        self._stream_id = uuid.uuid4().hex
        self._interval_index = 0
        self._missing_intervals = 0
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
            self._last_events.clear()
            self._total_counts.clear()
            self._stream_id = uuid.uuid4().hex
            self._interval_index = self._missing_intervals = 0
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
            if event not in ESSENTIAL_EVENTS:
                if self._last_events.get(event) == fields:
                    return
                self._last_events[event] = fields
            if isinstance(fields.get("reason"), str):
                self.counts[f"reason:{event}:{fields['reason']}"] += 1
            if event in ESSENTIAL_EVENTS:
                reason = fields.get("reason", fields.get("outcome", "unknown"))
                if event in {"selection_end", "selection_hold_end"}:
                    self.counts[f"outcome:{reason}"] += 1
                emit(event, priority=True, **fields)
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
            if not self._has_observations():
                return False
            self._total_counts.update(self.counts)
            self._interval_index += 1
            accepted = emit(
                self._event_name,
                priority=True,
                interval_id=uuid.uuid4().hex,
                observation_stream_id=self._stream_id,
                interval_index=self._interval_index,
                previous_intervals_dropped=self._missing_intervals,
                cumulative_counts=dict(self._total_counts),
                interval_s=interval,
                counts=dict(self.counts),
                eye_state_seconds=dict(self.durations),
                **self._summary_fields,
            )
            self.started = now
            self.counts.clear()
            self.durations.clear()
            self._missing_intervals = 0 if accepted else self._missing_intervals + 1
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
    """Observe timer boundaries; never infer a restart from a sampled phase."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.context = TargetContext(source)
        self.attempt = None
        self.completed = None
        self._state = None
        self._writer = None
        self._started_at = None
        self._credited_ms = 0.0
        self._fields = {}
        self._hold = None
        self._settings = None
        self._settings_id = None
        self._coverage = "unknown"
        self._rates = StreamMetrics(event_name="selection_summary", source=source)

    def _ready(self) -> bool:
        writer = diagnostic_writer()
        identity = (
            (writer, getattr(writer, "observation_generation", writer._generation))
            if writer
            else None
        )
        if identity != self._writer:
            self._state = self.attempt = self._started_at = self._hold = None
            self.completed = None
            self._settings = None
            self._writer = identity
        return writer is not None

    @staticmethod
    def _phase(snapshot: dict, pause_ms: int) -> str:
        if not snapshot["active"]:
            return "repeat_locked" if snapshot["blocked"] else "idle"
        if snapshot.get("tracking_hold"):
            return "tracking_" + snapshot["tracking_hold"] + "_hold"
        if snapshot["held"]:
            return "edge_hold"
        return "pause" if snapshot["credited_ms"] < pause_ms else "dwell"

    def _elapsed_ms(self):
        return (
            max(0.0, time.monotonic() - self._started_at) * 1000
            if self._started_at is not None
            else None
        )

    def observe(self, snapshot: dict, *, reason: str, pause_ms=0, dwell_ms=0) -> None:
        if not self._ready():
            return
        settings = pause_ms, dwell_ms
        if settings != self._settings:
            self._settings = settings
            self._settings_id = uuid.uuid4().hex
            emit(
                "selection_settings",
                priority=True,
                settings_id=self._settings_id,
                source=self.source,
                pause_ms=pause_ms,
                dwell_ms=dwell_ms,
            )
        if not snapshot["active"]:
            self.finish(snapshot, reason=reason if reason != "sample" else "target_departure")
            return
        target = self.context.token(snapshot["target"])
        identity = self.context.id, target
        if self.attempt is not None and identity != self._state[:2]:
            self.finish(
                None,
                reason="context_changed" if identity[0] != self._state[0] else "target_changed",
            )
        starting = self.attempt is None
        if starting:
            self.attempt = uuid.uuid4().hex
            self._started_at = time.monotonic()
            self._credited_ms = 0.0
            self._coverage = "partial_start" if snapshot["credited_ms"] > 0 else "observed_start"
            self.completed = None
        phase = self._phase(snapshot, pause_ms)
        fields = dict(
            source=self.source,
            surface=self.context.kind,
            role=control_role(snapshot["target"]),
            context_id=self.context.id,
            target_id=target,
            attempt_id=self.attempt,
            settings_id=self._settings_id,
            affected_eye=snapshot.get("affected_eye"),
        )
        self._fields = fields
        self._observe_hold(phase, snapshot["credited_ms"])
        state = (*identity, phase)
        if state != self._state:
            self._rates.event(
                "selection_state",
                phase=phase,
                reason=reason,
                credited_ms=snapshot["credited_ms"],
                elapsed_ms=self._elapsed_ms(),
                attempt_started=starting,
                **fields,
            )
        emit(
            "selection_sample",
            trace=True,
            phase=phase,
            reason=reason,
            credited_ms=snapshot["credited_ms"],
            **fields,
        )
        self._credited_ms = snapshot["credited_ms"]
        self._state = state
        self._rates.summary()

    def _observe_hold(self, phase, credit):
        held = phase.endswith("_hold")
        if self._hold is not None and not held:
            self._end_hold("resumed", "sample", credit)
        if held and self._hold is None:
            self._hold = (
                time.monotonic(),
                phase,
                self._credited_ms,
                self._fields.get("affected_eye"),
            )
        if credit < self._credited_ms:
            self._rates.event(
                "selection_credit_discarded",
                **self._fields,
                discarded_ms=self._credited_ms - credit,
                retained_ms=credit,
                reason="completed_pause_retained",
            )

    def _end_hold(self, outcome, reason, credit):
        if self._hold is None:
            return
        started, kind, original_credit, affected_eye = self._hold
        fields = {**self._fields, "affected_eye": affected_eye}
        self._rates.event(
            "selection_hold_end",
            **fields,
            kind=kind,
            duration_ms=max(0.0, time.monotonic() - started) * 1000,
            hold_started_monotonic_s=started,
            outcome=outcome,
            reason=reason,
            retained_ms=credit,
            discarded_ms=max(0.0, original_credit - credit),
        )
        self._hold = None

    def finish(self, snapshot, *, reason: str) -> None:
        if not self._ready() or self.attempt is None:
            return
        credit = snapshot["credited_ms"] if snapshot and snapshot["active"] else self._credited_ms
        self._end_hold("expired" if "expired" in reason else "cancelled", reason, 0)
        fields = dict(self._fields)
        self._rates.event(
            "selection_end",
            **fields,
            reason=reason,
            elapsed_ms=self._elapsed_ms(),
            credited_ms_before_end=credit,
            discarded_ms=0 if reason == "completed" else credit,
            coverage=self._coverage,
        )
        if reason == "completed":
            self.completed = fields
        self.attempt = self._started_at = self._state = None
        self._credited_ms = 0.0
