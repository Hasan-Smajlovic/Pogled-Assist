from __future__ import annotations

from itertools import product

import pytest
from _ui_fakes import FakeAppBar, FakeKeyboardInput
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, Qt

from pogled_assist.keyboard_layouts import ARABIC_LETTERS, ARABIC_SYMBOLS, SYMBOL_KEYS
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.ui.keyboard_window import KEYBOARD_WINDOW_ACTION_PREFIX, KeyboardWindow
from pogled_assist.ui.speech_window import BOSNIAN_LETTERS


@pytest.mark.e2e
@pytest.mark.parametrize(
    "layout",
    [
        pytest.param((script, letters), id=f"{letters}-{script}")
        for letters, script in product((1, 2, 5, 12), ("latin", "arabic"))
    ],
)
def test_sidebar_pages_fit_and_send_actual_unicode(qtbot, monkeypatch, layout):
    from pogled_assist.ui import sidebar_panel

    monkeypatch.setattr(sidebar_panel, "WindowsAppBar", FakeAppBar)
    script, letters_per_group = layout
    settings = SpeechSettings(keyboard_script=script, letters_per_group=letters_per_group)
    sidebar = _Sidebar(qtbot, settings)
    for symbols in (False, True):
        sidebar.check_pages(symbols)
    expected = (
        ARABIC_LETTERS + ARABIC_SYMBOLS if script == "arabic" else BOSNIAN_LETTERS + SYMBOL_KEYS
    )
    assert set(expected) <= set(sidebar.offered)
    if sidebar.types_every_key:
        assert set(expected) <= set(sidebar.input.typed)
    sidebar.window._script_button.click()
    assert sidebar.window._group_page == 0


class _Sidebar:
    def __init__(self, qtbot, settings):
        self.settings = settings
        self.window = KeyboardWindow(settings)
        qtbot.addWidget(self.window)
        self.input = FakeKeyboardInput()
        self.offered = []
        # One group size per script sends every key; the others check
        # each group's first and last key, where group and index offsets go wrong.
        self.types_every_key = settings.letters_per_group == 1
        self.window._input = self.input
        self.window.set_target_window(50)
        self.prefix = KEYBOARD_WINDOW_ACTION_PREFIX
        self.window.resize(380, 640)
        self.window.show()

    def check_pages(self, symbols):
        window = self.window
        if symbols:
            window._show_symbols()
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
        QCoreApplication.sendPostedEvents(None, QEvent.LayoutRequest)
        assert window.width() <= 380 and window.height() <= 640, (
            self.settings.keyboard_script,
            self.settings.letters_per_group,
            symbols,
            page,
            window.size(),
        )
        assert window._script_button.isVisible()
        assert window._action_buttons[f"{self.prefix}enter"].isVisible()
        if pages > 1:
            assert window._action_buttons[self._page_action(-1)].isEnabled() == (page > 0)
            assert window._action_buttons[self._page_action(1)].isEnabled() == (page + 1 < pages)

    def _check_buttons(self):
        window = self.window
        bounds = window.rect()
        for button in window._action_buttons.values():
            if not button.isVisible():
                continue
            assert bounds.contains(QRect(button.mapTo(window, QPoint(0, 0)), button.size())), (
                button.text()
            )
            assert button.height() >= 52
            if button.objectName() == "groupButton":
                assert all(
                    button.fontMetrics().horizontalAdvance(line) <= button.width() - 12
                    for line in button.text().splitlines()
                ), button.text()

    def _type_group(self, groups, group_index, symbols):
        window = self.window
        group_action = self._group_action(group_index, symbols)
        keys = groups[group_index]
        self.offered.extend(keys)
        key_action = "symbol:" if symbols else f"letter:{group_index}:"
        indices = range(len(keys)) if self.types_every_key else sorted({0, len(keys) - 1})
        for index in indices:
            # Selecting a key closes its group, so reopen it before each key.
            window._action_buttons[group_action].click()
            window._action_buttons[self.prefix + key_action + str(index)].click()
            assert self.input.typed[-1] == keys[index], (group_index, index)
        window._show_current_group_level()

    def _group_action(self, group_index, symbols):
        command = "symbol_group:" if symbols else "group:"
        return self.prefix + command + str(group_index)

    def _page_action(self, direction):
        return f"{self.prefix}group-page:{direction}"


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
@pytest.mark.parametrize("script", ["latin", "arabic"])
def test_keyboard_enter_stays_available_and_restores_external_target(qtbot, monkeypatch, script):
    from pogled_assist.ui import sidebar_panel

    monkeypatch.setattr(sidebar_panel, "WindowsAppBar", FakeAppBar)
    sidebar = _Sidebar(qtbot, SpeechSettings(keyboard_script=script))
    window = sidebar.window
    events = []
    # Pogled Assist has the foreground: restore the remembered external window first.
    monkeypatch.setattr(sidebar.input, "foreground_window", lambda: 99)
    monkeypatch.setattr(sidebar.input, "belongs_to_current_process", lambda hwnd: hwnd == 99)
    monkeypatch.setattr(
        sidebar.input, "set_foreground_window", lambda hwnd: events.append(("focus", hwnd)) or True
    )
    monkeypatch.setattr(sidebar.input, "press_key", lambda key: events.append(("key", key)))
    enter = window._action_buttons[f"{sidebar.prefix}enter"]
    geometry = None
    for show in (
        window._show_letter_groups,
        lambda: window._show_letter_group(0),
        window._show_numpad,
        lambda: window._show_numpad_group(0),
        window._show_symbols,
        lambda: window._show_symbol_group(0),
    ):
        show()
        qtbot.waitUntil(enter.isVisible)
        QCoreApplication.sendPostedEvents(None, QEvent.LayoutRequest)
        rect = window.action_bounds(f"{sidebar.prefix}enter")
        assert rect is not None and rect.height() >= 58 and rect.width() >= 150
        geometry = rect if geometry is None else geometry
        assert rect == geometry
        state = window._active_tab, window._group_page, window._active_group_index
        events.clear()
        qtbot.mouseClick(enter, Qt.LeftButton)
        assert events == [("focus", 50), ("key", "enter")]
        assert (window._active_tab, window._group_page, window._active_group_index) == state


@pytest.mark.e2e
@pytest.mark.parametrize("letter_layout", ["all", "groups"])
def test_sidebar_letters_stay_in_groups_whatever_the_speech_layout(qtbot, letter_layout):
    # "Sva slova" belongs to Speech only: the narrow sidebar keeps five-letter groups
    # on one page, so typing never needs Sljedeća.
    settings = SpeechSettings(letter_layout=letter_layout)
    sidebar = _Sidebar(qtbot, settings)
    prefix, group, letter = KEYBOARD_WINDOW_ACTION_PREFIX, "group", "letter"
    actions = sidebar.window._action_buttons

    groups = [actions[f"{prefix}{group}:{index}"].text() for index in range(6)]
    assert [label.split() for label in groups] == [
        BOSNIAN_LETTERS[start : start + 5] for start in range(0, 30, 5)
    ]
    assert f"{prefix}{group}:6" not in actions
    assert not [action for action in actions if "page:" in action]
    assert not [action for action in actions if action.startswith(f"{prefix}{letter}:")]
