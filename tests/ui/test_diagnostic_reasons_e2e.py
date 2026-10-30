"""Known UI cancellation boundaries must keep their actual diagnostic cause."""

from types import SimpleNamespace

import pytest
from _hotbar_fixtures import hotbar_gaze as hotbar_gaze
from PySide6.QtCore import QPoint

from pogled_assist import diagnostics

pytestmark = pytest.mark.e2e


@pytest.fixture
def observed_events(monkeypatch):
    events = []
    writer = SimpleNamespace(
        _generation=1, trace=False, event=lambda name, fields, **kw: events.append((name, fields))
    )
    monkeypatch.setattr(diagnostics, "diagnostic_writer", lambda: writer)
    return events


@pytest.mark.parametrize("reason", ["eye_gate_closed", "stale_gaze"])
def test_tracking_failure_closes_overlay_attempts_with_the_known_reason(
    hotbar_gaze, observed_events, reason
):
    hotbar, _controller, _feed, _actions, _progress = hotbar_gaze
    for overlay in (hotbar._quick_menu, hotbar._quick_zoom):
        overlay._selection_timer.update("target", 0, pause_ms=250, dwell_ms=1000)
    if reason == "stale_gaze":
        hotbar._invalidate_gaze(10)
    else:
        hotbar._handle_eye_status_changed(False, True)
    ends = [data for name, data in observed_events if name == "selection_end"]
    assert len(ends) == 2
    assert {data["reason"] for data in ends} == {reason}


def test_toolbar_departure_records_target_departure(hotbar_gaze, observed_events):
    hotbar, controller, feed, _actions, _progress = hotbar_gaze
    target = hotbar._buttons["quick_actions"].mapToGlobal(
        hotbar._buttons["quick_actions"].rect().center()
    )
    feed(target, 0)
    feed(target, 100)
    feed(QPoint(640, 600), 200)
    ends = [data for name, data in observed_events if name == "selection_end"]
    assert ends[-1]["reason"] == "target_departure"
    assert controller._toolbar_selection.target is None


def test_settings_departure_records_target_departure(hotbar_gaze, observed_events, qtbot):
    hotbar, _controller, _feed, _actions, _progress = hotbar_gaze
    hotbar._open_settings()
    window = hotbar._settings_window
    qtbot.waitUntil(window.isVisible)
    window._gaze_selection.update(window._exit_button, 0, pause_ms=250, dwell_ms=1000)
    window._handle_missing_gaze_target(QPoint(-500, -500))
    ends = [data for name, data in observed_events if name == "selection_end"]
    assert ends[-1]["reason"] == "target_departure"
