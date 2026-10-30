"""Shared log retention, run only by the serial background file worker."""

import re

from . import diagnostic_recording as policy


def maintain(store, *, budget_bytes=None):
    budget = store.budget_bytes if budget_bytes is None else budget_bytes
    root = store.directory.parent
    if not root.exists():
        store.storage = dict(
            usage_bytes=0,
            budget_bytes=budget,
            oldest_at=None,
            state="ready",
            pruned_items=0,
            protected_bytes=0,
        )
        return dict(store.storage)
    cleanup = Cleanup(store, budget)
    cleanup.run()
    store.storage = cleanup.result()
    return dict(store.storage)


def managed_items(directory):
    root = directory.parent
    if not policy._safe_storage_path(root):
        return
    for folder, pattern in (
        (root, r"(?:latest|\d{8}_\d{6}_\d+)\.txt"),
        (root / "diagnostics", r"[0-9a-f]{32}(?:\.part-\d{6})?\.jsonl"),
    ):
        yield from _ordinary_items(folder, pattern)
    if directory.exists() and policy._safe_storage_path(directory):
        for folder in directory.iterdir():
            item = _recording_item(folder)
            if item is not None:
                yield item


def _ordinary_items(folder, pattern):
    if not folder.exists() or not policy._safe_storage_path(folder):
        return
    for path in folder.iterdir():
        if not re.fullmatch(pattern, path.name):
            continue
        if not policy._safe_storage_path(path) or not path.is_file():
            continue
        try:
            stat = path.stat()
            yield path, (path,), stat.st_mtime, stat.st_size, policy._known_log_time(path)
        except OSError:
            continue


def _recording_item(folder):
    if not policy.RECORDING_ID.fullmatch(folder.name):
        return None
    if not policy._safe_storage_path(folder) or not folder.is_dir():
        return None
    try:
        paths = policy._recording_files(folder)
        if not all(policy._safe_storage_path(path) for path in paths):
            return None
        sizes = [path.stat() for path in paths]
        if sizes:
            return (
                folder,
                paths,
                min(s.st_mtime for s in sizes),
                sum(s.st_size for s in sizes),
                policy._known_log_time(folder / "snimak.jsonl"),
            )
    except OSError:
        return None


def _protected(key, directory):
    identity = policy._path_key(key)
    return identity in policy._RESERVATIONS or policy._is_active(directory, key.name)


def _claim(key, directory):
    identity = policy._path_key(key)
    with policy._RESERVATION_LOCK:
        if _protected(key, directory) or identity in policy._DELETING:
            return False
        policy._DELETING.add(identity)
        return True


def _delete(key, paths, root):
    if not all(policy._safe_storage_path(path) for path in (root, key.parent, key, *paths)):
        return False
    if key.is_dir():
        if not policy._retention_folder_is_safe(key, paths):
            return False
        policy._remove_recording(key, paths)
    else:
        key.unlink()
    return True


class Cleanup:
    def __init__(self, store, budget):
        self.store = store
        self.root = store.directory.parent
        self.budget = budget
        self.free = policy.disk_free(self.root)
        self.low = self.free < policy.LOW_SPACE_BYTES
        if store.storage.get("low_space", False):
            self.low |= self.free < policy.RECOVERY_SPACE_BYTES
        self.removed = 0
        self.failed = False

    def run(self):
        items = sorted(managed_items(self.store.directory), key=lambda item: item[2])
        total = sum(item[3] for item in items)
        attempted = 0
        for key, paths, _age, size, _known in items:
            if self._enough_space(total) or attempted >= policy.MAX_MAINTENANCE_ITEMS:
                break
            if not _claim(key, self.store.directory):
                continue
            attempted += 1
            if self._remove(key, paths):
                total -= size

    def _enough_space(self, total):
        recovered = not self.low or self.free >= policy.RECOVERY_SPACE_BYTES
        return total <= self.budget and recovered

    def _remove(self, key, paths):
        try:
            if not _delete(key, paths, self.root):
                return False
            self.removed += 1
            self.free = policy.disk_free(self.root)
            return True
        except OSError:
            self.failed = True
            return False
        finally:
            with policy._RESERVATION_LOCK:
                policy._DELETING.discard(policy._path_key(key))

    def result(self):
        retained = list(managed_items(self.store.directory))
        known = [item[4] for item in retained if item[4] is not None]
        total = sum(item[3] for item in retained)
        with policy._RESERVATION_LOCK:
            protected = sum(
                item[3] for item in retained if _protected(item[0], self.store.directory)
            )
        low = self.low and self.free < policy.RECOVERY_SPACE_BYTES
        return dict(
            usage_bytes=total,
            budget_bytes=self.budget,
            oldest_at=min(known) if known else None,
            protected_bytes=protected,
            pruned_items=self.removed,
            pruned_total=self.store.storage.get("pruned_total", 0) + self.removed,
            low_space=low,
            free_bytes=self.free,
            state=self._state(total, low),
            temporary_allowance_bytes=protected + 2 * policy.SEGMENT_BYTES,
        )

    def _state(self, total, low):
        if self.failed:
            return "cleanup_failed"
        if low:
            return "low_space"
        return "protected_over_budget" if total > self.budget else "ready"
