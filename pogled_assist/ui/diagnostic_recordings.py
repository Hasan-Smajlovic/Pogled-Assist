"""Application-owned recording lifecycle and bounded background export/history work."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Thread

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from .. import diagnostics
from ..diagnostic_recording import RecordingReadError, RecordingStore
from ..logging_setup import recording_writer


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
        self.entries: list[dict] = []
        self.loading = False
        self.history_error = False
        self._exporting = False
        self._queue: Queue = Queue(maxsize=4)
        self._stopped = Event()
        self._worker = None
        self._finished.connect(self._apply, Qt.QueuedConnection)
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.poll)
        self._timer.start()

    @property
    def busy(self) -> bool:
        return bool(self.status and self.status.get("busy"))

    def start(self, minutes: int, context: dict) -> bool:
        if self._stopped.is_set() or self.busy or self.loading or self.history_error:
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
        if self._writer is None:
            return
        status = self._writer.recording_status()
        was_busy = self.busy
        if status != self.status:
            self.status = status
            self.changed.emit()
        if was_busy and not self.busy:
            self.load()

    def load(self) -> None:
        if self.loading or self._stopped.is_set():
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
        self._exporting = self._submit(
            "export", recording_id, (recording_id, destination, deepcopy(report))
        )
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
            try:
                action, key, value = self._queue.get(timeout=0.2)
            except Empty:
                continue
            try:
                result = (
                    self.store.recover_and_load(active_id=value)
                    if action == "load"
                    else self.store.export(*value)
                )
                success = True
            except RecordingReadError:
                result, success = "unreadable", False
            except Exception:
                result, success = None, False
            try:
                self._finished.emit((action, key, success, result))
            except RuntimeError:
                return

    def _apply(self, outcome) -> None:
        if self._stopped.is_set():
            return
        action, key, success, result = outcome
        if action == "load":
            self.loading = False
            self.history_error = not success
            if success:
                self.entries = result
            self.changed.emit()
        else:
            self._exporting = False
            if result == "unreadable":
                self.entries = [
                    {**entry, "state": "unreadable", "complete": False}
                    if entry["id"] == key
                    else entry
                    for entry in self.entries
                ]
                self.changed.emit()
            self.exported.emit(key, success)

    def shutdown(self) -> None:
        self._timer.stop()
        self._stopped.set()
        if self._writer is not None:
            diagnostics.flush_summaries()
            self._writer.stop_recording("shutdown")
        # File workers are daemons. Application logging owns its bounded drain;
        # never join an export or a blocked disk from the Qt close callback.
