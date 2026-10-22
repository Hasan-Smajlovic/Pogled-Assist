from __future__ import annotations

import pytest
from _clock import freeze_monotonic
from _ui_fakes import FakeAppBar, FakeHotbarInput, FakeLibraryStore, FakeSpeechService
from PySide6.QtCore import QPoint

from pogled_assist.interaction.mouse_controller import QUICK_ACTIONS, GazeSettings
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.ui.keyboard_window import KEYBOARD_WINDOW_ACTION_PREFIX


@pytest.fixture
def hotbar_gaze(qtbot, monkeypatch, request):
    from pogled_assist import toolbar
    from pogled_assist.ui import sidebar_panel
    from scripts.ui.capture_ui import PreviewSuggestionService

    if hasattr(request, "param"):
        monkeypatch.setattr(toolbar, "TobiiGazeProvider", request.param)
    monkeypatch.setattr(toolbar, "WindowsAppBar", FakeAppBar)
    monkeypatch.setattr(toolbar, "WindowsInputController", FakeHotbarInput)
    monkeypatch.setattr(toolbar, "SpeechService", FakeSpeechService)
    monkeypatch.setattr(toolbar, "SuggestionService", PreviewSuggestionService)
    monkeypatch.setattr(toolbar, "speech_library_store", lambda _root: FakeLibraryStore())
    monkeypatch.setattr(
        toolbar,
        "load_app_settings",
        lambda: (GazeSettings(selection_pause_ms=500, dwell_ms=500), SpeechSettings()),
    )
    monkeypatch.setattr(toolbar.HotbarWindow, "_start_services", lambda _self: None)
    monkeypatch.setattr(toolbar, "save_app_settings", lambda *_settings: None)
    monkeypatch.setattr(sidebar_panel, "WindowsAppBar", FakeAppBar)
    monkeypatch.setattr(sidebar_panel, "WindowsInputController", FakeHotbarInput)
    hotbar = toolbar.HotbarWindow(simulate_gaze=not hasattr(request, "param"))
    qtbot.addWidget(hotbar)
    # Exercise physical/logical mapping at the target display's 150% scaling.
    width, height = 1280, 720
    hotbar.show()
    hotbar.setGeometry(0, 0, width, hotbar.BAR_HEIGHT)
    qtbot.wait(1)
    controller = hotbar._mouse
    if hasattr(request, "param"):
        controller._input = FakeHotbarInput()
    controller._logical_screen_rect = (0, 0, width, height)
    controller._physical_screen_rect = (0, 0, 1920, 1080)
    controller.handle_eye_status(True, True)
    now = freeze_monotonic(monkeypatch, 10.0)
    actions = []
    progress = []
    controller.toolbar_action_requested.connect(actions.append)
    controller.interaction_progress_changed.connect(
        lambda _point, value, _label: progress.append(value)
    )

    def feed(point, milliseconds):
        now[0] = 10.0 + milliseconds / 1000
        controller.handle_gaze(point.x() / (width - 1), point.y() / (height - 1), milliseconds)

    return hotbar, controller, feed, actions, progress


@pytest.fixture(params=["hotbar", "keyboard"])
def edge_surface(hotbar_gaze, qtbot, request):
    hotbar, controller, feed, actions, progress = hotbar_gaze
    if request.param == "hotbar":
        window = hotbar
        action = QUICK_ACTIONS
        button = hotbar._buttons[action]
    elif request.param == "speech":
        hotbar._open_speech()
        window = hotbar._speech_window
        window.showNormal()
        window.setGeometry(*controller._logical_screen_rect)
        qtbot.wait(1)
        action = window._action("group:0")
        button = window._action_buttons[action]
    else:
        hotbar._show_keyboard_sidebar()
        window = hotbar._keyboard_window
        _, _, width, height = controller._logical_screen_rect
        window.setGeometry(width - 380, hotbar.BAR_HEIGHT, 380, height - hotbar.BAR_HEIGHT)
        qtbot.wait(1)
        action = f"{KEYBOARD_WINDOW_ACTION_PREFIX}space"
        button = window._space_button
    center = button.mapToGlobal(button.rect().center())
    outside = button.mapToGlobal(QPoint(button.width() + 2, button.height() // 2))
    return window, controller, feed, actions, progress, action, center, outside


@pytest.fixture
def speech_gaze(hotbar_gaze, qtbot):
    hotbar, controller, feed, actions, progress = hotbar_gaze
    hotbar._open_speech()
    window = hotbar._speech_window
    window.showNormal()
    window.setGeometry(*controller._logical_screen_rect)
    qtbot.waitUntil(window.isVisible)
    qtbot.wait(1)
    return window, controller, hotbar._speech, feed, actions, progress
