from __future__ import annotations

import pytest

from pogled_assist.interaction.gaze_selection import GazeSelectionTimer


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


@pytest.mark.parametrize("last_seen", [400, 800])
@pytest.mark.parametrize("outside_target", [None, "neighbor"])
def test_edge_hold_freezes_pause_or_dwell_until_gaze_returns(last_seen, outside_target):
    timer = GazeSelectionTimer()
    timing = dict(pause_ms=500, dwell_ms=500, hold_ms=120)
    timer.update("button", 0, **timing)
    before = timer.update("button", last_seen, **timing)

    for offset in (20, 40):
        held = timer.update(outside_target, last_seen + offset, can_hold=True, **timing)
        assert timer.target == "button"
        assert held.progress == before.progress
        assert not held.ready

    resumed = timer.update("button", last_seen + 60, **timing)
    assert resumed.progress == before.progress
    assert not resumed.ready
    assert not timer.update("button", 1059, **timing).ready
    assert timer.update("button", 1060, **timing).ready


@pytest.mark.parametrize("target", [None, "neighbor", "button"])
def test_hold_expiry_discards_progress_even_if_next_sample_is_back_on_target(target):
    timer = GazeSelectionTimer()
    timing = dict(pause_ms=500, dwell_ms=500, hold_ms=120)
    timer.update("button", 0, **timing)
    timer.update("button", 980, **timing)
    assert not timer.update("neighbor", 1000, can_hold=True, **timing).ready

    expired = timer.update(target, 1120, can_hold=True, **timing)
    assert expired.progress is None
    assert not expired.ready
    if target is not None:
        assert not timer.update(target, 2119, **timing).ready
        assert timer.update(target, 2120, **timing).ready


def test_repeated_excursions_cannot_count_outside_time_toward_completion():
    timer = GazeSelectionTimer()
    timing = dict(pause_ms=500, dwell_ms=500, hold_ms=120)
    timer.update("button", 0, **timing)
    timer.update("button", 980, **timing)

    for now in range(1000, 5000, 40):
        held = timer.update(None, now, can_hold=True, **timing)
        returned = timer.update("button", now + 20, **timing)
        assert held.progress == pytest.approx(0.96)
        assert returned.progress == pytest.approx(0.96)
        assert not held.ready and not returned.ready


def test_far_target_switch_skips_hold_and_starts_its_own_full_pause():
    timer = GazeSelectionTimer()
    timing = dict(pause_ms=500, dwell_ms=500, hold_ms=120)
    timer.update("first", 0, **timing)
    timer.update("first", 800, **timing)
    timer.update("second", 820, can_hold=False, **timing)

    assert timer.target == "second"
    assert timer.update("second", 1319, **timing).progress is None
    assert timer.update("second", 1320, **timing).progress == 0.0
    assert timer.update("second", 1820, **timing).ready


def test_completed_target_stays_blocked_through_brief_excursions_and_eye_loss():
    timer = GazeSelectionTimer()
    timing = dict(pause_ms=500, dwell_ms=500, hold_ms=120)
    timer.update("button", 0, **timing)
    assert timer.update("button", 1000, **timing).ready
    timer.complete()

    timer.update(None, 1020, can_hold=True, **timing)
    timer.update("button", 1060, **timing)
    timer.pause()
    assert timer.is_blocked
    assert not timer.update("button", 3000, **timing).ready
    timer.update(None, 3020, can_hold=True, **timing)
    timer.update(None, 3140, can_hold=True, **timing)
    assert not timer.is_blocked
    timer.update("button", 3160, **timing)
    assert timer.update("button", 4160, **timing).ready


def test_completed_target_unlocks_when_first_return_is_after_hold_expiry():
    timer = GazeSelectionTimer()
    timing = dict(pause_ms=500, dwell_ms=500, hold_ms=120)
    timer.update("button", 0, **timing)
    assert timer.update("button", 1000, **timing).ready
    timer.complete()

    timer.update(None, 1020, can_hold=True, **timing)
    # A short delivery gap can skip the outside sample at the expiry boundary.
    returned = timer.update("button", 1160, **timing)
    assert not timer.is_blocked
    assert returned.progress is None
    assert not returned.ready
    assert not timer.update("button", 2159, **timing).ready
    assert timer.update("button", 2160, **timing).ready


@pytest.mark.parametrize("cancel", ["pause", "cancel", "restart"])
def test_cancellation_discards_frozen_time(cancel):
    timer = GazeSelectionTimer()
    timing = dict(pause_ms=500, dwell_ms=500, hold_ms=120)
    timer.update("button", 0, **timing)
    timer.update("button", 800, **timing)
    timer.update(None, 820, can_hold=True, **timing)
    if cancel == "restart":
        timer.update("button", 860, restart=True, **timing)
    else:
        getattr(timer, cancel)()
        timer.update("button", 860, **timing)
    assert timer.update("button", 1060, **timing).progress is None
    assert timer.update("button", 1860, **timing).ready
