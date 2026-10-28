from __future__ import annotations

from dataclasses import replace

import pytest
from _clock import freeze_monotonic
from _hotbar_fixtures import edge_surface as edge_surface
from _hotbar_fixtures import hotbar_gaze as hotbar_gaze
from _hotbar_fixtures import speech_gaze as speech_gaze
from _ui_fakes import click_speech_action
from PySide6.QtCore import QPoint, QRect, Qt

from pogled_assist.interaction.mouse_controller import GazeSettings
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.ui.settings_window import SettingsWindow

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize(
    "edge_surface,duration",
    [("speech", 0), ("speech", 120), ("speech", 240), ("hotbar", 240), ("keyboard", 240)],
    indirect=["edge_surface"],
)
def test_saved_edge_duration_controls_real_application_targets(edge_surface, duration):
    _window, controller, feed, actions, _progress, action, center, outside = edge_surface
    controller.update_settings(replace(controller.settings, edge_hold_ms=duration))
    feed(center, 0)
    feed(center, 800)
    for at in range(820, 1000, 20):
        feed(outside, at)
    assert actions == []
    feed(center, 1000)
    credit = controller._toolbar_selection.diagnostic_snapshot()["credited_ms"]
    assert credit == (800 if duration == 240 else 0)
    for at in range(1020, 1201, 20):
        feed(center, at)
    feed(center, 1201)
    assert actions == ([action] if duration == 240 else [])
    if duration != 240:
        for at in range(1220, 2001, 20):
            feed(center, at)
        feed(center, 2001)
        assert actions == [action]


@pytest.mark.parametrize("duration", [0, 120, 240])
def test_neighbor_starts_from_zero_only_after_edge_hold_expires(speech_gaze, qtbot, duration):
    window, controller, _speech, feed, actions, _progress = speech_gaze
    controller.update_settings(replace(controller.settings, edge_hold_ms=duration))
    click_speech_action(qtbot, window, "group:0")
    first = window._action_buttons[window._action("letter:0:0")]
    second = window._action_buttons[window._action("letter:0:1")]
    a = first.mapToGlobal(first.rect().center())
    b = second.mapToGlobal(QPoint(2, second.height() // 2))
    feed(a, 0)
    feed(a, 800)
    for at in range(820, 821 + duration, 20):
        feed(b, at)
    assert actions == []
    assert controller._toolbar_selection.target == window._action("letter:0:1")
    assert controller._toolbar_selection.diagnostic_snapshot()["credited_ms"] == 0
    for at in range(840 + duration, 1820 + duration, 20):
        feed(b, at)
        assert actions == []
    feed(b, 1821 + duration)
    assert actions == [window._action("letter:0:1")]
    assert window._input.text() == "B"


def test_changing_edge_duration_discards_pending_hold(edge_surface):
    _window, controller, feed, actions, _progress, _action, center, outside = edge_surface
    feed(center, 0)
    feed(center, 800)
    feed(outside, 820)
    controller.update_settings(replace(controller.settings, edge_hold_ms=240))
    assert not controller._toolbar_selection.diagnostic_snapshot()["active"]
    feed(center, 860)
    feed(center, 1101)
    assert actions == []


@pytest.mark.parametrize("size", [(1280, 720), (1920, 1080)])
def test_edge_setting_is_gaze_operable_and_fits_without_shrinking_controls(
    qtbot, monkeypatch, size
):
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    window = SettingsWindow(GazeSettings(), SpeechSettings())
    qtbot.addWidget(window)
    window.resize(*size)
    window._select_tab(1)
    window._gaze_page.show_tab(2)
    window.show()
    qtbot.wait(1)
    page = window._gaze_page
    assert page._edge_hold_value.text() == "120 ms"
    updates = []
    window.gaze_settings_changed.connect(updates.append)
    row = page._edge_hold_value.parentWidget()
    buttons = [w for w in window._controls._actions if w.parentWidget() is row]
    assert len(buttons) == 2
    plus = next(w for w in buttons if w.text() == "+ Više")
    minus = next(w for w in buttons if w.text() == "- Manje")
    center = plus.mapToGlobal(plus.rect().center())
    assert window._controls.action_at(center)[0] is plus
    window.handle_eye_status(True, True)
    now = freeze_monotonic(monkeypatch, 10.0)
    for sample in range(57):
        now[0] = 10 + sample * 0.02
        window.handle_gaze(center)
    assert updates[-1].edge_hold_ms == 140
    for _ in range(7):
        qtbot.mouseClick(minus, Qt.LeftButton)
    assert updates[-1].edge_hold_ms == 0
    assert page._edge_hold_value.text() == "Isključeno"
    for control in window._controls._actions:
        if control.isVisible():
            assert control.height() >= 58
            assert window.rect().contains(QRect(control.mapTo(window, QPoint()), control.size()))
