"""Bounded logging transport; only the writer touches output streams."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import Counter, deque
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from .log_context import update_context
from .log_output import OrdinaryOutput
from .log_snapshot import BoundedSnapshot

if TYPE_CHECKING:
    from .diagnostic_recording import Recording, RecordingSink

MAX_RECORD_BYTES = 8192
MAX_QUEUE_RECORDS = 1024
PRIORITY_RESERVE = 64
TRACE_SECONDS = 600
TRACE_BYTES = 32 * 1024 * 1024
SEGMENT_BYTES = 16 * 1024 * 1024
PROCESS_INSTANCE = uuid.uuid4().hex
SUMMARY_EVENTS = frozenset({"stream_summary", "selection_summary", "marker_summary"})


class LogWriter:
    """Keep disk and console waits off input threads, including runtime rotation."""

    def __init__(self, *, capacity: int = MAX_QUEUE_RECORDS) -> None:
        self.capacity = capacity
        self._condition = threading.Condition()
        self._queue: deque = deque()
        self._closing_segments: deque = deque()
        self._closing_records = 0
        self._generation = 0
        self._observation_generation = 0
        self._desired: tuple | None = None
        self._stopping = False
        self._sequence = 0
        self._trace = False
        self._trace_until = 0.0
        self._dropped: Counter = Counter()
        self._drop_start: float | None = None
        self._drop_end: float | None = None
        self._high_water = 0
        self._errors = 0
        self._truncated = 0
        self._context_snapshots = {}
        self._admitted_context = {}
        self._persistence = {}
        self._gap_history = deque(maxlen=64)
        self._gap_count = 0
        self._successful_writes = set()
        self._change_at = (time.monotonic(), time.time())
        self._recording: Recording | None = None
        self._recording_sink: RecordingSink | None = None
        self._recording_open_attempted = False
        self._recording_result: dict | None = None
        self._output = OrdinaryOutput(self, lambda: (SEGMENT_BYTES, TRACE_BYTES), PROCESS_INSTANCE)
        self._thread = threading.Thread(target=self._run, name="pogled-log-writer", daemon=True)
        self._thread.start()

    @property
    def enabled(self) -> bool:
        return (self._desired is not None or self.recording_active) and not self._stopping

    @property
    def recording_active(self) -> bool:
        return self._recording is not None and self._recording.accepting

    @property
    def observation_generation(self) -> tuple:
        return self._observation_generation

    @property
    def observation_start_sessions(self) -> tuple[str, ...]:
        """Destinations that cover a metrics stream's first observation."""
        with self._condition:
            sessions = (self._desired[3],) if self._desired is not None else ()
            if self.recording_active:
                sessions += (self._recording.id,)
            return sessions

    def start_recording(self, directory: Path, minutes: int, context: dict) -> str | None:
        from .diagnostic_recording import DURATIONS, Recording, set_recording_active

        if minutes not in DURATIONS:
            raise ValueError("Unsupported recording duration")
        with self._condition:
            if self._stopping or self._recording is not None:
                return None
            if not self.enabled:
                self._observation_generation += 1
            item = Recording(
                uuid.uuid4().hex,
                directory,
                time.monotonic(),
                time.time(),
                minutes,
                bounded_copy(context),
            )
            item.initial_snapshots = dict(self._admitted_context)
            self._recording = item
            set_recording_active(directory, item.id, True)
            self._recording_open_attempted = False
            self._recording_result = None
            self._condition.notify()
            return item.id

    def stop_recording(self, reason: str = "manual") -> None:
        with self._condition:
            item = self._recording
            if item is not None and item.accepting:
                item.accepting = False
                item.state, item.reason = "finishing", reason
                item.ended_mono, item.ended_wall = time.monotonic(), time.time()
                if reason == "time":
                    item.ended_mono = item.deadline
                    item.ended_wall = item.started_wall + item.minutes * 60
                self._condition.notify()

    def recording_status(self) -> dict | None:
        with self._condition:
            item = self._recording
            accepting = item is not None and item.accepting
            if accepting and time.monotonic() >= item.deadline:
                self.stop_recording("time")
            result = item.snapshot() if item else self._recording_result
            if result is None:
                return None
            result = dict(result)
            result["busy"] = item is not None
            if item is not None:
                if not item.accepting:
                    result["state"], result["complete"] = "finishing", False
                result["remaining_seconds"] = max(0, item.deadline - time.monotonic())
            return result

    @property
    def finished(self) -> bool:
        return not self._thread.is_alive()

    @property
    def normal_trace(self) -> bool:
        return bool(
            self._desired is not None and self._trace and time.monotonic() < self._trace_until
        )

    @property
    def trace(self) -> bool:
        now = time.monotonic()
        item = self._recording
        return self.enabled and (
            (self._trace and now < self._trace_until)
            or (item is not None and item.accepting and now < item.deadline)
        )

    def start_segment(self, latest: Path | None, console, *, trace: bool) -> None:
        with self._condition:
            if self._stopping:
                return
            if not self.enabled:
                self._observation_generation += 1
            self._seal_summaries("segment_replaced")
            self._discard_pending("segment_replaced")
            self._generation += 1
            self._sequence = 0
            session = uuid.uuid4().hex
            self._change_at = (time.monotonic(), time.time())
            self._trace = trace
            self._trace_until = time.monotonic() + TRACE_SECONDS
            self._desired = (
                self._generation,
                latest,
                console,
                session,
                trace,
                self._trace_until,
                dict(self._admitted_context),
                self._change_at,
            )
            self._condition.notify()
        self.event("session_start", {"mode": "trace" if trace else "basic"}, priority=True)

    def disable(self) -> None:
        with self._condition:
            self._seal_summaries("logging_disabled")
            self._desired = None
            self._change_at = (time.monotonic(), time.time())
            self._trace = False
            self._discard_pending("logging_disabled")
            self._condition.notify()

    def event(
        self, name: str, fields: dict, *, trace: bool = False, priority: bool = False
    ) -> bool:
        if not self.enabled:
            return False
        if trace and not self.trace:
            return False
        now = time.monotonic()
        generation = (
            self._generation
            if self._desired is not None and (not trace or self.normal_trace)
            else None
        )
        recording_id = self._recording.id if self.recording_active else None
        payload = (
            bounded_copy(fields, summary=True) if name in SUMMARY_EVENTS else bounded_copy(fields)
        )
        payload["observation_id"] = uuid.uuid4().hex
        return self._put(
            "event", (name, payload, now, time.time(), trace), priority, generation, recording_id
        )

    def record(self, record: logging.LogRecord) -> None:
        if self._desired is None or self._stopping:
            return
        generation = self._generation
        # Never retain a traceback's locals, ctypes objects or live Qt arguments.
        fields = {
            "name": record.name,
            "levelno": record.levelno,
            "levelname": record.levelname,
            "msg": record.msg,
            "args": record.args,
            "created": record.created,
            "msecs": record.msecs,
        }
        if record.exc_info:
            frames = []
            tb = record.exc_info[2]
            while tb is not None and len(frames) < 16:
                code = tb.tb_frame.f_code
                frames.append((code.co_filename, tb.tb_lineno, code.co_name))
                tb = tb.tb_next
            fields["exception_type"] = record.exc_info[0].__name__
            fields["exception_frames"] = frames
            # Exception text can contain user content; retain the type and stack only.
        self._put("record", bounded_copy(fields), record.levelno >= logging.ERROR, generation)

    def health(self) -> dict:
        with self._condition:
            return {
                "queued": len(self._queue) + self._closing_records,
                "capacity": self.capacity,
                "high_water": self._high_water,
                "dropped": dict(self._dropped),
                "drop_start_monotonic_s": self._drop_start,
                "drop_end_monotonic_s": self._drop_end,
                "writer_errors": self._errors,
                "bounded_snapshots": self._truncated,
            }

    def note_drop(self, reason: str) -> None:
        """Count producer-side loss without writing or logging recursively."""
        with self._condition:
            if self.enabled:
                self._drop(reason)

    def observation_failed(self) -> None:
        self._failure()
        with self._condition:
            if self.recording_active:
                item = self._recording
                item.dropped["observation_error"] = item.dropped.get("observation_error", 0) + 1

    def stop(self, timeout: float = 2.0) -> bool:
        self.stop_recording("shutdown")
        with self._condition:
            if not self._stopping:
                self._change_at = (time.monotonic(), time.time())
                self.event("session_end", {"reason": "shutdown"}, priority=True)
                self._stopping = True
                self._condition.notify()
        self._thread.join(max(0.0, timeout))
        return not self._thread.is_alive()

    def _put(
        self,
        kind: str,
        payload: object,
        priority: bool,
        generation: int | None,
        recording_id: str | None = None,
    ) -> bool:
        with self._condition:
            if not self.enabled:
                return False
            item = self._recordable(recording_id)
            if not self._accept_generation(generation, item):
                return False
            # A new destination needs the counter position at its boundary,
            # even if this preceding interval cannot enter the output queue.
            if kind == "event" and payload[0] in SUMMARY_EVENTS:
                update_context(self._admitted_context, payload[0], payload[1])
            if not self._queue_has_room(priority, kind, item):
                return False
            if kind == "event":
                update_context(self._admitted_context, payload[0], payload[1])
            self._count_snapshot(kind, payload, item)
            self._sequence += 1
            if item is not None:
                item.pending += 1
            self._queue.append(
                (generation, self._sequence, kind, payload, item.id if item is not None else None)
            )
            self._high_water = max(self._high_water, len(self._queue) + self._closing_records)
            self._condition.notify()
            return True

    def _recordable(self, recording_id):
        item = self._recording
        if item is None:
            return None
        if item.id != recording_id or not item.accepting:
            return None
        if time.monotonic() >= item.deadline:
            self.stop_recording("time")
            return None
        return item

    def _accept_generation(self, generation, recording) -> bool:
        if recording is not None:
            return True
        if generation is None:
            return False
        if generation != self._generation:
            self._drop("old_segment")
            return False
        return True

    def _queue_has_room(self, priority, kind, recording) -> bool:
        reserve = min(PRIORITY_RESERVE, self.capacity // 4)
        limit = self.capacity if priority else self.capacity - reserve
        if len(self._queue) + self._closing_records < limit:
            return True
        self._drop(kind)
        if recording is not None:
            recording.dropped[kind] = recording.dropped.get(kind, 0) + 1
        return False

    def _count_snapshot(self, kind, payload, recording) -> None:
        copied = payload[1] if kind == "event" else payload
        if not isinstance(copied, dict) or not copied.get("_snapshot_truncated"):
            return
        self._truncated += 1
        if recording is not None:
            recording.bounded_snapshots += 1

    def _drop(self, category: str, count: int = 1) -> None:
        self._dropped[category] += count
        now = time.monotonic()
        if self._drop_start is None:
            self._drop_start = now
        self._drop_end = now

    def _discard_pending(self, reason: str) -> None:
        if self._queue:
            retained, lost = deque(), 0
            for item in self._queue:
                if item[0] is not None:
                    lost += 1
                if item[4] is not None:
                    # Discard only the ordinary leg and account for its loss.
                    # The recording leg keeps its position in the shared queue.
                    retained.append((None, *item[1:]))
            if lost:
                self._drop(reason, lost)
            self._queue = retained

    def _seal_summaries(self, reason: str) -> None:
        """Retain bounded technical footers for the writer, never wait for I/O."""
        if self._desired is None:
            return
        if not any(_ordinary_event_in(item, SUMMARY_EVENTS) for item in self._queue):
            return
        # If the writer has not opened this segment, retain its lifecycle start
        # too. Ordinary backlog still follows the existing discard policy.
        retained, pending = [], deque()
        available = self.capacity - len(self._queue) - self._closing_records
        footer_events = SUMMARY_EVENTS | {"session_start"}
        for item in self._queue:
            if _ordinary_event_in(item, footer_events):
                available = self._retain_footer(item, retained, pending, available)
            else:
                pending.append(item)
        self._queue = pending
        self._closing_records += len(retained)
        self._closing_segments.append(
            (self._desired, (time.monotonic(), time.time()), reason, retained)
        )

    def _retain_footer(self, item, retained, pending, available):
        if item[4] is None:
            retained.append(item)
            return available
        # Ordinary footers can jump ahead; recording keeps its queue order.
        pending.append((None, *item[1:]))
        if available > 0:
            retained.append((*item[:4], None))
            return available - 1
        self._drop("segment_footer")
        return available

    def _run(self) -> None:
        end_reason = "shutdown"
        try:
            self._drain()
        except Exception:
            end_reason = "writer_failure"
            self._abort()
        finally:
            if self._recording is not None:
                self.stop_recording("writer_error")
                self._finish_recording()
            self._output._end_active(end_reason)
            self._output._close_files()

    def _drain(self) -> None:
        last_flush = time.monotonic()
        while True:
            self._update_recording()
            closing, desired, changed_at, item, done = self._next_batch()
            # A start can wake _next_batch together with its first sample.
            # Open the destination before consuming that sample.
            self._update_recording()
            if closing is not None:
                self._finish_segment(closing)
                continue
            if desired != self._output._active:
                self._output._switch_segment(desired, changed_at)
            self._output._retry_outputs()
            if item is not None:
                self._consume(item)
            self._update_recording()
            now = time.monotonic()
            if now - last_flush >= 0.25 or done:
                self._flush()
                last_flush = now
            if done:
                break

    def _next_batch(self) -> tuple:
        with self._condition:
            idle = not (self._queue or self._closing_segments or self._stopping)
            if idle and self._desired == self._output._active:
                self._condition.wait(0.25)
            closing = self._closing_segments.popleft() if self._closing_segments else None
            item = self._queue.popleft() if self._queue and closing is None else None
            done = self._stopping and item is None
            return closing, self._desired, self._change_at, item, done

    def _finish_segment(self, closing: tuple) -> None:
        segment, ended_at, reason, summaries = closing
        if self._output._active != segment:
            self._output._switch_segment(segment, ended_at)
        for summary in summaries:
            self._consume(summary)
            with self._condition:
                self._closing_records -= 1
        self._output._end_active(reason, ended_at)
        self._output._switch_segment(None, ended_at)

    def _belongs_to_active(self, item: tuple | None) -> bool:
        if item is None or self._output._active is None:
            return False
        return item[0] == self._output._active[0]

    def _abort(self) -> None:
        self._failure()
        with self._condition:
            self._stopping = True
            self._discard_pending("writer_failed")
            if self._closing_records:
                self._drop("writer_failed", self._closing_records)
            self._closing_records = 0
            self._closing_segments.clear()
            if self._recording is not None:
                self._recording.dropped["writer_failed"] = self._recording.pending
                self._recording.pending = 0
                self._recording.writer_errors += 1

    def _failure(self, output=None, reason="write") -> None:
        # Reporting through root logging here would recurse into this writer.
        with self._condition:
            self._errors += 1
            self._drop("writer_error")
            if output is None:
                return
            channel = (
                "text_rotation"
                if reason == "text_rotation"
                else "text"
                if reason.startswith("text")
                else "metadata"
                if reason == "metadata"
                else "json"
            )
            key = output, channel
            self._successful_writes.discard(key)
            if key not in self._persistence:
                self._gap_count += 1
                self._gap_history.append(
                    dict(
                        output=output,
                        channel=channel,
                        reason=reason,
                        started_at=time.time(),
                        recovered_at=None,
                    )
                )
            self._persistence[key] = reason

    def _recovered(self, output, channel):
        with self._condition:
            key = output, channel
            if key in self._persistence:
                self._persistence.pop(key, None)
                for gap in reversed(self._gap_history):
                    if (gap["output"], gap["channel"], gap["recovered_at"]) == (
                        output,
                        channel,
                        None,
                    ):
                        gap["recovered_at"] = time.time()
                        break

    def persistence_status(self) -> dict:
        with self._condition:
            return dict(
                failures=[
                    dict(output=key[0], channel=key[1], reason=value)
                    for key, value in self._persistence.items()
                    if key[0] != "ordinary" or self._desired is not None
                ],
                gaps=[dict(gap) for gap in self._gap_history],
                gaps_truncated=self._gap_count > len(self._gap_history),
            )

    def _flush(self) -> None:
        self._flush_stream(self._recording_sink, recording=True)
        for stream in (self._output._file, self._output._json, self._output._console):
            self._flush_stream(stream)

    def _flush_stream(self, stream, *, recording=False) -> None:
        if stream is None:
            return
        try:
            stream.flush()
            self._flushed(stream, recording)
        except Exception:
            if recording:
                self._recording_failure()
            else:
                self._failure(
                    "ordinary" if stream in (self._output._file, self._output._json) else None,
                    "text_flush" if stream is self._output._file else "json_flush",
                )

    def _flushed(self, stream, recording):
        if recording:
            self._recovered("manual", "json")
            return
        channel = "text" if stream is self._output._file else "json"
        if stream not in (self._output._file, self._output._json):
            return
        if ("ordinary", channel) in self._successful_writes:
            self._recovered("ordinary", channel)

    def _consume(self, queued: tuple) -> None:
        if queued[2] == "event":
            name, fields, *_rest = queued[3]
            update_context(self._context_snapshots, name, fields)
        item = self._recording
        if item is not None and queued[4] == item.id:
            try:
                self._consume_recording(queued, item)
            except Exception:
                self._recording_failure()
            finally:
                with self._condition:
                    item.pending -= 1
        if self._belongs_to_active(queued):
            self._output._write(queued)

    def _consume_recording(self, queued, item) -> None:
        if queued[2] != "event" or self._recording_sink is None:
            return
        from .diagnostic_recording import RecordingEvent

        name, fields, at, wall, _ = queued[3]
        if name in {"session_start", "session_end", "runtime", "trace_limit", "session_limit"}:
            return
        self._recording_sink.snapshots = self._context_snapshots
        self._recording_sink.write(RecordingEvent(name, fields, at, wall))

    def _recording_failure(self) -> None:
        with self._condition:
            if self._recording is not None:
                self._recording.writer_errors += 1
                self._failure("manual", "write")
                self.stop_recording("writer_error")
                self._recording.reason = "writer_error"

    def _update_recording(self) -> None:
        item = self._recording
        if item is None:
            return
        from .build_info import resolve_build_identity
        from .diagnostic_recording import RecordingSink

        if not self._recording_open_attempted:
            self._recording_open_attempted = True
            try:
                item.context["build"] = resolve_build_identity()
                self._recording_sink = RecordingSink(
                    item, PROCESS_INSTANCE, snapshots=self._recording_snapshots(item)
                )
            except Exception:
                self._recording_failure()
        if time.monotonic() >= item.deadline:
            self.stop_recording("time")
        if not item.accepting and item.pending == 0:
            self._finish_recording()

    def _recording_snapshots(self, item):
        snapshots = dict(item.initial_snapshots)
        runtime = self._context_snapshots.get(("runtime", None))
        if runtime is not None and len(snapshots) < 32:
            snapshots["runtime", None] = runtime
        return snapshots

    def _finish_recording(self) -> None:
        item = self._recording
        if item is None:
            return
        from .diagnostic_recording import (
            RecordingEvent,
            atomic_bytes,
            json_bytes,
            set_recording_active,
        )

        sink, self._recording_sink = self._recording_sink, None
        try:
            if sink is not None:
                item.end_present = sink.write(
                    RecordingEvent(
                        "session_end",
                        {"reason": item.reason, "recording_health": item.health()},
                        item.ended_mono or time.monotonic(),
                        item.ended_wall or time.time(),
                    ),
                    footer=True,
                )
                sink.close()
                if not item.writer_errors:
                    self._recovered("manual", "json")
        except Exception:
            item.writer_errors += 1
            item.reason = "writer_error"
            self._failure("manual", "write")
            if sink is not None:
                with suppress(Exception):
                    sink.close()
        item.complete = all(
            (
                item.end_present,
                item.reason in {"manual", "time"},
                not item.writer_errors,
                not item.dropped,
                not item.bounded_snapshots,
            )
        )
        item.state = (
            "error" if item.writer_errors else "completed" if item.complete else "interrupted"
        )
        try:
            atomic_bytes(item.directory / item.id / "recording.json", json_bytes(item.snapshot()))
            self._recovered("manual", "metadata")
            set_recording_active(item.directory, item.id, False)
        except Exception:
            item.writer_errors += 1
            item.complete, item.state = False, "error"
            self._failure("manual", "metadata")
        finally:
            set_recording_active(item.directory, item.id, False)
        with self._condition:
            self._recording_result = item.snapshot()
            self._recording = None


class QueueLogHandler(logging.Handler):
    def __init__(self, writer: LogWriter) -> None:
        super().__init__(logging.INFO)
        self.writer = writer

    def emit(self, record: logging.LogRecord) -> None:
        self.writer.record(record)

    def close(self) -> None:
        if not self._closed:
            self.writer.stop()
        super().close()


def bounded_copy(value: object, *, summary: bool = False) -> object:
    """Copy only bounded primitive data; never invoke arbitrary object formatting."""
    snapshot = BoundedSnapshot(MAX_RECORD_BYTES - 1024, summary=summary)
    result = snapshot.copy(value)
    if snapshot.truncated and isinstance(result, dict):
        result["_snapshot_truncated"] = True
    return result


def _event_in(item: tuple, names: frozenset) -> bool:
    return item[2] == "event" and item[3][0] in names


def _ordinary_event_in(item: tuple, names: frozenset) -> bool:
    return item[0] is not None and _event_in(item, names)
