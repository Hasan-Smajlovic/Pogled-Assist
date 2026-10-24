from __future__ import annotations

from dataclasses import replace

import pytest
from _clock import freeze_monotonic
from _speech_fixtures import make_speech_window as make_speech_window
from _ui_fakes import FakeLibraryStore, FakeSpeech
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QFrame, QToolButton, QWidget

from pogled_assist.interaction.mouse_controller import GazeSettings
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.ui.gaze_feedback import set_gaze_feedback, set_gaze_paused
from pogled_assist.ui.keyboard_window import KEYBOARD_STYLESHEET
from pogled_assist.ui.settings_window import SETTINGS_STYLESHEET, SettingsWindow
from pogled_assist.ui.theme import apply_theme

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize(
    "case",
    [
        (SETTINGS_STYLESHEET, "dangerButton", "#442b33"),
        (SETTINGS_STYLESHEET, "navButton", None),
        (KEYBOARD_STYLESHEET, "utilityButton", "#2b1f27"),
    ],
)
def test_calm_outline_overrides_named_controls_without_changing_fill(qtbot, case):
    stylesheet, name, fill = case
    parent = QWidget()
    parent.setObjectName("settingsRoot")
    qtbot.addWidget(parent)
    apply_theme(parent, stylesheet)
    button = QToolButton(parent)
    button.setObjectName(name)
    button.setText("Odaberi")
    button.resize(250, 58)
    parent.resize(300, 100)
    parent.show()
    set_gaze_feedback(button, True)
    image = button.grab().toImage()
    assert image.pixelColor(120, 1).name() == "#84c5d9"
    if fill is None:
        assert image.pixelColor(120, 8).alpha() == 0
    else:
        assert image.pixelColor(120, 8).name() == fill


def test_information_can_be_read_with_keyboard_without_closing_settings(qtbot, monkeypatch):
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    window = SettingsWindow(GazeSettings(), SpeechSettings())
    qtbot.addWidget(window)
    window.resize(800, 720)
    window.show()
    window._open_eleven()
    button = window._eleven_page.connection_help
    qtbot.waitUntil(button.isVisible)
    button.setFocus()
    qtbot.keyClick(button, Qt.Key_Space)
    qtbot.waitUntil(button.popup.isVisible)
    bounds = QRect(window.mapToGlobal(QPoint()), window.size())
    assert bounds.contains(button.popup.geometry())
    check = window._eleven_page.check_button
    assert window._controls.action_at(check.mapToGlobal(check.rect().center())) is None
    qtbot.keyClick(button.popup, Qt.Key_Escape)
    qtbot.waitUntil(button.popup.isHidden)
    assert window.isVisible()
    qtbot.waitUntil(button.hasFocus)
    qtbot.keyClick(button, Qt.Key_Return)
    qtbot.waitUntil(button.popup.isVisible)
    button.click()
    qtbot.waitUntil(button.popup.isHidden)


def test_support_actions_and_scrolling_keep_hidden_settings_out_of_gaze(qtbot, monkeypatch):
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    window = SettingsWindow(GazeSettings(), SpeechSettings())
    qtbot.addWidget(window)
    window.resize(1000, 640)
    window.show()
    window._select_tab(3)
    updates, requests = [], []
    window.gaze_settings_changed.connect(updates.append)
    window.diagnostics_requested.connect(lambda: requests.append(True))
    window._support_page._logging_checkbox.click()
    assert updates[-1].logging_enabled != GazeSettings().logging_enabled
    window._support_page._diagnostics_button.click()
    assert requests == [True]
    window._select_tab(1)
    window._gaze_page.layout().insertSpacing(0, 1000)
    qtbot.waitUntil(lambda: window._scroll.verticalScrollBar().maximum() > 0)
    control = window._gaze_page._policy_combo
    window._set_gaze_target(control)
    window._scroll.verticalScrollBar().setValue(58)
    window._scroll.verticalScrollBar().setValue(0)
    assert window._gaze_target is None
    point = control.mapToGlobal(control.rect().center())
    viewport = window._scroll.viewport()
    qtbot.waitUntil(
        lambda: (
            not viewport.rect().contains(
                viewport.mapFromGlobal(control.mapToGlobal(control.rect().center()))
            )
        )
    )
    point = control.mapToGlobal(control.rect().center())
    assert not viewport.rect().contains(viewport.mapFromGlobal(point))
    target = window._controls.action_at(point)
    assert target is None or target[0] is not control


@pytest.mark.parametrize("script", ["latin", "arabic"])
@pytest.mark.parametrize("group_size", [5, 12])
def test_letter_dialog_targets_fit_and_recording_does_not_move_them(
    qtbot, make_speech_window, script, group_size
):
    speech = FakeSpeech()
    speech._settings = SpeechSettings(keyboard_script=script)
    window = make_speech_window(
        speech, letters_per_group=group_size, library_store=FakeLibraryStore()
    )
    window.resize(1280, 720)
    window.show()
    window._open_letter_dialog(0)
    dialog = window._dialogs.letter
    qtbot.waitUntil(dialog.isVisible)
    buttons = [window._action_buttons[action] for action in window._dialogs.letter_actions]
    qtbot.waitUntil(lambda: all(button.width() > 100 for button in buttons))
    before = [QRect(button.geometry()) for button in buttons]
    assert dialog.height() < (640 if group_size == 12 else 430)
    assert max(rect.width() for rect in before) - min(rect.width() for rect in before) <= 1
    assert all(
        dialog.rect().contains(QRect(button.mapTo(dialog, QPoint()), button.size()))
        for button in buttons
    )
    badge = window._dialogs.recording_badges[0]
    badge.set_status({"busy": True, "state": "recording", "remaining_seconds": 80})
    qtbot.waitUntil(badge.isVisible)
    assert [button.geometry() for button in buttons] == before
    title = window._dialogs.letter_title
    assert badge.mapTo(dialog, QPoint()).x() > title.mapTo(dialog, QPoint()).x()
    first = window._action_buttons[window._action("letter:0:0")]
    second = window._action_buttons[window._action("letter:0:1")]
    assert (first.x() > second.x()) == (script == "arabic")


def test_gaze_highlight_stays_steady_during_selection_and_hold(qtbot):
    button = QToolButton()
    qtbot.addWidget(button)
    button.setText("Odaberi")
    button.resize(180, 80)
    button.show()
    set_gaze_feedback(button, True)
    state = button.property("gazePulse")
    qtbot.wait(220)
    assert button.property("gazePulse") == state
    set_gaze_paused(button, True)
    assert button.property("gazeTarget") is True
    set_gaze_paused(button, False)
    set_gaze_feedback(button, False)
    assert button.property("gazeTarget") is False


def test_voice_update_preserves_the_displayed_keyboard_page(qtbot, make_speech_window):
    window = make_speech_window(FakeSpeech(), letters_per_group=1, library_store=FakeLibraryStore())
    window.resize(1280, 720)
    window.show()
    window._next_page_button.click()
    window._next_page_button.click()
    qtbot.waitUntil(lambda: window._page_label.text() == "3 / 3")
    window.update_settings(replace(window._speech_settings, speed=200))
    assert window._keyboard_page == 2
    window._previous_page_button.click()
    assert window._page_label.text() == "2 / 3"
    assert window._action("group:12") in window._action_buttons
    window._phrases_button.click()
    window._add_item_button.click()
    assert window._page_label.text() == "1 / 3"
    assert window._action("group:0") in window._action_buttons


@pytest.mark.parametrize("script", ["latin", "arabic"])
def test_every_dense_editor_page_fits_without_resizing_the_window(
    qtbot, make_speech_window, script
):
    speech = FakeSpeech()
    speech._settings = SpeechSettings(keyboard_script=script)
    window = make_speech_window(speech, letters_per_group=1, library_store=FakeLibraryStore())
    window.resize(1280, 720)
    window.show()
    window._phrases_button.click()
    window._add_item_button.click()
    pages = window._keyboard_pages
    for page in range(pages):
        qtbot.waitUntil(lambda expected=page: window._keyboard_page == expected)
        qtbot.wait(1)
        assert (window.width(), window.height()) == (1280, 720)
        for action in window._main_dynamic_actions:
            button = window._action_buttons[action]
            rect = QRect(button.mapTo(window, QPoint()), button.size())
            assert window.rect().contains(rect)
            assert rect.bottom() < window._space_button.y()
        if page + 1 < pages:
            window._next_page_button.click()


def test_horizontal_scroll_cancels_pending_settings_selection(qtbot, monkeypatch):
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    window = SettingsWindow(GazeSettings(), SpeechSettings())
    qtbot.addWidget(window)
    window.resize(800, 720)
    window.show()
    window._open_eleven()
    window._eleven_page.setMinimumWidth(1600)
    bar = window._scroll.horizontalScrollBar()
    qtbot.waitUntil(lambda: bar.maximum() > 0)
    button = window._exit_button
    now = freeze_monotonic(monkeypatch, 10.0)
    window.handle_eye_status(True, True)
    window.handle_gaze(button.mapToGlobal(button.rect().center()))
    now[0] = 10.3
    window.handle_gaze(button.mapToGlobal(button.rect().center()))
    assert window._gaze_target is button
    bar.setValue(bar.maximum())
    assert window._gaze_target is None


def test_hidden_settings_pages_do_not_create_blank_scroll_space_after_relayout(qtbot, monkeypatch):
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    window = SettingsWindow(GazeSettings(), SpeechSettings())
    qtbot.addWidget(window)
    window.resize(1280, 720)
    for tab in (0, 2, 3, 1, 0):
        window._select_tab(tab)
        window.hide()
        window.show()
        window.layout().invalidate()
        window.layout().activate()
        window.grab()
        qtbot.waitUntil(
            lambda: (
                window._scroll.verticalScrollBar().maximum() == 0
                and window._stack.height() == window._scroll.viewport().height()
            )
        )
        assert window._stack.heightForWidth(window._stack.width()) == (
            window._stack.currentWidget().heightForWidth(window._stack.width())
        )


@pytest.mark.parametrize("script", ["latin", "arabic"])
def test_speech_sections_and_utility_groups_align_without_status_layout_shift(
    qtbot, make_speech_window, script
):
    speech = FakeSpeech()
    speech._settings = SpeechSettings(keyboard_script=script)
    window = make_speech_window(speech, library_store=FakeLibraryStore())
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    qtbot.waitUntil(lambda: window._space_button.width() > 200)
    utility = (
        window._space_button,
        window._backspace_button,
        window._keyboard_toggle_button,
        window._script_button,
    )
    before = [QRect(button.geometry()) for button in utility]
    assert len({rect.top() for rect in before}) == 1
    assert len({rect.height() for rect in before}) == 1
    assert max(rect.width() for rect in before) - min(rect.width() for rect in before) <= 1
    divider = window.findChild(QFrame, "utilityDivider")
    assert divider is not None
    assert before[1].right() < divider.x() < before[2].left()
    assert divider.height() == before[0].height()
    assert len(window.findChildren(QFrame, "speechDivider")) == 3
    if script == "latin":
        for row, command in enumerate(("alarm:start", "sleep:start", "exit")):
            group = window._action_buttons[window._action(f"group:{row * 2}")]
            system = window._action_buttons[window._action(command)]
            assert group.mapTo(window, QPoint()).y() == system.mapTo(window, QPoint()).y()
            assert abs(group.height() - system.height()) <= 1
    for action in window._main_dynamic_actions:
        button = window._action_buttons[action]
        rect = QRect(button.mapTo(window, QPoint()), button.size())
        assert window.rect().contains(rect)
        assert rect.bottom() < before[0].top()
    window._recording_badge.set_status(
        {"busy": True, "state": "recording", "remaining_seconds": 80}
    )
    qtbot.waitUntil(window._recording_badge.isVisible)
    assert [button.geometry() for button in utility] == before
    window._switch_keyboard_script()
    qtbot.waitUntil(lambda: window._speech_settings.keyboard_script != script)
    assert [button.geometry() for button in utility] == before
