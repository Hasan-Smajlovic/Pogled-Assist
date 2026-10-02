from __future__ import annotations

from PySide6.QtCore import QPoint

from pogled_assist.tracking.mouse_gaze_provider import MouseGazeProvider, _normalize_cursor_position
from pogled_assist.tracking.status import TrackingState, TrackingStatus


def test_cursor_position_is_normalized_and_clamped():
    geometry = (100, 200, 201, 101)

    assert _normalize_cursor_position(QPoint(150, 250), geometry) == (0.25, 0.5)
    assert _normalize_cursor_position(QPoint(-100, 900), geometry) == (0.0, 1.0)


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
