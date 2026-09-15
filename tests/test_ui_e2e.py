from __future__ import annotations

from dataclasses import replace

import pytest
from PySide6.QtCore import Qt

from gaze_mouse.controller_window import (
    CONTROLLER_WINDOW_ACTION_PREFIX,
    ControllerWindow,
)
from gaze_mouse.keyboard_window import KEYBOARD_WINDOW_ACTION_PREFIX, KeyboardWindow
from gaze_mouse.mouse_controller import (
    CONTROLLER,
    KEYBOARD,
    LEFT_CLICK,
    QUICK_ACTIONS,
    SETTINGS,
    SPEECH,
    GazeSettings,
)
from gaze_mouse.settings_window import SettingsWindow
from gaze_mouse.speech_service import SpeechSettings
from gaze_mouse.speech_window import SPEECH_WINDOW_ACTION_PREFIX, SpeechWindow
from gaze_mouse.windows_startup import StartupTaskResult


class FakeSpeech:
    def __init__(self):
        self._settings = SpeechSettings()
        self.requests = []

    @property
    def settings(self):
        return replace(self._settings)

    def speak(self, text, settings=None):
        self.requests.append((text, replace(settings) if settings is not None else self.settings))
        return True


class FakeKeyboardInput:
    def __init__(self):
        self.typed = []
        self.pressed = []

    def foreground_window(self):
        return 50

    def belongs_to_current_process(self, _hwnd):
        return False

    def type_text(self, text):
        self.typed.append(text)

    def press_key(self, key):
        self.pressed.append(key)

    def is_window(self, _hwnd):
        return True

    def set_foreground_window(self, _hwnd):
        return True


class FakeControllerInput(FakeKeyboardInput):
    def __init__(self):
        super().__init__()
        self.clicks = []
        self.scrolls = []

    def click(self, x, y, **options):
        self.clicks.append((x, y, options))

    def click_current(self, **options):
        self.clicks.append((None, None, options))

    def scroll(self, units):
        self.scrolls.append(units)


@pytest.mark.e2e
def test_speech_keyboard_entry_playback_and_phrase_workflow(qtbot, monkeypatch):
    saved = []
    monkeypatch.setattr("gaze_mouse.speech_window._load_phrases", list)
    monkeypatch.setattr(
        "gaze_mouse.speech_window._save_phrases",
        lambda phrases: saved.append([(record.text, record.uses) for record in phrases]),
    )
    speech = FakeSpeech()
    window = SpeechWindow(speech)
    qtbot.addWidget(window)
    window.show()

    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:1"].click()
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}letter:1:1"].click()
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}space"].click()
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"].click()
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:0"].click()
    window._play_button.click()

    assert window._input.text() == "Dž A"
    assert speech.requests[0][0] == "Dž A"

    window._phrases_button.click()
    window._new_phrase_button.click()
    window._input.setText("  Trebam   pomoć ")
    window._save_phrase_button.click()

    assert saved[-1] == [("Trebam pomoć", 0)]
    assert window._input.text() == "Dž A"

    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}phrase:select:0"].click()
    assert window._input.text() == "Dž A Trebam pomoć "
    assert saved[-1] == [("Trebam pomoć", 1)]


@pytest.mark.e2e
def test_keyboard_sidebar_routes_letters_numbers_symbols_and_keys(qtbot):
    window = KeyboardWindow(SpeechSettings(letters_per_group=5))
    qtbot.addWidget(window)
    fake_input = FakeKeyboardInput()
    window._input = fake_input

    window._action_buttons[f"{KEYBOARD_WINDOW_ACTION_PREFIX}group:0"].click()
    window._action_buttons[f"{KEYBOARD_WINDOW_ACTION_PREFIX}letter:0:0"].click()
    window._action_buttons[f"{KEYBOARD_WINDOW_ACTION_PREFIX}tab:numpad"].click()
    window._action_buttons[f"{KEYBOARD_WINDOW_ACTION_PREFIX}numpad_group:0"].click()
    window._action_buttons[f"{KEYBOARD_WINDOW_ACTION_PREFIX}numpad:0"].click()
    window._action_buttons[f"{KEYBOARD_WINDOW_ACTION_PREFIX}tab:symbols"].click()
    window._action_buttons[f"{KEYBOARD_WINDOW_ACTION_PREFIX}symbol_group:0"].click()
    window._action_buttons[f"{KEYBOARD_WINDOW_ACTION_PREFIX}symbol:1"].click()
    window._action_buttons[f"{KEYBOARD_WINDOW_ACTION_PREFIX}backspace"].click()

    assert fake_input.typed == ["A", "7", ","]
    assert fake_input.pressed == ["backspace"]


@pytest.mark.e2e
def test_settings_controls_emit_bounded_updates(qtbot, monkeypatch):
    monkeypatch.setattr("gaze_mouse.settings_window.is_windows_startup_enabled", lambda: False)
    monkeypatch.setattr("gaze_mouse.settings_window.set_application_logging_enabled", lambda _enabled: None)
    monkeypatch.setattr(
        "gaze_mouse.settings_window.set_windows_startup_enabled",
        lambda enabled, **_options: StartupTaskResult(enabled, True, "updated"),
    )
    window = SettingsWindow(GazeSettings(), SpeechSettings())
    qtbot.addWidget(window)
    gaze_updates = []
    speech_updates = []
    window.gaze_settings_changed.connect(gaze_updates.append)
    window.speech_settings_changed.connect(speech_updates.append)
    window.show()

    qtbot.mouseClick(window._gaze_tab_button, Qt.LeftButton)
    qtbot.mouseClick(window._move_pointer_button, Qt.LeftButton)
    qtbot.mouseClick(window._precision_zoom_checkbox, Qt.LeftButton)
    for _ in range(100):
        window._adjust_dwell_ms(-100)
        window._adjust_smoothing(-0.1)
    qtbot.mouseClick(window._speech_tab_button, Qt.LeftButton)
    for _ in range(100):
        window._adjust_speech_speed(10)
        window._adjust_letters_per_group(1)
    window._cycle_voice_preset()

    assert window._stack.currentIndex() == 2
    assert gaze_updates[-1].move_mouse is False
    assert gaze_updates[-1].use_precision_zoom is False
    assert gaze_updates[-1].dwell_ms == 150
    assert gaze_updates[-1].smoothing == 0.05
    assert speech_updates[-1].speed == 320
    assert speech_updates[-1].letters_per_group == 12
    assert speech_updates[-1].voice_preset == "human_like"


@pytest.mark.e2e
def test_controller_routes_shortcuts_keyboard_and_quick_settings(qtbot, monkeypatch):
    window = ControllerWindow(GazeSettings(), SpeechSettings())
    qtbot.addWidget(window)
    fake_input = FakeControllerInput()
    window._input = fake_input
    window.set_target_cursor_position((300, 400))
    settings = []
    speech_requests = []
    window.gaze_settings_changed.connect(settings.append)
    window.speech_requested.connect(lambda: speech_requests.append(True))

    window._trigger_action(f"{CONTROLLER_WINDOW_ACTION_PREFIX}left_click", source="mouse")
    window._trigger_action(f"{CONTROLLER_WINDOW_ACTION_PREFIX}double_left_click", source="gaze")
    window._trigger_action(f"{CONTROLLER_WINDOW_ACTION_PREFIX}enter")
    window._trigger_action(f"{CONTROLLER_WINDOW_ACTION_PREFIX}scroll_up")
    window._trigger_action(f"{CONTROLLER_WINDOW_ACTION_PREFIX}tab:keyboard")
    window._trigger_action(f"{CONTROLLER_WINDOW_ACTION_PREFIX}keyboard_group:0")
    window._trigger_action(f"{CONTROLLER_WINDOW_ACTION_PREFIX}keyboard_letter:0:0")
    window._trigger_action(f"{CONTROLLER_WINDOW_ACTION_PREFIX}tab:settings")
    window._trigger_action(f"{CONTROLLER_WINDOW_ACTION_PREFIX}settings:precision_zoom")
    window._trigger_action(f"{CONTROLLER_WINDOW_ACTION_PREFIX}settings:gaze_cursor")
    window._trigger_action(f"{CONTROLLER_WINDOW_ACTION_PREFIX}tab:speech")

    assert fake_input.clicks[0] == (300, 400, {"button": "left", "clicks": 1, "interval": 0.04})
    assert fake_input.clicks[1] == (None, None, {"button": "left", "clicks": 2, "interval": 0.04})
    assert fake_input.pressed == ["enter"]
    assert fake_input.scrolls == [3]
    assert fake_input.typed == ["A"]
    assert settings[-1].use_precision_zoom is False
    assert settings[-1].show_gaze_bubble is False
    assert speech_requests == [True]


class FakeAppBar:
    supported = False

    def register(self, *_args, **_kwargs):
        return False

    def unregister(self):
        return None

    def set_position(self, *_args):
        return None


class FakeHotbarInput(FakeControllerInput):
    def cursor_position(self):
        return 600, 500


class FakeSpeechService(FakeSpeech):
    available = True

    def update_settings(self, settings):
        self._settings = replace(settings)

    def stop(self):
        return None


@pytest.mark.e2e
def test_hotbar_coordinates_primary_ui_surfaces(qtbot, monkeypatch):
    from gaze_mouse import controller_window, keyboard_window, settings_window, toolbar

    monkeypatch.setattr(toolbar, "WindowsAppBar", FakeAppBar)
    monkeypatch.setattr(toolbar, "WindowsInputController", FakeHotbarInput)
    monkeypatch.setattr(toolbar, "SpeechService", FakeSpeechService)
    monkeypatch.setattr(toolbar, "load_app_settings", lambda: (GazeSettings(), SpeechSettings()))
    monkeypatch.setattr(toolbar, "save_app_settings", lambda *_settings: None)
    monkeypatch.setattr(keyboard_window, "WindowsAppBar", FakeAppBar)
    monkeypatch.setattr(keyboard_window, "WindowsInputController", FakeHotbarInput)
    monkeypatch.setattr(controller_window, "WindowsAppBar", FakeAppBar)
    monkeypatch.setattr(controller_window, "WindowsInputController", FakeHotbarInput)
    monkeypatch.setattr(settings_window, "is_windows_startup_enabled", lambda: False)

    window = toolbar.HotbarWindow()
    qtbot.addWidget(window)

    window._run_toolbar_action(LEFT_CLICK, checked=True, source="mouse")
    assert window._mouse.active_mode == LEFT_CLICK

    window._run_toolbar_action(QUICK_ACTIONS, checked=True, source="mouse")
    assert window._mouse.quick_actions_enabled is True
    assert window._buttons[LEFT_CLICK].isHidden()

    window._run_toolbar_action(KEYBOARD, checked=True, source="mouse")
    assert window._keyboard_window is not None and window._keyboard_window.isVisible()

    window._run_toolbar_action(CONTROLLER, checked=True, source="mouse")
    assert window._keyboard_window.isHidden()
    assert window._controller_window is not None and window._controller_window.isVisible()

    window._run_toolbar_action(SPEECH, source="mouse")
    assert window._speech_window is not None and window._speech_window.isVisible()

    window._run_toolbar_action(SETTINGS, source="mouse")
    assert window._controller_window.isHidden()
    assert window._settings_window is not None and window._settings_window.isVisible()
