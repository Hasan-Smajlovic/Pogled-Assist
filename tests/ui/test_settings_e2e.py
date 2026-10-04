from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QRect, Qt

from pogled_assist.interaction.mouse_controller import GazeSettings
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.ui.settings_window import SettingsWindow
from pogled_assist.windows.windows_startup import StartupTaskResult


@pytest.mark.e2e
@pytest.mark.parametrize("preset", ["default", "human_like"])
def test_settings_arabic_voice_caption_and_script_selection_fit_150_percent(
    qtbot, monkeypatch, preset
):
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    window = SettingsWindow(GazeSettings(), SpeechSettings(voice_preset=preset))
    qtbot.addWidget(window)
    window._select_tab(2)
    window.resize(1280, 720)
    window.show()
    updates = []
    window.speech_settings_changed.connect(updates.append)
    window._cycle_keyboard_script()
    qtbot.wait(1)
    assert updates[-1].keyboard_script == "arabic"
    assert updates[-1].voice_preset == preset
    assert window._voice_combo.currentText() == "Prirodni · Hamed"
    assert not window._voice_combo.isEnabled()
    assert window.width() <= 1280 and window.height() <= 720
    for control in (window._script_combo, window._voice_combo, window._test_speech_button):
        assert window.rect().contains(QRect(control.mapTo(window, QPoint(0, 0)), control.size()))
        assert control.height() >= 58
    window._cycle_keyboard_script()
    assert updates[-1].keyboard_script == "latin"
    assert updates[-1].voice_preset == preset
    assert window._voice_combo.currentData() == preset
    assert window._voice_combo.isEnabled()


@pytest.mark.e2e
def test_settings_controls_emit_bounded_updates(qtbot, monkeypatch):
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.set_application_logging_enabled", lambda _enabled: None
    )
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.set_windows_startup_enabled",
        lambda enabled, **_options: StartupTaskResult(enabled, True, "updated"),
    )
    window = SettingsWindow(GazeSettings(), SpeechSettings())
    qtbot.addWidget(window)
    assert window.windowTitle() == "Postavke"
    assert window._general_tab_button.text() == "Opće postavke"
    assert window._gaze_tab_button.text() == "Postavke pogleda"
    assert window._speech_tab_button.text() == "Postavke govora"
    gaze_updates = []
    speech_updates = []
    window.gaze_settings_changed.connect(gaze_updates.append)
    window.speech_settings_changed.connect(speech_updates.append)
    window.show()

    qtbot.mouseClick(window._gaze_tab_button, Qt.LeftButton)
    qtbot.mouseClick(window._move_pointer_button, Qt.LeftButton)
    qtbot.mouseClick(window._precision_zoom_checkbox, Qt.LeftButton)
    for _ in range(100):
        window._adjust_selection_pause(-100)
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
    assert gaze_updates[-1].selection_pause_ms == 100
    assert gaze_updates[-1].dwell_ms == 150
    assert gaze_updates[-1].smoothing == 0.05
    assert speech_updates[-1].speed == 320
    assert speech_updates[-1].letters_per_group == 12
    assert speech_updates[-1].voice_preset == "human_like"


@pytest.mark.e2e
@pytest.mark.parametrize("size", [(1280, 720), (1920, 1080)])
def test_settings_actions_use_equal_cells_and_preserve_gaze_targets(qtbot, monkeypatch, size):
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    window = SettingsWindow(GazeSettings(), SpeechSettings())
    qtbot.addWidget(window)
    window.resize(*size)
    window.show()
    qtbot.waitUntil(window.isVisible)
    assert (window.width(), window.height()) == size

    action_columns = None
    for tab, controls in (
        (0, (window._startup_checkbox, window._logging_checkbox, window._launcher_window_checkbox)),
        (
            1,
            (
                window._move_pointer_button,
                window._gaze_bubble_button,
                window._interaction_overlay_button,
                window._precision_zoom_checkbox,
                window._calibration_button,
            ),
        ),
        (2, (window._test_speech_button, window._learned_words_button)),
    ):
        window._select_tab(tab)
        qtbot.wait(1)
        for button in (window._exit_button, window._gaze_tab_button):
            rect = QRect(button.mapTo(window, QPoint()), button.size())
            assert window.rect().contains(rect), button.text()
            assert button.height() >= 58
        columns = _assert_action_cells(qtbot, window, controls)
        assert action_columns is None or columns == action_columns
        action_columns = columns


def _assert_action_cells(qtbot, window, controls):
    rects = [QRect(control.mapTo(window, QPoint()), control.size()) for control in controls]
    _assert_action_grid(window, rects)
    for index, control in enumerate(controls):
        assert all(not rects[index].intersects(other) for other in rects[index + 1 :])
        _assert_gaze_target(qtbot, window, control)
    return tuple((rect.left(), rect.width()) for rect in rects[:2])


def _assert_action_grid(window, rects):
    assert max(rect.width() for rect in rects) - min(rect.width() for rect in rects) <= 1
    assert all(rect.height() == 58 and window.rect().contains(rect) for rect in rects)
    assert len({rect.top() for rect in rects[:3]}) == 1
    if len(rects) > 3:
        assert rects[3].left() == rects[0].left()
        assert abs(rects[4].left() - rects[1].left()) <= 1
        assert rects[3].top() == rects[4].top() == rects[0].bottom() + 13


def _assert_gaze_target(qtbot, window, control):
    center = control.mapToGlobal(control.rect().center())
    assert window._controls.action_at(center)[0] is control
    window._set_gaze_target(control)
    qtbot.wait(1)
    assert control.height() == 58
    window._set_gaze_target(None)


@pytest.mark.e2e
@pytest.mark.parametrize("size", [(1280, 720), (1920, 1080)])
@pytest.mark.parametrize("script", ["latin", "arabic"])
def test_settings_speech_rows_keep_order_and_alignment_at_value_limits(
    qtbot, monkeypatch, size, script
):
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    window = SettingsWindow(GazeSettings(), SpeechSettings(keyboard_script=script))
    qtbot.addWidget(window)
    window.resize(*size)
    window._select_tab(2)
    window.show()
    qtbot.waitUntil(window.isVisible)
    assert (window.width(), window.height()) == size
    script_rect = QRect(window._script_combo.mapTo(window, QPoint()), window._script_combo.size())
    voice_rect = QRect(window._voice_combo.mapTo(window, QPoint()), window._voice_combo.size())
    assert script_rect.size() == voice_rect.size()
    assert script_rect.height() == 58
    assert script_rect.left() == voice_rect.left()
    assert script_rect.bottom() < voice_rect.top()
    original_columns = None
    for speed, letters in ((80, 1), (155, 5), (320, 12)):
        window.update_speech_settings(
            SpeechSettings(keyboard_script=script, speed=speed, letters_per_group=letters)
        )
        qtbot.wait(1)
        columns = [
            _assert_speech_row(window, value)
            for value in (window._speed_value, window._letters_group_value)
        ]
        assert columns[0] == columns[1]
        assert original_columns is None or columns[0] == original_columns
        original_columns = columns[0]
    assert voice_rect.bottom() < window._speed_value.mapTo(window, QPoint()).y()
    speed_row = window._speed_value.parentWidget().layout()
    speed_row.itemAtPosition(0, 1).widget().click()
    assert window._speech_settings.speed == 315
    letters_row = window._letters_group_value.parentWidget().layout()
    letters_row.itemAtPosition(0, 1).widget().click()
    assert window._speech_settings.letters_per_group == 11


def _assert_speech_row(window, value):
    row = value.parentWidget()
    controls = tuple(row.layout().itemAtPosition(0, column).widget() for column in (1, 2, 3))
    rects = [QRect(control.mapTo(window, QPoint()), control.size()) for control in controls]
    assert all(rect.height() == 58 and window.rect().contains(rect) for rect in rects)
    assert len({rect.top() for rect in rects}) == 1
    assert rects[0].width() == rects[2].width() == 104
    assert rects[1].width() == 216
    assert rects[0].right() + 13 == rects[1].left()
    assert rects[1].right() + 13 == rects[2].left()
    assert value.fontMetrics().horizontalAdvance(value.text()) + 26 <= value.width()
    return tuple((rect.left(), rect.width()) for rect in rects)


@pytest.mark.e2e
def test_settings_gaze_waits_before_progress_and_locks_completed_control(qtbot, monkeypatch):
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    window = SettingsWindow(GazeSettings(selection_pause_ms=250, dwell_ms=200), SpeechSettings())
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(window.isVisible)
    progress = []
    window.interaction_progress_changed.connect(
        lambda _point, value, _label: progress.append(value)
    )
    center = window._gaze_tab_button.mapToGlobal(window._gaze_tab_button.rect().center())
    times = iter((1.0, 1.249, 1.25, 1.45, 3.0, 4.0))
    monkeypatch.setattr("pogled_assist.ui.settings_window.time.monotonic", lambda: next(times))

    window.handle_gaze(QPoint(center))
    window.handle_gaze(QPoint(center))

    assert progress == []
    assert window._stack.currentIndex() == 0

    window.handle_gaze(QPoint(center))
    window.handle_gaze(QPoint(center))

    assert progress == [0.0, 1.0]

    window.pause_gaze_interaction()
    window.handle_gaze(QPoint(center))

    assert progress == [0.0, 1.0]
    assert window._stack.currentIndex() == 1

    window.handle_gaze(QPoint(center))

    assert progress == [0.0, 1.0]
