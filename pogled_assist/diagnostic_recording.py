"""Bounded recording files and local support ZIPs, used only by background workers."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from zipfile import ZIP_DEFLATED, ZipFile

from .log_reader import summarize
from .tracking.gaze_check_report import (
    ENVIRONMENT_KEYS,
    GazeCheckReport,
    report_text,
)

RECORDING_BYTES = 32 * 1024 * 1024
MAX_RECORDINGS = 5
TOTAL_BYTES = 200 * 1024 * 1024
DURATIONS = (1, 2, 5, 10)
RECORDING_ID = re.compile(r"[0-9a-f]{32}\Z")
_STORE_LOCK = RLock()  # File workers only; input/Qt producers never take this lock.
_ACTIVE_RECORDINGS: set[tuple[str, str]] = set()


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

    def selected(source, keys):
        result = {}
        for key in keys:
            value = source.get(key)
            if value is None or type(value) in (bool, int, float):
                result[key] = value
            elif isinstance(value, str):
                result[key] = value[:256]
            elif (
                key in ("logical_screen", "physical_screen")
                and isinstance(value, (tuple, list))
                and len(value) == 4
                and all(type(v) is int for v in value)
            ):
                result[key] = list(value)
        return result

    return {
        "gaze_settings": selected(settings, GAZE_KEYS),
        "environment": selected(
            environment, (*ENVIRONMENT_KEYS, "physical_screen", "eye_validity_source")
        ),
        "simulated": bool(simulated),
    }


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
        }


class RecordingSink:
    """A second structured destination of LogWriter, never a separate observation pipeline."""

    def __init__(self, recording: Recording, process: str) -> None:
        self.recording = recording
        self.process = process
        self.sequence = 0
        self.stream = None
        folder = recording.directory / recording.id
        folder.mkdir(parents=True, exist_ok=False)
        atomic_bytes(folder / "recording.json", json_bytes(recording.snapshot()))
        self.stream = (folder / "snimak.jsonl").open("w", encoding="utf-8", newline="\n")
        self.write(
            "session_start",
            {"mode": "manual_trace", "minutes": recording.minutes},
            recording.started_mono,
            recording.started_wall,
            footer=True,
        )
        self.write(
            "recording_context",
            recording.context,
            recording.started_mono,
            recording.started_wall,
            footer=True,
        )
        recording.state = "recording" if recording.accepting else "finishing"

    def write(self, name: str, fields: dict, at: float, wall: float, *, footer=False) -> bool:
        item = self.recording
        if self.stream is None:
            return False
        if name in {"stream_summary", "selection_summary", "marker_summary"} and isinstance(
            fields.get("counts"), dict
        ):
            # These counters describe the ordinary basic destination. Manual
            # trace receives the detailed events; its queue loss is separate.
            fields = {
                **fields,
                "counts": {
                    key: value
                    for key, value in fields["counts"].items()
                    if not key.startswith("suppressed:")
                },
            }
        self.sequence += 1
        record = {
            "schema_version": 1,
            "event": name,
            "session_id": item.id,
            "process_instance": self.process,
            "event_seq": self.sequence,
            "wall_time": utc_time(wall),
            "monotonic_s": at,
            "data": fields,
        }
        line = json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
        size = len(line.encode("utf-8"))
        # Reserve a bounded lifecycle footer inside the total 32 MiB cap.
        if item.bytes_written + size > RECORDING_BYTES - (0 if footer else 8192):
            return False
        self.stream.write(line)
        item.bytes_written += size
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


class RecordingStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

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
                self._prune(active_id=active_id)
            return self._load(active_id=active_id)

    def _load(self, *, active_id: str | None = None) -> list[dict]:
        if not self.directory.exists():
            return []
        entries = []
        for folder in self.directory.iterdir():
            if (
                not RECORDING_ID.fullmatch(folder.name)
                or folder.is_symlink()
                or not folder.is_dir()
            ):
                continue
            if folder.name == active_id or _is_active(self.directory, folder.name):
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
        folder = self.directory / recording_id
        if folder.is_symlink():
            raise ValueError("Linked recording")
        metadata_path, trace_path = folder / "recording.json", folder / "snimak.jsonl"
        if metadata_path.is_symlink() or trace_path.is_symlink():
            raise ValueError("Linked recording file")
        with metadata_path.open("rb") as stream:
            payload = stream.read(65537)
        if len(payload) > 65536:
            raise ValueError("Invalid metadata size")
        item = json.loads(payload)
        if item["id"] != recording_id or item.get("schema_version") != 1:
            raise ValueError("Invalid recording metadata")
        _validate_metadata(item)
        size = trace_path.stat().st_size
        if size > RECORDING_BYTES:
            raise ValueError("Invalid recording size")
        with trace_path.open("rb") as stream:
            first = json.loads(stream.readline(8193))
            stream.seek(max(0, size - 8192))
            tail = stream.read(8192)
        if first.get("session_id") != recording_id or first.get("event") != "session_start":
            raise ValueError("Invalid recording header")
        ended = False
        try:
            last = json.loads(tail.splitlines()[-1])
            ended = (
                last.get("event") == "session_end"
                and last.get("session_id") == recording_id
                and tail.endswith(b"\n")
            )
        except (ValueError, IndexError):
            pass
        analysis = summarize(trace_path) if analyze else None
        if analysis is not None and (
            analysis["session_id"] != recording_id
            or any(
                warning["reason"] != "partial_last_line" for warning in analysis["parse_warnings"]
            )
        ):
            raise ValueError("Invalid or mixed recording stream")
        item["bytes"] = size
        item["session_end_present"] = ended
        # A crash can leave the initial metadata next to a useful partial stream.
        if item["state"] in ("starting", "recording", "finishing") or (
            not ended and item["state"] == "completed"
        ):
            item.update(state="interrupted", reason="missing_end", complete=False)
        health = item.get("health", {})
        item["complete"] = bool(
            item.get("complete")
            and ended
            and (analysis is None or analysis["complete"])
            and not health.get("writer_errors")
            and not health.get("bounded_snapshots")
            and not any(health.get("dropped", {}).values())
        )
        if analysis is not None:
            item["analysis"] = analysis
        return item

    def prune(self, *, active_id: str | None = None) -> None:
        with _STORE_LOCK:
            self._prune(active_id=active_id)

    def _prune(self, *, active_id: str | None = None) -> None:
        total = 0
        retained = 0
        for item in self.load(active_id=active_id):
            # Retain even unreadable recordings within the budget, but never
            # touch unrelated files or folders containing additional content.
            folder = self.directory / item["id"]
            if _is_active(self.directory, item["id"]):
                continue
            paths = tuple(
                path
                for path in (folder / "snimak.jsonl", folder / "recording.json")
                if path.exists()
            )
            if any(path.is_symlink() for path in paths) or set(
                p.name for p in folder.iterdir()
            ) != {p.name for p in paths}:
                continue
            size = sum(p.stat().st_size for p in paths)
            total += size
            retained += 1
            if retained > MAX_RECORDINGS or total > TOTAL_BYTES:
                for path in paths:
                    path.unlink()
                folder.rmdir()

    def export(
        self, recording_id: str, destination: Path, report: GazeCheckReport | None = None
    ) -> None:
        with _STORE_LOCK:
            self._export(recording_id, destination, report)

    def _export(self, recording_id: str, destination: Path, report: GazeCheckReport | None) -> None:
        if _is_active(self.directory, recording_id):
            raise ValueError("Recording is still active")
        if destination.resolve() in (
            (self.directory / recording_id / name).resolve()
            for name in ("recording.json", "snimak.jsonl")
        ):
            raise ValueError("Cannot replace recording source")
        try:
            item = self.inspect(recording_id)
            folder = self.directory / recording_id
            with (folder / "snimak.jsonl").open("rb") as stream:
                trace = stream.read(RECORDING_BYTES + 1)
            if len(trace) > RECORDING_BYTES:
                raise ValueError("Recording too large")
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
            raise RecordingReadError("Recording cannot be exported") from error
        files = {
            "snimak.jsonl": trace,
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
        manifest = {
            "schema_version": 1,
            "recording": {k: v for k, v in item.items() if k != "analysis"},
            "selected_gaze_check": selected,
            "files": [
                {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                for name, data in files.items()
            ],
        }
        files["manifest.json"] = json_bytes(manifest)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, prefix=".support-export-", delete=False
            ) as stream:
                temporary = Path(stream.name)
            with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
                for name, payload in files.items():
                    archive.writestr(name, payload)
            with temporary.open("r+b") as stream:
                os.fsync(stream.fileno())
            # Keep the exact path for which Windows asked about overwriting.
            os.replace(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


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


def _validate_metadata(item: dict) -> None:
    expected = {
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
    if set(item) != expected or item["state"] not in {
        "starting",
        "recording",
        "finishing",
        "completed",
        "interrupted",
        "error",
    }:
        raise ValueError("Unsupported recording metadata")
    if item["reason"] not in {
        None,
        "manual",
        "time",
        "size",
        "shutdown",
        "writer_error",
        "missing_end",
    }:
        raise ValueError("Invalid end reason")
    if (
        item["minutes"] not in DURATIONS
        or type(item["complete"]) is not bool
        or type(item["session_end_present"]) is not bool
    ):
        raise ValueError("Invalid recording state")
    for name in ("duration_seconds", "bytes"):
        value = item[name]
        if value is None and name == "duration_seconds" and item["reason"] == "missing_end":
            continue
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("Invalid recording measurement")
    for name in ("started_at", "ended_at"):
        if item[name] is not None and datetime.fromisoformat(item[name]).utcoffset() is None:
            raise ValueError("Missing recording timezone")
    context = item["context"]
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
    build = context["build"]
    if set(build) != {"app_version", "build_revision", "build_dirty"} or not isinstance(
        build["app_version"], str
    ):
        raise ValueError("Invalid build identity")
    if build["build_revision"] is not None and not re.fullmatch(
        r"[0-9a-f]{40,64}", build["build_revision"]
    ):
        raise ValueError("Invalid revision")
    if build["build_dirty"] is not None and type(build["build_dirty"]) is not bool:
        raise ValueError("Invalid build state")
    health = item["health"]
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
