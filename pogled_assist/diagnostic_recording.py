"""Bounded recording files and local support ZIPs, used only by background workers."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, RLock
from zipfile import ZIP_DEFLATED, ZipFile

from .log_reader import summarize
from .tracking.gaze_check_report import (
    ENVIRONMENT_KEYS,
    GazeCheckReport,
    report_text,
)

SEGMENT_BYTES = 16 * 1024 * 1024
LOW_SPACE_BYTES = 1_000_000_000
RECOVERY_SPACE_BYTES = 2_000_000_000
DEFAULT_BUDGET_BYTES = 4_000_000_000
MAX_MAINTENANCE_ITEMS = 128
DURATIONS = (1, 2, 5, 10)
RECORDING_ID = re.compile(r"[0-9a-f]{32}\Z")
_STORE_LOCK = RLock()  # File workers only; input/Qt producers never take this lock.
_ACTIVE_RECORDINGS: set[tuple[str, str]] = set()
_RESERVATION_LOCK = Lock()
_RESERVATIONS: dict[str, int] = {}
_DELETING: set[str] = set()


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def reserve_path(path: Path) -> bool:
    key = _path_key(path)
    with _RESERVATION_LOCK:
        if key in _DELETING:
            return False
        _RESERVATIONS[key] = _RESERVATIONS.get(key, 0) + 1
        return True


def release_path(path: Path) -> None:
    key = _path_key(path)
    with _RESERVATION_LOCK:
        count = _RESERVATIONS.get(key, 0)
        if count > 1:
            _RESERVATIONS[key] = count - 1
        else:
            _RESERVATIONS.pop(key, None)


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


def set_recording_active(directory: Path, recording_id: str, active: bool) -> None:
    key = (os.path.normcase(os.path.abspath(directory)), recording_id)
    if active:
        _ACTIVE_RECORDINGS.add(key)
    else:
        _ACTIVE_RECORDINGS.discard(key)


def _is_active(directory: Path, recording_id: str) -> bool:
    return (os.path.normcase(os.path.abspath(directory)), recording_id) in _ACTIVE_RECORDINGS


class RecordingReadError(ValueError):
    """The selected recording cannot be read as one supported, consistent stream."""


GAZE_KEYS = (
    "eye_tracking_policy",
    "eye_tracking_hold_ms",
    "selection_pause_ms",
    "dwell_ms",
    "edge_hold_ms",
    "dwell_radius_px",
    "click_cooldown_ms",
    "smoothing",
    "move_mouse",
    "use_precision_zoom",
    "screen_margin_px",
    "require_leave_after_click",
    "leave_radius_px",
    "show_interaction_overlay",
    "show_gaze_bubble",
    "show_tracking_notifications",
)


def utc_time(wall: float) -> str:
    return datetime.fromtimestamp(wall, timezone.utc).isoformat(timespec="milliseconds")


def recording_context(settings: dict, environment: dict, *, simulated: bool) -> dict:
    """Explicit allowlist; never serialize complete settings or device objects."""
    return {
        "gaze_settings": _selected_recording_context(settings, GAZE_KEYS),
        "environment": _selected_recording_context(
            environment, (*ENVIRONMENT_KEYS, "physical_screen", "eye_validity_source")
        ),
        "simulated": bool(simulated),
    }


def _selected_recording_context(source: dict, keys: tuple[str, ...]) -> dict:
    result = {}
    for key in keys:
        value = source.get(key)
        if value is None or type(value) in (bool, int, float):
            result[key] = value
        elif isinstance(value, str):
            result[key] = value[:256]
        elif _is_screen_geometry(key, value):
            result[key] = list(value)
    return result


def _is_screen_geometry(key: str, value) -> bool:
    return (
        key in ("logical_screen", "physical_screen")
        and isinstance(value, (tuple, list))
        and len(value) == 4
        and all(type(coordinate) is int for coordinate in value)
    )


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
        if event.name in {"stream_summary", "selection_summary", "marker_summary"} and isinstance(
            event.fields.get("counts"), dict
        ):
            # These counters describe the ordinary basic destination. Manual
            # trace receives the detailed events; its queue loss is separate.
            event = RecordingEvent(
                event.name,
                {
                    **event.fields,
                    "counts": {
                        key: value
                        for key, value in event.fields["counts"].items()
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
        line = json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
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
        line = json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
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


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")


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
        warning["reason"] != "partial_last_line" for warning in analysis["parse_warnings"]
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
    if not _safe_storage_path(metadata) or not _safe_storage_path(trace):
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
        """File-worker maintenance. Registry locks cover claims only, never disk work."""
        root = self.directory.parent
        budget = self.budget_bytes if budget_bytes is None else budget_bytes
        if not root.exists():
            self.storage = dict(
                usage_bytes=0,
                budget_bytes=budget,
                oldest_at=None,
                state="ready",
                pruned_items=0,
                protected_bytes=0,
            )
            return self.storage
        items = sorted(self._managed_items(), key=lambda item: item[2])
        total = sum(item[3] for item in items)
        free = disk_free(root)
        low = free < LOW_SPACE_BYTES or (
            self.storage.get("low_space", False) and free < RECOVERY_SPACE_BYTES
        )
        removed = set()
        failed = False
        for key, paths, _age, size, _known in items:
            if total <= budget and (not low or free >= RECOVERY_SPACE_BYTES):
                break
            if len(removed) >= MAX_MAINTENANCE_ITEMS:
                break
            identity = _path_key(key)
            with _RESERVATION_LOCK:
                protected = identity in _RESERVATIONS or identity in _DELETING
                if key.parent == self.directory:
                    protected |= _is_active(self.directory, key.name)
                if protected:
                    continue
                _DELETING.add(identity)
            try:
                # Recheck the allowlist immediately before each deletion.
                if not all(_safe_storage_path(path) for path in (root, key.parent, key, *paths)):
                    continue
                if key.is_dir():
                    if not _retention_folder_is_safe(key, paths):
                        continue
                    _remove_recording(key, paths)
                else:
                    if not _safe_storage_path(key):
                        continue
                    key.unlink()
                removed.add(identity)
                total -= size
                free = disk_free(root)
            except OSError:
                failed = True
            finally:
                with _RESERVATION_LOCK:
                    _DELETING.discard(identity)
        # A partially failed deletion must be measured again, not subtracted optimistically.
        retained = list(self._managed_items())
        known = [item[4] for item in retained if item[4] is not None]
        with _RESERVATION_LOCK:
            protected_bytes = sum(
                item[3]
                for item in retained
                if _path_key(item[0]) in _RESERVATIONS or _is_active(self.directory, item[0].name)
            )
        total = sum(item[3] for item in retained)
        self.storage = dict(
            usage_bytes=total,
            budget_bytes=budget,
            oldest_at=min(known) if known else None,
            protected_bytes=protected_bytes,
            pruned_items=len(removed),
            pruned_total=self.storage.get("pruned_total", 0) + len(removed),
            low_space=low and free < RECOVERY_SPACE_BYTES,
            free_bytes=free,
            state="cleanup_failed"
            if failed
            else "low_space"
            if low and free < RECOVERY_SPACE_BYTES
            else "protected_over_budget"
            if total > budget
            else "ready",
            temporary_allowance_bytes=protected_bytes + 2 * SEGMENT_BYTES,
        )
        return dict(self.storage)

    def _managed_items(self):
        root = self.directory.parent
        if not _safe_storage_path(root):
            return
        for folder, pattern in (
            (root, r"(?:latest|\d{8}_\d{6}_\d+)\.txt"),
            (root / "diagnostics", r"[0-9a-f]{32}(?:\.part-\d{6})?\.jsonl"),
        ):
            if not folder.exists() or not _safe_storage_path(folder):
                continue
            for path in folder.iterdir():
                if re.fullmatch(pattern, path.name) and _safe_storage_path(path) and path.is_file():
                    try:
                        stat = path.stat()
                        yield path, (path,), stat.st_mtime, stat.st_size, _known_log_time(path)
                    except OSError:
                        continue
        if not self.directory.exists() or not _safe_storage_path(self.directory):
            return
        for folder in self.directory.iterdir():
            if (
                not RECORDING_ID.fullmatch(folder.name)
                or not _safe_storage_path(folder)
                or not folder.is_dir()
            ):
                continue
            try:
                paths = _recording_files(folder)
                if not all(_safe_storage_path(p) for p in paths):
                    continue
                sizes = [path.stat() for path in paths]
                if sizes:
                    known = _known_log_time(folder / "snimak.jsonl")
                    yield (
                        folder,
                        paths,
                        min(s.st_mtime for s in sizes),
                        sum(s.st_size for s in sizes),
                        known,
                    )
            except OSError:
                continue

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
                    recovered = {key: value for key, value in item.items() if key != "analysis"}
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
        traces = tuple(
            path for path in _recording_files(metadata_path.parent) if path.suffix == ".jsonl"
        )
        if any(path.is_symlink() for path in traces):
            raise ValueError("Linked recording segment")
        size, ended = _read_recording_edges(trace_path, recording_id)
        if len(traces) > 1:
            size = sum(path.stat().st_size for path in traces)
            with traces[-1].open("rb") as stream:
                stream.seek(max(0, traces[-1].stat().st_size - 8192))
                ended = _has_recording_end(stream.read(8192), recording_id)
        analysis = _analyze_recording(
            metadata_path.parent if len(traces) > 1 else trace_path, recording_id, analyze=analyze
        )
        item.update(bytes=size, session_end_present=ended)
        _mark_interrupted_metadata(item, ended)
        item["complete"] = _recording_is_complete(item, ended, analysis)
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

        files, selected = self._export_files(item, trace, report)
        manifest = self._export_manifest(item, files, selected)
        files["manifest.json"] = json_bytes(manifest)
        self._write_export(destination, files)

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

    @staticmethod
    def _export_files(
        item: dict, trace: tuple[Path, ...], report: GazeCheckReport | None
    ) -> tuple[dict[str, bytes | Path], dict | None]:
        files = {
            **{path.name: path for path in trace},
            "kontekst.json": json_bytes(item["context"]),
            "sazetak.txt": recording_text(item).encode("utf-8"),
        }
        selected = None
        if report is not None:
            report.validate()
            files.update(
                {
                    "provjera/rezultat.json": report.to_json(),
                    "provjera/izvjestaj.txt": report_text(report).encode("utf-8"),
                }
            )
            selected = {
                "id": report.id,
                "started_at": report.started_at,
                "state": report.state,
                "simulated": report.simulated,
                "eye_tracking_policy": report.settings.get("eye_tracking_policy"),
            }
        return files, selected

    @staticmethod
    def _export_manifest(item: dict, files: dict[str, bytes | Path], selected: dict | None) -> dict:
        return {
            "schema_version": 1,
            "recording": {key: value for key, value in item.items() if key != "analysis"},
            "selected_gaze_check": selected,
            "files": [{"path": name, **_payload_info(data)} for name, data in files.items()],
        }

    @staticmethod
    def _write_export(destination: Path, files: dict[str, bytes | Path]) -> None:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, prefix=".support-export-", delete=False
            ) as stream:
                temporary = Path(stream.name)
            with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
                for name, payload in files.items():
                    if isinstance(payload, Path):
                        digest = hashlib.sha256()
                        with (
                            payload.open("rb") as source,
                            archive.open(name, "w", force_zip64=True) as target,
                        ):
                            for chunk in iter(lambda: source.read(256 * 1024), b""):
                                target.write(chunk)
                                digest.update(chunk)
                        expected = json.loads(files["manifest.json"])["files"]
                        if digest.hexdigest() != next(
                            item["sha256"] for item in expected if item["path"] == name
                        ):
                            raise ValueError("Recording changed during export")
                    else:
                        archive.writestr(name, payload)
            with temporary.open("r+b") as stream:
                os.fsync(stream.fileno())
            # Keep the exact path for which Windows asked about overwriting.
            os.replace(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _payload_info(payload: bytes | Path) -> dict:
    if isinstance(payload, bytes):
        return dict(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    digest = hashlib.sha256()
    size = 0
    with payload.open("rb") as source:
        for chunk in iter(lambda: source.read(256 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return dict(bytes=size, sha256=digest.hexdigest())


def recording_text(item: dict) -> str:
    labels = {
        "manual": "Ručno zaustavljeno",
        "time": "Isteklo trajanje",
        "size": "Limit 32 MiB",
        "shutdown": "Zatvorena aplikacija",
        "writer_error": "Greška zapisivanja",
        "missing_end": "Nedostaje potvrđeni završetak",
    }
    analysis = item.get("analysis", {})
    lines = [
        "POGLED ASSIST · DIJAGNOSTIČKO SNIMANJE",
        f"ID: {item['id']}",
        f"Početak: {item.get('started_at')}",
        f"Kraj: {item.get('ended_at')}",
        "Trajanje: "
        + (
            "Nije dostupno"
            if item.get("duration_seconds") is None
            else f"{item['duration_seconds']:.3f} s"
        ),
        f"Razlog: {labels.get(item.get('reason'), item.get('reason'))}",
        f"Potpun snimak: {'Da' if item.get('complete') else 'Ne'}",
        f"Završni zapis: {'Da' if item.get('session_end_present') else 'Ne'}",
        "Zdravlje samo ovog snimka: " + json.dumps(item.get("health", {}), ensure_ascii=False),
        "",
        "POČETNE POSTAVKE I OKRUŽENJE",
        json.dumps(item.get("context", {}), ensure_ascii=False, indent=2),
        "",
        "ZABILJEŽENI DOGAĐAJI",
        json.dumps(analysis.get("events", {}), ensure_ascii=False),
        "Razlozi završetka odabira: "
        + json.dumps(analysis.get("selection_end_reasons_from_events", {}), ensure_ascii=False),
        "",
        "Koordinate i geometrija kontrola mogu otkriti aktivnost. Nema poruka, zvuka, ekrana, biblioteke ni ključeva.",
        "Važenje SDK podataka nije dokaz fizički zatvorenog oka. Završeni odabir nije dokaz namjeravane mete.",
        "Nedostajući i izostavljeni događaji ograničavaju zaključke; ovim se ne mjeri Tobii preciznost bez poznate mete.",
    ]
    return "\n".join(lines) + "\n"


_RECORDING_METADATA_KEYS = {
    "schema_version",
    "id",
    "state",
    "reason",
    "started_at",
    "ended_at",
    "duration_seconds",
    "minutes",
    "bytes",
    "health",
    "session_end_present",
    "complete",
    "context",
}
_RECORDING_STATES = {
    "starting",
    "recording",
    "finishing",
    "completed",
    "interrupted",
    "error",
}
_RECORDING_REASONS = {
    None,
    "manual",
    "time",
    "size",
    "shutdown",
    "writer_error",
    "missing_end",
}


def _validate_recording_state(item: dict) -> None:
    if (
        set(item) - {"segment_count"} != _RECORDING_METADATA_KEYS
        or item["state"] not in _RECORDING_STATES
    ):
        raise ValueError("Unsupported recording metadata")
    if "segment_count" in item and (
        type(item["segment_count"]) is not int or item["segment_count"] < 1
    ):
        raise ValueError("Invalid recording segments")
    if item["reason"] not in _RECORDING_REASONS:
        raise ValueError("Invalid end reason")
    _validate_recording_flags(item)
    _validate_recording_measurements(item)
    _validate_recording_timestamps(item)


def _validate_recording_flags(item: dict) -> None:
    if item["minutes"] not in DURATIONS:
        raise ValueError("Invalid recording state")
    if type(item["complete"]) is not bool or type(item["session_end_present"]) is not bool:
        raise ValueError("Invalid recording state")


def _validate_recording_measurements(item: dict) -> None:
    for name in ("duration_seconds", "bytes"):
        value = item[name]
        unknown_duration = name == "duration_seconds" and item["reason"] == "missing_end"
        if value is None and unknown_duration:
            continue
        if not _is_valid_recording_measurement(value):
            raise ValueError("Invalid recording measurement")


def _is_valid_recording_measurement(value) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _validate_recording_timestamps(item: dict) -> None:
    for name in ("started_at", "ended_at"):
        if name == "ended_at" and item[name] is None:
            continue
        if datetime.fromisoformat(item[name]).utcoffset() is None:
            raise ValueError("Missing recording timezone")


def _validate_recording_context(context: dict) -> None:
    if not isinstance(context, dict) or set(context) != {
        "gaze_settings",
        "environment",
        "simulated",
        "build",
    }:
        raise ValueError("Invalid recording context")
    safe = recording_context(
        context["gaze_settings"], context["environment"], simulated=context["simulated"]
    )
    if any(safe[key] != context[key] for key in safe):
        raise ValueError("Unexpected recording context")


def _validate_build_identity(build: dict) -> None:
    if set(build) != {"app_version", "build_revision", "build_dirty"} or not isinstance(
        build["app_version"], str
    ):
        raise ValueError("Invalid build identity")
    _validate_build_revision(build["build_revision"])
    if build["build_dirty"] is not None and type(build["build_dirty"]) is not bool:
        raise ValueError("Invalid build state")


def _validate_build_revision(revision: str | None) -> None:
    if revision is not None and not re.fullmatch(r"[0-9a-f]{40,64}", revision):
        raise ValueError("Invalid revision")


def _validate_recording_health(health: dict) -> None:
    if set(health) != {"dropped", "writer_errors", "bounded_snapshots"} or not isinstance(
        health["dropped"], dict
    ):
        raise ValueError("Invalid recording health")
    if any(
        type(count) is not int or count < 0
        for count in (
            *health["dropped"].values(),
            health["writer_errors"],
            health["bounded_snapshots"],
        )
    ):
        raise ValueError("Invalid loss count")


def _validate_metadata(item: dict) -> None:
    _validate_recording_state(item)
    context = item["context"]
    _validate_recording_context(context)
    _validate_build_identity(context["build"])
    _validate_recording_health(item["health"])
