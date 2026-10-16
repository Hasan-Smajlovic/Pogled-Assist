from __future__ import annotations

from dataclasses import replace

import pytest
from _hotbar_fixtures import hotbar_gaze as hotbar_gaze
from PySide6.QtCore import QPoint, QRect

from pogled_assist.ui.speech_window import SPEECH_WINDOW_ACTION_PREFIX


@pytest.mark.e2e
def test_keyboard_script_is_global_and_persisted(hotbar_gaze, qtbot, monkeypatch):
    from pogled_assist import toolbar
    from pogled_assist.ui import settings_window

    hotbar = hotbar_gaze[0]
    saved = []
    monkeypatch.setattr(
        toolbar, "save_app_settings", lambda gaze, speech: saved.append(replace(speech))
    )
    monkeypatch.setattr(settings_window, "is_windows_startup_enabled", lambda: False)
    hotbar._show_keyboard_sidebar()
    hotbar._keyboard_window._script_button.click()
    assert hotbar._speech.settings.keyboard_script == "arabic"
    assert saved[-1].keyboard_script == "arabic"
    hotbar._open_speech()
    assert hotbar._speech_window._speech_settings.keyboard_script == "arabic"
    hotbar._speech_window._input.setText("سَلَامٌ")
    hotbar._show_controller_sidebar()
    hotbar._controller_window._show_keyboard_tab()
    hotbar._controller_window._script_button.click()
    assert hotbar._speech_window._input.text() == "سَلَامٌ"
    assert hotbar._speech_window._speech_settings.keyboard_script == "latin"
    assert hotbar._keyboard_window._settings.keyboard_script == "latin"
    assert saved[-1].keyboard_script == "latin"


@pytest.mark.e2e
def test_arabic_script_gaze_switch_cannot_repeat_on_replacement_label(
    speech_gaze, qtbot, monkeypatch
):
    monkeypatch.setattr("pogled_assist.toolbar.save_app_settings", lambda *_args: None)
    window, controller, _speech, feed, actions, _progress = speech_gaze
    switch = window._script_button.mapToGlobal(window._script_button.rect().center())
    feed(switch, 0)
    feed(switch, 1001)
    assert window._speech_settings.keyboard_script == "arabic"
    assert actions == [f"{SPEECH_WINDOW_ACTION_PREFIX}script-toggle"]
    feed(switch, 1500)
    feed(switch, 3000)
    assert window._speech_settings.keyboard_script == "arabic"
    qtbot.wait(1)
    group = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"]
    group_point = group.mapToGlobal(group.rect().center())
    assert window.action_at_global_point(group_point) == f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"
    feed(group_point, 3100)
    feed(group_point, 3900)
    controller.handle_eye_status(True, False)
    feed(group_point, 4500)
    assert window._dialogs.active is None
    controller.handle_eye_status(True, True)
    feed(group_point, 4600)
    feed(group_point, 5599)
    assert window._dialogs.active is None
    feed(group_point, 5601)
    assert window._dialogs.active is window._dialogs.letter
    qtbot.wait(1)
    letter = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:0"]
    feed(letter.mapToGlobal(letter.rect().center()), 6000)
    feed(letter.mapToGlobal(letter.rect().center()), 7001)
    assert window._input.text() == "\u0627"


@pytest.mark.e2e
def test_failed_settings_save_stays_live_and_retries_from_settings(
    hotbar_gaze, qtbot, monkeypatch, tmp_path
):
    from pathlib import Path

    from pogled_assist import settings_store, toolbar
    from pogled_assist.ui import settings_window

    hotbar = hotbar_gaze[0]
    monkeypatch.setattr(settings_window, "is_windows_startup_enabled", lambda: False)
    monkeypatch.setattr(settings_store, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(toolbar, "save_app_settings", settings_store.save_app_settings)
    assert settings_store.save_app_settings(hotbar._mouse.settings, hotbar._speech.settings)
    path = tmp_path / "data" / settings_store.SETTINGS_FILE
    original = path.read_bytes()
    with monkeypatch.context() as patch:

        def locked(*_args):
            raise PermissionError("Synthetic locked settings")

        patch.setattr(Path, "replace", locked)
        hotbar._update_gaze_settings(replace(hotbar._mouse.settings, dwell_ms=850))
        hotbar._change_keyboard_script("arabic")
        assert hotbar._mouse.settings.dwell_ms == 850
        assert hotbar._speech.settings.keyboard_script == "arabic"
        assert path.read_bytes() == original
        assert hotbar._settings_button.text() == "Postavke *"
        hotbar._open_settings()
        window = hotbar._settings_window
        window.showNormal()
        window.resize(1280, 720)
        qtbot.wait(1)
        for tab in range(3):
            window._select_tab(tab)
            assert "nisu sačuvane" in window._save_note.text()
            assert window._retry_save_button.isVisible()
        window._retry_save_button.click()
        assert window._retry_save_button.isVisible()
    retry = window._retry_save_button
    assert retry.height() >= 66
    assert window.rect().contains(QRect(retry.mapTo(window, QPoint()), retry.size()))
    target = window._controls.action_at(retry.mapToGlobal(retry.rect().center()))
    assert target is not None and target[0] is retry
    target[1]()
    assert retry.isHidden()
    assert hotbar._settings_button.text() == "Postavke"
    gaze, speech = settings_store.load_app_settings()
    assert gaze.dwell_ms == 850
    assert speech.keyboard_script == "arabic"


@pytest.mark.e2e
def test_settings_voice_test_reports_late_failure(hotbar_gaze, monkeypatch):
    from pogled_assist.ui import settings_window

    monkeypatch.setattr(settings_window, "is_windows_startup_enabled", lambda: False)
    hotbar = hotbar_gaze[0]
    hotbar._open_settings()
    hotbar._test_current_speech_settings()
    hotbar._speech.playback_changed.emit(hotbar._speech.request_id, "failed")
    assert hotbar._settings_window._status_label.text() == "Govor nije uspio. Pokušajte ponovo."

