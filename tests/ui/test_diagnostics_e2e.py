from __future__ import annotations

import json
from threading import Event
from zipfile import ZipFile

import pytest
from _hotbar_fixtures import hotbar_gaze as hotbar_gaze

from pogled_assist import build_info
from pogled_assist.diagnostic_recording import RecordingStore, recording_context
from pogled_assist.log_transport import LogWriter
from pogled_assist.tracking.gaze_check_report import GazeCheckReport, identity
from pogled_assist.tracking.gaze_check_store import GazeCheckStore
from pogled_assist.ui.diagnostic_recordings import DiagnosticRecordings
from pogled_assist.ui.diagnostics_window import DiagnosticsWindow
from pogled_assist.ui.gaze_check_reports import GazeCheckReports

pytestmark = pytest.mark.e2e


@pytest.fixture
def recording_ui(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(
        build_info,
        "_identity",
        {"app_version": "0.1.0", "build_revision": "d" * 40, "build_dirty": True},
    )
    writer = LogWriter()
    recordings = DiagnosticRecordings(
        RecordingStore(tmp_path / "recordings"), writer=lambda: writer
    )
    reports = GazeCheckReports(GazeCheckStore(tmp_path / "results"))
    context = recording_context(
        {"eye_tracking_policy": "both", "selection_pause_ms": 250, "dwell_ms": 850},
        {},
        simulated=True,
    )
    window = DiagnosticsWindow(recordings, reports, lambda: context, logging_enabled=lambda: False)
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    qtbot.waitUntil(lambda: not recordings.loading)
    yield window, recordings, reports, writer, context
    window.close()
    recordings.shutdown()
    reports.shutdown()
    assert writer.stop()


def test_window_close_keeps_recording_active_and_history_survives_restart(recording_ui, qtbot):
    window, recordings, reports, writer, context = recording_ui
    assert window._minutes == 2 and window._durations.checkedId() == 2
    window._durations.button(5).click()
    window._primary.click()
    assert recordings.busy
    assert all(not button.isEnabled() for button in window._durations.buttons())
    key = recordings.status["id"]
    window.close()
    writer.event("after_window_closed", {"x": 0.25}, trace=True)
    assert writer.recording_status()["busy"]
    reopened = DiagnosticsWindow(
        recordings, reports, lambda: context, logging_enabled=lambda: False
    )
    qtbot.addWidget(reopened)
    reopened.show()
    reopened._primary.click()
    qtbot.waitUntil(lambda: not recordings.busy and bool(recordings.entries))
    assert reopened._tabs.currentIndex() == 1
    assert recordings.entries[0]["id"] == key
    assert recordings.store.inspect(key)["analysis"]["events"]["after_window_closed"] == 1
    restarted = DiagnosticRecordings(RecordingStore(recordings.store.directory))
    restarted.load()
    qtbot.waitUntil(lambda: not restarted.loading)
    assert restarted.entries[0]["complete"]
    restarted.shutdown()


def test_optional_report_export_exact_path_cancel_failure_and_retry(
    recording_ui, qtbot, monkeypatch, tmp_path
):
    from pogled_assist.ui import diagnostics_window as module

    window, recordings, reports, _writer, context = recording_ui
    report = GazeCheckReport(
        identity(),
        "2026-10-21T13:00:00+02:00",
        "2026-10-21T13:00:01+02:00",
        1,
        "interrupted",
        "Synthetic interruption",
        True,
        {"eye_tracking_policy": "any"},
        {},
        [],
    )
    reports.record(report, auto_save=False)
    assert window._check.currentData() is None
    assert "Prekinuto" in window._check.itemText(1) and "SIMULACIJA" in window._check.itemText(1)
    recordings.start(1, context)
    recordings.stop()
    qtbot.waitUntil(lambda: not recordings.busy and bool(recordings.entries))
    window._tabs.setCurrentIndex(1)
    window._check.setCurrentIndex(1)
    monkeypatch.setattr(module.QFileDialog, "getSaveFileName", lambda *_args: ("", ""))
    window._primary.click()
    assert not recordings._exporting
    destination = tmp_path / "native.chosen"
    monkeypatch.setattr(
        module.QFileDialog, "getSaveFileName", lambda *_args: (str(destination), "")
    )
    export = recordings.store.export
    monkeypatch.setattr(
        recordings.store,
        "export",
        lambda *_args: (_ for _ in ()).throw(OSError("Synthetic failure")),
    )
    window._primary.click()
    qtbot.waitUntil(lambda: "nije uspio" in window._status.text())
    monkeypatch.setattr(recordings.store, "export", export)
    window._primary.click()
    qtbot.waitUntil(lambda: "ZIP je izvezen" in window._status.text())
    with ZipFile(destination) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["selected_gaze_check"]["id"] == report.id
    assert reports.states[report.id] == "memory"
    assert not destination.with_suffix(".zip").exists()

    key = recordings.entries[0]["id"]
    source = recordings.store.directory / key / "snimak.jsonl"
    with source.open("a", encoding="utf-8") as output:
        output.write('{"schema_version":1,"session_id":"mixed","event":"session_end","data":{}}\n')
    window._primary.click()
    qtbot.waitUntil(lambda: recordings.entries[0]["state"] == "unreadable")
    assert "nije čitljiv" in window._detail.text()
    assert not window._primary.isEnabled()


def test_blocked_export_and_shutdown_leave_qt_responsive(
    recording_ui, qtbot, monkeypatch, tmp_path
):
    _window, recordings, _reports, _writer, context = recording_ui
    recordings.start(1, context)
    recordings.stop()
    qtbot.waitUntil(lambda: not recordings.busy and bool(recordings.entries))
    entered, release = Event(), Event()
    original = recordings.store.export

    def blocked(*args):
        entered.set()
        release.wait(3)
        original(*args)

    monkeypatch.setattr(recordings.store, "export", blocked)
    recordings.export(recordings.entries[0]["id"], tmp_path / "background.zip")
    try:
        assert entered.wait(1)
        from PySide6.QtCore import QTimer

        delivered = []
        QTimer.singleShot(0, lambda: delivered.append(True))
        qtbot.waitUntil(lambda: bool(delivered), timeout=500)
        recordings.shutdown()
        assert recordings._stopped.is_set()
    finally:
        release.set()


def test_settings_and_check_shortcuts_preserve_input_suspension_and_result(
    hotbar_gaze, qtbot, monkeypatch
):
    from pogled_assist import toolbar

    hotbar, controller, _feed, _actions, _progress = hotbar_gaze
    # Use the existing Settings fixture's safe startup and release services.
    monkeypatch.setattr(
        toolbar.SettingsWindow, "_sync_startup_setting_from_windows", lambda _self: None
    )
    hotbar._open_settings()
    settings = hotbar._settings_window
    settings._general_page._diagnostics_button.click()
    assert hotbar._diagnostics_window is not None and controller._input_suspended
    assert not settings.isVisible()
    hotbar._diagnostics_window.close()
    assert not controller._input_suspended and settings.isVisible()
    hotbar._open_gaze_check()
    check = hotbar._gaze_check_window
    check._start_precision()
    check._request_diagnostics()
    assert hotbar._diagnostics_window is None
    check._stop_test()
    report = check._view_report
    check._request_diagnostics()
    assert hotbar._diagnostics_window is not None and controller._input_suspended
    assert not check._timer.isActive() and not check.isVisible()
    assert not hotbar._gaze._check_active
    hotbar._diagnostics_window.close()
    assert check._view_report is report and check._phase == "results"
    assert controller._input_suspended and check._timer.isActive()
    check.close()
    assert not controller._input_suspended


def test_recording_badges_preserve_targets_and_do_not_intercept_input(hotbar_gaze, qtbot):
    from pogled_assist.interaction.mouse_controller import SETTINGS

    hotbar, _controller, _feed, _actions, _progress = hotbar_gaze
    hotbar._open_speech()
    qtbot.wait(1)
    speech = hotbar._speech_window
    button = hotbar._buttons[SETTINGS]
    geometry = button.geometry()
    targets = {action: widget.geometry() for action, widget in speech._action_buttons.items()}
    status = {"busy": True, "remaining_seconds": 119, "state": "recording"}
    hotbar._diagnostic_recordings.status = status
    hotbar._recording_changed()
    from PySide6.QtCore import Qt

    for badge in (hotbar._recording_badge, speech._recording_badge):
        assert badge.isVisible()
        assert badge.testAttribute(Qt.WA_TransparentForMouseEvents)
        assert badge.focusPolicy() == Qt.NoFocus
        assert badge.parentWidget().rect().contains(badge.geometry())
    assert speech._recording_badge.text() == "● Snimanje dijagnostike · 01:59"
    assert speech._recording_badge.fontMetrics().horizontalAdvance(
        speech._recording_badge.text()
    ) <= speech._recording_badge.contentsRect().width()
    assert button.geometry() == geometry
    assert targets == {
        action: widget.geometry() for action, widget in speech._action_buttons.items()
    }
    hotbar._diagnostic_recordings.status = None
    hotbar._recording_changed()
    assert hotbar._recording_badge.isHidden() and speech._recording_badge.isHidden()


def test_recording_indicator_waits_for_writer_and_shares_confirmation_deadline(
    recording_ui, qtbot, monkeypatch
):
    window, recordings, reports, writer, context = recording_ui
    entered, release = Event(), Event()
    finish = writer._finish_recording

    def blocked_finish():
        entered.set()
        release.wait(3)
        finish()

    monkeypatch.setattr(writer, "_finish_recording", blocked_finish)
    assert recordings.indicator._confirmation.interval() == 5000
    window._primary.click()
    qtbot.waitUntil(lambda: "Snimanje dijagnostike" in window._recording_badge.text())
    window.close()
    assert recordings.busy
    reopened = DiagnosticsWindow(
        recordings, reports, lambda: context, logging_enabled=lambda: False
    )
    qtbot.addWidget(reopened)
    reopened.show()
    assert reopened._recording_badge.text() == window._recording_badge.text()
    try:
        recordings.stop()
        qtbot.waitUntil(entered.is_set)
        recordings.poll()
        assert recordings.busy
        assert "Završavam snimak…" in reopened._recording_badge.text()
        assert "sačuvan" not in reopened._recording_badge.text()
    finally:
        release.set()
    qtbot.waitUntil(lambda: "Snimak je sačuvan" in reopened._recording_badge.text())
    from pogled_assist.ui.recording_badge import RecordingBadge

    remaining = recordings.indicator._confirmation.remainingTime()
    late = RecordingBadge(reopened)
    late.bind_indicator(recordings.indicator)
    assert late.text() == reopened._recording_badge.text()
    assert 0 < recordings.indicator._confirmation.remainingTime() <= remaining
    recordings.indicator._confirmation.setInterval(10)
    qtbot.waitUntil(late.isHidden)
    assert reopened._recording_badge.isHidden() and window._recording_badge.isHidden()
    recordings.changed.emit()
    recordings.indicator.set_status(recordings.status)
    assert late.isHidden()


@pytest.mark.parametrize("reason", ["size", "shutdown"])
def test_partial_recording_never_shows_saved_confirmation(recording_ui, qtbot, reason):
    window, recordings, _reports, writer, context = recording_ui
    recordings.start(1, context)
    writer.stop_recording(reason)
    qtbot.waitUntil(lambda: not recordings.busy and not recordings.loading)
    assert "Snimak nije potpun" in window._recording_badge.text()
    assert not recordings.indicator._confirmation.isActive()
    assert recordings.start(1, context)
    assert "Snimanje dijagnostike" in window._recording_badge.text()
    recordings.stop()
    qtbot.waitUntil(lambda: not recordings.busy)


def test_recording_save_failure_keeps_warning_instead_of_success(recording_ui, qtbot, monkeypatch):
    from pogled_assist.diagnostic_recording import RecordingSink

    window, recordings, _reports, _writer, context = recording_ui
    write = RecordingSink.write

    def fail_footer(self, *args, **kwargs):
        if kwargs.get("footer"):
            raise OSError("Synthetic footer write failure")
        return write(self, *args, **kwargs)

    monkeypatch.setattr(RecordingSink, "write", fail_footer)
    recordings.start(1, context)
    recordings.stop()
    qtbot.waitUntil(lambda: not recordings.busy)
    assert "Greška čuvanja snimka" in window._recording_badge.text()
    assert not recordings.indicator._confirmation.isActive()
    recordings.changed.emit()
    assert "Greška čuvanja snimka" in window._recording_badge.text()


def test_new_windows_and_speech_dialogs_show_current_recording(hotbar_gaze, qtbot, monkeypatch):
    from PySide6.QtCore import Qt

    from pogled_assist import toolbar

    hotbar, _controller, _feed, _actions, _progress = hotbar_gaze
    hotbar._diagnostic_recordings.status = {
        "id": "synthetic-recording",
        "busy": True,
        "state": "recording",
        "remaining_seconds": 101.2,
    }
    hotbar._recording_changed()
    hotbar._show_keyboard_sidebar()
    hotbar._show_controller_sidebar()
    hotbar._open_speech()
    speech = hotbar._speech_window
    speech._open_letter_dialog(0)
    qtbot.wait(1)
    letter_targets = {
        action: speech._action_buttons[action].geometry() for action in speech._dialogs.letter_actions
    }
    badges = [
        hotbar._keyboard_window._recording_badge,
        hotbar._controller_window._recording_badge,
        speech._recording_badge,
        *speech._dialogs.recording_badges,
    ]
    for badge in badges:
        assert "Snimanje dijagnostike · 01:42" in badge.text()
        assert badge.testAttribute(Qt.WA_TransparentForMouseEvents)
        assert badge.focusPolicy() == Qt.NoFocus
    hotbar._diagnostic_recordings.status["state"] = "finishing"
    hotbar._recording_changed()
    qtbot.wait(1)
    assert letter_targets == {
        action: speech._action_buttons[action].geometry() for action in speech._dialogs.letter_actions
    }
    speech._close_dialog()
    monkeypatch.setattr(toolbar.SettingsWindow, "_sync_startup_setting_from_windows", lambda _: None)
    hotbar._open_settings()
    assert "Završavam snimak…" in hotbar._settings_window._recording_badge.text()
    hotbar._open_gaze_check()
    check = hotbar._gaze_check_window
    assert "Završavam snimak…" in check._recording_badge.text()
    check._start_free()
    qtbot.wait(1)
    assert check._test_recording_badge.isVisible()
    geometry = check._test_controls.geometry()
    hotbar._diagnostic_recordings.status = {
        "id": "synthetic-recording",
        "busy": False,
        "state": "error",
        "complete": False,
    }
    hotbar._recording_changed()
    qtbot.wait(1)
    assert "Greška čuvanja snimka" in check._test_recording_badge.text()
    assert check._test_controls.geometry() == geometry
    assert check._test_controls.height() == 168
    assert not hotbar._diagnostic_recordings.indicator._confirmation.isActive()
