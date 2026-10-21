from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint

from pogled_assist.tracking import mouse_gaze_provider
from pogled_assist.tracking.mouse_gaze_provider import MouseGazeProvider, _normalize_cursor_position
from pogled_assist.tracking.status import TrackingState, TrackingStatus


def test_cursor_position_is_normalized_and_clamped():
    geometry = (100, 200, 201, 101)

    assert _normalize_cursor_position(QPoint(150, 250), geometry) == (0.25, 0.5)
    assert _normalize_cursor_position(QPoint(-100, 900), geometry) == (0.0, 1.0)


def test_experimental_simulation_delivers_single_eye_coordinates_and_pauses_without_them(simulation):
    provider, events, _now = simulation
    provider.set_eye_tracking_policy("any")
    provider.toggle_left_eye()
    events.clear()
    provider._emit_cursor_sample()
    assert events == [("gaze", 0.25, 0.5)]
    provider.toggle_gaze()
    events.clear()
    provider._emit_cursor_sample()
    assert events == []


def test_mouse_provider_emits_active_eyes_and_cursor_gaze(qapp, monkeypatch):
    monkeypatch.setattr(
        "pogled_assist.tracking.mouse_gaze_provider._primary_screen_geometry",
        lambda: (100, 200, 201, 101),
    )
    provider = MouseGazeProvider(cursor_position=lambda: QPoint(150, 250))
    gaze = []
    eyes = []
    statuses = []
    trackers = []
    tracking = []
    provider.tracking_status_changed.connect(tracking.append)
    provider.gaze_updated.connect(lambda x, y, timestamp: gaze.append((x, y, timestamp)))
    provider.eye_status_changed.connect(lambda left, right: eyes.append((left, right)))
    provider.status_changed.connect(statuses.append)
    provider.tracker_changed.connect(trackers.append)

    provider.start()

    assert provider._timer.isActive()
    assert gaze[0][:2] == (0.25, 0.5)
    assert isinstance(gaze[0][2], int)
    assert eyes == [(True, True)]
    assert statuses == ["Praćenje simulacijom miša je aktivno."]
    assert trackers == ["Simulator pogleda mišem"]
    assert tracking == [TrackingStatus(TrackingState.SIMULATING)]

    provider.stop()

    assert not provider._timer.isActive()
    assert eyes[-1] == (False, False)
    assert tracking[-1] == TrackingStatus(TrackingState.STOPPED)


def test_mouse_provider_reports_missing_primary_screen(qapp, monkeypatch):
    monkeypatch.setattr(
        "pogled_assist.tracking.mouse_gaze_provider._primary_screen_geometry",
        lambda: None,
    )
    provider = MouseGazeProvider(cursor_position=lambda: QPoint())
    statuses = []
    tracking = []
    provider.tracking_status_changed.connect(tracking.append)
    provider.status_changed.connect(statuses.append)

    provider.start()

    assert not provider._timer.isActive()
    assert statuses == ["Simulacija pogleda nije dostupna jer nema glavnog ekrana."]
    assert tracking == [TrackingStatus(TrackingState.UNAVAILABLE)]


@pytest.fixture
def simulation(qapp, monkeypatch):
    now = [10.0]
    monkeypatch.setattr(
        mouse_gaze_provider,
        "time",
        SimpleNamespace(monotonic=lambda: now[0], monotonic_ns=lambda: int(now[0] * 1e9)),
    )
    monkeypatch.setattr(
        mouse_gaze_provider, "_primary_screen_geometry", lambda: (100, 200, 201, 101)
    )
    provider = MouseGazeProvider(cursor_position=lambda: QPoint(150, 250))
    events = []
    provider.eye_status_changed.connect(lambda left, right: events.append(("eyes", left, right)))
    provider.gaze_updated.connect(lambda x, y, _stamp: events.append(("gaze", x, y)))
    provider.start()
    provider._timer.stop()
    events.clear()
    try:
        yield provider, events, now
    finally:
        provider.stop()


@pytest.mark.parametrize(
    ("action", "eyes"),
    [("toggle_left_eye", (False, True)), ("toggle_right_eye", (True, False))],
)
def test_simulated_eye_loss_stops_gaze_until_a_fresh_sample(simulation, action, eyes):
    provider, events, now = simulation
    toggle = getattr(provider, action)
    toggle()
    provider._emit_cursor_sample()
    assert events == [("eyes", *eyes)]

    toggle()
    assert events[-1] == ("eyes", True, True)
    assert not any(event[0] == "gaze" for event in events)
    now[0] += 0.02
    provider._emit_cursor_sample()
    assert events[-1] == ("gaze", 0.25, 0.5)


def test_simulated_gaze_gap_cancels_dwell_before_delivering_resumed_coordinates(simulation):
    provider, events, now = simulation
    provider.toggle_gaze()
    events.clear()
    now[0] += 1.0
    provider._emit_cursor_sample()
    assert events == []

    provider.toggle_gaze()
    events.clear()
    provider._emit_cursor_sample()
    assert events == [("eyes", False, False), ("eyes", True, True), ("gaze", 0.25, 0.5)]


def test_reconnection_preserves_other_simulated_failures_and_reset_clears_them(simulation):
    provider, events, _now = simulation
    provider.toggle_left_eye()
    provider.toggle_gaze()
    provider.toggle_connection()
    assert events[-1] == ("eyes", False, False)
    events.clear()
    provider._emit_cursor_sample()
    assert events == []

    provider.toggle_connection()
    provider._emit_cursor_sample()
    assert events == [("eyes", False, True)]
    provider.toggle_left_eye()
    events.clear()
    provider._emit_cursor_sample()
    assert events == []

    provider.reset()
    assert events == [("eyes", False, False), ("eyes", True, True)]
    provider._emit_cursor_sample()
    assert events[-1] == ("gaze", 0.25, 0.5)


def test_simulation_controls_cannot_restart_a_stopped_provider(simulation):
    provider, events, _now = simulation
    provider.stop()
    events.clear()
    provider.toggle_left_eye()
    provider.toggle_right_eye()
    provider.toggle_gaze()
    provider.toggle_connection()
    provider.reset()
    provider._emit_cursor_sample()
    assert events == []
    assert not provider._timer.isActive()


@pytest.mark.parametrize(
    ("action", "eyes"),
    [
        ("toggle_left_eye", (False, True)),
        ("toggle_right_eye", (True, False)),
        ("toggle_connection", (False, False)),
        ("reset", (True, True)),
    ],
)
def test_simulated_loss_immediately_updates_caregiver_check(simulation, action, eyes):
    provider, _events, _now = simulation
    provider.set_check_active(True)
    provider._emit_cursor_sample()
    assert provider.check_snapshot().gaze == (0.25, 0.5)
    snapshots = []
    provider.diagnostics_updated.connect(snapshots.append)

    getattr(provider, action)()

    assert (snapshots[-1].left, snapshots[-1].right) == eyes
    assert snapshots[-1].gaze is None
    provider.reset()
    assert (snapshots[-1].left, snapshots[-1].right) == (True, True)
    assert snapshots[-1].gaze is None
    provider._emit_cursor_sample()
    assert snapshots[-1].gaze == (0.25, 0.5)
