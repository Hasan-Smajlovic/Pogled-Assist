"""In-process claims shared by the file writer, retention and export workers."""

import os
from pathlib import Path
from threading import Lock

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


def set_recording_active(directory: Path, recording_id: str, active: bool) -> None:
    key = (os.path.normcase(os.path.abspath(directory)), recording_id)
    if active:
        _ACTIVE_RECORDINGS.add(key)
    else:
        _ACTIVE_RECORDINGS.discard(key)


def _is_active(directory: Path, recording_id: str) -> bool:
    return (os.path.normcase(os.path.abspath(directory)), recording_id) in _ACTIVE_RECORDINGS
