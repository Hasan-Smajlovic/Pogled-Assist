"""Offline JSONL session summary; never imports Qt or starts tracking."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .diagnostic_report import SessionAnalysis
from .log_validation import diagnostic_fields_valid


def summarize(path: Path) -> dict:
    if path.is_dir():
        from .log_folder import summarize_folder

        return summarize_folder(path)
    session = _SessionReader()
    _read_file(path, session)
    return session.result()


def _read_file(path, session, observe=None):
    try:
        with path.open(encoding="utf-8", errors="replace") as stream:
            number = 0
            while line := stream.readline(65537):
                number += 1
                if len(line) > 65536:
                    while line and not line.endswith("\n"):
                        line = stream.readline(65537)
                    session.warn(number, "oversized_record")
                    continue
                item = session.read(number, line)
                if item is not None and observe is not None:
                    observe(item)
    except OSError:
        session.warn(0, "file_unavailable")


class _SessionReader:
    def __init__(self) -> None:
        self.counts: Counter = Counter()
        self.rejected: Counter = Counter()
        self.cancellations: Counter = Counter()
        self.warnings: list[dict] = []
        self.warning_count = 0
        self.session = None
        self.process = None
        self.identity_set = False
        self.health: dict = {}
        self.manual_trace = False
        self.recording_health: dict | None = None
        self.end_reason: str | None = None
        self.analysis = SessionAnalysis()

    def warn(self, line_number, reason):
        self.warning_count += 1
        if len(self.warnings) < 200:
            self.warnings.append({"line": line_number, "reason": reason})

    def read(self, line_number: int, line: str) -> dict | None:
        try:
            item = json.loads(line)
        except (ValueError, RecursionError):
            reason = "invalid_json" if line.endswith("\n") else "partial_last_line"
        else:
            reason = self._reject_reason(item)
        if reason is not None:
            self.warn(line_number, reason)
            return
        self.session = item.get("session_id")
        self.process = item.get("process_instance")
        self.identity_set = True
        self._observe(item)
        return item

    def _reject_reason(self, item: object) -> str | None:
        if not isinstance(item, dict):
            return "unsupported_record"
        if item.get("schema_version") != 1 or not isinstance(item.get("data"), dict):
            return "unsupported_record"
        if self.identity_set:
            mismatch = self._identity_mismatch(item)
            if mismatch is not None:
                return mismatch
        if not isinstance(item.get("event"), str):
            return "missing_event"
        if not diagnostic_fields_valid(item["data"]):
            return "invalid_diagnostic_fields"
        return None

    def _identity_mismatch(self, item: dict) -> str | None:
        if self.session != item.get("session_id"):
            return "mixed_sessions"
        if self.process != item.get("process_instance"):
            return "mixed_processes"
        return None

    def _observe(self, item: dict) -> None:
        event, data = item["event"], item["data"]
        self.counts[event] += 1
        self.analysis.observe(item)
        if event == "stream_summary":
            self._observe_rejections(data.get("counts"))
        if event == "selection_end" and isinstance(data.get("reason"), str):
            self.cancellations[data["reason"]] += 1
        if isinstance(item.get("logging_health"), dict):
            self.health = item["logging_health"]
        if event == "session_start":
            self.manual_trace = data.get("mode") == "manual_trace"
        if event == "session_end":
            reason = data.get("reason")
            self.end_reason = reason if isinstance(reason, str) else None
            health = data.get("recording_health")
            self.recording_health = health if isinstance(health, dict) else None

    def _observe_rejections(self, counts: object) -> None:
        if not isinstance(counts, dict):
            return
        for reason, count in counts.items():
            if reason.startswith("rejected:") and isinstance(count, int):
                self.rejected[reason.removeprefix("rejected:")] += count

    def _records_missing(self, health: dict) -> bool:
        loss = health.get("dropped", {})
        return isinstance(loss, dict) and any(
            isinstance(count, int) and count > 0 for count in loss.values()
        )

    def _manual_footer_valid(self) -> bool:
        health = self.recording_health
        if not isinstance(health, dict) or set(health) != {
            "dropped",
            "writer_errors",
            "bounded_snapshots",
        }:
            return False
        dropped = health["dropped"]
        if not isinstance(dropped, dict):
            return False
        counts = (*dropped.values(), health["writer_errors"], health["bounded_snapshots"])
        return all(type(count) is int and count >= 0 for count in counts)

    def result(self) -> dict:
        started = "session_start" in self.counts
        ended = "session_end" in self.counts
        health = (self.recording_health or {}) if self.manual_trace else self.health
        complete = all(
            (
                started,
                ended,
                not self.warnings,
                "session_limit" not in self.counts,
                not self._records_missing(health),
                not health.get("writer_errors"),
                not health.get("bounded_snapshots"),
                not self.manual_trace
                or (self.end_reason in {"manual", "time"} and self._manual_footer_valid()),
            )
        )
        return {
            "schema_version": 1,
            "session_id": self.session,
            "session_start_present": started,
            "session_end_present": ended,
            "events": dict(self.counts),
            "provider_rejections_from_summaries": dict(self.rejected),
            "selection_end_reasons_from_events": dict(self.cancellations),
            "logging_health_process_cumulative": self.health,
            "recording_health": self.recording_health,
            "session_end_reason": self.end_reason,
            "parse_warnings": self.warnings,
            "parse_warning_count": self.warning_count,
            "warnings_truncated": self.warning_count > len(self.warnings),
            "lifecycle_complete": started and ended,
            "complete": complete,
            "analysis": self.analysis.result(complete=complete),
            "limits": "Basic rate limits and queue drops can omit individual events; SDK validity is not physical eye closure.",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(summarize(arguments.session), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
