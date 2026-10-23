from __future__ import annotations

import threading

import pytest
from _clock import freeze_monotonic
from PySide6.QtCore import QRect

from pogled_assist.interaction.eye_tracking_policy import EyeTrackingGate
from pogled_assist.interaction.gaze_selection import GazeSelectionTimer
from pogled_assist.interaction.gaze_targets import GazeTargets
from pogled_assist.interaction.mouse_controller import GazeMouseController, GazeSettings
from pogled_assist.tracking.gaze_provider import TobiiGazeProvider


@pytest.fixture
def selection(monkeypatch):
    now = freeze_monotonic(monkeypatch, 10.0)
    gate = EyeTrackingGate()
    gate.configure("hold", 150)
    timer = GazeSelectionTimer()
    gate.interrupted.connect(timer.pause)
    gate.hold_started.connect(timer.hold_tracking)
    gate.update_eyes(True, True)

    def sample(at, target="button"):
        now[0] = at
        if gate.sample(at):
            return timer.update(target, at * 1000, pause_ms=250, dwell_ms=850)
        return None

    sample(10.0)
    sample(11.0)
    return gate, timer, now, sample


def test_hold_excludes_loss_and_first_return_interval(selection):
    gate, timer, now, sample = selection
    now[0] = 11.01
    gate.update_eyes(True, False)
    assert timer.tracking_held
    now[0] = 11.04
    gate.update_eyes(True, True)
    assert gate.holding
    resumed = sample(11.05)
    assert resumed.progress == pytest.approx(750 / 850)
    assert not resumed.ready
    assert not sample(11.149).ready
    assert sample(11.15).ready


def test_hold_deadline_is_not_extended_by_reports_or_status_only_recovery(selection):
    gate, timer, now, _sample = selection
    now[0] = 11.01
    gate.update_eyes(True, False)
    now[0] = 11.10
    gate.update_eyes(True, False)
    gate.update_eyes(True, True)
    now[0] = 11.161
    gate._deadline.timeout.emit()
    assert timer.target is None
    assert not gate.holding


def test_delayed_qt_loss_uses_native_deadline(selection):
    gate, timer, now, _sample = selection
    now[0] = 11.3
    gate.update_eyes(True, False, received_at=11.01)
    assert timer.target is None
    assert not gate.holding


@pytest.mark.parametrize("invalid_at,preserved", [(11.005, False), (11.015, True)])
def test_native_invalid_gaze_timing_cannot_be_hidden_by_a_later_hold(
    selection, invalid_at, preserved
):
    gate, timer, now, _sample = selection
    now[0] = 11.01
    gate.update_eyes(True, False)
    now[0] = 11.02
    gate.update_eyes(True, True)
    gate.invalidate_gaze(invalid_at)
    assert timer.tracking_held is preserved
    assert (timer.target is not None) is preserved


@pytest.mark.parametrize("duration", [50, 150, 500])
def test_hold_duration_runs_from_loss_and_does_not_expire_from_prior_sample(selection, duration):
    gate, timer, now, _sample = selection
    gate.configure("hold", duration)
    gate.sample()
    timer.update("button", 11000, pause_ms=250, dwell_ms=850)
    now[0] = 11.02
    gate.update_eyes(True, False)
    now[0] = 11.02 + duration / 1000 - 0.001
    gate._freshness.timeout.emit()
    assert timer.tracking_held
    now[0] += 0.002
    gate._deadline.timeout.emit()
    assert timer.target is None


@pytest.mark.parametrize("eyes", [(False, False), (False, True)])
def test_both_eye_loss_or_switch_of_sole_eye_cancels_hold(selection, eyes):
    gate, timer, now, _sample = selection
    now[0] = 11.01
    gate.update_eyes(True, False)
    now[0] = 11.02
    gate.update_eyes(*eyes)
    assert timer.target is None
    assert not gate.holding


@pytest.mark.parametrize("target", ["neighbor", None])
def test_return_to_another_target_cannot_reuse_held_progress(selection, target):
    gate, _timer, now, sample = selection
    now[0] = 11.01
    gate.update_eyes(True, False)
    gate.update_eyes(True, True)
    result = sample(11.05, target)
    assert result.progress is None
    assert not result.ready


def test_expired_hold_cannot_fire_when_timer_dispatch_is_late(selection):
    gate, _timer, now, sample = selection
    now[0] = 11.01
    gate.update_eyes(True, False)
    now[0] = 11.17
    gate.update_eyes(True, True)
    result = sample(11.17)
    assert result.progress is None
    assert not result.ready


def test_switching_sole_eye_requires_fresh_both_eye_gaze_to_keep_progress(monkeypatch):
    now = freeze_monotonic(monkeypatch, 10.0)
    gate = EyeTrackingGate()
    gate.configure("any", 150)
    resets = []
    gate.interrupted.connect(lambda: resets.append(now[0]))
    gate.update_eyes(True, False)
    assert gate.sample()
    gate.update_eyes(True, True)
    gate.update_eyes(False, True)
    assert resets == [10.0]
    assert gate.sample()
    gate.update_eyes(True, True)
    assert gate.sample()
    gate.update_eyes(True, False)
    assert resets == [10.0]
    now[0] += 0.501
    gate._freshness.timeout.emit()
    assert resets == [10.0, 10.501]


def test_completed_target_remains_blocked_after_hold_and_disconnect(selection):
    gate, timer, now, sample = selection
    assert sample(11.1).ready
    timer.complete()
    now[0] = 11.11
    gate.update_eyes(True, False)
    gate.update_eyes(False, False)
    gate.update_eyes(True, True)
    assert sample(12.0).progress is None
    assert timer.is_blocked
    sample(12.01, None)
    assert sample(12.02).progress is None
    assert sample(13.12).ready


@pytest.mark.parametrize("policy,allows_single", [("both", False), ("hold", False), ("any", True)])
def test_stream_and_research_only_deliver_eligible_real_coordinates(policy, allows_single):
    provider = TobiiGazeProvider()
    provider.set_eye_tracking_policy(policy)
    samples = []
    provider.gaze_updated.connect(lambda x, y, _stamp: samples.append((x, y)))
    provider._on_stream_engine_eye_status(True, False, 1)
    provider._on_stream_engine_gaze(0.2, 0.7, 2)
    provider._emit_latest_gaze_sample()
    assert samples == ([(0.2, 0.7)] if allows_single else [])
    samples.clear()
    provider._on_gaze_data(
        {
            "left_gaze_point_validity": 0,
            "right_gaze_point_validity": 1,
            "right_gaze_point_on_display_area": (0.3, 0.6),
        }
    )
    provider._emit_latest_gaze_sample()
    assert samples == ([(0.3, 0.6)] if allows_single else [])
    provider._on_stream_engine_gaze(float("nan"), 0.5, 3)
    provider._emit_latest_gaze_sample()
    assert len(samples) == int(allows_single)


def test_worker_backlog_preserves_both_invalid_and_single_eye_switches(monkeypatch):
    now = freeze_monotonic(monkeypatch, 10.0)
    provider = TobiiGazeProvider()
    provider.set_eye_tracking_policy("any")
    gaze, eyes = provider._new_stream_callbacks()
    events = []
    provider.eye_state_changed.connect(events.append)
    events.clear()

    def backlog():
        for left, right in ((True, True), (True, False), (False, False), (False, True)):
            eyes(left, right, 1)
        gaze(0.5, 0.5, 2)

    worker = threading.Thread(target=backlog)
    worker.start()
    worker.join(timeout=1)
    assert not worker.is_alive()
    now[0] = 10.2
    provider._emit_latest_gaze_sample()
    assert [(event.left, event.right) for event in events] == [
        (True, True),
        (True, False),
        (False, False),
        (False, True),
    ]
    assert all(event.received_at == 10.0 for event in events)
    provider.stop()
    events.clear()
    eyes(True, True, 3)
    provider._flush_eye_status()
    assert events == []


def test_one_eye_app_selection_never_moves_or_clicks_the_desktop(monkeypatch):
    now = freeze_monotonic(monkeypatch, 10.0)
    bounds = QRect(0, 0, 50, 50)
    controller = GazeMouseController(
        GazeTargets(
            lambda point: "speech" if bounds.contains(point) else None,
            lambda *_args: bounds.center(),
            bounds.contains,
            lambda _action: bounds,
        )
    )
    controller._logical_screen_rect = (0, 0, 101, 101)
    controller._physical_screen_rect = (0, 0, 151, 151)

    class Input:
        def move_to(self, *_args):
            pytest.fail("One-eye gaze moved the desktop pointer")

        def click(self, *_args, **_kwargs):
            pytest.fail("One-eye gaze clicked the desktop")

    controller._input = Input()
    controller.update_settings(
        GazeSettings(
            eye_tracking_policy="any",
            selection_pause_ms=250,
            dwell_ms=850,
            use_precision_zoom=False,
        )
    )
    actions = []
    external_points = []
    controller.toolbar_action_requested.connect(actions.append)
    controller.desktop_gaze_position_changed.connect(external_points.append)
    controller.handle_eye_status(True, False)
    controller.handle_gaze(0.2, 0.2, 1)
    now[0] += 1.1
    controller.handle_gaze(0.2, 0.2, 2)
    assert actions == ["speech"]
    for index in range(5):
        now[0] += 0.4
        controller.handle_gaze(0.9, 0.9, index)
    assert external_points == []


def test_backlog_overflow_forces_cancellation_before_final_eye_state():
    provider = TobiiGazeProvider()
    events = []
    provider.eye_state_changed.connect(events.append)

    def backlog():
        for index in range(80):
            provider._emit_eye_status(True, bool(index % 2), "synthetic")

    worker = threading.Thread(target=backlog)
    worker.start()
    worker.join(timeout=1)
    assert not worker.is_alive()
    assert len(provider._eye_events) <= 64
    provider._flush_eye_status()
    assert (events[0].left, events[0].right) == (False, False)
    assert (events[-1].left, events[-1].right) == (True, True)
