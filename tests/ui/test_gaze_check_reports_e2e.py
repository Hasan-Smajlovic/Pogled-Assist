from __future__ import annotations

from threading import Event
from zipfile import ZipFile

import pytest
from _clock import freeze_monotonic
from PySide6.QtCore import QRect

from pogled_assist.interaction.mouse_controller import GazeSettings
from pogled_assist.tracking.gaze_check import FixationResult
from pogled_assist.tracking.gaze_check_store import GazeCheckStore
from pogled_assist.ui.gaze_check_reports import GazeCheckReports
from pogled_assist.ui.gaze_check_window import GazeCheckWindow

pytestmark = pytest.mark.e2e


@pytest.fixture
def check(qtbot, monkeypatch, tmp_path, request):
    reports = GazeCheckReports(GazeCheckStore(tmp_path / "results"))
    window = GazeCheckWindow(
        GazeSettings(logging_enabled=getattr(request, "param", True)),
        reports=reports,
        simulated=True,
    )
    qtbot.addWidget(window)
    window.setGeometry(QRect(0, 0, 1280, 720))
    window.show()
    qtbot.wait(1)
    window._timer.stop()
    now = freeze_monotonic(monkeypatch, 10)
    yield window, reports, now
    window.close()
    reports.shutdown()
    reports.deleteLater()


def complete_precision(window, qtbot):
    window._start_precision()
    qtbot.waitUntil(lambda: window._check is not None)
    window._check.results = [
        FixationResult(name, 90, 0.9, 12, 8, True, (x, y)) for name, x, y in window._check.targets
    ]
    window._show_results()


@pytest.mark.parametrize("check", [False, True], indirect=True)
def test_completion_saves_only_with_logging_and_keeps_memory_on_reopen(check, qtbot):
    window, reports, _now = check
    complete_precision(window, qtbot)
    report_id = window._report.id
    if window._settings.logging_enabled:
        qtbot.waitUntil(lambda: reports.states[report_id] == "saved")
        assert reports.store.load()[0].report.id == report_id
    else:
        assert reports.states[report_id] == "memory"
        assert not reports.store.directory.exists()
    window._show_results()  # Rendering must not create another report or emit new measurements.
    window.close()
    assert list(reports.reports) == [report_id]
    reopened = GazeCheckWindow(GazeSettings(), reports=reports)
    qtbot.addWidget(reopened)
    reopened.show()
    reopened._open_history()
    qtbot.waitUntil(lambda: not reports.loading)
    assert reopened._history_list.count() == 1
    reopened._primary_button.click()
    assert reopened._archived
    assert reopened._view_report.id == report_id
    assert reopened._view_report.simulated
    assert not reopened._primary_button.isVisible()


@pytest.mark.parametrize(
    "trigger", ["close", "repeat", "resize", "minimize", "disconnect", "cancel"]
)
def test_interruption_finalizes_once_without_fabricating_misses(check, qtbot, trigger):
    window, reports, now = check
    window._start_precision()
    qtbot.waitUntil(lambda: window._check is not None)
    name, x, y = window._check.targets[0]
    window._check.results = [FixationResult(name, 90, 0.9, 12, 8, True, (x, y))]
    now[0] += 4
    if trigger == "close":
        window.close()
    elif trigger == "repeat":
        window._start_precision()
    elif trigger == "resize":
        window.resize(1200, 700)
    elif trigger == "minimize":
        window.showMinimized()
    elif trigger == "disconnect":
        window.tracking_unavailable()
    else:
        window._test_back_button.click()
    qtbot.waitUntil(lambda: bool(reports.reports))
    stored = next(iter(reports.reports.values()))
    assert stored.state == "interrupted" and stored.reason
    assert stored.precision[0].near is True
    assert [row.state for row in stored.precision[1:]] == ["unmeasured"] * 4
    assert all(row.near is None and row.samples is None for row in stored.precision[1:])
    assert len(reports.reports) == 1
    if trigger == "cancel":
        assert not window._primary_button.isEnabled()
        assert "Ponovi preciznost" in window._result_advice.text()
        assert "govornu tastaturu" not in window._result_advice.text()
        assert len(window._result_map.targets) == 5


def test_repeated_trials_keep_attempt_ids_and_per_group_counts(check, qtbot):
    window, reports, now = check
    complete_precision(window, qtbot)
    report_id = window._report.id
    for _attempt in range(2):
        window._start_trial()
        for index in range(3):
            now[0] = window._trial_ready_at + 2
            window._trial_wrong_selections += index + 1
            window._trial_departures += 1
            window._finish_trial_target(index == 0, now[0])
    saved = reports.reports[report_id]
    assert len(saved.trials) == 2
    assert len({trial.id for trial in saved.trials}) == 2
    assert [row.wrong_selections for row in saved.trials[-1].rows] == [1, 2, 3]
    assert [row.departures for row in saved.trials[-1].rows] == [1, 1, 1]
    assert [row.state for row in saved.trials[-1].rows] == ["insufficient"] * 3
    assert window._trial_attempts.count() == 2
    assert saved.id == report_id


def test_save_failure_is_visible_retry_works_and_export_does_not_change_storage(
    check, qtbot, monkeypatch, tmp_path
):
    from pogled_assist.ui import gaze_check_history

    window, reports, _now = check
    actual_save = reports.store.save

    def fail(_report):
        raise OSError("Synthetic storage failure")

    monkeypatch.setattr(reports.store, "save", fail)
    complete_precision(window, qtbot)
    key = window._report.id
    qtbot.waitUntil(lambda: reports.states[key] == "error")
    assert window._retry_save_button.isVisible()
    destination = tmp_path / "manual.zip"
    monkeypatch.setattr(
        gaze_check_history.QFileDialog, "getSaveFileName", lambda *_a: (str(destination), "")
    )
    window._export_button.click()
    qtbot.waitUntil(lambda: "ZIP je izvezen" in window._export_status.text())
    assert reports.states[key] == "error"
    with ZipFile(destination) as archive:
        assert archive.read("rezultat.json") == reports.reports[key].to_json()
    monkeypatch.setattr(reports.store, "save", actual_save)
    window._retry_save_button.click()
    qtbot.waitUntil(lambda: reports.states[key] == "saved")
    assert not window._retry_save_button.isVisible()


def test_blocked_disk_worker_keeps_qt_responsive_and_older_save_cannot_mark_new_revision_saved(
    check, qtbot, monkeypatch
):
    window, reports, _now = check
    entered, release = Event(), Event()
    newer_entered, newer_release = Event(), Event()
    save = reports.store.save

    def block(value):
        waiting, allowed = (newer_entered, newer_release) if value.trials else (entered, release)
        waiting.set()
        if not allowed.wait(3):
            raise OSError("Synthetic timeout")
        save(value)

    monkeypatch.setattr(reports.store, "save", block)
    try:
        complete_precision(window, qtbot)
        qtbot.waitUntil(entered.is_set)
        window._history_button.click()
        assert window._phase == "history"
        assert reports.loading
        window._repeat_button.click()
        window._start_trial()
        window._test_back_button.click()
        key = window._report.id
        release.set()
        qtbot.waitUntil(newer_entered.is_set)
        qtbot.waitUntil(lambda: not reports.loading)
        # The first save has reached Qt, but the newer trial is still blocked on disk.
        assert reports.states[key] == "saving"
        assert "Čuvam rezultat" in window._storage_label.text()
    finally:
        release.set()
        newer_release.set()
    qtbot.waitUntil(lambda: reports.states[key] == "saved")
    assert reports.store.load()[0].report.trials[-1].state == "interrupted"


def test_export_cancel_failure_and_retry_preserve_result_and_exact_path(
    check, qtbot, monkeypatch, tmp_path
):
    from pogled_assist.ui import gaze_check_history

    window, reports, _now = check
    complete_precision(window, qtbot)
    key = window._report.id
    qtbot.waitUntil(lambda: reports.states[key] == "saved")
    monkeypatch.setattr(gaze_check_history.QFileDialog, "getSaveFileName", lambda *_a: ("", ""))
    window._export_button.click()
    assert window._export_token is None
    destination = tmp_path / "report.txt"
    other = tmp_path / "report.txt.zip"
    other.write_bytes(b"Do not overwrite")
    monkeypatch.setattr(
        gaze_check_history.QFileDialog, "getSaveFileName", lambda *_a: (str(destination), "")
    )
    export = reports.store.export

    def fail(*_args):
        raise OSError("Synthetic export failure")

    monkeypatch.setattr(reports.store, "export", fail)
    window._export_button.click()
    qtbot.waitUntil(lambda: "nije uspio" in window._export_status.text())
    assert reports.states[key] == "saved" and not destination.exists()
    monkeypatch.setattr(reports.store, "export", export)
    window._export_button.click()
    qtbot.waitUntil(lambda: "ZIP je izvezen" in window._export_status.text())
    with ZipFile(destination) as archive:
        assert archive.read("rezultat.json") == reports.reports[key].to_json()
    assert other.read_bytes() == b"Do not overwrite"


def test_finalized_trial_summary_survives_reset_history_return_and_archived_details(check, qtbot):
    window, reports, now = check
    complete_precision(window, qtbot)
    window._start_trial()
    for _index in range(3):
        start = window._trial_ready_at
        for sample in range(100):
            window._trial_coverage.add(start + sample * 0.02)
        window._trial_departures += 1
        now[0] = start + 2
        window._finish_trial_target(True, now[0])
    summary, advice = window._trial_summary.text(), window._result_advice.text()
    key = window._report.id
    window._calibration_button.click()
    assert window._phase == "position"
    window._open_history()
    window._repeat_button.click()
    assert window._trial_summary.text() == summary
    assert window._result_advice.text() == advice
    window._trial_departures = 77
    window._trial_losses = 88
    window._view_report = reports.reports[key]
    window._archived = True
    window._render_report()
    window._details_button.click()
    assert "77" not in window._result_detail.text()
    assert "88" not in window._result_detail.text()
    window._result_tabs.setCurrentIndex(1)
    assert "0 / 0 / 1" in window._trial_detail.text()
    assert all(row.departures == 1 for row in window._view_report.trials[-1].rows)


def test_late_export_status_does_not_attach_to_a_new_report(check, qtbot, monkeypatch, tmp_path):
    from pogled_assist.ui import gaze_check_history

    window, reports, _now = check
    complete_precision(window, qtbot)
    monkeypatch.setattr(
        gaze_check_history.QFileDialog,
        "getSaveFileName",
        lambda *_a: (str(tmp_path / "old.zip"), ""),
    )
    monkeypatch.setattr(reports, "export", lambda *_args: "previous-report-export")
    window._export_button.click()
    assert window._export_status.isVisible()
    complete_precision(window, qtbot)
    reports.exported.emit("previous-report-export", True)
    assert not window._export_status.isVisible()
