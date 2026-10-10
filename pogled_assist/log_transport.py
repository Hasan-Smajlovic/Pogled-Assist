"""Bounded logging transport; only the writer touches output streams."""

from __future__ import annotations

import json
import logging
import math
import platform
import shutil
import sys
import threading
import time
import uuid
from collections import Counter, deque
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

MAX_RECORD_BYTES = 8192
MAX_QUEUE_RECORDS = 1024
PRIORITY_RESERVE = 64
TRACE_SECONDS = 600
TRACE_BYTES = 32 * 1024 * 1024
SESSION_BYTES = 64 * 1024 * 1024
PROCESS_INSTANCE = uuid.uuid4().hex


class LogWriter:
    """Keep disk and console waits off input threads, including runtime rotation."""

    def __init__(self, *, capacity: int = MAX_QUEUE_RECORDS) -> None:
        self.capacity = capacity
        self._condition = threading.Condition()
        self._queue: deque = deque()
        self._generation = 0
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
        self._file = None
        self._json = None
        self._console = None
        self._active: tuple | None = None
        self._bytes = 0
        self._trace_bytes = 0
        self._active_trace = False
        self._active_sequence = 0
        self._ended = False
        self._change_at = (time.monotonic(), time.time())
        self._thread = threading.Thread(target=self._run, name="pogled-log-writer", daemon=True)
        self._thread.start()

    @property
    def enabled(self) -> bool:
        return self._desired is not None and not self._stopping

    @property
    def finished(self) -> bool:
        return not self._thread.is_alive()

    @property
    def trace(self) -> bool:
        return self.enabled and self._trace and time.monotonic() < self._trace_until

    def start_segment(self, latest: Path | None, console, *, trace: bool) -> None:
        with self._condition:
            if self._stopping:
                return
            self._discard_pending("segment_replaced")
            self._generation += 1
            self._sequence = 0
            session = uuid.uuid4().hex
            self._change_at = (time.monotonic(), time.time())
            self._trace = trace
            self._trace_until = time.monotonic() + TRACE_SECONDS
            self._desired = (self._generation, latest, console, session, trace, self._trace_until)
            self._condition.notify()
        self.event("session_start", {"mode": "trace" if trace else "basic"}, priority=True)

    def disable(self) -> None:
        with self._condition:
            self._desired = None
            self._change_at = (time.monotonic(), time.time())
            self._trace = False
            self._discard_pending("logging_disabled")
            self._condition.notify()

    def event(
        self, name: str, fields: dict, *, trace: bool = False, priority: bool = False
    ) -> bool:
        if not self.enabled or (trace and not self.trace):
            return False
        now = time.monotonic()
        generation = self._generation
        payload = bounded_copy(fields)
        return self._put("event", (name, payload, now, time.time(), trace), priority, generation)

    def record(self, record: logging.LogRecord) -> None:
        if not self.enabled:
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
                "queued": len(self._queue),
                "capacity": self.capacity,
                "high_water": self._high_water,
                "dropped": dict(self._dropped),
                "drop_start_monotonic_s": self._drop_start,
                "drop_end_monotonic_s": self._drop_end,
                "writer_errors": self._errors,
                "bounded_snapshots": self._truncated,
            }

    def stop(self, timeout: float = 2.0) -> bool:
        with self._condition:
            if not self._stopping:
                self._change_at = (time.monotonic(), time.time())
                self.event("session_end", {"reason": "shutdown"}, priority=True)
                self._stopping = True
                self._condition.notify()
        self._thread.join(max(0.0, timeout))
        return not self._thread.is_alive()

    def _put(self, kind: str, payload: object, priority: bool, generation: int) -> bool:
        with self._condition:
            if not self.enabled:
                return False
            if generation != self._generation:
                self._drop("old_segment")
                return False
            reserve = min(PRIORITY_RESERVE, self.capacity // 4)
            limit = self.capacity if priority else self.capacity - reserve
            if len(self._queue) >= limit:
                self._drop(kind)
                return False
            self._sequence += 1
            copied = payload[1] if kind == "event" else payload
            if isinstance(copied, dict) and copied.get("_snapshot_truncated"):
                self._truncated += 1
            self._queue.append((self._generation, self._sequence, kind, payload))
            self._high_water = max(self._high_water, len(self._queue))
            self._condition.notify()
            return True

    def _drop(self, category: str, count: int = 1) -> None:
        self._dropped[category] += count
        now = time.monotonic()
        if self._drop_start is None:
            self._drop_start = now
        self._drop_end = now

    def _discard_pending(self, reason: str) -> None:
        if self._queue:
            self._drop(reason, len(self._queue))
            self._queue.clear()

    def _run(self) -> None:
        last_flush = time.monotonic()
        end_reason = "shutdown"
        try:
            while True:
                with self._condition:
                    if not self._queue and not self._stopping and self._desired == self._active:
                        self._condition.wait(0.25)
                    desired = self._desired
                    changed_at = self._change_at
                    item = self._queue.popleft() if self._queue else None
                    done = self._stopping and item is None
                if desired != self._active:
                    self._switch_segment(desired, changed_at)
                if item is not None and self._active and item[0] == self._active[0]:
                    self._write(item)
                now = time.monotonic()
                if now - last_flush >= 0.25 or done:
                    self._flush()
                    last_flush = now
                if done:
                    break
        except Exception:
            end_reason = "writer_failure"
            self._failure()
            with self._condition:
                self._stopping = True
                self._discard_pending("writer_failed")
        finally:
            self._end_active(end_reason)
            self._close_files()

    def _switch_segment(self, desired: tuple | None, changed_at: tuple) -> None:
        self._end_active(
            "segment_replaced" if desired is not None else "logging_disabled", changed_at
        )
        self._close_files()
        self._active = desired
        self._console = None
        self._bytes = self._trace_bytes = 0
        self._active_sequence = 0
        self._ended = False
        if desired is None:
            return
        _, latest, self._console, session, self._active_trace, _ = desired
        if latest is None:
            return
        try:
            latest.parent.mkdir(parents=True, exist_ok=True)
            mode = "w"
            if latest.exists():
                archive = latest.with_name(datetime.now().strftime("%Y%m%d_%H%M%S_%f.txt"))
                try:
                    shutil.copy2(latest, archive)
                except OSError:
                    # An archive failure must not destroy the only copy of the old log.
                    self._failure()
                    mode = "a"
            self._file = latest.open(mode, encoding="utf-8")
        except Exception:
            self._failure()
        try:
            folder = latest.parent / "diagnostics"
            folder.mkdir(parents=True, exist_ok=True)
            self._json = (folder / f"{session}.jsonl").open("w", encoding="utf-8")
        except Exception:
            self._failure()
        if self._file is not None:
            try:
                self._file.write(
                    f"Diagnostic session: {session}; logs/diagnostics/{session}.jsonl\n"
                )
            except Exception:
                self._failure()
        try:
            root = (
                Path(sys.executable).resolve().parent
                if getattr(sys, "frozen", False)
                else Path(__file__).resolve().parents[1]
            )
            version = "unknown"
            with suppress(OSError):
                version = (root / "VERSION").read_text(encoding="utf-8").strip()[:64]
            self._write_json(
                0,
                "runtime",
                {
                    "application_version": version,
                    "build_revision": "unknown",
                    "frozen": bool(getattr(sys, "frozen", False)),
                    "python": platform.python_version(),
                    "platform": sys.platform,
                },
                time.monotonic(),
                time.time(),
            )
        except Exception:
            self._failure()

    def _write(self, item: tuple) -> None:
        _, sequence, kind, data = item
        self._active_sequence = sequence
        try:
            if kind == "record":
                fields = dict(data)
                frames = fields.pop("exception_frames", ())
                error_type = fields.pop("exception_type", None)
                truncated = fields.pop("_snapshot_truncated", False)
                record = logging.makeLogRecord(fields)
                line = logging.Formatter(
                    "%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                ).format(record)
                if error_type:
                    line += f"\n{error_type} (exception message omitted)"
                    line += "".join(
                        f"\n  {frame[0]}:{frame[1]} in {frame[2]}"
                        for frame in frames
                        if isinstance(frame, tuple) and len(frame) == 3
                    )
                if truncated:
                    line += "\nLog snapshot truncated."
                for stream in (self._file, self._console):
                    if stream is not None:
                        try:
                            stream.write(line + "\n")
                        except Exception:
                            self._failure()
            else:
                self._write_event(sequence, data)
        except Exception:
            self._failure()

    def _write_event(self, sequence: int, data: tuple) -> None:
        name, fields, at, wall, trace = data
        deadline = self._active[5]
        if self._active_trace and (at >= deadline or self._trace_bytes >= TRACE_BYTES):
            self._active_trace = False
            with self._condition:
                # An old session may finish writing after a new one has been enabled.
                if self._active[0] == self._generation:
                    self._trace = False
            self._write_json(
                sequence,
                "trace_limit",
                {"reason": "time" if at >= deadline else "size"},
                at,
                wall,
            )
        if trace and not self._active_trace:
            with self._condition:
                self._drop("trace_limit")
            return
        written = self._write_json(sequence, name, fields, at, wall)
        if trace:
            self._trace_bytes += written

    def _write_json(self, sequence: int, name: str, fields: dict, at: float, wall: float) -> int:
        if self._json is None or self._active is None:
            return 0
        record = {
            "schema_version": 1,
            "event": name,
            "session_id": self._active[3],
            "process_instance": PROCESS_INSTANCE,
            "event_seq": sequence,
            "wall_time": datetime.fromtimestamp(wall, timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "monotonic_s": at,
            "data": fields,
        }
        line = json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
        size = len(line.encode("utf-8"))
        if self._bytes + size > SESSION_BYTES - MAX_RECORD_BYTES:
            record["event"] = "session_limit"
            record["data"] = {"reason": "size", "health": self.health()}
            self._json.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._json.close()
            self._json = None
            self._active_trace = False
            with self._condition:
                if self._active[0] == self._generation:
                    self._trace = False
            if self._file:
                self._file.write("Structured diagnostic session reached its size limit.\n")
            return 0
        if name in {"session_end", "stream_summary", "ui_heartbeat"}:
            record["logging_health"] = self.health()
            line = json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
            size = len(line.encode("utf-8"))
        self._json.write(line)
        if name == "session_end":
            self._ended = True
        self._bytes += size
        return size

    def _end_active(self, reason: str, changed_at: tuple | None = None) -> None:
        if self._json is not None and not self._ended:
            try:
                self._write_json(
                    self._active_sequence + 1,
                    "session_end",
                    {"reason": reason},
                    *(changed_at or self._change_at),
                )
            except Exception:
                self._failure()

    def _failure(self) -> None:
        # Reporting through root logging here would recurse into this writer.
        with self._condition:
            self._errors += 1
            self._drop("writer_error")

    def _flush(self) -> None:
        for stream in (self._file, self._json, self._console):
            if stream is not None:
                try:
                    stream.flush()
                except Exception:
                    self._failure()

    def _close_files(self) -> None:
        for name in ("_file", "_json"):
            stream = getattr(self, name)
            setattr(self, name, None)
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    self._failure()


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


def bounded_copy(value: object) -> object:
    """Copy only bounded primitive data; never invoke arbitrary object formatting."""
    remaining = MAX_RECORD_BYTES - 1024
    truncated = False

    def copy(item: object, depth: int = 0):
        nonlocal remaining, truncated
        if remaining < 128 or depth > 4:
            truncated = True
            return "<truncated>"
        if item is None or type(item) in (bool, int, float):
            result = item
            if type(item) is int and item.bit_length() > 128:
                result = "<large integer>"
                truncated = True
            if isinstance(item, float) and not math.isfinite(item):
                result = None
        elif type(item) is str:
            result = item[: min(2048, max(0, (remaining - 128) // 4))]
            truncated |= len(result) < len(item)
        elif type(item) in (tuple, list):
            truncated |= len(item) > 32
            remaining -= 128 + 8 * min(32, len(item))
            return tuple(copy(part, depth + 1) for part in item[:32])
        elif type(item) is dict:
            remaining -= 256 + 64 * min(32, len(item))
            result = {}
            for index, (key, part) in enumerate(item.items()):
                if index >= 32 or remaining < 128:
                    truncated = True
                    break
                if isinstance(key, str):
                    # Copy keys first so a large value cannot erase its field name.
                    field = copy(key, depth + 1)
                    result[field] = copy(part, depth + 1)
            return result
        else:
            result = "<non-primitive>"
        remaining -= sys.getsizeof(result)
        return result

    result = copy(value)
    if truncated and isinstance(result, dict):
        result["_snapshot_truncated"] = True
    return result
