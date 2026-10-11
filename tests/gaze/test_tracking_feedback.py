from __future__ import annotations

import pytest

from pogled_assist.tracking.feedback import TrackingFeedbackState
from pogled_assist.tracking.status import TrackingState, TrackingStatus

CONNECTED = TrackingStatus(TrackingState.CONNECTED)


def ready(state, now):
    return state.update(CONNECTED, (True, True), now, now)


def test_brief_loss_is_silent_and_does_not_show_success():
    state = TrackingFeedbackState()
    assert ready(state, 0) is None
    assert state.update(CONNECTED, (False, True), None, 1) is None
    assert state.update(CONNECTED, (False, True), None, 1.2) is None
    assert ready(state, 1.3) is None
    assert ready(state, 2) is None


@pytest.mark.parametrize(
    ("eyes", "title"),
    [
        ((False, True), "Lijevo oko"),
        ((True, False), "Desno oko"),
        ((False, False), "Praćenje oba oka"),
    ],
)
def test_sustained_loss_recovers_only_with_fresh_gaze(eyes, title):
    state = TrackingFeedbackState()
    state.update(CONNECTED, eyes, None, 1)
    notice = state.update(CONNECTED, eyes, None, 1.81)
    assert notice.title.startswith(title)
    assert notice.eyes == eyes
    assert state.update(CONNECTED, (True, True), None, 2).title == "Čekam podatke o pogledu"
    assert state.update(CONNECTED, (True, True), 1, 2.1).tone != "ready"
    assert ready(state, 3).title == "Praćenje se vraća"
    assert ready(state, 3.3).tone != "ready"
    assert ready(state, 3.51).title == "Možete nastaviti"
    assert ready(state, 5.49).tone == "ready"
    assert ready(state, 5.51) is None


def test_repeated_subthreshold_gaps_warn_without_claiming_selection_is_stopped():
    state = TrackingFeedbackState()
    for start in (1, 2):
        assert state.update(CONNECTED, (True, False), None, start) is None
        assert ready(state, start + 0.4) is None
    state.update(CONNECTED, (True, False), None, 3)
    notice = ready(state, 3.4)
    assert notice.title == "Praćenje često prekida"
    assert notice.eyes == (True, True)
    assert "zaustavljen" not in notice.text
    assert ready(state, 3.91).tone == "ready"
    assert ready(state, 5.91) is None
    assert ready(state, 6) is None  # Old history must not reopen the banner every tick.
    state.update(CONNECTED, (False, False), None, 6.1)
    assert ready(state, 6.2) is None  # Nor can a subsequent short blink reopen it.


def test_repeated_gaps_age_out_and_normal_short_blinks_do_not_accumulate():
    state = TrackingFeedbackState()
    for start in range(20):
        state.update(CONNECTED, (False, False), None, start)
        assert ready(state, start + 0.2) is None
    for start in (25, 26, 40):
        state.update(CONNECTED, (False, True), None, start)
        assert ready(state, start + 0.4) is None


def test_new_problem_interrupts_green_and_requires_another_stable_recovery():
    state = TrackingFeedbackState()
    state.update(CONNECTED, (True, False), None, 0)
    state.update(CONNECTED, (True, False), None, 1)
    ready(state, 2)
    assert ready(state, 2.51).tone == "ready"
    assert state.update(CONNECTED, (False, True), None, 2.6).title.startswith("Lijevo")
    ready(state, 2.7)
    assert ready(state, 3).tone != "ready"
    assert ready(state, 3.21).tone == "ready"


@pytest.mark.parametrize(
    ("tracking", "title", "tone"),
    [
        (TrackingState.CONNECTING, "Povezivanje s uređajem", "quiet"),
        (TrackingState.WAITING, "Čekam podatke o pogledu", "quiet"),
        (TrackingState.RETRYING, "Uređaj nije povezan", "error"),
    ],
)
def test_lifecycle_message_takes_precedence_over_invalid_eye_placeholders(tracking, title, tone):
    state = TrackingFeedbackState()
    status = TrackingStatus(tracking, "Diagnostic text must not become UI copy")
    state.update(status, (False, False), None, 0)
    notice = state.update(status, (False, False), None, 1)
    assert notice.title == title
    assert notice.tone == tone
    assert notice.eyes is None


def test_stale_gaze_is_not_ready_even_when_both_eyes_are_valid():
    state = TrackingFeedbackState()
    ready(state, 0)
    assert state.update(CONNECTED, (True, True), 0, 0.6) is None
    notice = state.update(CONNECTED, (True, True), 0, 1.5)
    assert notice.title == "Čekam podatke o pogledu"
    assert notice.tone != "ready"


def test_repeated_connection_gaps_do_not_suggest_repositioning_eyes():
    state = TrackingFeedbackState()
    for start in (1, 2, 3, 4):
        state.update(TrackingStatus(TrackingState.RETRYING), None, None, start)
        assert ready(state, start + 0.4) is None


@pytest.mark.parametrize(
    "tracking", [TrackingState.STOPPED, TrackingState.SIMULATING, TrackingState.UNAVAILABLE]
)
def test_inactive_or_non_tobii_context_clears_without_success(tracking):
    state = TrackingFeedbackState()
    state.update(CONNECTED, (False, True), None, 0)
    assert state.update(CONNECTED, (False, True), None, 1) is not None
    assert state.update(TrackingStatus(tracking), None, None, 2) is None
    assert ready(state, 3) is None
    state.update(CONNECTED, (False, True), None, 4)
    state.update(CONNECTED, (False, True), None, 5)
    assert state.update(CONNECTED, (False, True), None, 6, active=False) is None
    assert state.update(CONNECTED, (False, True), None, 7) is None
    assert state.update(CONNECTED, (False, True), None, 7.81) is not None
