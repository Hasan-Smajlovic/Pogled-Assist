from __future__ import annotations

import pytest
from _ui_fakes import FakeAppBar, FakeHotbarInput, FakeLibraryStore, FakeSpeechService

from pogled_assist.interaction.mouse_controller import GazeSettings
from pogled_assist.speech.speech_service import SpeechSettings


@pytest.fixture(params=[(1920, 1080), (1280, 720)])
def hotbar_gaze(qtbot, monkeypatch, request):
    from pogled_assist import toolbar
    from pogled_assist.ui import sidebar_panel
    from scripts.ui.capture_ui import PreviewSuggestionService

    monkeypatch.setattr(toolbar, "WindowsAppBar", FakeAppBar)
    monkeypatch.setattr(toolbar, "WindowsInputController", FakeHotbarInput)
    monkeypatch.setattr(toolbar, "SpeechService", FakeSpeechService)
    monkeypatch.setattr(toolbar, "SuggestionService", PreviewSuggestionService)
    monkeypatch.setattr(toolbar, "speech_library_store", lambda _root: FakeLibraryStore())
    monkeypatch.setattr(toolbar, "load_app_settings", lambda: (GazeSettings(), SpeechSettings()))
    monkeypatch.setattr(toolbar.HotbarWindow, "_start_services", lambda _self: None)
    monkeypatch.setattr(toolbar, "save_app_settings", lambda *_settings: None)
    monkeypatch.setattr(sidebar_panel, "WindowsAppBar", FakeAppBar)
    monkeypatch.setattr(sidebar_panel, "WindowsInputController", FakeHotbarInput)
    hotbar = toolbar.HotbarWindow(simulate_gaze=True)
    qtbot.addWidget(hotbar)
    width, height = request.param
    hotbar.show()
    hotbar.setGeometry(0, 0, width, hotbar.BAR_HEIGHT)
    qtbot.wait(1)
    controller = hotbar._mouse
    controller._logical_screen_rect = (0, 0, width, height)
    controller._physical_screen_rect = (0, 0, 1920, 1080)
    controller.handle_eye_status(True, True)
    now = [10.0]
    monkeypatch.setattr("pogled_assist.interaction.mouse_controller.time.monotonic", lambda: now[0])
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
