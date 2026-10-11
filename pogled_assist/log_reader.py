"""Offline JSONL session summary; never imports Qt or starts tracking."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .diagnostic_report import SessionAnalysis


def summarize(path: Path) -> dict:
    session = _SessionReader()
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            session.read(line_number, line)
    return session.result()


class _SessionReader:
    def __init__(self) -> None:
        self.counts: Counter = Counter()
        self.rejected: Counter = Counter()
        self.cancellations: Counter = Counter()
        self.warnings: list[dict] = []
        self.session = None
        self.process = None
        self.identity_set = False
        self.health: dict = {}
        self.analysis = SessionAnalysis()

    def read(self, line_number: int, line: str) -> None:
        try:
            item = json.loads(line)
        except ValueError:
            reason = "invalid_json" if line.endswith("\n") else "partial_last_line"
        else:
            reason = self._reject_reason(item)
        if reason is not None:
            self.warnings.append({"line": line_number, "reason": reason})
            return
        self.session = item.get("session_id")
        self.process = item.get("process_instance")
        self.identity_set = True
        self._observe(item)

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

    def _observe_rejections(self, counts: object) -> None:
        if not isinstance(counts, dict):
            return
        for reason, count in counts.items():
            if reason.startswith("rejected:") and isinstance(count, int):
                self.rejected[reason.removeprefix("rejected:")] += count

    def _records_missing(self) -> bool:
        loss = self.health.get("dropped", {})
        return isinstance(loss, dict) and any(
            isinstance(count, int) and count > 0 for count in loss.values()
        )

    def result(self) -> dict:
        started = "session_start" in self.counts
        ended = "session_end" in self.counts
        complete = all(
            (
                started,
                ended,
                not self.warnings,
                "session_limit" not in self.counts,
                not self._records_missing(),
                not self.health.get("writer_errors"),
                not self.health.get("bounded_snapshots"),
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
            "parse_warnings": self.warnings,
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
