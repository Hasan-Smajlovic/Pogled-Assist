from __future__ import annotations

from itertools import product

import pytest
from _ui_fakes import FakeAppBar, FakeControllerInput, FakeKeyboardInput
from PySide6.QtCore import QPoint, QRect

from pogled_assist.interaction.mouse_controller import GazeSettings
from pogled_assist.keyboard_layouts import ARABIC_LETTERS, ARABIC_SYMBOLS, SYMBOL_KEYS
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.ui.controller_window import (
    CONTROLLER_WINDOW_ACTION_PREFIX,
    ControllerWindow,
)
from pogled_assist.ui.keyboard_window import KEYBOARD_WINDOW_ACTION_PREFIX, KeyboardWindow
from pogled_assist.ui.speech_window import BOSNIAN_LETTERS


@pytest.mark.e2e
@pytest.mark.parametrize("kind", ["keyboard", "controller"])
@pytest.mark.parametrize(
    "layout",
    [
        pytest.param((script, letters), id=f"{letters}-{script}")
        for letters, script in product((1, 2, 5, 12), ("latin", "arabic"))
    ],
)
def test_sidebar_pages_fit_and_send_actual_unicode(qtbot, monkeypatch, kind, layout):
    from pogled_assist.ui import sidebar_panel

    monkeypatch.setattr(sidebar_panel, "WindowsAppBar", FakeAppBar)
    script, letters_per_group = layout
    settings = SpeechSettings(keyboard_script=script, letters_per_group=letters_per_group)
    sidebar = _Sidebar(qtbot, kind, settings)
    for symbols in (False, True):
        sidebar.check_pages(symbols)
    expected = (
        ARABIC_LETTERS + ARABIC_SYMBOLS if script == "arabic" else BOSNIAN_LETTERS + SYMBOL_KEYS
    )
    assert set(expected) <= set(sidebar.input.typed)
    sidebar.window._script_button.click()
    assert (
        sidebar.window._group_page if kind == "keyboard" else sidebar.window._keyboard_group_page
    ) == 0


class _Sidebar:
    def __init__(self, qtbot, kind, settings):
        self.qtbot = qtbot
        self.kind = kind
        self.settings = settings
        self.window = (
            KeyboardWindow(settings)
            if kind == "keyboard"
            else ControllerWindow(GazeSettings(), settings)
        )
        qtbot.addWidget(self.window)
        self.input = FakeControllerInput()
        self.window._input = self.input
        self.window.set_target_window(50)
        self.prefix = (
            KEYBOARD_WINDOW_ACTION_PREFIX if kind == "keyboard" else CONTROLLER_WINDOW_ACTION_PREFIX
        )
        if kind == "controller":
            self.window._show_settings_tab()
            self.window.show()
            qtbot.wait(1)
            self.window._show_keyboard_tab()
        self.window.resize(380, 640)
        self.window.show()

    def check_pages(self, symbols):
        window = self.window
        if symbols:
            (window._show_symbols if self.kind == "keyboard" else window._show_keyboard_symbols)()
        groups = window._symbol_groups if symbols else window._letter_groups
        pages = (len(groups) + 7) // 8
        for page in range(pages):
            self._check_page(page, pages, symbols)
            self._check_buttons()
            for group_index in range(page * 8, min(len(groups), (page + 1) * 8)):
                self._type_group(groups, group_index, symbols)
            if page + 1 < pages:
                window._action_buttons[self._page_action(1)].click()

    def _check_page(self, page, pages, symbols):
        window = self.window
        self.qtbot.wait(1)
        assert window.width() <= 380 and window.height() <= 640, (
            self.kind,
            self.settings.keyboard_script,
            self.settings.letters_per_group,
            symbols,
            page,
            window.size(),
        )
        assert window._script_button.isVisible()
        if pages > 1:
            assert window._action_buttons[self._page_action(-1)].isEnabled() == (page > 0)
            assert window._action_buttons[self._page_action(1)].isEnabled() == (page + 1 < pages)

    def _check_buttons(self):
        window = self.window
        bounds = window.rect()
        for button in window._action_buttons.values():
            if not button.isVisible():
                continue
            assert bounds.contains(
                QRect(button.mapTo(window, QPoint(0, 0)), button.size())
            ), button.text()
            assert button.height() >= (
                46
                if self.kind == "controller" and button.objectName() == "keyboardSubTabButton"
                else 52
            )
            if button.objectName() == "groupButton":
                assert all(
                    button.fontMetrics().horizontalAdvance(line) <= button.width() - 12
                    for line in button.text().splitlines()
                ), button.text()

    def _type_group(self, groups, group_index, symbols):
        window = self.window
        group_action = self._group_action(group_index, symbols)
        window._action_buttons[group_action].click()
        for index, key in enumerate(groups[group_index]):
            key_action = (
                ("symbol:" if symbols else f"letter:{group_index}:")
                if self.kind == "keyboard"
                else ("keyboard_symbol:" if symbols else f"keyboard_letter:{group_index}:")
            )
            window._action_buttons[self.prefix + key_action + str(index)].click()
            assert self.input.typed[-1] == key
            # Selecting a key closes its group, so reopen it before the next key.
            if index < len(groups[group_index]) - 1:
                window._action_buttons[group_action].click()
        (
            window._show_current_group_level
            if self.kind == "keyboard"
            else window._show_keyboard_current_group_level
        )()

    def _group_action(self, group_index, symbols):
        commands = {
            "keyboard": ("group:", "symbol_group:"),
            "controller": ("keyboard_group:", "keyboard_symbol_group:"),
        }
        return self.prefix + commands[self.kind][symbols] + str(group_index)

    def _page_action(self, direction):
        command = "group-page" if self.kind == "keyboard" else "keyboard-page"
        return f"{self.prefix}{command}:{direction}"


@pytest.mark.e2e
def test_keyboard_sidebar_routes_letters_numbers_symbols_and_keys(qtbot):
    window = KeyboardWindow(SpeechSettings(letters_per_group=5))
    qtbot.addWidget(window)
    assert window.windowTitle() == "Tastatura"
    assert [button.text() for button in window._tab_buttons.values()] == [
        "Slova",
        "Brojevi",
        "Znakovi",
    ]
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
def test_controller_routes_shortcuts_keyboard_and_quick_settings(qtbot, monkeypatch):
    window = ControllerWindow(GazeSettings(), SpeechSettings())
    qtbot.addWidget(window)
    assert window.windowTitle() == "Upravljač"
    assert [button.text() for button in window._tab_buttons.values()] == [
        "Opće",
        "Tastatura",
        "Govor",
        "Postavke",
    ]
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
