"""Offline JSONL session summary; never imports Qt or starts tracking."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

from .diagnostic_report import SessionAnalysis, finite_number


def summarize(path: Path) -> dict:
    if path.is_dir():
        return _summarize_folder(path)
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


def _segment_order(path):
    match = re.search(r"(?:part-|snimak-)(\d+)\.jsonl$", path.name)
    return int(match[1]) if match else 0


def _summarize_folder(root):
    groups = {}
    starts = {}
    unavailable = 0
    for path in root.rglob("*.jsonl"):
        if path.is_symlink() or any(
            parent.is_symlink() for parent in path.parents if parent != root.parent
        ):
            continue
        try:
            with path.open(encoding="utf-8", errors="replace") as stream:
                for line in iter(lambda: stream.readline(65537), ""):
                    try:
                        first = json.loads(line)
                    except ValueError:
                        continue
                    if (
                        isinstance(first, dict)
                        and isinstance(first.get("session_id"), str)
                        and isinstance(first.get("process_instance"), str)
                    ):
                        groups.setdefault(
                            (first["process_instance"], first["session_id"]), []
                        ).append(path)
                        key = first["process_instance"], first["session_id"]
                        at = first.get("monotonic_s")
                        if finite_number(at):
                            starts[key] = min(at, starts.get(key, at))
                        break
                else:
                    unavailable += 1
        except OSError:
            unavailable += 1
    results, processes = [], {}
    counts = Counter()
    duplicates = 0
    legacy = False
    # A temporary SQLite identity index bounds RAM even for multi-GB overlapping copies.
    with sqlite3.connect("") as identities:
        identities.execute("PRAGMA cache_size=-1024")
        identities.execute(
            "CREATE TABLE seen (process TEXT, identity TEXT, PRIMARY KEY(process, identity)) WITHOUT ROWID"
        )
        for (process, _session_id), paths in sorted(
            groups.items(),
            key=lambda pair: (pair[0][0], starts.get(pair[0], float("inf")), pair[0][1]),
        ):
            session = _SessionReader()
            analysis = processes.setdefault(process, SessionAnalysis())

            def observe(item, process=process, analysis=analysis):
                nonlocal duplicates, legacy
                identity = item["data"].get("observation_id")
                if isinstance(identity, str):
                    inserted = identities.execute(
                        "INSERT OR IGNORE INTO seen VALUES (?, ?)", (process, identity)
                    ).rowcount
                    if not inserted:
                        duplicates += 1
                        return
                elif item["event"] not in {
                    "session_start",
                    "session_end",
                    "segment_context",
                    "recording_context",
                    "runtime",
                }:
                    legacy = True
                counts[item["event"]] += 1
                analysis.observe(item)

            indices = sorted(_segment_order(path) for path in paths)
            if indices != list(range(len(indices))):
                session.warn(0, "missing_or_duplicate_segments_unknown_cause")
            for path in sorted(paths, key=lambda p: (_segment_order(p), p.name)):
                _read_file(path, session, observe)
            result = session.result()
            result["process_instance"] = process
            results.append(result)
        identities.commit()
    complete = bool(results) and all(result["complete"] for result in results) and not unavailable
    if len(results) == 1:
        result = results[0]
    else:
        result = dict(
            schema_version=1,
            session_id=None,
            complete=complete,
            sessions=results,
            events=dict(counts),
            parse_warnings=[],
            lifecycle_complete=complete,
        )
    result.update(
        complete=complete,
        events=dict(counts),
        deduplicated_observations=duplicates,
        deduplication_limited=legacy,
        unavailable_files=unavailable,
        processes=[
            dict(process_instance=process, analysis=analysis.result(complete=complete))
            for process, analysis in processes.items()
        ],
    )
    if len(processes) == 1:
        result["analysis"] = next(iter(processes.values())).result(complete=complete)
    return result


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
        except ValueError:
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
