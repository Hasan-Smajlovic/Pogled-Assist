from __future__ import annotations

import pytest
from _hotbar_fixtures import hotbar_gaze as hotbar_gaze
from PySide6.QtCore import QPoint, QRect

from pogled_assist.interaction.mouse_controller import GazeSettings
from pogled_assist.speech.speech_service import SpeechSettings


@pytest.mark.e2e
def test_version_dropdown_keeps_installed_label_and_requires_install_action(qtbot, monkeypatch):
    from pogled_assist.release_update import StableVersion
    from pogled_assist.ui.settings_window import SettingsServices, SettingsWindow
    from scripts.ui.capture_ui import PreviewReleaseManager

    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    manager = PreviewReleaseManager()
    window = SettingsWindow(GazeSettings(), SpeechSettings(), services=SettingsServices(update_manager=manager))
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    requested = []
    window.update_requested.connect(requested.append)
    row = window._general_page._update_row
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
    row = hotbar._settings_window._general_page._update_row
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
    hotbar._settings_window._general_page._update_row._confirm_button.click()
    assert quits == [True]
    assert (tmp_path / "install").exists()
