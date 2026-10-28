from __future__ import annotations

from queue import Queue
from threading import Event, Thread

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from pogled_assist.diagnostic_recording import RecordingStore
from pogled_assist.tracking.gaze_check_report import GazeCheckReport, identity
from pogled_assist.tracking.gaze_check_store import GazeCheckStore
from pogled_assist.ui import diagnostic_recordings, gaze_check_reports


class SlowIdleQueue(Queue):
    def __init__(self, maxsize):
        super().__init__(maxsize)
        self.waiting = Event()

    def get(self, *args, **kwargs):
        if kwargs.get("block") is False:
            return super().get(*args, **kwargs)
        if self.empty():
            self.waiting.set()
        # Stretch polling so only an actual wakeup can satisfy the shutdown test.
        return super().get(timeout=5)


@pytest.fixture(
    params=[
        (gaze_check_reports, gaze_check_reports.GazeCheckReports, GazeCheckStore),
        (diagnostic_recordings, diagnostic_recordings.DiagnosticRecordings, RecordingStore),
    ],
    ids=["reports", "recordings"],
)
def idle_service(request, qtbot, tmp_path, monkeypatch):
    module, service_type, store_type = request.param
    monkeypatch.setattr(module, "Queue", SlowIdleQueue)
    service = service_type(store_type(tmp_path), QCoreApplication.instance())
    try:
        yield service
    finally:
        service.shutdown()
        if service._worker is not None:
            service._worker.join(timeout=6)
        service.deleteLater()


def test_shutdown_wakes_idle_file_worker(qtbot, idle_service):
    service = idle_service
    service.load()
    qtbot.waitUntil(lambda: not service.loading and service._queue.waiting.is_set())
    service.shutdown()
    qtbot.waitUntil(lambda: not service._worker.is_alive(), timeout=1000)
    service.shutdown()


def report():
    return GazeCheckReport(
        identity(),
        "2026-10-21T13:00:00+02:00",
        "2026-10-21T13:00:01+02:00",
        1,
        "interrupted",
        "Synthetic interruption",
        True,
        {},
        {},
        [],
    )


def test_report_shutdown_drains_full_queue_and_rejects_later_exports(
    qtbot, qapp, tmp_path, monkeypatch
):
    monkeypatch.setattr(gaze_check_reports, "Queue", lambda **_kwargs: Queue(maxsize=1))
    reports = gaze_check_reports.GazeCheckReports(GazeCheckStore(tmp_path / "reports"), qapp)
    entered, release = Event(), Event()
    export = reports.store.export

    def blocked(value, path):
        entered.set()
        assert release.wait(3)
        export(value, path)

    monkeypatch.setattr(reports.store, "export", blocked)
    completed = []
    reports.exported.connect(lambda key, success: completed.append((key, success)))
    first, second, late = [tmp_path / name for name in ("first.zip", "second.zip", "late.zip")]
    releaser = Thread(target=lambda: (reports._stopped.wait(3), release.set()))
    try:
        first_key = reports.export(report(), first)
        assert entered.wait(1)
        second_key = reports.export(report(), second)
        assert reports._queue.full()
        releaser.start()
        reports.shutdown()
        assert not reports._worker.is_alive()
        assert first.exists() and second.exists()
        qtbot.waitUntil(lambda: len(completed) == 2)
        late_key = reports.export(report(), late)
        qtbot.waitUntil(lambda: len(completed) == 3)
        assert completed == [(first_key, True), (second_key, True), (late_key, False)]
        assert not late.exists()
        reports.load()
        assert not reports.loading and reports.history_error
    finally:
        release.set()
        if releaser.ident is not None:
            releaser.join(timeout=3)
        reports.shutdown()
        reports.deleteLater()


def test_recording_shutdown_discards_queued_history_without_waiting_for_export(
    qtbot, qapp, tmp_path, monkeypatch
):
    monkeypatch.setattr(diagnostic_recordings, "Queue", lambda **_kwargs: Queue(maxsize=1))
    recordings = diagnostic_recordings.DiagnosticRecordings(RecordingStore(tmp_path), qapp)
    entered, release = Event(), Event()
    loads, exported = [], []

    def blocked(*_args):
        entered.set()
        assert release.wait(3)

    monkeypatch.setattr(recordings.store, "export", blocked)
    monkeypatch.setattr(recordings.store, "recover_and_load", lambda **kwargs: loads.append(kwargs))
    recordings.exported.connect(lambda *args: exported.append(args))
    try:
        assert recordings.export("a" * 32, tmp_path / "out.zip")
        assert entered.wait(1)
        recordings.load()
        assert recordings._queue.full()
        with monkeypatch.context() as shutdown_patch:
            shutdown_patch.setattr(
                recordings._worker, "join", lambda **_kwargs: pytest.fail("Qt shutdown joined disk")
            )
            recordings.shutdown()
        assert recordings._worker.is_alive()
        assert not recordings._timer.isActive()
        assert not recordings.export("late", tmp_path / "late.zip")
        release.set()
        qtbot.waitUntil(lambda: not recordings._worker.is_alive())
        QCoreApplication.sendPostedEvents(recordings, QEvent.MetaCall)
        assert loads == [] and exported == []
    finally:
        release.set()
        recordings.shutdown()
        if recordings._worker is not None:
            recordings._worker.join(timeout=3)
        recordings.deleteLater()
