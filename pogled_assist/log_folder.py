"""Disk-backed chronological merge of overlapping sessions, isolated by process."""

import json
import re
import sqlite3
from collections import Counter
from contextlib import closing

from .diagnostic_report import SessionAnalysis, finite_number
from .log_reader import _read_file, _SessionReader

CONTEXT_EVENTS = frozenset(
    {
        "session_start",
        "session_end",
        "segment_context",
        "recording_context",
        "runtime",
    }
)


def segment_order(path):
    match = re.search(r"(?:part-|snimak-)(\d+)\.jsonl$", path.name)
    return int(match[1]) if match else 0


def _identity(path):
    try:
        with path.open(encoding="utf-8", errors="replace") as stream:
            while line := stream.readline(65537):
                if len(line) > 65536:
                    while line and not line.endswith("\n"):
                        line = stream.readline(65537)
                    continue
                try:
                    item = json.loads(line)
                except (ValueError, RecursionError):
                    continue
                if not isinstance(item, dict):
                    continue
                pair = item.get("process_instance"), item.get("session_id")
                if all(isinstance(value, str) for value in pair):
                    return pair
    except OSError:
        pass
    return None


def _groups(root):
    groups, unavailable = {}, 0
    for path in root.rglob("*.jsonl"):
        if _linked(path, root):
            continue
        identity = _identity(path)
        if identity is None:
            unavailable += 1
        else:
            groups.setdefault(identity, []).append(path)
    return groups, unavailable


def _linked(path, root):
    while path != root:
        if path.is_symlink():
            return True
        path = path.parent
    return root.is_symlink()


class ObservationMerge:
    def __init__(self, database):
        self.database = database
        database.execute("PRAGMA cache_size=-1024")
        database.execute("PRAGMA temp_store=FILE")
        database.execute(
            "CREATE TABLE events (process TEXT, at REAL, ordinal INTEGER PRIMARY KEY, payload TEXT)"
        )
        database.execute(
            "CREATE TABLE seen (process TEXT, identity TEXT, PRIMARY KEY(process, identity)) WITHOUT ROWID"
        )
        self.duplicates = 0
        self.legacy = False
        self.counts = Counter()

    def add(self, item):
        process = item.get("process_instance")
        identity = item["data"].get("observation_id")
        if isinstance(identity, str):
            inserted = self.database.execute(
                "INSERT OR IGNORE INTO seen VALUES (?, ?)", (process, identity)
            ).rowcount
            if not inserted:
                self.duplicates += 1
                return
        elif item["event"] not in CONTEXT_EVENTS:
            self.legacy = True
        at = item.get("monotonic_s")
        self.database.execute(
            "INSERT INTO events(process, at, payload) VALUES (?, ?, ?)",
            (process, float(at) if finite_number(at) else None, json.dumps(item)),
        )
        self.counts[item["event"]] += 1

    def analyses(self, complete):
        self.database.execute("CREATE INDEX event_order ON events(process, at, ordinal)")
        results = []
        for (process,) in self.database.execute("SELECT DISTINCT process FROM events"):
            analysis = SessionAnalysis()
            for (payload,) in self.database.execute(
                "SELECT payload FROM events WHERE process=? ORDER BY at, ordinal", (process,)
            ):
                analysis.observe(json.loads(payload))
            results.append(
                dict(process_instance=process, analysis=analysis.result(complete=complete))
            )
        return results


def _read_session(paths, process, merge):
    session = _SessionReader()
    indices = sorted(segment_order(path) for path in paths)
    if indices != list(range(len(indices))):
        session.warn(0, "missing_or_duplicate_segments_unknown_cause")
    for path in sorted(paths, key=lambda p: (segment_order(p), p.name)):
        _read_file(path, session, merge.add)
    return {**session.result(), "process_instance": process}


def summarize_folder(root):
    groups, unavailable = _groups(root)
    with closing(sqlite3.connect("")) as database:
        merge = ObservationMerge(database)
        sessions = [
            _read_session(paths, process, merge)
            for (process, _session), paths in sorted(groups.items())
        ]
        complete = bool(sessions) and all(item["complete"] for item in sessions) and not unavailable
        processes = merge.analyses(complete)
        result = (
            sessions[0]
            if len(sessions) == 1
            else dict(
                schema_version=1,
                session_id=None,
                sessions=sessions,
                parse_warnings=[],
                lifecycle_complete=complete,
            )
        )
        result.update(
            complete=complete,
            events=dict(merge.counts),
            deduplicated_observations=merge.duplicates,
            deduplication_limited=merge.legacy,
            unavailable_files=unavailable,
            processes=processes,
        )
        if len(processes) == 1:
            result["analysis"] = processes[0]["analysis"]
        return result
