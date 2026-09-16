from __future__ import annotations

import pytest

from gaze_mouse.gaze_selection import GazeSelectionTimer


def test_pause_and_configured_dwell_have_separate_boundaries():
    timer = GazeSelectionTimer()

    assert timer.update("button", 1000, 500).progress is None
    assert timer.update("button", 1499, 500).progress is None

    filling = timer.update("button", 1500, 500)
    almost_ready = timer.update("button", 1999, 500)
    ready = timer.update("button", 2000, 500)

    assert filling.progress == 0.0
    assert filling.ready is False
    assert almost_ready.progress == pytest.approx(0.998)
    assert almost_ready.ready is False
    assert ready.progress == 1.0
    assert ready.ready is True


def test_changed_dwell_does_not_change_initial_pause():
    timer = GazeSelectionTimer()

    timer.update("button", 1000, 900)

    assert timer.update("button", 1499, 900).progress is None
    assert timer.update("button", 1500, 900).progress == 0.0
    assert timer.update("button", 2399, 900).ready is False
    assert timer.update("button", 2400, 900).ready is True


def test_completed_target_requires_leave_before_it_can_restart():
    timer = GazeSelectionTimer()
    timer.update("button", 1000, 200)
    assert timer.update("button", 1700, 200).ready is True

    timer.complete()

    assert timer.update("button", 5000, 200).progress is None
    timer.update(None, 5001, 200)
    assert timer.update("button", 6000, 200).progress is None
    assert timer.update("button", 6500, 200).progress == 0.0


def test_target_change_and_mouse_cancellation_start_a_full_pause():
    timer = GazeSelectionTimer()
    timer.update("first", 1000, 200)
    assert timer.update("first", 1500, 200).progress == 0.0

    assert timer.update("second", 1600, 200).progress is None
    assert timer.update("second", 2099, 200).progress is None
    timer.cancel(require_leave=True)

    assert timer.update("second", 3000, 200).progress is None
    assert timer.update("third", 3100, 200).progress is None
    assert timer.update("third", 3600, 200).progress == 0.0
