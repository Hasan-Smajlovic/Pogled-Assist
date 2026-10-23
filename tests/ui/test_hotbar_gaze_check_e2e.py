from __future__ import annotations

import pytest
from _hotbar_fixtures import hotbar_gaze as hotbar_gaze
from _ui_fakes import FakeHotbarInput
from PySide6.QtCore import QPoint


@pytest.mark.e2e
def test_opening_check_by_gaze_stops_the_same_pointer_sample(hotbar_gaze, qtbot, monkeypatch):
    from pogled_assist.ui import settings_window

    monkeypatch.setattr(settings_window, "is_windows_startup_enabled", lambda: False)
    hotbar, controller, feed, _actions, _progress = hotbar_gaze
    controller._input = FakeHotbarInput()
    controller._pointer_movement_enabled = True
    feed(QPoint(600, 500), 0)
    assert controller._input.moves  # Exercise the real pointer path, not simulator suppression.
    hotbar._open_settings()
    settings = hotbar._settings_window
    settings._select_tab(1)
    settings._gaze_page.show_tab(1)
    qtbot.wait(1)
    button = settings._gaze_page._gaze_check_button
    point = button.mapToGlobal(button.rect().center())
    feed(point, 100)
    feed(point, 600)
    assert hotbar._gaze_check_window is None
    controller._input.moves.clear()
    feed(point, 1200)
    assert hotbar._gaze_check_window is not None
    assert controller._input_suspended
    assert controller._input.moves == []


@pytest.mark.e2e
def test_gaze_check_suspends_all_input_and_preserves_speech_and_settings(
    hotbar_gaze, qtbot, monkeypatch
):
    from pogled_assist.tracking.status import TrackingState, TrackingStatus
    from pogled_assist.ui import settings_window

    monkeypatch.setattr(settings_window, "is_windows_startup_enabled", lambda: False)
    hotbar, controller, feed, actions, _progress = hotbar_gaze
    hotbar._open_speech()
    hotbar._speech_window._input.setText("Synthetic test message")
    original_message = hotbar._speech_window._input.text()
    hotbar._open_settings()
    settings = hotbar._settings_window
    settings._gaze_page._gaze_check_button.click()
    check = hotbar._gaze_check_window
    qtbot.wait(1)
    assert check.isVisible()
    assert controller._input_suspended
    assert not settings.isVisible()
    positions = []
    controller.gaze_position_changed.connect(positions.append)
    for at in (0, 500, 1100, 3000):
        feed(QPoint(500, 400), at)
    assert positions == actions == []
    check._start_trial()
    hotbar._gaze.tracking_status_changed.emit(TrackingStatus(TrackingState.RETRYING))
    assert check._phase == "position"
    check.close()
    assert hotbar._gaze_check_window is None
    assert not controller._input_suspended
    assert settings.isVisible()
    assert hotbar._speech_window._input.text() == original_message
    feed(QPoint(500, 400), 3100)
    assert positions
    assert actions == []


@pytest.mark.e2e
def test_gaze_check_calibration_handoff_keeps_pause_and_shutdown_closes_check(
    hotbar_gaze, qtbot, monkeypatch
):
    from pogled_assist import toolbar
    from pogled_assist.ui import settings_window

    monkeypatch.setattr(settings_window, "is_windows_startup_enabled", lambda: False)
    requests = []
    monkeypatch.setattr(
        toolbar, "launch_tobii_settings", lambda: requests.append(True) or "Requested"
    )
    hotbar, controller, _feed, _actions, _progress = hotbar_gaze
    hotbar._open_settings()
    settings = hotbar._settings_window
    settings._gaze_page._gaze_check_button.click()
    check = hotbar._gaze_check_window
    check._calibration_button.click()
    qtbot.wait(1)
    assert requests == [True]
    assert controller._input_suspended
    assert check.isMinimized()
    hotbar._open_settings()
    assert not check.isMinimized()
    hotbar.close()
    assert hotbar._gaze_check_window is None
    assert not settings.isVisible()


@pytest.mark.e2e
@pytest.mark.parametrize("launch_fails", [False, True])
def test_gaze_check_settings_feedback_keeps_one_actionable_profile_route(
    hotbar_gaze, qtbot, monkeypatch, launch_fails
):
    from pogled_assist import toolbar
    from pogled_assist.ui import settings_window

    def launch():
        if launch_fails:
            raise RuntimeError("Synthetic launch failure")
        return "Otvaranje Tobii postavki je zatraženo."

    monkeypatch.setattr(settings_window, "is_windows_startup_enabled", lambda: False)
    monkeypatch.setattr(toolbar, "launch_tobii_settings", launch)
    hotbar, controller, _feed, _actions, _progress = hotbar_gaze
    hotbar._open_settings()
    hotbar._settings_window._gaze_page._gaze_check_button.click()
    check = hotbar._gaze_check_window
    check._calibration_button.click()
    qtbot.wait(1)
    assert controller._input_suspended
    assert check._notice.text().count("Test and recalibrate") == 1
    assert "> Recalibrate" in check._notice.text()
    assert "profil korisnika" in check._notice.text()
    if launch_fails:
        assert not check.isMinimized()
        assert "pored sata" in check._notice.text()
    else:
        assert check.isMinimized()


@pytest.mark.e2e
def test_history_and_native_export_keep_all_normal_gaze_input_suspended(
    hotbar_gaze, qtbot, monkeypatch, tmp_path
):
    from pogled_assist.ui import gaze_check_history

    hotbar, controller, feed, actions, _progress = hotbar_gaze
    hotbar._open_gaze_check()
    check = hotbar._gaze_check_window
    check._start_trial()
    check._test_back_button.click()
    check._history_button.click()
    qtbot.waitUntil(lambda: not check._reports.loading)
    assert controller._input_suspended
    check._primary_button.click()
    assert check._archived
    delivered = []
    controller.gaze_position_changed.connect(delivered.append)

    def save_dialog(*_args):
        assert controller._input_suspended
        for at in (100, 600, 1200, 3000):
            feed(QPoint(500, 400), at)
        assert delivered == actions == []
        return str(tmp_path / "caregiver.zip"), ""

    monkeypatch.setattr(gaze_check_history.QFileDialog, "getSaveFileName", save_dialog)
    check._export_button.click()
    qtbot.waitUntil(lambda: "ZIP je izvezen" in check._export_status.text())
    assert controller._input_suspended
    check.close()
    assert not controller._input_suspended
