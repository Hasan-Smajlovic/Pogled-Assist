"""Bounded recording files and local support ZIPs, used only by background workers."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from threading import RLock

from .log_reader import summarize
from .log_reservations import (
    _ACTIVE_RECORDINGS as _ACTIVE_RECORDINGS,
)
from .log_reservations import (
    _DELETING as _DELETING,
)
from .log_reservations import (
    _RESERVATION_LOCK as _RESERVATION_LOCK,
)
from .log_reservations import (
    _RESERVATIONS as _RESERVATIONS,
)
from .log_reservations import (
    _is_active as _is_active,
)
from .log_reservations import (
    _path_key as _path_key,
)
from .log_reservations import (
    release_path as release_path,
)
from .log_reservations import (
    reserve_path as reserve_path,
)
from .log_reservations import (
    set_recording_active as set_recording_active,
)
from .log_snapshot import NumericSnapshot, expand_numeric_snapshot
from .recording_export import export_files, export_manifest, write_export
from .recording_metadata import (
    _RECORDING_METADATA_KEYS,
    _validate_metadata,
)
from .recording_metadata import (
    DURATIONS as DURATIONS,
)
from .recording_metadata import (
    GAZE_KEYS as GAZE_KEYS,
)
from .recording_metadata import (
    json_bytes as json_bytes,
)
from .recording_metadata import (
    recording_context as recording_context,
)
from .tracking.gaze_check_report import (
    GazeCheckReport,
)

SEGMENT_BYTES = 16 * 1024 * 1024
LOW_SPACE_BYTES = 1_000_000_000
RECOVERY_SPACE_BYTES = 2_000_000_000
DEFAULT_BUDGET_BYTES = 4_000_000_000
MAX_MAINTENANCE_ITEMS = 128
RECORDING_ID = re.compile(r"[0-9a-f]{32}\Z")
_STORE_LOCK = RLock()  # File workers only; input/Qt producers never take this lock.


def disk_free(root: Path) -> int:
    return shutil.disk_usage(root).free


def _safe_storage_path(path: Path) -> bool:
    try:
        return not path.is_symlink() and not (
            getattr(path.lstat(), "st_file_attributes", 0) & 0x400
        )
    except OSError:
        return False


def _known_log_time(path: Path) -> str | None:
    if path.suffix != ".jsonl":
        return None
    try:
        with path.open("rb") as stream:
            value = json.loads(stream.readline(8193)).get("wall_time")
        parsed = datetime.fromisoformat(value)
        return (
            parsed.astimezone(timezone.utc).isoformat() if parsed.utcoffset() is not None else None
        )
    except (OSError, ValueError, TypeError, AttributeError):
        return None


class RecordingReadError(ValueError):
    """The selected recording cannot be read as one supported, consistent stream."""


def utc_time(wall: float) -> str:
    return datetime.fromtimestamp(wall, timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class Recording:
    id: str
    directory: Path
    started_mono: float
    started_wall: float
    minutes: int
    context: dict
    accepting: bool = True
    state: str = "starting"
    reason: str | None = None
    ended_mono: float | None = None
    ended_wall: float | None = None
    bytes_written: int = 0
    pending: int = 0
    dropped: dict = field(default_factory=dict)
    writer_errors: int = 0
    bounded_snapshots: int = 0
    end_present: bool = False
    complete: bool = False
    segment_count: int = 1
    initial_snapshots: dict = field(default_factory=dict)

    @property
    def deadline(self) -> float:
        return self.started_mono + self.minutes * 60

    def health(self) -> dict:
        return {
            "dropped": dict(self.dropped),
            "writer_errors": self.writer_errors,
            "bounded_snapshots": self.bounded_snapshots,
        }

    def snapshot(self) -> dict:
        return {
            "schema_version": 1,
            "id": self.id,
            "state": self.state,
            "reason": self.reason,
            "started_at": utc_time(self.started_wall),
            "ended_at": utc_time(self.ended_wall) if self.ended_wall is not None else None,
            "duration_seconds": max(0, (self.ended_mono or self.started_mono) - self.started_mono),
            "minutes": self.minutes,
            "bytes": self.bytes_written,
            "health": self.health(),
            "session_end_present": self.end_present,
            "complete": self.complete,
            "context": self.context,
            "segment_count": self.segment_count,
        }


@dataclass(frozen=True)
class RecordingEvent:
    name: str
    fields: dict
    monotonic_time: float
    wall_time: float


class RecordingSink:
    """A second structured destination of LogWriter, never a separate observation pipeline."""

    def __init__(self, recording: Recording, process: str, *, snapshots=None) -> None:
        self.recording = recording
        self.process = process
        self.sequence = 0
        self.stream = None
        self._segment_bytes = 0
        self.snapshots = snapshots if snapshots is not None else {}
        folder = recording.directory / recording.id
        folder.mkdir(parents=True, exist_ok=False)
        atomic_bytes(folder / "recording.json", json_bytes(recording.snapshot()))
        self.stream = (folder / "snimak.jsonl").open("w", encoding="utf-8", newline="\n")
        self.write(
            RecordingEvent(
                "session_start",
                {"mode": "manual_trace", "minutes": recording.minutes},
                recording.started_mono,
                recording.started_wall,
            ),
            footer=True,
        )
        self.write(
            RecordingEvent(
                "recording_context",
                recording.context,
                recording.started_mono,
                recording.started_wall,
            ),
            footer=True,
        )
        recording.state = "recording" if recording.accepting else "finishing"
        self._write_context(recording.started_mono, recording.started_wall)

    def _write_context(self, at, wall):
        self.write(
            RecordingEvent(
                "segment_context",
                {
                    "segment_index": self.recording.segment_count - 1,
                    "context": self.recording.context,
                },
                at,
                wall,
            ),
            footer=True,
        )
        for snapshot in tuple(self.snapshots.values()):
            self.write(
                RecordingEvent("segment_context", {"snapshot": snapshot}, at, wall), footer=True
            )

    def write(self, event: RecordingEvent, *, footer=False) -> bool:
        item = self.recording
        if self.stream is None:
            return False
        counts = event.fields.get("counts")
        if type(counts) is NumericSnapshot:
            counts = expand_numeric_snapshot(counts)
        if event.name in {"stream_summary", "selection_summary", "marker_summary"} and isinstance(
            counts, dict
        ):
            # These counters describe the ordinary basic destination. Manual
            # trace receives the detailed events; its queue loss is separate.
            event = RecordingEvent(
                event.name,
                {
                    **event.fields,
                    "counts": {
                        key: value
                        for key, value in counts.items()
                        if not key.startswith("suppressed:")
                    },
                },
                event.monotonic_time,
                event.wall_time,
            )
        record = {
            "schema_version": 1,
            "event": event.name,
            "session_id": item.id,
            "process_instance": self.process,
            "event_seq": self.sequence + 1,
            "wall_time": utc_time(event.wall_time),
            "monotonic_s": event.monotonic_time,
            "data": event.fields,
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
        if (
            event.name != "segment_context"
            and self._segment_bytes
            and self._segment_bytes + size > SEGMENT_BYTES
        ):
            self.close()
            item.segment_count += 1
            self.stream = (
                item.directory / item.id / f"snimak-{item.segment_count - 1:06}.jsonl"
            ).open("x", encoding="utf-8", newline="\n")
            self._segment_bytes = 0
            self._write_context(event.monotonic_time, event.wall_time)
        self.sequence += 1
        record["event_seq"] = self.sequence
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
        self.stream.write(line)
        item.bytes_written += size
        self._segment_bytes += size
        return True

    def flush(self) -> None:
        if self.stream is not None:
            self.stream.flush()

    def close(self) -> None:
        if self.stream is not None:
            stream, self.stream = self.stream, None
            try:
                stream.flush()
                os.fsync(stream.fileno())
            finally:
                stream.close()


def atomic_bytes(path: Path, payload: bytes) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".diagnostic-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _read_recording_metadata(path: Path, recording_id: str) -> dict:
    with path.open("rb") as stream:
        payload = stream.read(65537)
    if len(payload) > 65536:
        raise ValueError("Invalid metadata size")
    item = json.loads(payload)
    if item["id"] != recording_id or item.get("schema_version") != 1:
        raise ValueError("Invalid recording metadata")
    _validate_metadata(item)
    return item


def _read_recording_edges(path: Path, recording_id: str) -> tuple[int, bool]:
    size = path.stat().st_size
    with path.open("rb") as stream:
        first = json.loads(stream.readline(8193))
        stream.seek(max(0, size - 8192))
        tail = stream.read(8192)
    if first.get("session_id") != recording_id or first.get("event") != "session_start":
        raise ValueError("Invalid recording header")
    return size, _has_recording_end(tail, recording_id)


def _has_recording_end(tail: bytes, recording_id: str) -> bool:
    try:
        last = json.loads(tail.splitlines()[-1])
    except (ValueError, IndexError):
        return False
    return (
        last.get("event") == "session_end"
        and last.get("session_id") == recording_id
        and tail.endswith(b"\n")
    )


def _analyze_recording(path: Path, recording_id: str, *, analyze: bool) -> dict | None:
    if not analyze:
        return None
    analysis = summarize(path)
    mixed_stream = analysis["session_id"] != recording_id
    unexpected_warnings = any(
        warning["reason"]
        not in {"partial_last_line", "missing_or_duplicate_segments_unknown_cause"}
        for warning in analysis["parse_warnings"]
    )
    if mixed_stream or unexpected_warnings:
        raise ValueError("Invalid or mixed recording stream")
    return analysis


def _mark_interrupted_metadata(item: dict, ended: bool) -> None:
    unfinished_state = item["state"] in ("starting", "recording", "finishing")
    completed_without_end = not ended and item["state"] == "completed"
    if unfinished_state or completed_without_end:
        item.update(state="interrupted", reason="missing_end", complete=False)


def _recording_is_complete(item: dict, ended: bool, analysis: dict | None) -> bool:
    health = item.get("health", {})
    return bool(
        item.get("complete")
        and ended
        and (analysis is None or analysis["complete"])
        and not health.get("writer_errors")
        and not health.get("bounded_snapshots")
        and not any(health.get("dropped", {}).values())
    )


def _recording_files(folder: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            (
                path
                for path in folder.iterdir()
                if path.name in {"snimak.jsonl", "recording.json"}
                or re.fullmatch(r"snimak-\d{6}\.jsonl", path.name)
            ),
            key=lambda path: (path.name != "snimak.jsonl", path.name),
        )
    )


def _recording_segments(folder):
    traces = tuple(path for path in _recording_files(folder) if path.suffix == ".jsonl")
    if not traces or any(not _safe_storage_path(path) for path in traces):
        raise ValueError("Missing or linked recording segments")
    return traces


def _segment_edges(traces, trace_path, recording_id):
    if trace_path.exists():
        _read_recording_edges(trace_path, recording_id)
    size = sum(path.stat().st_size for path in traces)
    last = traces[-1]
    with last.open("rb") as stream:
        stream.seek(max(0, last.stat().st_size - 8192))
        ended = _has_recording_end(stream.read(8192), recording_id)
    return size, ended


def _segment_gaps(traces, expected):
    indices = {
        0 if path.name == "snimak.jsonl" else int(path.stem.split("-")[-1]) for path in traces
    }
    end = max(expected, max(indices) + 1)
    gaps = []
    cursor = 0
    for index in sorted(indices | {end}):
        gaps.extend(islice(range(cursor, index), 201 - len(gaps)))
        if len(gaps) > 200:
            break
        cursor = index + 1
    return gaps[:200], len(gaps) > 200


def _retention_folder_is_safe(folder: Path, paths: tuple[Path, ...]) -> bool:
    if any(path.is_symlink() for path in paths):
        return False
    return {path.name for path in folder.iterdir()} == {path.name for path in paths}


def _remove_recording(folder: Path, paths: tuple[Path, ...]) -> None:
    for path in paths:
        path.unlink()
    folder.rmdir()


def _is_recording_folder(folder: Path, directory: Path, active_id: str | None) -> bool:
    if not RECORDING_ID.fullmatch(folder.name):
        return False
    if folder.is_symlink() or not folder.is_dir():
        return False
    return folder.name != active_id and not _is_active(directory, folder.name)


def _recording_paths(directory: Path, recording_id: str) -> tuple[Path, Path]:
    folder = directory / recording_id
    if not _safe_storage_path(directory) or not _safe_storage_path(folder):
        raise ValueError("Linked recording")
    metadata = folder / "recording.json"
    trace = folder / "snimak.jsonl"
    if not _safe_storage_path(metadata) or (trace.exists() and not _safe_storage_path(trace)):
        raise ValueError("Linked recording file")
    return metadata, trace


class RecordingStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.budget_bytes = DEFAULT_BUDGET_BYTES
        self.storage: dict = {}

    reserve_path = staticmethod(reserve_path)
    release_path = staticmethod(release_path)

    def reserve_export(self, recording_id: str) -> bool:
        if not RECORDING_ID.fullmatch(recording_id) or _is_active(self.directory, recording_id):
            return False
        return reserve_path(self.directory / recording_id)

    def release_export(self, recording_id: str) -> None:
        release_path(self.directory / recording_id)

    def maintain(self, *, budget_bytes: int | None = None) -> dict:
        from .log_storage import maintain

        return maintain(self, budget_bytes=budget_bytes)

    def load(self, *, active_id: str | None = None) -> list[dict]:
        with _STORE_LOCK:
            return self._load(active_id=active_id)

    def recover_and_load(self, *, active_id: str | None = None) -> list[dict]:
        """Confirm readable crash remnants before restoring the managed budget."""
        with _STORE_LOCK:
            entries = self._load(active_id=active_id)
            saved = False
            for item in entries:
                if item.get("state") == "unreadable":
                    continue
                if item.get("reason") == "missing_end" and item.get("duration_seconds") is not None:
                    recovered = {
                        key: value
                        for key, value in item.items()
                        if key in _RECORDING_METADATA_KEYS | {"segment_count"}
                    }
                    recovered["duration_seconds"] = None
                    atomic_bytes(
                        self.directory / item["id"] / "recording.json", json_bytes(recovered)
                    )
                saved = True
            # Final metadata can have reached disk just before a killed process
            # missed pruning. Initial-only remnants become confirmed partial
            # recordings above; a failed recovery never deletes older data.
            if saved:
                self.maintain()
            return self._load(active_id=active_id)

    def _load(self, *, active_id: str | None = None) -> list[dict]:
        if not self.directory.exists():
            return []
        entries = []
        for folder in self.directory.iterdir():
            if not _is_recording_folder(folder, self.directory, active_id):
                continue
            try:
                entries.append(self.inspect(folder.name, analyze=False))
            except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
                entries.append(
                    {
                        "id": folder.name,
                        "state": "unreadable",
                        "complete": False,
                        "started_at": utc_time(folder.stat().st_mtime),
                    }
                )
        return sorted(entries, key=lambda item: item.get("started_at", ""), reverse=True)

    def inspect(self, recording_id: str, *, analyze: bool = True) -> dict:
        if not RECORDING_ID.fullmatch(recording_id):
            raise ValueError("Invalid recording identity")
        metadata_path, trace_path = _recording_paths(self.directory, recording_id)
        item = _read_recording_metadata(metadata_path, recording_id)
        traces = _recording_segments(metadata_path.parent)
        size, ended = _segment_edges(traces, trace_path, recording_id)
        gaps, truncated = _segment_gaps(traces, item.get("segment_count", len(traces)))
        analysis = _analyze_recording(metadata_path.parent, recording_id, analyze=analyze)
        item.update(bytes=size, session_end_present=ended)
        _mark_interrupted_metadata(item, ended)
        item["complete"] = _recording_is_complete(item, ended, analysis)
        if gaps or truncated:
            item.update(
                state="interrupted",
                reason="missing_segments",
                complete=False,
                segment_gaps=gaps,
                segment_gaps_truncated=truncated,
            )
        if analysis is not None:
            item["analysis"] = analysis
        return item

    def prune(self, *, active_id: str | None = None) -> None:
        self.maintain()

    def export(
        self, recording_id: str, destination: Path, report: GazeCheckReport | None = None
    ) -> None:
        if not self.reserve_export(recording_id):
            raise ValueError("Recording is still active or unavailable")
        try:
            self._export(recording_id, destination, report)
        finally:
            self.release_export(recording_id)

    def _export(self, recording_id: str, destination: Path, report: GazeCheckReport | None) -> None:
        self._validate_export_destination(recording_id, destination)
        try:
            item, trace = self._read_export_source(recording_id)
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
            raise RecordingReadError("Recording cannot be exported") from error

        files, selected = export_files(item, trace, report)
        manifest = export_manifest(item, files, selected)
        files["manifest.json"] = json_bytes(manifest)
        write_export(destination, files)

    def _validate_export_destination(self, recording_id: str, destination: Path) -> None:
        if _is_active(self.directory, recording_id):
            raise ValueError("Recording is still active")
        folder = (self.directory / recording_id).resolve()
        if destination.resolve().parent == folder:
            raise ValueError("Cannot replace recording source")

    def _read_export_source(self, recording_id: str) -> tuple[dict, tuple[Path, ...]]:
        item = self.inspect(recording_id)
        paths = tuple(
            path
            for path in _recording_files(self.directory / recording_id)
            if path.suffix == ".jsonl"
        )
        return item, paths
