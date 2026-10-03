"""Reversible local word counts with atomic persistence and explicit recovery."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .text import START, spelling, valid_word, words

Key = tuple[str, ...]
READ_ERROR = "Naučene riječi nisu učitane. Datoteka je sačuvana. Pokušajte ponovo u Postavkama."
WRITE_ERROR = "Učenje nije sačuvano. Pokušajte ponovo u Postavkama."
READ_FAILURES = (OSError, ValueError, TypeError, KeyError)
MAX_FILE_SIZE = 16 * 1024 * 1024
MAX_COUNT = 2**31 - 1


@dataclass
class Contribution:
    key: Key
    generation: tuple[int, ...]
    active: bool = True


class LearningStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._io_lock = threading.Lock()
        self._counts: Counter[Key] = Counter()
        self._pending: Counter[Key] = Counter()
        self._forgotten: set[str] = set()
        self._generations: Counter[str] = Counter()
        self.revision = 0
        self.saved_revision = 0
        self.error = ""
        self._unreadable = False
        try:
            self._counts = self._read()
        except READ_FAILURES:
            self._unreadable = True
            self.error = READ_ERROR

    def snapshot(self) -> Counter[Key]:
        with self._lock:
            return self._counts.copy()

    def snapshot_if_changed(self, revision: int) -> tuple[int, Counter[Key]] | None:
        with self._lock:
            if self.revision == revision:
                return None
            return self.revision, self._counts.copy()

    def learned_words(self) -> list[str]:
        with self._lock:
            return sorted(
                key[0] for key, count in self._counts.items() if len(key) == 1 and count > 0
            )

    def credit(self, key: Key) -> Contribution:
        with self._lock:
            self._change(key, 1)
            return Contribution(key, self._generation(key))

    def revoke(self, contribution: Contribution) -> None:
        with self._lock:
            if contribution.active and self._is_current(contribution):
                self._change(contribution.key, -1)
            contribution.active = False

    def restore(self, contribution: Contribution) -> None:
        with self._lock:
            if not contribution.active and self._is_current(contribution):
                self._change(contribution.key, 1)
                contribution.active = True

    def learn_text(self, text: str) -> None:
        for token in words(text):
            for key in token.keys:
                self.credit(key)

    def forget(self, word: str) -> None:
        word = spelling(word)
        with self._lock:
            self._generations[word] += 1
            self._forgotten.add(word)
            self._counts = _without_words(self._counts, {word})
            self._pending = _without_words(self._pending, {word})
            self.revision += 1

    def save(self, *, retry: bool = False) -> bool:
        """Persist a snapshot without blocking count updates during disk writes."""
        with self._io_lock:
            if self._unreadable and not retry:
                return False
            if self._unreadable and not self._merge_disk():
                return False
            with self._lock:
                revision = self.revision
                pending = self._pending.copy()
                forgotten = {word: self._generations[word] for word in self._forgotten}
                payload = _payload(self._counts)
            try:
                if self.path is not None:
                    self._write(payload)
            except (OSError, ValueError):
                self.error = WRITE_ERROR
                return False
            self._mark_saved(revision, pending, forgotten)
            return True

    def _mark_saved(self, revision: int, pending: Counter[Key], forgotten: dict[str, int]) -> None:
        with self._lock:
            self.saved_revision = revision
            self._pending.subtract(pending)
            self._pending = Counter({key: count for key, count in self._pending.items() if count})
            self._forgotten.difference_update(
                word
                for word, generation in forgotten.items()
                if self._generations[word] == generation
            )
            self.error = ""

    def _merge_disk(self) -> bool:
        try:
            disk = self._read()
        except READ_FAILURES:
            self.error = READ_ERROR
            return False
        with self._lock:
            disk = _without_words(disk, self._forgotten)
            disk.update(self._pending)
            self._counts = +disk
            self.revision += 1
            self._unreadable = False
        return True

    def _is_current(self, contribution: Contribution) -> bool:
        return contribution.generation == self._generation(contribution.key)

    def _generation(self, key: Key) -> tuple[int, ...]:
        return tuple(self._generations[word] for word in key)

    def _change(self, key: Key, delta: int) -> None:
        delta = max(-self._counts[key], delta)
        if delta:
            self._counts[key] += delta
            if not self._counts[key]:
                del self._counts[key]
            self._pending[key] += delta
            self.revision += 1

    def _read(self) -> Counter[Key]:
        if self.path is None or not self.path.exists():
            return Counter()
        if self.path.stat().st_size > MAX_FILE_SIZE:
            raise ValueError("Personal model exceeds the supported size")
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        counts: Counter[Key] = Counter()
        for key, count in map(_learned_entry, _entries(payload)):
            if key in counts:
                raise ValueError("Invalid learned word")
            counts[key] = count
        return counts

    def _write(self, payload: dict) -> None:
        assert self.path is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=self.path.name + ".",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _without_words(counts: Counter[Key], removed: set[str]) -> Counter[Key]:
    return Counter({key: count for key, count in counts.items() if not removed.intersection(key)})


def _payload(counts: Counter[Key]) -> dict:
    return {
        "version": 1,
        "counts": [[" ".join(key), count] for key, count in sorted(counts.items()) if count > 0],
    }


def _entries(payload: object) -> list:
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("Unsupported personal data version")
    entries = payload.get("counts")
    if not isinstance(entries, list):
        raise ValueError("Invalid personal data")
    return entries


def _learned_entry(entry: object) -> tuple[Key, int]:
    if not _is_entry(entry):
        raise ValueError("Invalid learned entry")
    raw, count = entry
    key = tuple(raw.split(" "))
    if not _valid_count(count):
        raise ValueError("Invalid learned count")
    if not _valid_key(key):
        raise ValueError("Invalid learned word")
    return key, count


def _is_entry(entry: object) -> bool:
    return isinstance(entry, list) and len(entry) == 2 and isinstance(entry[0], str)


def _valid_count(count: object) -> bool:
    return type(count) is int and 0 < count <= MAX_COUNT


def _valid_key(key: Key) -> bool:
    words = key[1:] if len(key) > 1 and key[0] == START else key
    return 1 <= len(key) <= 3 and all(valid_word(word) for word in words)
