from __future__ import annotations

import pytest
from _hotbar_fixtures import hotbar_gaze as hotbar_gaze
from _speech_fixtures import make_speech_window as make_speech_window
from _ui_fakes import FakeAppBar, FakeControllerInput, FakeLibraryStore, FakeSpeech
from PySide6.QtCore import QPoint, QRect, Qt

from pogled_assist.interaction.mouse_controller import GazeSettings
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.ui.controller_window import CONTROLLER_WINDOW_ACTION_PREFIX, ControllerWindow
from pogled_assist.ui.speech_window import SPEECH_WINDOW_ACTION_PREFIX


@pytest.mark.e2e
@pytest.mark.parametrize(
    "case",
    [
        ((1280, 720), "latin", 1, False),
        ((1280, 720), "latin", 5, True),
        ((1280, 720), "latin", 12, False),
        ((1280, 720), "arabic", 1, True),
        ((1280, 720), "arabic", 5, False),
        ((1280, 720), "arabic", 12, True),
        ((1440, 900), "latin", 5, False),
        ((1440, 900), "arabic", 5, True),
        ((1920, 1080), "latin", 5, False),
        ((1920, 1080), "arabic", 5, True),
    ],
)
def test_speech_bottom_buttons_fit_and_preserve_mouse_and_gaze_actions(
    qtbot, make_speech_window, case
):
    size, script, letters_per_group, use_gaze = case
    speech = FakeSpeech()
    speech._settings = SpeechSettings(keyboard_script=script)
    window = make_speech_window(
        speech, letters_per_group=letters_per_group, library_store=FakeLibraryStore()
    )
    window.resize(*size)
    window.show()
    qtbot.waitUntil(window.isVisible)

    controls = (
        (window._space_button, "space"),
        (window._backspace_button, "backspace"),
        (window._keyboard_toggle_button, "keyboard-toggle"),
    )
    assert window.width() == size[0]
    assert window.height() == size[1]
    previous = None
    for button, command in controls:
        assert button.minimumHeight() == 95
        assert button.height() == 95
        rect = QRect(button.mapTo(window, QPoint(0, 0)), button.size())
        assert window.rect().contains(rect)
        if previous is not None:
            assert previous.right() < rect.left()
        previous = rect
        # The extra bottom five pixels must be selectable by gaze too.
        point = button.mapToGlobal(QPoint(button.width() // 2, button.height() - 1))
        assert window.action_at_global_point(point) == f"{SPEECH_WINDOW_ACTION_PREFIX}{command}"

    assert window._script_button.minimumHeight() == 95
    alarm = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}alarm:start"]
    script_rect = QRect(window._script_button.mapTo(window, QPoint()), window._script_button.size())
    alarm_rect = QRect(alarm.mapTo(window, QPoint()), alarm.size())
    keys_rect = QRect(window._key_grid_host.mapTo(window, QPoint()), window._key_grid_host.size())
    numbers_rect = QRect(
        window._keyboard_toggle_button.mapTo(window, QPoint()),
        window._keyboard_toggle_button.size(),
    )
    assert script_rect.left() == alarm_rect.left()
    assert script_rect.right() == alarm_rect.right()
    assert numbers_rect.right() == keys_rect.right()
    assert script_rect.left() - numbers_rect.right() - 1 == 12
    assert (
        window.action_at_global_point(
            window._script_button.mapToGlobal(window._script_button.rect().center())
        )
        == f"{SPEECH_WINDOW_ACTION_PREFIX}script-toggle"
    )
    window._input.setText("ABC")
    for button, command in controls[:2]:
        _select_speech_control(window, button, command, use_gaze)
        assert window._input.text() == ("ABC " if command == "space" else "ABC")

    original = window._symbols_mode
    _select_speech_control(window, window._keyboard_toggle_button, "keyboard-toggle", use_gaze)
    assert window._symbols_mode != original
    assert window._input.text() == "ABC"


def _select_speech_control(window, button, command, use_gaze):
    if use_gaze:
        window.handle_gaze_action(f"{SPEECH_WINDOW_ACTION_PREFIX}{command}")
    else:
        button.click()


@pytest.mark.e2e
def test_simulator_shortcuts_cancel_eye_loss_and_require_fresh_gaze(hotbar_gaze, monkeypatch):
    hotbar, controller, _feed, actions, _progress = hotbar_gaze
    point = QPoint(300, 250)
    monkeypatch.setattr(
        "pogled_assist.tracking.mouse_gaze_provider._primary_screen_geometry",
        lambda: controller._logical_screen_rect,
    )
    provider = hotbar._gaze
    provider._cursor_position = lambda: point
    provider.start()
    provider._timer.stop()
    shortcuts = {shortcut.key().toString(): shortcut for shortcut in hotbar._simulation_shortcuts}
    assert set(shortcuts) == {"F6", "F7", "F8", "F9", "F10"}
    assert controller._both_eyes_open
    assert hotbar._gaze_bubble.isVisible()

    shortcuts["F6"].activated.emit()
    provider._emit_cursor_sample()
    assert not controller._both_eyes_open
    assert hotbar._gaze_bubble.isHidden()
    assert hotbar._tracking_status._view.title == "Simulacija uz riječ"
    assert hotbar._tracking_status._view.detail == "Lijevo —   Desno ✓"
    assert actions == []

    shortcuts["F10"].activated.emit()
    assert controller._both_eyes_open
    assert hotbar._gaze_bubble.isHidden()
    provider._emit_cursor_sample()
    assert hotbar._gaze_bubble.isVisible()
    shortcuts["F9"].activated.emit()
    assert not controller._both_eyes_open
    assert hotbar._gaze_bubble.isHidden()
    assert hotbar._tracking_status._view.title == "Simulacija uz riječ"


@pytest.mark.e2e
@pytest.mark.parametrize("eyes", [(True, False), (False, True)])
def test_speech_marker_waits_for_fresh_gaze_after_eye_loss(hotbar_gaze, qtbot, eyes):
    hotbar, _controller, feed, _actions, _progress = hotbar_gaze
    hotbar._open_speech()
    qtbot.waitUntil(hotbar._speech_window.isVisible)
    bubble = hotbar._gaze_bubble
    feed(QPoint(300, 250), 0)
    assert bubble.isVisible()

    hotbar._gaze.eye_status_changed.emit(*eyes)
    assert bubble.isHidden()
    bubble.set_enabled(False)
    bubble.set_enabled(True)
    assert bubble.isHidden()

    hotbar._gaze.eye_status_changed.emit(True, True)
    assert bubble.isHidden()
    feed(QPoint(600, 450), 600)
    assert bubble.isVisible()
    assert bubble.pos() == QPoint(600 - bubble.width() // 2, 450 - bubble.height() // 2)


@pytest.mark.e2e
@pytest.mark.parametrize("script", ["latin", "arabic"])
def test_speech_rest_control_uses_bosnian_copy_and_preserves_message(
    qtbot, make_speech_window, script
):
    speech = FakeSpeech()
    speech._settings = SpeechSettings(keyboard_script=script)
    window = make_speech_window(speech, library_store=FakeLibraryStore())
    window.resize(1280, 720)
    window.show()
    window._input.setText("TREBAM ODMOR")
    rest = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}sleep:start"]
    assert rest.text() == "Odmor\nOdmori oči"
    rest.click()
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.sleep)
    window.handle_gaze_action(f"{SPEECH_WINDOW_ACTION_PREFIX}sleep:wake")
    assert window._dialogs.active is None
    assert window._input.text() == "TREBAM ODMOR"


def _check_sidebar_row(window, buttons):
    rects = [QRect(button.mapTo(window, QPoint(0, 0)), button.size()) for button in buttons]
    assert min(rect.left() for rect in rects) == 10
    assert max(rect.right() for rect in rects) == window.width() - 11
    assert max(rect.width() for rect in rects) - min(rect.width() for rect in rects) <= 1
    assert all(window.rect().contains(rect) for rect in rects)
    for button in buttons:
        _assert_sidebar_hit(window, button)


def _assert_sidebar_hit(window, button):
    center = button.mapToGlobal(button.rect().center())
    expected = (
        next(action for action, target in window._action_buttons.items() if target is button)
        if button.isEnabled()
        else None
    )
    assert window.action_at_global_point(center) == expected


@pytest.mark.e2e
@pytest.mark.parametrize(
    "case",
    [
        ((320, 640), "latin", 2),
        ((320, 640), "arabic", 2),
        ((380, 640), "latin", 5),
        ((380, 640), "arabic", 5),
        ((380, 950), "latin", 2),
        ((380, 950), "arabic", 5),
    ],
)
def test_controller_keyboard_rows_fill_sidebar_width(qtbot, monkeypatch, case):
    from pogled_assist.ui import sidebar_panel

    size, script, letters_per_group = case
    monkeypatch.setattr(sidebar_panel, "WindowsAppBar", FakeAppBar)
    window = ControllerWindow(
        GazeSettings(),
        SpeechSettings(keyboard_script=script, letters_per_group=letters_per_group),
    )
    qtbot.addWidget(window)
    window._input = FakeControllerInput()
    window.resize(*size)
    window.show()
    prefix = CONTROLLER_WINDOW_ACTION_PREFIX

    def check_row(buttons):
        qtbot.waitUntil(lambda: _check_sidebar_row(window, buttons))

    window._tab_buttons["keyboard"].click()
    for tab, group_command, key_command in (
        ("letters", "keyboard_group", "keyboard_letter:0"),
        ("numpad", "keyboard_numpad_group", "keyboard_numpad"),
        ("symbols", "keyboard_symbol_group", "keyboard_symbol"),
    ):
        window._keyboard_tab_buttons[tab].click()
        check_row(list(window._keyboard_tab_buttons.values()))
        check_row([window._action_buttons[f"{prefix}{group_command}:{i}"] for i in (0, 1)])
        check_row(
            [
                window._action_buttons[f"{prefix}{command}"]
                for command in ("keyboard_space", "keyboard_backspace")
            ]
        )
        _check_controller_paging(window, check_row)

        window._action_buttons[f"{prefix}{group_command}:0"].click()
        check_row(list(window._keyboard_tab_buttons.values()))
        _check_controller_key_row(window, key_command, check_row)
        check_row(
            [
                window._action_buttons[f"{prefix}{command}"]
                for command in ("keyboard_groups", "keyboard_space", "keyboard_backspace")
            ]
        )
        window.handle_gaze_action(f"{prefix}{key_command}:0")
        check_row(list(window._keyboard_tab_buttons.values()))
        check_row([window._action_buttons[f"{prefix}{group_command}:{i}"] for i in (0, 1)])

    def check_first_row():
        buttons = [
            button
            for button in window._action_buttons.values()
            if button.isVisible() and button.objectName() in ("shortcutButton", "checkButton")
        ]
        assert buttons
        first_row = [
            button for button in buttons if button.y() == min(target.y() for target in buttons)
        ]
        _check_sidebar_row(window, first_row)

    for tab in ("general", "settings"):
        window._tab_buttons[tab].click()
        qtbot.waitUntil(check_first_row)


def _check_controller_paging(window, check_row):
    prefix = CONTROLLER_WINDOW_ACTION_PREFIX
    if f"{prefix}keyboard-page:1" not in window._action_buttons:
        return
    check_row([window._action_buttons[f"{prefix}keyboard-page:{i}"] for i in (-1, 1)])
    window._action_buttons[f"{prefix}keyboard-page:1"].click()
    check_row(list(window._keyboard_tab_buttons.values()))
    window._action_buttons[f"{prefix}keyboard-page:-1"].click()


def _check_controller_key_row(window, key_command, check_row):
    prefix = CONTROLLER_WINDOW_ACTION_PREFIX
    if f"{prefix}{key_command}:2" in window._action_buttons:
        check_row([window._action_buttons[f"{prefix}{key_command}:{i}"] for i in range(3)])


@pytest.mark.e2e
def test_twelve_inline_letters_fit_150_percent_display_and_accept_gaze(qtbot, make_speech_window):
    window = make_speech_window(
        FakeSpeech(), letters_per_group=12, library_store=FakeLibraryStore()
    )
    window.resize(1280, 720)
    window.show()
    qtbot.waitUntil(window.isVisible)

    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"].click()
    assert window._dialogs.active is None
    qtbot.wait(1)

    bounds = window._key_grid_host.rect()
    for action in window._main_dynamic_actions:
        button = window._action_buttons[action]
        rect = QRect(button.mapTo(window._key_grid_host, QPoint(0, 0)), button.size())
        assert bounds.contains(rect), action
        assert button.width() >= 140, action
        assert button.height() >= 72, action
        assert window.action_at_global_point(button.mapToGlobal(button.rect().center())) == action

    last_letter = f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:11"
    window.handle_gaze_action(last_letter)
    qtbot.waitUntil(lambda: window._dialogs.active is None)
    assert window._input.text() == window._letter_groups[0][-1]


@pytest.mark.e2e
def test_single_letter_groups_fit_150_percent_display(qtbot, make_speech_window):
    window = make_speech_window(FakeSpeech(), letters_per_group=1, library_store=FakeLibraryStore())
    window.resize(1280, 720)
    window.show()
    qtbot.waitUntil(window.isVisible)

    assert window.size().width() <= 1280
    assert window.size().height() <= 720
    bounds = QRect(0, 0, 1280, 720)
    reached = set()
    for page, expected_count in enumerate((12, 12, 6)):
        group_actions = sorted(
            action
            for action in window._action_buttons
            if action.startswith(f"{SPEECH_WINDOW_ACTION_PREFIX}group:")
        )
        assert len(group_actions) == expected_count
        assert window._page_label.text() == f"{page + 1} / 3"
        reached.update(group_actions)
        for action in (*group_actions, f"{SPEECH_WINDOW_ACTION_PREFIX}keyboard-toggle"):
            button = window._action_buttons[action]
            rect = QRect(button.mapTo(window, QPoint(0, 0)), button.size())
            assert bounds.contains(rect), action
            assert button.height() >= 72, action
        assert window._next_page_button.isEnabled() == (page < 2)
        if page < 2:
            window._next_page_button.click()
            qtbot.wait(1)
    assert reached == {
        f"{SPEECH_WINDOW_ACTION_PREFIX}group:{index}" for index in range(len(window._letter_groups))
    }
    last = len(window._letter_groups) - 1
    window.handle_gaze_action(f"{SPEECH_WINDOW_ACTION_PREFIX}group:{last}")
    window.handle_gaze_action(f"{SPEECH_WINDOW_ACTION_PREFIX}letter:{last}:0")
    assert window._input.text() == window._letter_groups[last][0]
    qtbot.waitUntil(window._action_buttons[window._action(f"group:{last}")].isVisible)
    assert window._keyboard_page == 2
    window.handle_gaze_action(window._action(f"group:{last}"))
    assert window._next_page_button.isHidden()
    window.handle_gaze_action(window._action("letters:close"))
    assert window._keyboard_page == 2
    assert window._page_label.text() == "3 / 3"


@pytest.mark.e2e
def test_speech_symbols_backspace_clear_and_play(qtbot, make_speech_window):
    speech = FakeSpeech()
    window = make_speech_window(speech, library_store=FakeLibraryStore())
    window.show()
    qtbot.waitUntil(window.isVisible)

    qtbot.mouseClick(window._keyboard_toggle_button, Qt.LeftButton)
    assert window._symbols_mode is True
    symbol = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}symbol:0"]
    qtbot.waitUntil(symbol.isVisible)
    qtbot.mouseClick(symbol, Qt.LeftButton)
    assert window._input.text() == "1"

    qtbot.mouseClick(window._keyboard_toggle_button, Qt.LeftButton)
    assert window._symbols_mode is False
    assert f"{SPEECH_WINDOW_ACTION_PREFIX}group:0" in window._action_buttons

    for value in ("DŽ", "LJ", "NJ", "dž", "lj", "nj"):
        window._input.setText(value)
        qtbot.mouseClick(window._backspace_button, Qt.LeftButton)
        assert window._input.text() == ""

    window._input.setText("Trebam pomoć")
    qtbot.mouseClick(window._play_button, Qt.LeftButton)
    assert speech.requests[-1][0] == "TREBAM POMOĆ"
    assert window._input.text() == "TREBAM POMOĆ"

    qtbot.mouseClick(window._clear_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.confirm)
    qtbot.mouseClick(
        window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:cancel"], Qt.LeftButton
    )
    qtbot.waitUntil(lambda: window._dialogs.active is None)
    assert window._input.text() == "TREBAM POMOĆ"

    qtbot.mouseClick(window._clear_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.confirm)
    qtbot.mouseClick(
        window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:accept"], Qt.LeftButton
    )
    qtbot.waitUntil(lambda: window._dialogs.active is None)
    assert window._input.text() == ""

    qtbot.mouseClick(window._clear_button, Qt.LeftButton)
    assert window._dialogs.active is None


@pytest.mark.e2e
def test_library_retry_is_gaze_selectable_and_preserves_the_message(
    qtbot, make_speech_window, tmp_path, monkeypatch
):
    from pathlib import Path

    from pogled_assist.speech.speech_library import (
        CategoryRecord,
        PhraseRecord,
        SpeechLibrary,
        SpeechLibraryStore,
    )

    primary, legacy = tmp_path / "library.json", tmp_path / "phrases.json"
    original = SpeechLibrary(
        [CategoryRecord("Synthetic custom", ["Synthetic answer"])],
        [PhraseRecord("Synthetic phrase", 5)],
    )
    assert SpeechLibraryStore(primary, legacy_path=legacy).save(original)
    before = primary.read_bytes()
    read_text = Path.read_text

    def unavailable(path, *args, **kwargs):
        if path == primary:
            raise PermissionError("Synthetic failure")
        return read_text(path, *args, **kwargs)

    store = SpeechLibraryStore(primary, legacy_path=legacy)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", unavailable)
        window = make_speech_window(FakeSpeech(), library_store=store)
    window.resize(1280, 720)
    window.show()
    window._view_mode = "phrases"
    window._show_list_level()
    qtbot.wait(1)
    window._input.setText("SYNTHETIC MESSAGE")
    window.handle_gaze_action(f"{SPEECH_WINDOW_ACTION_PREFIX}list:select:0")
    message = window._input.text()
    assert "SYNTHETIC PHRASE" in message
    assert primary.read_bytes() == before
    assert window._add_item_button.isHidden()
    assert window._delete_mode_button.isHidden()
    retry = window._retry_library_button
    assert retry.isVisible() and retry.height() >= 80
    assert window.rect().contains(QRect(retry.mapTo(window, QPoint()), retry.size()))
    assert (
        window.action_at_global_point(retry.mapToGlobal(retry.rect().center()))
        == f"{SPEECH_WINDOW_ACTION_PREFIX}list:retry"
    )
    window.handle_gaze_action(f"{SPEECH_WINDOW_ACTION_PREFIX}list:retry")
    assert not store.read_error
    assert window._library == original
    assert window._input.text() == message
    assert retry.isHidden()
    assert window._add_item_button.isVisible()


@pytest.mark.e2e
def test_speech_lifecycle_updates_status_and_ignores_previous_request(qtbot, make_speech_window):
    speech = FakeSpeech()
    window = make_speech_window(speech, library_store=FakeLibraryStore())
    window.show()
    window._input.setText("SYNTHETIC MESSAGE")
    window._play_button.click()
    first = speech.request_id
    assert window._status_label.text() == "Pokrećem govor."
    speech.playback_changed.emit(first, "speaking")
    assert window._status_label.text() == "Poruka se izgovara."
    speech.playback_changed.emit(first, "failed")
    assert window._status_label.text() == "Govor nije uspio. Pokušajte ponovo."
    assert window._input.text() == "SYNTHETIC MESSAGE"
    window._play_button.click()
    second = speech.request_id
    speech.playback_changed.emit(first, "finished")
    assert window._status_label.text() == "Pokrećem govor."
    speech.playback_changed.emit(second, "finished")
    assert window._status_label.text() == "Čitanje je završeno."
