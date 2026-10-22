from __future__ import annotations

import threading
from dataclasses import replace

import pytest
from _clock import freeze_monotonic
from _hotbar_fixtures import hotbar_gaze as hotbar_gaze
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QGuiApplication

from pogled_assist.interaction.mouse_controller import QUICK_ACTIONS, GazeSettings
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.tracking.gaze_check import CheckSnapshot
from pogled_assist.tracking.gaze_provider import TobiiGazeProvider
from pogled_assist.tracking.status import TrackingState, TrackingStatus
from pogled_assist.ui.gaze_check_window import GazeCheckWindow
from pogled_assist.ui.settings_window import SettingsWindow

pytestmark = pytest.mark.e2e


def test_policy_tabs_and_controls_fit_target_display_and_preserve_duration(qtbot, monkeypatch):
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    window = SettingsWindow(GazeSettings(), SpeechSettings())
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window._select_tab(1)
    window.show()
    qtbot.wait(1)
    page = window._gaze_page
    updates = []
    window.gaze_settings_changed.connect(updates.append)
    assert not page._hold_row.isEnabled()
    page._policy_combo.setCurrentIndex(page._policy_combo.findData("hold"))
    assert page._hold_row.isEnabled()
    window._adjust_eye_tracking_hold(50)
    assert updates[-1].eye_tracking_hold_ms == 200
    for tab in (0, 1, 2):
        page.show_tab(tab)
        qtbot.wait(1)
        visible = [control for control in window._controls._actions if control.isVisible()]
        for control in visible:
            assert control.height() >= 58
            assert window.rect().contains(QRect(control.mapTo(window, QPoint()), control.size()))
    page.show_tab(0)
    page._policy_combo.setCurrentIndex(page._policy_combo.findData("any"))
    assert not page._hold_row.isEnabled()
    assert page._hold_value.text() == "200 ms"
    assert updates[-1].eye_tracking_policy == "any"


@pytest.mark.parametrize("surface", ["hotbar", "keyboard", "speech", "controller"])
@pytest.mark.parametrize("hotbar_gaze", [TobiiGazeProvider], indirect=True)
@pytest.mark.parametrize("eyes", [(True, False), (False, True)], ids=["left", "right"])
def test_one_eye_selects_app_controls_including_controller_clicks(
    hotbar_gaze, qtbot, monkeypatch, surface, eyes
):
    hotbar, controller, _feed, actions, _progress = hotbar_gaze
    now = freeze_monotonic(monkeypatch, 10.0)
    hotbar._update_gaze_settings(
        replace(
            controller.settings,
            eye_tracking_policy="any",
            selection_pause_ms=250,
            dwell_ms=850,
        )
    )
    if surface == "hotbar":
        action = QUICK_ACTIONS
        button = hotbar._buttons[action]
    elif surface == "keyboard":
        hotbar._show_keyboard_sidebar()
        window = hotbar._keyboard_window
        window.setGeometry(900, hotbar.BAR_HEIGHT, 380, 720 - hotbar.BAR_HEIGHT)
        action = next(key for key in window._action_buttons if key.endswith("space"))
        button = window._action_buttons[action]
    elif surface == "speech":
        hotbar._open_speech()
        window = hotbar._speech_window
        window.showNormal()
        window.setGeometry(0, 0, 1280, 720)
        action = next(key for key in window._action_buttons if key.endswith("space"))
        button = window._action_buttons[action]
    else:
        hotbar._show_controller_sidebar()
        window = hotbar._controller_window
        action = next(key for key in window._action_buttons if key.endswith("left_click"))
        button = window._action_buttons[action]
    qtbot.wait(1)
    point = button.mapToGlobal(button.rect().center())
    provider = hotbar._gaze
    gaze, eye_status = provider._new_stream_callbacks()

    def sample(at):
        now[0] = at
        eye_status(*eyes, 1)
        gaze(point.x() / 1279, point.y() / 719, 2)
        provider._emit_latest_gaze_sample()

    for index in range(24):
        sample(10.0 + index * 0.05)
    assert actions == [action]
    if surface == "controller":
        assert len(window._input.clicks) == 1
    sample(12.5)
    assert actions == [action]


def test_hold_freezes_feedback_and_first_return_cannot_activate(hotbar_gaze):
    hotbar, controller, feed, actions, progress = hotbar_gaze
    hotbar._update_gaze_settings(replace(controller.settings, eye_tracking_policy="hold"))
    button = hotbar._buttons[QUICK_ACTIONS]
    point = button.mapToGlobal(button.rect().center())
    feed(point, 0)
    feed(point, 900)
    before = progress[-1]
    controller.handle_eye_status(True, False)
    assert hotbar._interaction_overlay._mode == "paused"
    assert button.property("gazePaused")
    assert not button._gaze_feedback_timer.isActive()
    feed(point, 950)
    assert progress[-1] == before
    controller.handle_eye_status(True, True)
    feed(point, 960)
    assert progress[-1] == before
    assert actions == []
    feed(point, 1061)
    assert actions == [QUICK_ACTIONS]
    assert not button.property("gazePaused")


def test_settings_hold_expires_without_another_gaze_sample(qtbot, monkeypatch):
    now = freeze_monotonic(monkeypatch, 10.0)
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    window = SettingsWindow(GazeSettings(eye_tracking_policy="hold"), SpeechSettings())
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window._select_tab(1)
    window.show()
    qtbot.wait(1)
    window.handle_eye_status(True, True)
    button = window._gaze_page._interaction_overlay_button
    point = button.mapToGlobal(button.rect().center())
    window.handle_gaze(point)
    now[0] += 0.8
    window.handle_gaze(point)
    window.handle_eye_status(True, False)
    assert window._gaze_selection.tracking_held
    now[0] += 0.151
    window._eye_gate._deadline.timeout.emit()
    assert window._gaze_selection.target is None
    assert not button.property("gazeTarget")
    assert window._gaze_settings.show_interaction_overlay


def test_one_eye_check_free_view_and_fixation_keep_real_eye_indicators(qtbot, monkeypatch):
    now = freeze_monotonic(monkeypatch, 10.0)
    window = GazeCheckWindow(GazeSettings(eye_tracking_policy="any"))
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    window.handle_tracking_status(TrackingStatus(TrackingState.CONNECTED))
    qtbot.wait(1)
    window._start_free()
    window.handle_snapshot(CheckSnapshot(True, False, gaze=(0.5, 0.5), gaze_at=now[0]))
    assert window._target.gaze_point is not None
    assert window._snapshot.right is False
    now[0] += 0.501
    window._tick()
    assert window._target.gaze_point is None
    window._start_precision()
    qtbot.waitUntil(lambda: window._check is not None)
    _, x, y = window._check.targets[0]
    for index in range(100):
        now[0] = window._check.started_at + 1 + index * 0.02
        window.handle_snapshot(CheckSnapshot(True, False, gaze=(x, y), gaze_at=now[0]))
    now[0] = window._check.started_at + 3.01
    window._tick()
    assert window._check.results[0].near is True
    assert "Jedno oko je dovoljno" in window._policy_text


def test_changed_settings_target_geometry_does_not_resume_a_hold(qtbot, monkeypatch):
    now = freeze_monotonic(monkeypatch, 10.0)
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    window = SettingsWindow(GazeSettings(eye_tracking_policy="hold"), SpeechSettings())
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window._select_tab(1)
    window.show()
    qtbot.wait(1)
    window.handle_eye_status(True, True)
    button = window._gaze_page._interaction_overlay_button
    point = button.mapToGlobal(button.rect().center())
    window.handle_gaze(point)
    now[0] += 0.8
    window.handle_gaze(point)
    window.handle_eye_status(True, False)
    button.move(button.x() + 10, button.y())
    now[0] += 0.05
    window.handle_eye_status(True, True)
    window.handle_gaze(button.mapToGlobal(button.rect().center()))
    assert window._gaze_settings.show_interaction_overlay
    assert window._gaze_selection.diagnostic_snapshot()["credited_ms"] == 0


@pytest.mark.parametrize("hotbar_gaze", [TobiiGazeProvider], indirect=True)
@pytest.mark.parametrize("delay", [0.03, 0.20])
@pytest.mark.parametrize("invalid_before_loss", [False, True])
def test_native_worker_hold_deadline_through_hotbar_dispatch(
    hotbar_gaze, monkeypatch, delay, invalid_before_loss
):
    hotbar, controller, _feed, actions, progress = hotbar_gaze
    now = freeze_monotonic(monkeypatch, 10.0)
    hotbar._update_gaze_settings(replace(controller.settings, eye_tracking_policy="hold"))
    provider = hotbar._gaze
    gaze, eyes = provider._new_stream_callbacks()
    button = hotbar._buttons[QUICK_ACTIONS]
    point = button.mapToGlobal(button.rect().center())
    x, y = point.x() / 1279, point.y() / 719
    for index in range(10):
        now[0] = 10.0 + index / 10
        eyes(True, True, index)
        gaze(x, y, index)
        provider._emit_latest_gaze_sample()
    before = progress[-1]
    now[0] = 10.91
    if invalid_before_loss:
        now[0] = 10.905
        provider._invalid_callback(provider._stream_generation)(100)
        now[0] = 10.91
    worker = threading.Thread(target=lambda: eyes(True, False, 100))
    worker.start()
    worker.join(timeout=1)
    assert not worker.is_alive()
    now[0] += delay
    worker = threading.Thread(target=lambda: (eyes(True, True, 101), gaze(x, y, 101)))
    worker.start()
    worker.join(timeout=1)
    assert not worker.is_alive()
    provider._emit_latest_gaze_sample()
    assert actions == []
    if delay < 0.15 and not invalid_before_loss:
        assert progress[-1] == before
    else:
        assert controller._toolbar_selection.diagnostic_snapshot()["credited_ms"] == 0


@pytest.mark.parametrize("hotbar_gaze", [TobiiGazeProvider], indirect=True)
def test_native_invalid_gaze_closes_quick_action_refinement(hotbar_gaze, monkeypatch):
    hotbar, _controller, _feed, _actions, _progress = hotbar_gaze
    now = freeze_monotonic(monkeypatch, 10.0)
    provider = hotbar._gaze
    gaze, eyes = provider._new_stream_callbacks()
    hotbar._open_quick_action_zoom(QPoint(400, 400))
    zoom = hotbar._quick_zoom
    point = zoom._screen_geometry.topLeft() + zoom._display_rect.center()
    x, y = point.x() / 1279, point.y() / 719
    for index in range(10):
        now[0] = 10.0 + index / 10
        eyes(True, True, index)
        gaze(x, y, index)
        provider._emit_latest_gaze_sample()
    assert zoom.isVisible()
    assert zoom._candidate_progress > 0
    now[0] = 10.91
    provider._invalid_callback(provider._stream_generation)(100)
    provider._emit_latest_gaze_sample()
    assert not zoom.isVisible()
    assert hotbar._zoom_context is None
    now[0] = 11.01
    eyes(True, True, 101)
    gaze(x, y, 101)
    provider._emit_latest_gaze_sample()
    assert not hotbar._quick_menu.isVisible()


def test_settings_one_eye_selection_requires_eye_validity_and_fresh_point(qtbot, monkeypatch):
    now = freeze_monotonic(monkeypatch, 10.0)
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    window = SettingsWindow(
        GazeSettings(
            eye_tracking_policy="any",
            selection_pause_ms=250,
            dwell_ms=850,
        ),
        SpeechSettings(),
    )
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window._select_tab(1)
    window.show()
    qtbot.wait(1)
    button = window._gaze_page._interaction_overlay_button
    point = button.mapToGlobal(button.rect().center())
    window.handle_eye_status(False, False)
    window.handle_gaze(point)
    assert window._gaze_selection.target is None
    window.handle_eye_status(True, False)
    for at in (10.0, 10.6, 11.101):
        now[0] = at
        window.handle_gaze(point)
    assert not window._gaze_settings.show_interaction_overlay
    window.handle_eye_status(False, False)
    window.handle_eye_status(False, True)
    now[0] = 20.0
    window.handle_gaze(point)
    assert not window._gaze_settings.show_interaction_overlay


@pytest.mark.parametrize("policy", ["any", "hold"])
def test_check_trial_completes_with_policy_and_excludes_held_time(qtbot, monkeypatch, policy):
    now = freeze_monotonic(monkeypatch, 10.0)
    window = GazeCheckWindow(
        GazeSettings(
            eye_tracking_policy=policy,
            selection_pause_ms=250,
            dwell_ms=850,
        )
    )
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    qtbot.wait(1)
    window._start_trial()
    rect = QGuiApplication.primaryScreen().geometry()
    point = window._target.mapToGlobal(window._target.button_rect().center())
    gaze = (
        (point.x() - rect.left()) / (rect.width() - 1),
        (point.y() - rect.top()) / (rect.height() - 1),
    )
    eyes = (True, False) if policy == "any" else (True, True)

    def sample(at, interruptions=0):
        now[0] = at
        window.handle_snapshot(
            CheckSnapshot(*eyes, gaze=gaze, gaze_at=at, gaze_interruptions=interruptions)
        )

    for index in range(9):
        sample(10.0 + index / 10)
    if policy == "hold":
        before = window._target.progress
        now[0] = 10.81
        window.handle_eye_status(True, False)
        assert window._target.paused
        window.handle_snapshot(CheckSnapshot(True, False, gaze_interruptions=1))
        assert window._target.progress == before
        now[0] = 10.84
        window.handle_eye_status(True, True)
        sample(10.85, 1)
        assert window._target.progress == before
        assert window._trial_results == []
        sample(11.151, 1)
    else:
        sample(11.101)
    assert window._trial_results == [True]


@pytest.mark.parametrize("change", ["eye_tracking_policy", "eye_tracking_hold_ms"])
def test_policy_change_cancels_active_progress_and_keeps_completed_lock(hotbar_gaze, change):
    hotbar, controller, feed, actions, _progress = hotbar_gaze
    hotbar._update_gaze_settings(replace(controller.settings, eye_tracking_policy="hold"))
    button = hotbar._buttons[QUICK_ACTIONS]
    point = button.mapToGlobal(button.rect().center())
    feed(point, 0)
    feed(point, 900)
    value = "any" if change == "eye_tracking_policy" else 200
    hotbar._update_gaze_settings(replace(controller.settings, **{change: value}))
    feed(point, 950)
    assert controller._toolbar_selection.diagnostic_snapshot()["credited_ms"] == 0
    assert actions == []
    feed(point, 1951)
    assert actions == [QUICK_ACTIONS]
    value = "both" if change == "eye_tracking_policy" else 250
    hotbar._update_gaze_settings(replace(controller.settings, **{change: value}))
    feed(point, 5000)
    assert actions == [QUICK_ACTIONS]


@pytest.mark.parametrize("hotbar_gaze", [TobiiGazeProvider], indirect=True)
@pytest.mark.parametrize("surface", ["hotbar", "settings"])
@pytest.mark.parametrize("policy", ["both", "hold", "any"])
def test_queued_gaze_keeps_native_freshness_through_application_gates(
    hotbar_gaze, qtbot, monkeypatch, surface, policy
):
    hotbar, controller, _feed, actions, _progress = hotbar_gaze
    now = freeze_monotonic(monkeypatch, 9.0)
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    hotbar._update_gaze_settings(
        replace(
            controller.settings,
            eye_tracking_policy=policy,
            dwell_ms=5000,
        )
    )
    provider = hotbar._gaze
    gaze, eyes = provider._new_stream_callbacks()
    if surface == "settings":
        hotbar._open_settings()
        window = hotbar._settings_window
        window.setGeometry(0, 0, 1280, 720)
        window._select_tab(1)
        qtbot.wait(1)
        button = window._gaze_page._interaction_overlay_button
        selection = window._gaze_selection
        gate = window._eye_gate
    else:
        button = hotbar._buttons[QUICK_ACTIONS]
        selection = controller._toolbar_selection
        gate = controller._eye_gate
    provider._set_tracking_status(TrackingState.CONNECTED)
    point = button.mapToGlobal(button.rect().center())
    x, y = point.x() / 1279, point.y() / 719
    for index in range(11):
        now[0] = 9.0 + index / 10
        eyes(True, True, index)
        gaze(x, y, index)
        provider._emit_latest_gaze_sample()
    now[0] = 10.01
    gaze(x, y, 20)
    now[0] = 10.45
    eyes(True, True, 21)
    now[0] = 10.46
    provider._emit_latest_gaze_sample()
    assert selection.diagnostic_snapshot()["credited_ms"] > 1000
    assert hotbar._tracking_status._last_gaze_at == 10.01
    assert hotbar._tracking_feedback._gaze_at == 10.01
    now[0] = 10.52
    if policy == "hold":
        eyes(True, False, 22)
        # The native point is 510 ms old, although delivered only 60 ms ago.
        assert not gate.holding
    now[0] = 10.55
    eyes(True, True, 23)
    gaze(x, y, 24)
    provider._emit_latest_gaze_sample()
    assert selection.diagnostic_snapshot()["credited_ms"] == 0
    assert actions == []
