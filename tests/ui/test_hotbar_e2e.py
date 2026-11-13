from __future__ import annotations

import pytest
from _hotbar_fixtures import edge_surface as edge_surface
from _hotbar_fixtures import hotbar_gaze as hotbar_gaze
from _ui_fakes import FakeAppBar, FakeHotbarInput, FakeSpeechService
from PySide6.QtCore import QPoint

from pogled_assist.interaction.mouse_controller import (
    KEYBOARD,
    LEFT_CLICK,
    QUICK_ACTIONS,
    SCROLL_DOWN,
    SETTINGS,
    SPEECH,
    TYPE_HERE,
    GazeScreenPoint,
    GazeSettings,
)
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.toolbar import HotbarWindow

# Bound before the hotbar fixture replaces startup services with a no-op.
REAL_START_SERVICES = HotbarWindow._start_services


@pytest.mark.e2e
def test_hotbar_coordinates_primary_ui_surfaces(qtbot, monkeypatch):
    from pogled_assist import toolbar
    from pogled_assist.ui import settings_window, sidebar_panel

    monkeypatch.setattr(toolbar, "WindowsAppBar", FakeAppBar)
    monkeypatch.setattr(toolbar, "WindowsInputController", FakeHotbarInput)
    monkeypatch.setattr(toolbar, "SpeechService", FakeSpeechService)
    monkeypatch.setattr(toolbar, "load_app_settings", lambda: (GazeSettings(), SpeechSettings()))
    monkeypatch.setattr(toolbar, "save_app_settings", lambda *_settings: None)
    monkeypatch.setattr(sidebar_panel, "WindowsAppBar", FakeAppBar)
    monkeypatch.setattr(sidebar_panel, "WindowsInputController", FakeHotbarInput)
    monkeypatch.setattr(settings_window, "is_windows_startup_enabled", lambda: False)

    window = toolbar.HotbarWindow()
    qtbot.addWidget(window)
    quit_requests = []
    window._quit_application = lambda: quit_requests.append(True)

    assert window._hide_button.text() == "Sakrij"
    assert window._settings_button.text() == "Postavke"
    assert window._quick_actions_button.text() == "Brze radnje"
    assert window._foreground.ready
    assert window._foreground.window == 50
    assert "Upravljač" not in [button.text() for button in window._buttons.values()]

    window._run_toolbar_action(LEFT_CLICK, checked=True, source="mouse")
    assert window._mouse.active_mode == LEFT_CLICK

    window._run_toolbar_action(QUICK_ACTIONS, checked=True, source="mouse")
    assert window._mouse.quick_actions_enabled is True
    assert window._buttons[LEFT_CLICK].isHidden()

    window._run_toolbar_action(KEYBOARD, checked=True, source="mouse")
    assert window._keyboard_window is not None and window._keyboard_window.isVisible()

    window._run_toolbar_action(SPEECH, source="mouse")
    assert window._speech_window is not None and window._speech_window.isVisible()
    window._speech_window.quit_requested.emit()
    assert quit_requests == [True]

    window._run_toolbar_action(SETTINGS, source="mouse")
    assert window._keyboard_window.isHidden()
    assert window._settings_window is not None and window._settings_window.isVisible()


@pytest.mark.e2e
@pytest.mark.parametrize(("action", "opens_keyboard"), [(TYPE_HERE, True), (SCROLL_DOWN, False)])
def test_quick_grid_type_here_clicks_then_opens_the_keyboard(
    qtbot, monkeypatch, action, opens_keyboard
):
    from pogled_assist import toolbar
    from pogled_assist.ui import sidebar_panel

    monkeypatch.setattr(toolbar, "WindowsAppBar", FakeAppBar)
    monkeypatch.setattr(toolbar, "WindowsInputController", FakeHotbarInput)
    monkeypatch.setattr(toolbar, "SpeechService", FakeSpeechService)
    monkeypatch.setattr(toolbar, "load_app_settings", lambda: (GazeSettings(), SpeechSettings()))
    monkeypatch.setattr(toolbar, "save_app_settings", lambda *_settings: None)
    monkeypatch.setattr(sidebar_panel, "WindowsAppBar", FakeAppBar)
    monkeypatch.setattr(sidebar_panel, "WindowsInputController", FakeHotbarInput)
    window = toolbar.HotbarWindow()
    qtbot.addWidget(window)
    mouse = window._mouse
    mouse._input = FakeHotbarInput()
    mouse.handle_eye_status(True, True)
    mouse._quick_menu_open = True
    mouse._quick_target = GazeScreenPoint(QPoint(30, 40), QPoint(130, 240))

    window._quick_action_selected_handler(action)

    keyboard = window._keyboard_window
    assert (keyboard is not None and keyboard.isVisible()) is opens_keyboard
    if opens_keyboard:
        assert mouse._input.clicks == [(130, 240, {"button": "left"})]
    else:
        assert mouse._input.scrolls == [-3]


@pytest.mark.e2e
def test_hotbar_and_keyboard_hold_progress_without_selecting_outside(edge_surface):
    _window, _controller, feed, actions, progress, action, center, outside = edge_surface
    feed(center, 0)
    feed(center, 800)
    feed(outside, 820)
    feed(outside, 860)
    assert progress[-1] == pytest.approx(0.6)
    assert actions == []
    feed(center, 900)
    feed(center, 1099)
    assert actions == []
    feed(center, 1101)
    assert actions == [action]
    feed(outside, 1120)
    feed(center, 1160)
    feed(center, 2500)
    assert actions == [action]


@pytest.mark.e2e
@pytest.mark.parametrize("reset", ["eye", "long-departure", "hide", "resize"])
def test_hotbar_and_keyboard_discard_progress_after_interruption(edge_surface, reset):
    window, controller, feed, actions, _progress, _action, center, outside = edge_surface
    feed(center, 0)
    feed(center, 800)
    feed(outside, 820)
    if reset == "eye":
        controller.handle_eye_status(True, False)
        controller.handle_eye_status(True, True)
    elif reset == "long-departure":
        feed(outside, 950)
    elif reset == "hide":
        if hasattr(window, "_hide_hotbar"):
            window._hide_hotbar()
        else:
            window.hide_sidebar()
    else:
        window.resize(window.width() - 1, window.height())
    feed(center, 980)
    feed(center, 1200)
    assert actions == []


@pytest.mark.e2e
def test_startup_prepares_predictions_and_one_selection_sound_before_speech_opens(
    hotbar_gaze, monkeypatch, qtbot
):
    from pogled_assist import toolbar

    hotbar = hotbar_gaze[0]
    preloads = []
    monkeypatch.setattr(hotbar._suggestions, "preload", lambda: preloads.append(True), False)
    monkeypatch.setattr(toolbar, "PREDICTION_PRELOAD_DELAY_MS", 0)
    for service in (hotbar._mouse, hotbar._foreground, hotbar._gaze):
        monkeypatch.setattr(service, "start", lambda: None)

    # The fixture skips startup services; run the real ones.
    REAL_START_SERVICES(hotbar)
    qtbot.waitUntil(lambda: preloads == [True])

    # Speech and Settings reuse the hotbar's player instead of loading Qt Multimedia
    # again when they open.
    hotbar._open_speech()
    assert hotbar._speech_window._selection_sound is hotbar._selection_sound
    hotbar._open_settings()
    qtbot.waitUntil(lambda: hotbar._settings_window is not None)
    assert hotbar._settings_window._selection_sound is hotbar._selection_sound
