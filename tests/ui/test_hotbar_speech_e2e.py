from __future__ import annotations

import pytest
from _hotbar_fixtures import hotbar_gaze as hotbar_gaze
from _hotbar_fixtures import speech_gaze as speech_gaze
from _ui_fakes import click_speech_action
from PySide6.QtCore import QPoint

from pogled_assist.ui.speech_window import SPEECH_WINDOW_ACTION_PREFIX


@pytest.mark.e2e
def test_inline_replacement_requires_leaving_before_selecting_a_letter(speech_gaze, qtbot):
    window, _controller, _speech, feed, actions, _progress = speech_gaze
    group = window._action_buttons[window._action("group:0")]
    center = group.mapToGlobal(group.rect().center())
    feed(center, 0)
    feed(center, 1001)
    assert actions == [window._action("group:0")]
    qtbot.waitUntil(window._action_buttons[window._action("letter:0:0")].isVisible)
    replacement = next(
        action
        for action in window._main_dynamic_actions
        if window._action_buttons[action]
        .rect()
        .contains(window._action_buttons[action].mapFromGlobal(center))
    )
    assert replacement.startswith(window._action("letter:"))
    assert window.action_at_global_point(center) is None
    feed(center, 1400)
    feed(center, 3000)
    assert window._input.text() == ""
    assert actions == [window._action("group:0")]
    space = window._space_button.mapToGlobal(window._space_button.rect().center())
    feed(space, 3100)
    feed(center, 3200)
    feed(center, 4201)
    assert actions == [window._action("group:0"), replacement]
    assert window._input.text()
    feed(center, 4600)
    feed(center, 6000)
    assert actions == [window._action("group:0"), replacement]
    click_speech_action(qtbot, window, "group:1")
    assert window._active_group_index == 1


@pytest.mark.e2e
def test_efendija_failed_test_keeps_classified_reason_after_playback_event(
    hotbar_gaze, monkeypatch
):
    hotbar = hotbar_gaze[0]
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    hotbar._open_settings()
    hotbar._test_efendija()
    request = hotbar._efendija_test_id
    message = "Proba Efendije nije uspjela. ElevenLabs ključ nema potrebne dozvole."
    hotbar._speech.test_finished.emit(request, message)
    hotbar._speech.playback_changed.emit(request, "failed")
    assert hotbar._settings_window._status_label.text() == message


@pytest.mark.e2e
@pytest.mark.parametrize("command", ["group:0", "letter:0:0", "suggestion:0", "play"])
def test_speech_gaze_keeps_progress_through_brief_edge_excursion(speech_gaze, qtbot, command):
    window, _controller, speech, feed, actions, progress = speech_gaze
    window._input.setText("ŽELIM ")
    if command.startswith("letter:"):
        click_speech_action(qtbot, window, "group:0")
    button = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}{command}"]
    center = button.mapToGlobal(button.rect().center())
    outside = button.mapToGlobal(QPoint(button.width() + 4, button.height() // 2))
    expected_word = button.text()

    feed(center, 0)
    feed(center, 800)
    assert progress[-1] == pytest.approx(0.6)
    feed(outside, 820)
    feed(outside, 840)
    feed(center, 860)
    assert progress[-1] == pytest.approx(0.6)
    feed(center, 1040)
    assert actions == []
    feed(center, 1061)

    assert actions == [f"{SPEECH_WINDOW_ACTION_PREFIX}{command}"]
    if command == "letter:0:0":
        assert window._input.text() == "ŽELIM A"
    elif command == "suggestion:0":
        assert window._input.text() == f"ŽELIM {expected_word} "
    elif command == "play":
        assert speech.requests[0][0] == "ŽELIM"
    else:
        assert window._active_group_index == 0
        assert window._dialogs.active is None


@pytest.mark.e2e
@pytest.mark.parametrize("near_edge", [True, False])
def test_speech_gaze_switches_letters_without_transferring_progress(speech_gaze, qtbot, near_edge):
    window, _controller, _speech, feed, actions, _progress = speech_gaze
    click_speech_action(qtbot, window, "group:0")
    first = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:0"]
    second = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:1"]
    first_center = first.mapToGlobal(first.rect().center())
    second_point = second.mapToGlobal(
        QPoint(2, second.height() // 2) if near_edge else second.rect().center()
    )
    assert window.action_at_global_point(second_point) == f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:1"
    feed(first_center, 0)
    feed(first_center, 980)
    feed(second_point, 1000)
    feed(second_point, 1100)
    assert actions == []
    feed(second_point, 1121)
    finish = 2122 if near_edge else 2001
    feed(second_point, finish - 2)
    assert actions == []
    feed(second_point, finish)
    assert window._input.text() == "B"
    assert actions == [f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:1"]


@pytest.mark.e2e
def test_speech_gaze_can_return_from_neighbor_without_selecting_it(speech_gaze, qtbot):
    window, _controller, _speech, feed, actions, progress = speech_gaze
    click_speech_action(qtbot, window, "group:0")
    first = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:0"]
    second = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:1"]
    center = first.mapToGlobal(first.rect().center())
    neighbor = second.mapToGlobal(QPoint(2, second.height() // 2))
    feed(center, 0)
    feed(center, 980)
    feed(neighbor, 1000)
    feed(neighbor, 1060)
    assert actions == []
    assert progress[-1] == pytest.approx(0.96)
    feed(center, 1080)
    assert actions == []
    feed(center, 1101)
    assert window._input.text() == "A"


@pytest.mark.e2e
@pytest.mark.parametrize("cancel", ["eye_loss", "mouse", "resize", "disable"])
def test_speech_gaze_discards_held_progress_when_context_is_lost(speech_gaze, qtbot, cancel):
    window, controller, _speech, feed, actions, _progress = speech_gaze
    button = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"]
    center = button.mapToGlobal(button.rect().center())
    outside = button.mapToGlobal(QPoint(button.width() + 4, button.height() // 2))
    feed(center, 0)
    feed(center, 800)
    feed(outside, 820)
    if cancel == "eye_loss":
        controller.handle_eye_status(True, False)
        feed(center, 840)
        controller.handle_eye_status(True, True)
    elif cancel == "mouse":
        click_speech_action(qtbot, window, "group:1")
        click_speech_action(qtbot, window, "letters:close")
        button = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"]
        qtbot.waitUntil(button.isVisible)
    elif cancel == "resize":
        window.resize(window.width() - 20, window.height())
        qtbot.wait(1)
    else:
        button.setEnabled(False)
        feed(center, 840)
        button.setEnabled(True)
    center = button.mapToGlobal(button.rect().center())
    feed(center, 860)
    feed(center, 1061)
    assert actions == []
    if cancel in {"mouse", "resize"}:
        other = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:1"]
        feed(other.mapToGlobal(other.rect().center()), 1080)
        feed(center, 1100)
    feed(center, 2101)
    assert actions == [f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"]


@pytest.mark.e2e
@pytest.mark.parametrize("during_hold", [False, True])
def test_speech_gaze_changed_suggestion_requires_confirmed_departure(speech_gaze, during_hold):
    window, _controller, _speech, feed, actions, _progress = speech_gaze
    button = window._prediction_buttons[0]
    center = button.mapToGlobal(button.rect().center())
    outside = button.mapToGlobal(QPoint(button.width() + 4, button.height() // 2))
    feed(center, 0)
    feed(center, 800)
    if during_hold:
        feed(outside, 820)
    window._input.setText("ŽELIM ")
    feed(center, 860)
    feed(center, 2000)
    assert actions == []
    feed(outside, 2020)
    feed(center, 2060)
    feed(center, 3500)
    assert actions == []
    other = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"]
    feed(other.mapToGlobal(other.rect().center()), 3520)
    feed(center, 3540)
    feed(center, 4541)
    assert window._input.text() == "ŽELIM VODU "


@pytest.mark.e2e
def test_speech_gaze_switch_during_cooldown_waits_before_starting_selection(speech_gaze):
    window, _controller, _speech, feed, actions, _progress = speech_gaze
    window._input.setText("ŽELIM ")
    play = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}play"]
    group = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"]
    play_center = play.mapToGlobal(play.rect().center())
    group_center = group.mapToGlobal(group.rect().center())
    feed(play_center, 0)
    feed(play_center, 1001)
    feed(group_center, 1020)
    feed(group_center, 1340)
    feed(group_center, 1360)
    feed(group_center, 2359)
    assert actions == [f"{SPEECH_WINDOW_ACTION_PREFIX}play"]
    assert window._dialogs.active is None
    feed(group_center, 2361)
    assert actions == [
        f"{SPEECH_WINDOW_ACTION_PREFIX}play",
        f"{SPEECH_WINDOW_ACTION_PREFIX}group:0",
    ]
    assert window._active_group_index == 0
    assert window._dialogs.active is None


@pytest.mark.e2e
@pytest.mark.parametrize("command", ["play", "suggestion:0"])
def test_speech_gaze_edge_jitter_cannot_repeat_completed_action(speech_gaze, command):
    window, _controller, _speech, feed, actions, _progress = speech_gaze
    window._input.setText("ŽELIM ")
    button = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}{command}"]
    center = button.mapToGlobal(button.rect().center())
    outside = button.mapToGlobal(QPoint(button.width() + 4, button.height() // 2))
    feed(center, 0)
    feed(center, 1001)
    assert len(actions) == 1
    feed(outside, 1020)
    feed(center, 1060)
    feed(center, 2400)
    feed(outside, 2420)
    feed(center, 2460)
    feed(center, 3800)
    assert len(actions) == 1
    feed(outside, 3820)
    feed(outside, 3941)
    feed(center, 3960)
    feed(center, 4961)
    assert len(actions) == 2


@pytest.mark.e2e
def test_speech_bottom_edge_gaze_cannot_restart_after_playback_completes(speech_gaze, qtbot):
    window, _controller, speech, feed, actions, _progress = speech_gaze
    window._input.setText("ŽELIM VODU")
    qtbot.wait(1)
    button = window._play_button
    point = button.mapToGlobal(QPoint(button.width() // 2, button.height() - 2))
    feed(point, 0)
    feed(point, 1001)
    request = speech.request_id
    assert len(actions) == 1
    qtbot.wait(1)
    feed(point, 1100)
    feed(point, 1250)
    speech.playback_changed.emit(request, "finished")
    qtbot.wait(1)
    feed(point, 1500)
    feed(point, 2501)
    assert len(actions) == 1
    assert len(speech.requests) == 1


@pytest.mark.e2e
@pytest.mark.parametrize("command", ["play", "suggestion:0"])
@pytest.mark.parametrize("during_cooldown", [False, True])
def test_speech_gaze_can_repeat_after_departure_with_no_expiry_sample(
    speech_gaze, command, during_cooldown
):
    window, _controller, _speech, feed, actions, _progress = speech_gaze
    window._input.setText("ŽELIM ")
    button = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}{command}"]
    center = button.mapToGlobal(button.rect().center())
    outside = button.mapToGlobal(QPoint(button.width() + 4, button.height() // 2))
    feed(center, 0)
    feed(center, 1001)
    feed(center, 1010 if during_cooldown else 1400)
    assert len(actions) == 1
    feed(outside, 1020 if during_cooldown else 1420)
    # Return after the 120 ms hold, without another sample while outside.
    feed(center, 1160 if during_cooldown else 1560)
    start = 1360 if during_cooldown else 1560
    feed(center, start)
    feed(center, start + 999)
    assert len(actions) == 1
    feed(center, start + 1001)
    assert len(actions) == 2
