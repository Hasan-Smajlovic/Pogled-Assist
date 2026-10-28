"""Application-owned recording lifecycle and bounded background export/history work."""

from __future__ import annotations

import time
from contextlib import suppress
from copy import deepcopy
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Thread

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from .. import diagnostics
from ..diagnostic_recording import RecordingReadError, RecordingStore
from ..logging_setup import recording_writer
from .recording_badge import RecordingIndicator


class DiagnosticRecordings(QObject):
    changed = Signal()
    exported = Signal(str, bool)
    _finished = Signal(object)

    def __init__(self, store: RecordingStore, parent: QObject | None = None, *, writer=None):
        super().__init__(parent)
        self.store = store
        self._writer_source = writer or recording_writer
        self._writer = None
        self.status: dict | None = None
        self.indicator = RecordingIndicator(self)
        self.entries: list[dict] = []
        self.loading = False
        self._reload_pending = False
        self.history_error = False
        self._exporting = False
        self._queue: Queue = Queue(maxsize=4)
        self._stopped = Event()
        self._worker = None
        self.storage = {}
        self.persistence = {}
        self._maintenance_pending = False
        self._next_maintenance = 0.0
        self._recovered = False
        self._finished.connect(self._apply, Qt.QueuedConnection)
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.poll)
        self._timer.start()

    @property
    def busy(self) -> bool:
        return bool(self.status and self.status.get("busy"))

    def start(self, minutes: int, context: dict) -> bool:
        if any((self._stopped.is_set(), self.busy, self.loading, self.history_error)):
            return False
        diagnostics.flush_summaries()
        self._writer = self._writer_source()
        started = self._writer.start_recording(self.store.directory, minutes, context)
        self.poll()
        return started is not None

    def stop(self) -> None:
        diagnostics.flush_summaries()
        if self._writer is not None:
            self._writer.stop_recording()
        self.poll()

    def poll(self) -> None:
        writer = self._writer or self._writer_source()
        if hasattr(writer, "persistence_status"):
            persistence = writer.persistence_status()
            if persistence != self.persistence:
                self.persistence = persistence
                self.indicator.set_persistence(persistence)
                self.changed.emit()
        self._schedule_maintenance()
        if self._writer is None:
            return
        status = self._writer.recording_status()
        was_busy = self.busy
        if status != self.status:
            self.status = status
            self.indicator.set_status(status)
            self.changed.emit()
        if was_busy and not self.busy:
            self.load()

    def _schedule_maintenance(self):
        if not self._recovered or self._maintenance_pending:
            return
        if time.monotonic() < self._next_maintenance:
            return
        self._maintenance_pending = self._submit("maintenance", "", None)
        self._next_maintenance = time.monotonic() + 5

    def set_budget(self, gigabytes: int) -> None:
        self.store.budget_bytes = gigabytes * 1_000_000_000
        self._next_maintenance = 0

    def load(self) -> None:
        if self._stopped.is_set():
            return
        if self.loading:
            self._reload_pending = True
            return
        self.loading = True
        active_id = self.status.get("id") if self.busy else None
        if not self._submit("load", "", active_id):
            self.loading, self.history_error = False, True
        self.changed.emit()

    def export(self, recording_id: str, destination: Path, report=None) -> bool:
        # One export at a time; preserve immutable selected report/path across UI changes.
        if self._stopped.is_set() or self._exporting:
            return False
        if self.busy and self.status["id"] == recording_id:
            return False
        if not self.store.reserve_export(recording_id):
            return False
        self._exporting = self._submit(
            "export", recording_id, (recording_id, destination, deepcopy(report))
        )
        if not self._exporting:
            self.store.release_export(recording_id)
        return self._exporting

    def _submit(self, action, key, value) -> bool:
        try:
            self._queue.put_nowait((action, key, value))
        except Full:
            return False
        if self._worker is None:
            self._worker = Thread(target=self._run, name="diagnostic-packages", daemon=True)
            self._worker.start()
        return True

    def _run(self) -> None:
        while not self._stopped.is_set():
            task = self._queue.get()
            if task is None:
                return
            if self._stopped.is_set():
                if task[0] == "export":
                    self.store.release_export(task[1])
                return
            action, key, _value = task
            success, result = self._execute(task)
            try:
                self._finished.emit((action, key, success, result))
            except RuntimeError:
                return

    def _execute(self, task):
        action, key, value = task
        try:
            return True, self._file_operation(action, value)
        except RecordingReadError:
            return False, "unreadable"
        except Exception:
            return False, None
        finally:
            if action == "export":
                self.store.release_export(key)

    def _file_operation(self, action, value):
        if action == "load":
            return self.store.recover_and_load(active_id=value)
        if action == "maintenance":
            return self.store.maintain()
        return self.store.export(*value)

    def _apply(self, outcome) -> None:
        if self._stopped.is_set():
            return
        action, key, success, result = outcome
        if action == "maintenance":
            self._maintenance_pending = False
            self.storage = result if success else {**self.storage, "state": "unavailable"}
            self.changed.emit()
            return
        if action == "load":
            self._apply_load(success, result)
            return
        self._exporting = False
        if result == "unreadable":
            self.entries = [
                {**entry, "state": "unreadable", "complete": False} if entry["id"] == key else entry
                for entry in self.entries
            ]
            self.changed.emit()
        self.exported.emit(key, success)

    def _apply_load(self, success, result):
        self.loading = False
        self.history_error = not success
        if success:
            self.entries = result
            self._recovered = True
        if self._reload_pending:
            self._reload_pending = False
            self.load()
        self.changed.emit()

    def shutdown(self) -> None:
        self._timer.stop()
        self._stopped.set()
        while True:
            try:
                task = self._queue.get_nowait()
            except Empty:
                break
            if task is not None and task[0] == "export":
                self.store.release_export(task[1])
        # A busy worker observes the stop before taking another queued job.
        with suppress(Full):
            self._queue.put_nowait(None)
        if self._writer is not None:
            diagnostics.flush_summaries()
            self._writer.stop_recording("shutdown")
        # File workers are daemons. Application logging owns its bounded drain;
        # never join an export or a blocked disk from the Qt close callback.
