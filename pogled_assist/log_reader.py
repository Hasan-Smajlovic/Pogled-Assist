"""Offline JSONL session summary; never imports Qt or starts tracking."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def summarize(path: Path) -> dict:
    counts: Counter = Counter()
    rejected: Counter = Counter()
    cancellations: Counter = Counter()
    warnings = []
    started = ended = False
    session = None
    health = {}
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                item = json.loads(line)
            except ValueError:
                warnings.append(
                    {
                        "line": line_number,
                        "reason": "invalid_json" if line.endswith("\n") else "partial_last_line",
                    }
                )
                continue
            if (
                not isinstance(item, dict)
                or item.get("schema_version") != 1
                or not isinstance(item.get("data"), dict)
            ):
                warnings.append({"line": line_number, "reason": "unsupported_record"})
                continue
            if session is not None and session != item.get("session_id"):
                warnings.append({"line": line_number, "reason": "mixed_sessions"})
            session = item.get("session_id")
            event = item.get("event")
            if not isinstance(event, str):
                warnings.append({"line": line_number, "reason": "missing_event"})
                continue
            counts[event] += 1
            started |= event == "session_start"
            ended |= event == "session_end"
            data = item["data"]
            if event == "stream_summary" and isinstance(data.get("counts"), dict):
                for reason, count in data["counts"].items():
                    if reason.startswith("rejected:") and isinstance(count, int):
                        rejected[reason.removeprefix("rejected:")] += count
            if event == "selection_end" and isinstance(data.get("reason"), str):
                cancellations[data["reason"]] += 1
            if isinstance(item.get("logging_health"), dict):
                health = item["logging_health"]
    loss = health.get("dropped", {})
    missing = isinstance(loss, dict) and any(
        isinstance(count, int) and count > 0 for count in loss.values()
    )
    return {
        "schema_version": 1,
        "session_id": session,
        "session_start_present": started,
        "session_end_present": ended,
        "events": dict(counts),
        "provider_rejections_from_summaries": dict(rejected),
        "selection_end_reasons_from_events": dict(cancellations),
        "logging_health_process_cumulative": health,
        "parse_warnings": warnings,
        "lifecycle_complete": started and ended,
        "complete": started
        and ended
        and not warnings
        and "session_limit" not in counts
        and not missing
        and not health.get("writer_errors")
        and not health.get("bounded_snapshots"),
        "limits": "Basic rate limits and queue drops can omit individual events; SDK validity is not physical eye closure.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(summarize(arguments.session), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
