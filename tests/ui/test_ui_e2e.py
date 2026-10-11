from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from _speech_fixtures import make_speech_window as make_speech_window
from _ui_fakes import FakeAppBar, FakeControllerInput, FakeLibraryStore, FakeSpeech
from PySide6.QtCore import QPoint, QRect, Qt
from test_hotbar_e2e import hotbar_gaze as hotbar_gaze

from pogled_assist.interaction.mouse_controller import GazeSettings
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.ui.controller_window import CONTROLLER_WINDOW_ACTION_PREFIX, ControllerWindow
from pogled_assist.ui.speech_window import SPEECH_WINDOW_ACTION_PREFIX


@pytest.mark.e2e
def test_version_dropdown_keeps_installed_label_and_requires_install_action(qtbot, monkeypatch):
    from pogled_assist.release_update import StableVersion
    from pogled_assist.ui.settings_window import SettingsWindow
    from scripts.ui.capture_ui import PreviewReleaseManager

    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    manager = PreviewReleaseManager()
    window = SettingsWindow(GazeSettings(), SpeechSettings(), update_manager=manager)
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    requested = []
    window.update_requested.connect(requested.append)
    row = window._update_row
    assert row._installed_label.text() == "Trenutno koristite v0.3.5"
    assert "novija verzija v0.4.0" in row._status_label.text()
    row._version_combo.setCurrentIndex(3)
    assert requested == []
    assert row._installed_label.text() == "Trenutno koristite v0.3.5"
    assert row._version_combo.currentData() == StableVersion(0, 1, 0)
    row._update_button.click()
    assert requested == [StableVersion(0, 1, 0)]
    assert not row._version_combo.isEnabled()
    assert "otvorena" in row._status_label.text()
    row.show_error("Paket nije provjeren.")
    assert row._version_combo.isEnabled()
    row._version_combo.setCurrentIndex(1)
    assert not row._update_button.isEnabled()
    row._check_failed("Nema internet veze.")
    assert row._installed_label.text() == "Trenutno koristite v0.3.5"
    assert not row._version_combo.isEnabled()
    assert not row._update_button.isEnabled()
    row._check_button.click()
    assert row._version_combo.isEnabled()
    qtbot.wait(1)
    for control in (row._version_combo, row._update_button, row._check_button):
        assert window.rect().contains(QRect(control.mapTo(window, QPoint(0, 0)), control.size()))
        assert control.height() >= 58


@pytest.mark.e2e
@pytest.mark.parametrize("editing", [False, True])
def test_version_restart_warning_cancels_without_losing_input(
    hotbar_gaze, qtbot, monkeypatch, tmp_path, editing
):
    from pogled_assist.release_update import ReleaseCheckResult, StableVersion

    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    hotbar = hotbar_gaze[0]
    hotbar._open_speech()
    speech = hotbar._speech_window
    speech._input.setText("SYNTHETIC UNSAVED MESSAGE")
    if editing:
        speech._categories_button.click()
        speech._start_editor()
        assert speech._input.text() == ""
    hotbar._open_settings()
    row = hotbar._settings_window._update_row
    version = StableVersion(0, 1, 0)
    row._check_completed(
        ReleaseCheckResult(StableVersion(0, 3, 5), StableVersion(0, 3, 5), (version,))
    )
    manager = hotbar._release_update_manager
    manager._control_directory = tmp_path
    manager._installing = True
    monkeypatch.setattr(manager, "prepare", lambda selected: None)
    quits = []
    monkeypatch.setattr(hotbar, "_quit_application", lambda: quits.append(True))
    row._update_button.click()
    assert quits == []
    manager._prepare_done.emit(tmp_path, None)
    qtbot.waitUntil(row._warning.isVisible)
    assert quits == []
    row._cancel_button.click()
    assert quits == []
    assert speech.has_unsaved_input
    assert (
        speech._editor is not None
        if editing
        else speech._input.text() == "SYNTHETIC UNSAVED MESSAGE"
    )
    assert (tmp_path / "cancel").exists()
    assert not (tmp_path / "install").exists()


@pytest.mark.e2e
def test_verified_version_restarts_only_after_explicit_confirmation(
    hotbar_gaze, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    hotbar = hotbar_gaze[0]
    hotbar._open_speech()
    hotbar._speech_window._input.setText("SYNTHETIC MESSAGE")
    hotbar._open_settings()
    manager = hotbar._release_update_manager
    manager._control_directory = tmp_path
    manager._installing = True
    (tmp_path / "ready.json").write_text('{"ready":true}', encoding="utf-8")
    quits = []
    monkeypatch.setattr(hotbar, "_quit_application", lambda: quits.append(True))
    manager._prepare_done.emit(tmp_path, None)
    assert quits == []
    hotbar._settings_window._update_row._confirm_button.click()
    assert quits == [True]
    assert (tmp_path / "install").exists()


@pytest.mark.e2e
def test_settings_gaze_controls_remain_usable_during_startup_query(qtbot, monkeypatch):
    from pogled_assist.ui import settings_window

    entered, release = threading.Event(), threading.Event()
    now = [10.0]

    def query():
        entered.set()
        release.wait(5)
        return False

    monkeypatch.setattr(settings_window, "is_windows_startup_enabled", query)
    monkeypatch.setattr(settings_window, "time", SimpleNamespace(monotonic=lambda: now[0]))
    window = settings_window.SettingsWindow(
        GazeSettings(selection_pause_ms=100, dwell_ms=150), SpeechSettings()
    )
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    try:
        qtbot.waitUntil(entered.is_set)
        window._gaze_tab_button.click()
        qtbot.wait(1)
        target = window._gaze_bubble_button
        center = target.mapToGlobal(target.rect().center())
        for stamp in (10.0, 10.1, 10.251):
            now[0] = stamp
            window.handle_gaze(center)
        assert not window._gaze_settings.show_gaze_bubble
        assert window._startup_busy
        release.set()
        qtbot.waitUntil(lambda: not window._startup_busy)
        assert not window._gaze_settings.show_gaze_bubble
    finally:
        release.set()
        qtbot.waitUntil(lambda: not window._startup_busy)


@pytest.mark.e2e
@pytest.mark.parametrize("eyes", [(True, False), (False, True), (False, False)])
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


def _check_sidebar_row(window, buttons, qtbot):
    qtbot.wait(1)
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
@pytest.mark.parametrize("script", ["latin", "arabic"])
@pytest.mark.parametrize("letters_per_group", [2, 5])
@pytest.mark.parametrize("size", [(320, 640), (380, 640), (380, 950)])
def test_controller_keyboard_rows_fill_sidebar_width(
    qtbot, monkeypatch, script, letters_per_group, size
):
    from pogled_assist.ui import sidebar_panel

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
        _check_sidebar_row(window, buttons, qtbot)

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
        if f"{prefix}keyboard-page:1" in window._action_buttons:
            check_row([window._action_buttons[f"{prefix}keyboard-page:{i}"] for i in (-1, 1)])
            window._action_buttons[f"{prefix}keyboard-page:1"].click()
            check_row(list(window._keyboard_tab_buttons.values()))
            window._action_buttons[f"{prefix}keyboard-page:-1"].click()

        window._action_buttons[f"{prefix}{group_command}:0"].click()
        check_row(list(window._keyboard_tab_buttons.values()))
        if f"{prefix}{key_command}:2" in window._action_buttons:
            check_row([window._action_buttons[f"{prefix}{key_command}:{i}"] for i in range(3)])
        check_row(
            [
                window._action_buttons[f"{prefix}{command}"]
                for command in ("keyboard_groups", "keyboard_space", "keyboard_backspace")
            ]
        )
        window.handle_gaze_action(f"{prefix}{key_command}:0")
        check_row(list(window._keyboard_tab_buttons.values()))
        check_row([window._action_buttons[f"{prefix}{group_command}:{i}"] for i in (0, 1)])

    for tab in ("general", "settings"):
        window._tab_buttons[tab].click()
        qtbot.wait(1)
        buttons = [
            button
            for button in window._action_buttons.values()
            if button.isVisible() and button.objectName() in ("shortcutButton", "checkButton")
        ]
        first_row = [
            button for button in buttons if button.y() == min(target.y() for target in buttons)
        ]
        check_row(first_row)


@pytest.mark.e2e
def test_twelve_letter_dialog_fits_150_percent_display_and_accepts_gaze(qtbot, make_speech_window):
    window = make_speech_window(
        FakeSpeech(), letters_per_group=12, library_store=FakeLibraryStore()
    )
    window.resize(1280, 720)
    window.show()
    qtbot.waitUntil(window.isVisible)

    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"].click()
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.letter)
    dialog = window._dialogs.letter
    assert dialog.height() <= window.height() - 64
    assert dialog.width() <= window.width() - 64

    bounds = dialog.rect()
    for action in window._dialogs.letter_actions:
        button = window._action_buttons[action]
        rect = QRect(button.mapTo(dialog, QPoint(0, 0)), button.size())
        assert bounds.contains(rect), action
        assert button.width() >= 140, action
        assert button.height() >= 110, action
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
    group_actions = [
        f"{SPEECH_WINDOW_ACTION_PREFIX}group:{index}" for index in range(len(window._letter_groups))
    ]
    for action in (*group_actions, f"{SPEECH_WINDOW_ACTION_PREFIX}keyboard-toggle"):
        button = window._action_buttons[action]
        rect = QRect(button.mapTo(window, QPoint(0, 0)), button.size())
        assert bounds.contains(rect), action
        assert button.height() >= 72, action


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
