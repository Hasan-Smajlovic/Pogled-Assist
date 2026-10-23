"""Atomic report storage and explicit ZIP export; no diagnostic transport dependency."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .gaze_check_report import MAX_REPORT_BYTES, GazeCheckReport, report_text

REPORT_NAME = re.compile(r"gaze-check-[0-9a-f-]{36}\.json\Z")
MAX_REPORTS = 100
MAX_TOTAL_BYTES = 10 * 1024 * 1024


@dataclass
class StoredReport:
    key: str
    report: GazeCheckReport | None
    error: str | None = None


class GazeCheckStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def load(self) -> list[StoredReport]:
        if not self.directory.exists():
            return []
        entries = []
        for path in self.directory.iterdir():
            if not REPORT_NAME.fullmatch(path.name) or path.is_symlink() or not path.is_file():
                continue
            try:
                with path.open("rb") as source:
                    report = GazeCheckReport.from_json(source.read(MAX_REPORT_BYTES + 1))
                if path.name != f"gaze-check-{report.id}.json":
                    raise ValueError("Report identity mismatch")
                entries.append(StoredReport(report.id, report))
            except (
                OSError,
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
                OverflowError,
                RecursionError,
            ):
                entries.append(
                    StoredReport(path.name, None, "Rezultat nije čitljiv ili format nije podržan.")
                )
        return sorted(
            entries,
            key=lambda e: (
                datetime.fromisoformat(e.report.started_at)
                if e.report
                else datetime.min.replace(tzinfo=timezone.utc)
            ),
            reverse=True,
        )

    def save(self, report: GazeCheckReport) -> None:
        report.validate()
        payload = report.to_json()
        if len(payload) > MAX_TOTAL_BYTES:
            raise ValueError(
                "Report exceeds automatic storage limit; manual export remains available"
            )
        self.directory.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self.directory / f"gaze-check-{report.id}.json", payload)
        self._prune()

    def _prune(self) -> None:
        # Unsupported/corrupt reports and unrelated files are never retention candidates.
        entries = [entry.report for entry in self.load() if entry.report is not None]
        entries.sort(key=lambda report: datetime.fromisoformat(report.started_at), reverse=True)
        total = 0
        for index, report in enumerate(entries):
            path = self.directory / f"gaze-check-{report.id}.json"
            size = path.stat().st_size
            total += size
            if index >= MAX_REPORTS or total > MAX_TOTAL_BYTES:
                path.unlink()

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=".gaze-check-", delete=False
            ) as output:
                temporary = Path(output.name)
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def export(report: GazeCheckReport, destination: Path) -> None:
        report.validate()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, prefix=".gaze-export-", delete=False
            ) as output:
                temporary = Path(output.name)
            with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr("rezultat.json", report.to_json())
                archive.writestr("izvjestaj.txt", report_text(report).encode("utf-8"))
            os.replace(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
