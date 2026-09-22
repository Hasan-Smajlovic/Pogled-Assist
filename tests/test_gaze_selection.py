from __future__ import annotations

import pytest

from gaze_mouse.gaze_selection import GazeSelectionTimer


def test_pause_and_configured_dwell_have_separate_boundaries():
    timer = GazeSelectionTimer()

    assert timer.update("button", 1000, pause_ms=500, dwell_ms=500).progress is None
    assert timer.update("button", 1499, pause_ms=500, dwell_ms=500).progress is None

    filling = timer.update("button", 1500, pause_ms=500, dwell_ms=500)
    almost_ready = timer.update("button", 1999, pause_ms=500, dwell_ms=500)
    ready = timer.update("button", 2000, pause_ms=500, dwell_ms=500)

    assert filling.progress == 0.0
    assert filling.ready is False
    assert almost_ready.progress == pytest.approx(0.998)
    assert almost_ready.ready is False
    assert ready.progress == 1.0
    assert ready.ready is True


def test_pause_and_dwell_can_be_configured_independently():
    timer = GazeSelectionTimer()

    timer.update("button", 1000, pause_ms=250, dwell_ms=900)

    assert timer.update("button", 1249, pause_ms=250, dwell_ms=900).progress is None
    assert timer.update("button", 1250, pause_ms=250, dwell_ms=900).progress == 0.0
    assert timer.update("button", 2149, pause_ms=250, dwell_ms=900).ready is False
    assert timer.update("button", 2150, pause_ms=250, dwell_ms=900).ready is True


def test_completed_target_requires_leave_before_it_can_restart():
    timer = GazeSelectionTimer()
    timer.update("button", 1000, pause_ms=500, dwell_ms=200)
    assert timer.update("button", 1700, pause_ms=500, dwell_ms=200).ready is True

    timer.complete()

    assert timer.update("button", 5000, pause_ms=500, dwell_ms=200).progress is None
    timer.update(None, 5001, pause_ms=500, dwell_ms=200)
    assert timer.update("button", 6000, pause_ms=500, dwell_ms=200).progress is None
    assert timer.update("button", 6500, pause_ms=500, dwell_ms=200).progress == 0.0


def test_target_change_and_mouse_cancellation_start_a_full_pause():
    timer = GazeSelectionTimer()
    timer.update("first", 1000, pause_ms=500, dwell_ms=200)
    assert timer.update("first", 1500, pause_ms=500, dwell_ms=200).progress == 0.0

    assert timer.update("second", 1600, pause_ms=500, dwell_ms=200).progress is None
    assert timer.update("second", 2099, pause_ms=500, dwell_ms=200).progress is None
    timer.cancel(require_leave=True)

    assert timer.update("second", 3000, pause_ms=500, dwell_ms=200).progress is None
    assert timer.update("third", 3100, pause_ms=500, dwell_ms=200).progress is None
    assert timer.update("third", 3600, pause_ms=500, dwell_ms=200).progress == 0.0


def test_invalid_gaze_pause_preserves_only_an_existing_repeat_lock():
    timer = GazeSelectionTimer()
    timer.update("button", 1000, pause_ms=500, dwell_ms=200)
    assert timer.update("button", 1700, pause_ms=500, dwell_ms=200).ready is True
    timer.complete()

    timer.pause()

    assert timer.update("button", 3000, pause_ms=500, dwell_ms=200).progress is None
    timer.update(None, 3001, pause_ms=500, dwell_ms=200)
    assert timer.update("button", 4000, pause_ms=500, dwell_ms=200).progress is None

    pending = GazeSelectionTimer()
    pending.update("button", 1000, pause_ms=500, dwell_ms=200)
    pending.pause()
    assert pending.update("button", 2000, pause_ms=500, dwell_ms=200).progress is None
    assert pending.update("button", 2500, pause_ms=500, dwell_ms=200).progress == 0.0
