from __future__ import annotations

from types import SimpleNamespace

import pytest
from _hotbar_fixtures import hotbar_gaze as hotbar_gaze
from PySide6.QtCore import QPoint

from pogled_assist import diagnostics
from pogled_assist.interaction.mouse_controller import KEYBOARD, SETTINGS, SPEECH
from pogled_assist.ui.keyboard_window import KEYBOARD_WINDOW_ACTION_PREFIX


@pytest.mark.e2e
def test_confirmation_edge_hold_keeps_one_diagnostic_attempt(hotbar_gaze, qtbot, monkeypatch):
    events = []
    writer = SimpleNamespace(
        _generation=1, trace=True, event=lambda name, data, **_kwargs: events.append((name, data))
    )
    monkeypatch.setattr(diagnostics, "diagnostic_writer", lambda: writer)
    hotbar, controller, feed, actions, _progress = hotbar_gaze
    hotbar._open_speech()
    window = hotbar._speech_window
    window.showNormal()
    window.setGeometry(*controller._logical_screen_rect)
    qtbot.wait(1)
    window._input.setText("Synthetic message")
    window._open_clear_dialog()
    qtbot.wait(1)
    action = window._action("confirm:accept")
    button = window._action_buttons[action]
    center = button.mapToGlobal(button.rect().center())
    outside = button.mapToGlobal(QPoint(button.width() + 2, button.height() // 2))
    feed(center, 0)
    feed(center, 700)
    observer = controller._toolbar_selection._observer
    attempt, context = observer.attempt, observer.context.id
    feed(outside, 720)
    assert controller._toolbar_selection.diagnostic_snapshot()["held"]
    assert controller._toolbar_selection.target == action
    assert observer.attempt == attempt
    assert observer.context.id == context
    feed(center, 760)
    assert actions == []
    assert observer.attempt == attempt
    assert observer.context.id == context
    assert not any(name == "selection_end" for name, _data in events)
    assert controller._toolbar_selection.diagnostic_snapshot()["credited_ms"] == 700
    controller.handle_eye_status(True, False)
    ends = [data for name, data in events if name == "selection_end"]
    assert len(ends) == 1
    assert ends[0]["attempt_id"] == attempt
    assert ends[0]["reason"] == "eye_gate_closed"
    assert ends[0]["context_id"] == context


@pytest.mark.e2e
@pytest.mark.parametrize("action", [SPEECH, KEYBOARD, SETTINGS])
def test_hotbar_gaze_acquires_buttons_at_top_edge(hotbar_gaze, monkeypatch, action):
    hotbar, _controller, feed, actions, _progress = hotbar_gaze
    from pogled_assist.ui import settings_window

    monkeypatch.setattr(settings_window, "is_windows_startup_enabled", lambda: False)
    point = hotbar._buttons[action].mapToGlobal(QPoint(50, 0))
    point.setY(0)
    assert hotbar.action_at_global_point(point) == action
    feed(point, 0)
    feed(point, 800)
    assert hotbar._buttons[action].property("gazeTarget") is True
    feed(point, 1001)
    assert actions == [action]
    opened = {
        SPEECH: hotbar._speech_window,
        KEYBOARD: hotbar._keyboard_window,
        SETTINGS: hotbar._settings_window,
    }[action]
    assert opened is not None and opened.isVisible()


@pytest.mark.e2e
def test_hotbar_top_edge_has_distinct_targets_and_neutral_gaps(hotbar_gaze):
    hotbar, _controller, _feed, _actions, _progress = hotbar_gaze
    bounds = [(action, hotbar.action_bounds(action)) for action in hotbar._buttons]
    bounds = [(action, rect) for action, rect in bounds if rect is not None]
    for x in range(hotbar.width()):
        point = QPoint(x, 0)
        matches = [action for action, rect in bounds if rect.contains(point)]
        assert len(matches) <= 1
        assert hotbar.action_at_global_point(point) == (matches[0] if matches else None)
    hotbar._buttons[SPEECH].setEnabled(False)
    assert hotbar.action_bounds(SPEECH) is None
    hotbar.hide()
    assert hotbar.action_at_global_point(QPoint(50, 0)) is None


@pytest.mark.e2e
def test_keyboard_letter_entry_survives_brief_edge_jitter(hotbar_gaze, qtbot):
    hotbar, controller, feed, actions, _progress = hotbar_gaze
    hotbar._show_keyboard_sidebar()
    window = hotbar._keyboard_window
    _, _, width, height = controller._logical_screen_rect
    window.setGeometry(width - 380, 76, 380, height - 76)
    window._show_letter_group(0)
    qtbot.wait(1)
    action = f"{KEYBOARD_WINDOW_ACTION_PREFIX}letter:0:0"
    button = window._action_buttons[action]
    center = button.mapToGlobal(button.rect().center())
    outside = button.mapToGlobal(QPoint(button.width() + 2, button.height() // 2))
    feed(center, 0)
    feed(center, 800)
    feed(outside, 820)
    feed(center, 900)
    feed(center, 1101)
    assert actions == [action]
    assert window._input.typed == ["A"]
    assert window._active_group_index is None
