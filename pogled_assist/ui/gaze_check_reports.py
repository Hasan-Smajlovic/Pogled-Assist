"""Application-lifetime report memory and one serial, non-Qt file worker."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Thread

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from ..tracking.gaze_check_report import GazeCheckReport, identity
from ..tracking.gaze_check_store import GazeCheckStore, StoredReport


class GazeCheckReports(QObject):
    changed = Signal()
    exported = Signal(str, bool)
    _finished = Signal(object)

    def __init__(self, store: GazeCheckStore, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.reports: dict[str, GazeCheckReport] = {}
        self.states: dict[str, str] = {}
        self.unreadable: list[StoredReport] = []
        self.history_error = False
        self.loading = False
        self._revisions: dict[str, int] = {}
        self._queue: Queue = Queue(maxsize=128)
        self._finished.connect(self._apply, Qt.QueuedConnection)
        self._worker: Thread | None = None
        self._stopped = Event()
        stopped = self._stopped
        self.destroyed.connect(stopped.set)

    def record(self, report: GazeCheckReport, *, auto_save: bool) -> None:
        self.reports[report.id] = deepcopy(report)
        self._revisions[report.id] = self._revisions.get(report.id, 0) + 1
        self.states[report.id] = "saving" if auto_save else "memory"
        if auto_save and not self._submit(
            "save", report.id, self._revisions[report.id], deepcopy(report)
        ):
            self.states[report.id] = "error"
        self.changed.emit()

    def shutdown(self) -> None:
        self._stopped.set()
        if self._worker is not None:
            self._worker.join(timeout=2)

    def retry(self, report_id: str) -> None:
        self.record(self.reports[report_id], auto_save=True)

    def load(self) -> None:
        if self.loading:
            return
        self.loading = True
        self.history_error = False
        if not self._submit("load", "", 0, None):
            self.loading = False
            self.history_error = True
        self.changed.emit()

    def export(self, report: GazeCheckReport, path: Path) -> str:
        token = identity()
        if not self._submit("export", token, 0, (deepcopy(report), path)):
            QTimer.singleShot(0, lambda: self.exported.emit(token, False))
        return token

    def _submit(self, action, key, revision, value) -> bool:
        try:
            self._queue.put_nowait((action, key, revision, value))
        except Full:
            return False
        if self._worker is None:
            self._worker = Thread(target=self._run, name="gaze-check-reports", daemon=True)
            self._worker.start()
        return True

    def _run(self) -> None:
        while True:
            try:
                task = self._queue.get(timeout=0.2)
            except Empty:
                if self._stopped.is_set():
                    return
                continue
            action, key, revision, value = task
            try:
                result = None
                if action == "save":
                    self.store.save(value)
                    result = self.store.load()
                elif action == "load":
                    result = self.store.load()
                else:
                    self.store.export(*value)
                success = True
            except Exception:
                result, success = None, False
            try:
                self._finished.emit((action, key, revision, success, result))
            except RuntimeError:
                self._stopped.set()

    def _apply(self, outcome) -> None:
        action, key, revision, success, entries = outcome
        if action == "export":
            self.exported.emit(key, success)
            return
        if action == "save" and self._revisions.get(key) == revision:
            self.states[key] = "saved" if success else "error"
        if action == "load":
            self.loading = False
            self.history_error = not success
        if entries is not None:
            disk_ids = {entry.key for entry in entries if entry.report is not None}
            for report_id, state in list(self.states.items()):
                if state == "saved" and report_id not in disk_ids:
                    self.states[report_id] = "memory"
            for entry in entries:
                if entry.report is not None and entry.key not in self.reports:
                    self.reports[entry.key] = entry.report
                    self.states[entry.key] = "saved"
            self.unreadable = [entry for entry in entries if entry.report is None]
        self.changed.emit()
