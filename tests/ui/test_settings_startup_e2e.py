from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer

from pogled_assist.interaction.mouse_controller import GazeSettings
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.ui.settings_window import SettingsWindow
from pogled_assist.windows import startup_tasks
from pogled_assist.windows.windows_startup import StartupTaskResult


@pytest.mark.e2e
def test_slow_startup_query_keeps_settings_and_qt_heartbeat_responsive(qtbot, monkeypatch):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def query():
        entered.set()
        release.wait(5)
        finished.set()
        return True

    monkeypatch.setattr("pogled_assist.ui.settings_window.is_windows_startup_enabled", query)
    window = SettingsWindow(GazeSettings(), SpeechSettings())
    qtbot.addWidget(window)
    ticks = []
    timer = QTimer(window)
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(True))
    try:
        window.show()
        timer.start()
        qtbot.waitUntil(entered.is_set)
        assert not finished.is_set(), "the startup query must still be waiting off the Qt thread"
        window._gaze_tab_button.click()
        window._gaze_page._gaze_bubble_button.click()
        assert window._stack.currentIndex() == 1
        assert not window._gaze_settings.show_gaze_bubble
        qtbot.waitUntil(lambda: len(ticks) >= 3)
        assert not finished.is_set()
        release.set()
        qtbot.waitUntil(lambda: not window._startup_busy)
        assert window._general_page._startup_checkbox.isChecked()
        assert not window._gaze_settings.show_gaze_bubble
    finally:
        release.set()
        timer.stop()
        qtbot.waitUntil(lambda: not window._startup_busy)


@pytest.mark.e2e
def test_startup_query_does_not_overwrite_newer_choices_and_pending_work_is_bounded(
    qtbot, monkeypatch
):
    entered, release = threading.Event(), threading.Event()
    writes = []

    def query():
        entered.set()
        release.wait(5)
        return True

    def update(enabled, **options):
        writes.append((enabled, options["show_launcher_window"]))
        return StartupTaskResult(enabled, True, "updated")

    monkeypatch.setattr("pogled_assist.ui.settings_window.is_windows_startup_enabled", query)
    monkeypatch.setattr("pogled_assist.ui.settings_window.set_windows_startup_enabled", update)
    window = SettingsWindow(GazeSettings(), SpeechSettings())
    qtbot.addWidget(window)
    updates = []
    window.gaze_settings_changed.connect(updates.append)
    try:
        window.show()
        qtbot.waitUntil(entered.is_set)
        window._general_page._startup_checkbox.click()
        window._general_page._launcher_window_checkbox.click()
        window._general_page._startup_checkbox.click()
        assert writes == []
        window._adjust_dwell_ms(100)
        release.set()
        qtbot.waitUntil(lambda: not window._startup_busy)
        assert writes == [(False, True)]
        assert not window._general_page._startup_checkbox.isChecked()
        assert updates[-1].start_with_windows is False
        assert updates[-1].show_launcher_window is True
        assert updates[-1].dwell_ms == 600
    finally:
        release.set()
        qtbot.waitUntil(lambda: not window._startup_busy)


@pytest.mark.e2e
def test_slow_startup_update_keeps_qt_running_and_preserves_later_gaze_changes(qtbot, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )

    def update(enabled, **_options):
        entered.set()
        release.wait(5)
        return StartupTaskResult(enabled, True, "updated")

    monkeypatch.setattr("pogled_assist.ui.settings_window.set_windows_startup_enabled", update)
    window = SettingsWindow(GazeSettings(), SpeechSettings())
    qtbot.addWidget(window)
    updates = []
    window.gaze_settings_changed.connect(updates.append)
    ticks = []
    timer = QTimer(window)
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(True))
    try:
        window.show()
        qtbot.waitUntil(lambda: not window._startup_busy)
        timer.start()
        window._general_page._startup_checkbox.click()
        qtbot.waitUntil(entered.is_set)
        window._adjust_selection_pause(100)
        qtbot.waitUntil(lambda: len(ticks) >= 3)
        assert window._startup_busy
        release.set()
        qtbot.waitUntil(lambda: not window._startup_busy)
        assert updates[-1].start_with_windows is True
        assert updates[-1].selection_pause_ms == 600
    finally:
        release.set()
        timer.stop()
        qtbot.waitUntil(lambda: not window._startup_busy)


@pytest.mark.e2e
def test_closed_settings_ignores_the_late_startup_query(qtbot, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def query():
        entered.set()
        release.wait(5)
        return True

    monkeypatch.setattr("pogled_assist.ui.settings_window.is_windows_startup_enabled", query)
    window = SettingsWindow(GazeSettings(), SpeechSettings())
    qtbot.addWidget(window)
    updates = []
    window.gaze_settings_changed.connect(updates.append)
    try:
        window.show()
        qtbot.waitUntil(entered.is_set)
        window.close()
        release.set()
        qtbot.waitUntil(lambda: not window._startup_busy)
        assert not window._gaze_settings.start_with_windows
        assert not window._general_page._startup_checkbox.isChecked()
        assert updates == []
    finally:
        release.set()
        qtbot.waitUntil(lambda: not window._startup_busy)


@pytest.mark.e2e
def test_closed_settings_cancels_a_startup_query_waiting_for_another_window(qtbot, monkeypatch):
    from pogled_assist.ui import settings_window

    calls = []

    def query():
        calls.append(True)
        return False

    monkeypatch.setattr(settings_window, "is_windows_startup_enabled", query)
    with startup_tasks._task_lock:
        window = SettingsWindow(GazeSettings(), SpeechSettings())
        qtbot.addWidget(window)
        window.show()
        window.close()
        qtbot.waitUntil(lambda: not window._startup_busy)
        assert calls == []


@pytest.mark.e2e
def test_deleted_settings_preserves_last_startup_write_before_reopened_query(qtbot, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    actual, writes, reads = [False], [], []

    def query():
        reads.append(actual[0])
        return actual[0]

    def update(enabled, **_options):
        writes.append(enabled)
        if enabled:
            entered.set()
            release.wait(5)
        actual[0] = enabled
        return StartupTaskResult(enabled, True, "updated")

    monkeypatch.setattr("pogled_assist.ui.settings_window.is_windows_startup_enabled", query)
    monkeypatch.setattr("pogled_assist.ui.settings_window.set_windows_startup_enabled", update)
    window = SettingsWindow(GazeSettings(), SpeechSettings())
    tasks = window._startup_tasks
    window.show()
    try:
        qtbot.waitUntil(lambda: not window._startup_busy)
        window._general_page._startup_checkbox.click()
        qtbot.waitUntil(entered.is_set)
        window._general_page._startup_checkbox.click()
        assert window._startup_desired_enabled is False
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        reopened = SettingsWindow(GazeSettings(), SpeechSettings())
        qtbot.addWidget(reopened)
        reopened.show()
        assert reads == [False]
        release.set()
        qtbot.waitUntil(lambda: not reopened._startup_busy)
        assert writes == [True, False]
        assert reads == [False, False]
        assert not actual[0]
        assert not reopened._general_page._startup_checkbox.isChecked()
    finally:
        release.set()
        qtbot.waitUntil(lambda: not tasks._running)


@pytest.mark.e2e
def test_waiting_startup_write_finishes_before_a_reopened_window_can_query(qtbot, monkeypatch):
    from pogled_assist.ui import settings_window

    actual, writes, reads = [False], [], []

    def query():
        reads.append(actual[0])
        return actual[0]

    def update(enabled, **_options):
        writes.append(enabled)
        actual[0] = enabled
        return StartupTaskResult(enabled, True, "updated")

    monkeypatch.setattr(settings_window, "is_windows_startup_enabled", query)
    monkeypatch.setattr(settings_window, "set_windows_startup_enabled", update)
    with startup_tasks._task_lock:
        window = SettingsWindow(GazeSettings(), SpeechSettings())
        window.show()
        window._general_page._startup_checkbox.click()
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        reopened = SettingsWindow(GazeSettings(), SpeechSettings())
        qtbot.addWidget(reopened)
        reopened.show()
        assert writes == reads == []
    qtbot.waitUntil(lambda: not reopened._startup_busy)
    assert writes == [True]
    assert reads == [True]
    assert reopened._general_page._startup_checkbox.isChecked()


@pytest.mark.e2e
@pytest.mark.parametrize("saved,actual", [(False, True), (True, True), (True, False)])
def test_launcher_change_during_initial_query_uses_actual_windows_state(
    qtbot, monkeypatch, saved, actual
):
    entered, release = threading.Event(), threading.Event()
    writes = []

    def query():
        entered.set()
        release.wait(5)
        return actual

    def update(enabled, **options):
        writes.append((enabled, options["show_launcher_window"]))
        return StartupTaskResult(enabled, True, "updated")

    monkeypatch.setattr("pogled_assist.ui.settings_window.is_windows_startup_enabled", query)
    monkeypatch.setattr("pogled_assist.ui.settings_window.set_windows_startup_enabled", update)
    window = SettingsWindow(GazeSettings(start_with_windows=saved), SpeechSettings())
    qtbot.addWidget(window)
    window.show()
    try:
        qtbot.waitUntil(entered.is_set)
        window._general_page._launcher_window_checkbox.click()
        release.set()
        qtbot.waitUntil(lambda: not window._startup_busy)
        assert writes == ([(True, True)] if actual else [])
        assert window._gaze_settings.start_with_windows is actual
        assert window._gaze_settings.show_launcher_window
    finally:
        release.set()
        qtbot.waitUntil(lambda: not window._startup_busy)


@pytest.mark.e2e
def test_pending_startup_choice_stays_checked_when_other_settings_refresh(qtbot, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )

    def update(enabled, **_options):
        entered.set()
        release.wait(5)
        return StartupTaskResult(enabled, True, "updated")

    monkeypatch.setattr("pogled_assist.ui.settings_window.set_windows_startup_enabled", update)
    window = SettingsWindow(GazeSettings(), SpeechSettings())
    qtbot.addWidget(window)
    window.show()
    try:
        qtbot.waitUntil(lambda: not window._startup_busy)
        window._general_page._startup_checkbox.click()
        qtbot.waitUntil(entered.is_set)
        window._adjust_dwell_ms(100)
        assert window._general_page._startup_checkbox.isChecked()
        release.set()
        qtbot.waitUntil(lambda: not window._startup_busy)
        assert window._gaze_settings.start_with_windows
    finally:
        release.set()
        qtbot.waitUntil(lambda: not window._startup_busy)


@pytest.mark.e2e
def test_settings_gaze_controls_remain_usable_during_startup_query(qtbot, monkeypatch):
    from pogled_assist.ui import settings_window

    entered, release = threading.Event(), threading.Event()
    now = [10.0]

    def query():
        entered.set()
        release.wait(5)
        return False

    monkeypatch.setattr(settings_window, "is_windows_startup_enabled", query)
    monkeypatch.setattr(settings_window, "time", SimpleNamespace(monotonic=lambda: now[0]))
    window = settings_window.SettingsWindow(
        GazeSettings(selection_pause_ms=100, dwell_ms=150), SpeechSettings()
    )
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    try:
        qtbot.waitUntil(entered.is_set)
        window._gaze_tab_button.click()
        qtbot.wait(1)
        target = window._gaze_page._gaze_bubble_button
        center = target.mapToGlobal(target.rect().center())
        for stamp in (10.0, 10.1, 10.251):
            now[0] = stamp
            window.handle_gaze(center)
        assert not window._gaze_settings.show_gaze_bubble
        assert window._startup_busy
        release.set()
        qtbot.waitUntil(lambda: not window._startup_busy)
        assert not window._gaze_settings.show_gaze_bubble
    finally:
        release.set()
        qtbot.waitUntil(lambda: not window._startup_busy)
