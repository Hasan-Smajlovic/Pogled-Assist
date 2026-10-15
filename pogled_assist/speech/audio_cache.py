"""Lazy audio storage for whole saved entries; free-form messages stay in memory."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from threading import RLock

from .elevenlabs import MAX_AUDIO_BYTES

MAGIC = b"PogledAudio1\0"


def saved_text(text: str) -> str:
    return " ".join(text.split()).upper()


def cache_root() -> Path | None:
    root = os.environ.get("LOCALAPPDATA", "")
    return Path(root) / "PogledAssist" / "speech-audio" if root else None


class AudioCache:
    def __init__(self, root: Path | None) -> None:
        self.root = root
        self._lock = RLock()
        self._texts: set[str] = set()
        self._identity = ""
        self._allowed: set[str] = set()
        self._generation = 0
        self._blocked: set[str] = set()

    def configure(self, identity: str, texts: set[str]) -> None:
        with self._lock:
            cleaned = {saved_text(text) for text in texts if text.strip()}
            if identity == self._identity and cleaned == self._texts:
                return
            self._generation += 1
            self._identity, self._texts = identity, cleaned
            self._allowed = {self._key(text) for text in cleaned}
            self._remove_except(self._allowed)

    def ticket(self, text: str, identity: str | None = None) -> tuple[int, str] | None:
        with self._lock:
            if identity is not None and identity != self._identity:
                return None
            key = self._key(saved_text(text))
            return (self._generation, key) if key in self._allowed else None

    def read(self, ticket: tuple[int, str] | None) -> bytes | None:
        with self._lock:
            if not self._valid(ticket) or ticket[1] in self._blocked:
                return None
            path = self.root / (ticket[1] + ".audio")
            try:
                if path.stat().st_size > MAX_AUDIO_BYTES + len(MAGIC) + 32:
                    return None
                data = path.read_bytes()
            except OSError:
                return None
            header = len(MAGIC) + 32
            audio = data[header:]
            if (
                not audio or not data.startswith(MAGIC)
                or data[len(MAGIC):header] != hashlib.sha256(audio).digest()
            ):
                self.discard(ticket)
                return None
            return audio

    def write(self, ticket: tuple[int, str] | None, audio: bytes) -> bool:
        with self._lock:
            if not self._valid(ticket) or not audio or len(audio) > MAX_AUDIO_BYTES:
                return False
            path = self.root / (ticket[1] + ".audio")
            temporary = path.with_suffix(".tmp")
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                temporary.write_bytes(MAGIC + hashlib.sha256(audio).digest() + audio)
                temporary.replace(path)
                self._blocked.discard(ticket[1])
                return True
            except OSError:
                return False
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def discard(self, ticket: tuple[int, str] | None) -> None:
        with self._lock:
            if self._valid(ticket):
                self._blocked.add(ticket[1])
                try:
                    (self.root / (ticket[1] + ".audio")).unlink(missing_ok=True)
                except OSError:
                    pass

    def clear(self) -> bool:
        with self._lock:
            self._generation += 1
            self._blocked.update(self._allowed)
            return self._remove_except(set())

    def _key(self, text: str) -> str:
        return hashlib.sha256((self._identity + "\0" + text).encode()).hexdigest()

    def _valid(self, ticket: tuple[int, str] | None) -> bool:
        return (
            self.root is not None and ticket is not None
            and ticket[0] == self._generation and ticket[1] in self._allowed
        )

    def _remove_except(self, allowed: set[str]) -> bool:
        if self.root is None:
            return True
        try:
            for path in self.root.iterdir():
                if path.suffix in (".audio", ".tmp") and path.stem not in allowed:
                    self._blocked.add(path.stem)
                    path.unlink(missing_ok=True)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False
