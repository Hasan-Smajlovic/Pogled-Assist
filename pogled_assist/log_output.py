"""Ordinary log files and rotation, owned exclusively by the logging worker."""

from __future__ import annotations

import json
import logging
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .log_snapshot import expand_numeric_snapshot


class OrdinaryOutput:
    def __init__(self, writer, limits, process):
        self._writer = writer
        self._limits = limits
        self._process = process
        self._file = None
        self._json = None
        self._console = None
        self._active = None
        self._bytes = 0
        self._text_bytes = 0
        self._segment_index = 0
        self._json_path = None
        self._text_path = None
        self._retry_at = 0.0
        self._text_rotation_retry = 0.0
        self._trace_bytes = 0
        self._active_trace = False
        self._active_sequence = 0
        self._ended = False

    def _switch_segment(self, desired: tuple | None, changed_at: tuple) -> None:
        self._end_active(
            "segment_replaced" if desired is not None else "logging_disabled", changed_at
        )
        self._close_files()
        self._active = desired
        self._console = None
        self._bytes = self._trace_bytes = self._text_bytes = 0
        self._segment_index = 0
        self._active_sequence = 0
        self._ended = False
        if desired is None:
            return
        _, latest, self._console, session, self._active_trace, _, snapshots, opened_at = desired
        if latest is None:
            return
        self._open_text(latest)
        self._open_json(latest, session)
        self._write_session_header(session)
        self._write_runtime()
        for snapshot in snapshots.values():
            self._write_json(0, "segment_context", {"snapshot": snapshot}, opened_at)

    def _open_text(self, latest: Path, *, recovering=False) -> None:
        from .log_reservations import reserve_path

        try:
            if self._text_path is None:
                if not reserve_path(latest):
                    raise OSError("Log path is being pruned")
                self._text_path = latest
            latest.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if recovering else self._archive_mode(latest)
            self._file = latest.open(mode, encoding="utf-8")
            self._text_bytes = latest.stat().st_size
        except Exception:
            self._writer._failure("ordinary", "text_open")

    def _archive_mode(self, latest: Path) -> str:
        if not latest.exists():
            return "w"
        archive = latest.with_name(datetime.now().strftime("%Y%m%d_%H%M%S_%f.txt"))
        try:
            os.replace(latest, archive)
            self._writer._recovered("ordinary", "text_rotation")
        except OSError:
            # An archive failure must not destroy the only copy of the old log.
            self._writer._failure("ordinary", "text_rotation")
            self._text_rotation_retry = time.monotonic() + 2
            return "a"
        return "w"

    def _open_json(self, latest: Path, session: str, *, recovering=False) -> None:
        from .log_reservations import reserve_path

        try:
            folder = latest.parent / "diagnostics"
            if self._json_path is None:
                suffix = f".part-{self._segment_index:06}" if self._segment_index else ""
                path = folder / f"{session}{suffix}.jsonl"
                if not reserve_path(path):
                    raise OSError("Log path is being pruned")
                self._json_path = path
            folder.mkdir(parents=True, exist_ok=True)
            self._json = self._json_path.open(
                "a" if recovering else "x", encoding="utf-8", newline="\n"
            )
            self._bytes = self._json_path.stat().st_size
        except Exception:
            self._writer._failure("ordinary", "json_open")

    def _write_session_header(self, session: str) -> None:
        if self._file is not None:
            try:
                self._file.write(
                    f"Diagnostic session: {session}; logs/diagnostics/{session}.jsonl\n"
                )
            except Exception:
                self._writer._failure("ordinary", "text_write")

    def _write_runtime(self) -> None:
        from .build_info import resolve_build_identity

        try:
            build = resolve_build_identity()
            self._write_json(
                0,
                "runtime",
                {
                    "application_version": build["app_version"],
                    "build_revision": build["build_revision"],
                    "build_dirty": build["build_dirty"],
                    "frozen": bool(getattr(sys, "frozen", False)),
                    "python": platform.python_version(),
                    "platform": sys.platform,
                },
                (time.monotonic(), time.time()),
            )
        except Exception:
            self._writer._failure()

    def _write(self, item: tuple) -> None:
        _, sequence, kind, data, _ = item
        self._active_sequence = sequence
        try:
            if kind == "record":
                self._write_record(data)
            else:
                self._write_event(sequence, data)
        except Exception:
            self._writer._failure("ordinary", "json_write" if kind == "event" else "text_write")

    def _write_record(self, data: dict) -> None:
        line = _format_record(data)
        size = len((line + "\n").encode("utf-8"))
        if self._needs_text_rotation(size):
            self._rotate_text()
        for stream in (self._file, self._console):
            if stream is not None:
                try:
                    stream.write(line + "\n")
                    if stream is self._file:
                        self._text_bytes += size
                        self._writer._successful_writes.add(("ordinary", "text"))
                except Exception:
                    self._writer._failure(
                        "ordinary" if stream is self._file else None, "text_write"
                    )

    def _needs_text_rotation(self, size):
        if self._file is None or self._text_bytes + size <= self._limits()[0]:
            return False
        return time.monotonic() >= self._text_rotation_retry

    def _rotate_text(self):
        latest = self._active[1]
        self._file.close()
        self._file = None
        try:
            self._file = latest.open(self._archive_mode(latest), encoding="utf-8")
            self._text_bytes = latest.stat().st_size
        except OSError:
            self._writer._failure("ordinary", "text_rotation")

    def _write_event(self, sequence: int, data: tuple) -> None:
        name, fields, at, wall, trace = data
        deadline = self._active[5]
        trace_expired = at >= deadline or self._trace_bytes >= self._limits()[1]
        if self._active_trace and trace_expired:
            self._active_trace = False
            with self._writer._condition:
                # An old session may finish writing after a new one has been enabled.
                if self._active[0] == self._writer._generation:
                    self._writer._trace = False
            self._write_json(
                sequence,
                "trace_limit",
                {"reason": "time" if at >= deadline else "size"},
                (at, wall),
            )
        if trace and not self._active_trace:
            with self._writer._condition:
                self._writer._drop("trace_limit")
            return
        written = self._write_json(sequence, name, fields, (at, wall))
        if trace:
            self._trace_bytes += written

    def _write_json(self, sequence: int, name: str, fields: dict, captured_at: tuple) -> int:
        if self._json is None or self._active is None:
            return 0
        at, wall = captured_at
        record = {
            "schema_version": 1,
            "event": name,
            "session_id": self._active[3],
            "process_instance": self._process,
            "event_seq": sequence,
            "wall_time": datetime.fromtimestamp(wall, timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "monotonic_s": at,
            "data": fields,
        }
        line = (
            json.dumps(
                record,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                default=expand_numeric_snapshot,
            )
            + "\n"
        )
        size = len(line.encode("utf-8"))
        if self._needs_json_rotation(name, size):
            self._rotate_json(sequence, captured_at)
            if self._json is None:
                return 0
        record["segment_index"] = self._segment_index
        if name in {"session_end", "stream_summary", "ui_heartbeat"}:
            record["logging_health"] = self._writer.health()
        line = (
            json.dumps(
                record,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                default=expand_numeric_snapshot,
            )
            + "\n"
        )
        size = len(line.encode("utf-8"))
        self._json.write(line)
        self._writer._successful_writes.add(("ordinary", "json"))
        if name in {"runtime", "gaze_settings", "screen_mapping", "selection_settings"}:
            self._writer._context_snapshots[name, fields.get("source")] = {
                "event": name,
                "data": fields,
            }
        if name == "session_end":
            self._ended = True
        self._bytes += size
        return size

    def _needs_json_rotation(self, name, size):
        if name == "segment_context" or not self._bytes:
            return False
        return self._bytes + size > self._limits()[0]

    def _rotate_json(self, sequence, captured_at):
        from .log_reservations import release_path

        self._json.close()
        self._json = None
        release_path(self._json_path)
        self._json_path = None
        self._segment_index += 1
        self._bytes = 0
        self._open_json(self._active[1], self._active[3])
        if self._json is None:
            return
        self._write_json(
            sequence, "segment_context", {"segment_index": self._segment_index}, captured_at
        )
        for snapshot in tuple(self._writer._context_snapshots.values()):
            self._write_json(sequence, "segment_context", {"snapshot": snapshot}, captured_at)

    def _end_active(self, reason: str, changed_at: tuple | None = None) -> None:
        if self._json is not None and not self._ended:
            try:
                self._write_json(
                    self._active_sequence + 1,
                    "session_end",
                    {"reason": reason},
                    changed_at or self._writer._change_at,
                )
            except Exception:
                self._writer._failure("ordinary", "json_write")

    def _retry_outputs(self):
        if self._active is None or self._active[1] is None:
            return
        if time.monotonic() < self._retry_at:
            return
        self._retry_at = time.monotonic() + 2
        latest = self._active[1]
        if self._file is None:
            self._open_text(latest, recovering=True)
        if self._json is not None:
            return
        self._open_json(latest, self._active[3], recovering=True)
        if self._json is None:
            return
        try:
            self._write_json(
                self._active_sequence,
                "persistence_recovered",
                {
                    "reason": "reopened",
                    "coverage_gap": True,
                },
                (time.monotonic(), time.time()),
            )
        except OSError:
            self._writer._failure("ordinary", "reopen")

    def _close_files(self) -> None:
        from .log_reservations import release_path

        for name in ("_file", "_json"):
            self._close_stream(name)
        for name in ("_json_path", "_text_path"):
            path = getattr(self, name)
            if path is not None:
                release_path(path)
                setattr(self, name, None)

    def _close_stream(self, name):
        stream = getattr(self, name)
        setattr(self, name, None)
        if stream is None:
            return
        try:
            stream.close()
        except Exception:
            self._writer._failure()


def _format_record(data: dict) -> str:
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
    return line
