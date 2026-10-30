from __future__ import annotations

import pytest
from _clock import freeze_monotonic
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QAbstractButton, QLabel, QStyle, QStyleOptionComboBox

from pogled_assist.interaction.mouse_controller import GazeSettings
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.ui.settings_window import SettingsWindow
from pogled_assist.windows.windows_startup import StartupTaskResult


@pytest.mark.e2e
def test_shared_log_budget_control_clamps_and_emits_settings(qtbot, monkeypatch):
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    window = SettingsWindow(GazeSettings(), SpeechSettings())
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    window._select_tab(3)
    updates = []
    window.gaze_settings_changed.connect(updates.append)
    assert window._support_page._budget_value.text() == "4 GB"
    window._adjust_log_storage(1)
    assert updates[-1].log_storage_gb == 5
    assert window._support_page._budget_value.text() == "5 GB"
    window._adjust_log_storage(100)
    assert updates[-1].log_storage_gb == 10
    window._adjust_log_storage(-100)
    assert updates[-1].log_storage_gb == 1


@pytest.mark.e2e
@pytest.mark.parametrize("width", [800, 1280])
def test_gaze_guidance_stays_with_active_tab_without_clipping(qtbot, monkeypatch, width):
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    window = SettingsWindow(GazeSettings(eye_tracking_policy="any"), SpeechSettings())
    qtbot.addWidget(window)
    window.resize(width, 720)
    window._select_tab(1)
    window.show()
    page = window._gaze_page
    for index, expected in enumerate(("Primjena režima", "Pokazivač i provjera", "Kratak izlazak")):
        page.show_tab(index)
        notes = page.findChildren(QLabel, "settingGuidance")
        qtbot.waitUntil(lambda notes=notes: len([note for note in notes if note.isVisible()]) == 1)
        note = next(note for note in notes if note.isVisible())
        assert expected in note.text()
        assert note.wordWrap()
        assert note.width() <= 860
        assert note.height() >= note.heightForWidth(note.width())
        assert note.mapTo(page, QPoint()).x() >= 0
        assert note.mapTo(page, QPoint(note.width(), 0)).x() <= page.width()
        if width == 1280:
            qtbot.waitUntil(lambda: window._scroll.verticalScrollBar().maximum() == 0)
            assert note.visibleRegion().boundingRect() == note.rect()
        if index == 2:
            assert "nema napretka ni potvrde" in note.text()
            assert "niti ispravlja kalibraciju" in note.text()


@pytest.mark.e2e
@pytest.mark.parametrize("policy", ["both", "hold", "any"])
def test_eye_policy_choice_shows_its_full_label(qtbot, monkeypatch, policy):
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    window = SettingsWindow(GazeSettings(eye_tracking_policy=policy), SpeechSettings())
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window._select_tab(1)
    window.show()
    qtbot.wait(1)
    combo = window._gaze_page._policy_combo
    option = QStyleOptionComboBox()
    combo.initStyleOption(option)
    field = combo.style().subControlRect(
        QStyle.CC_ComboBox, option, QStyle.SC_ComboBoxEditField, combo
    )
    assert combo.fontMetrics().horizontalAdvance(combo.currentText()) <= field.width()


@pytest.mark.e2e
@pytest.mark.parametrize("script", ["latin", "arabic"])
@pytest.mark.parametrize("preset", ["default", "human_like", "efendija"])
@pytest.mark.parametrize("width", [800, 1280])
def test_voice_help_has_breathing_room_within_its_group(qtbot, monkeypatch, script, preset, width):
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    window = SettingsWindow(
        GazeSettings(), SpeechSettings(keyboard_script=script, voice_preset=preset)
    )
    qtbot.addWidget(window)
    window.resize(width, 720)
    window._select_tab(2)
    window.show()
    qtbot.wait(1)
    page = window._speech_page
    controls = page._arabic_voice if script == "arabic" else page._voice_choices
    control_bottom = controls.mapTo(page, QPoint()).y() + controls.height()
    hint_top = page._voice_hint.mapTo(page, QPoint()).y()
    assert hint_top - control_bottom >= 12
    hint_bottom = hint_top + page._voice_hint.height()
    group_index = page.layout().indexOf(controls.parentWidget())
    following = next(
        page.layout().itemAt(index).widget()
        for index in range(group_index + 1, page.layout().count())
        if page.layout().itemAt(index).widget() is not None
        and page.layout().itemAt(index).widget().isVisible()
    )
    assert following.mapTo(page, QPoint()).y() - hint_bottom >= 16
    if width == 1280:
        assert window._scroll.horizontalScrollBar().maximum() == 0
    assert all(button.height() == 58 for button in page._voice_buttons.values())


@pytest.mark.e2e
def test_settings_navigation_has_no_scroll_buttons(qtbot, monkeypatch):
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    window = SettingsWindow(GazeSettings(), SpeechSettings())
    qtbot.addWidget(window)
    nav = window.findChild(QLabel, "navSectionLabel").parentWidget()
    assert {button.text() for button in nav.findChildren(QAbstractButton)} == {
        "Aplikacija",
        "Pogled i odabir",
        "Govor i tastatura",
        "Podrška",
        "Pokušaj sačuvati",
    }


@pytest.mark.e2e
def test_tracking_notifications_setting_is_on_by_default_and_fits_gaze_page(qtbot, monkeypatch):
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    window = SettingsWindow(GazeSettings(), SpeechSettings())
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window._select_tab(1)
    window.show()
    qtbot.wait(1)
    checkbox = window._gaze_page._tracking_notifications_checkbox
    assert checkbox.isChecked()
    assert checkbox.height() >= 58
    assert window.rect().contains(QRect(checkbox.mapTo(window, QPoint()), checkbox.size()))
    assert checkbox.width() >= checkbox.fontMetrics().horizontalAdvance(checkbox.text()) + 50
    updates = []
    window.gaze_settings_changed.connect(updates.append)
    checkbox.click()
    assert not updates[-1].show_tracking_notifications
    assert not checkbox.isChecked()
    checkbox.click()
    assert updates[-1].show_tracking_notifications
    assert checkbox.isChecked()


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
    assert "Prirodni · Hamed" in [
        label.text() for label in window._speech_page._arabic_voice.findChildren(QLabel)
    ]
    assert not window._speech_page._voice_choices.isVisible()
    assert window.width() <= 1280 and window.height() <= 720
    for control in (
        window._speech_page._script_combo,
        window._speech_page._arabic_voice,
        window._speech_page._test_speech_button,
    ):
        assert window.rect().contains(QRect(control.mapTo(window, QPoint(0, 0)), control.size()))
        assert control.height() >= 58
    window._cycle_keyboard_script()
    assert updates[-1].keyboard_script == "latin"
    assert updates[-1].voice_preset == preset
    assert window._speech_page._voice_buttons[preset].isChecked()
    assert window._speech_page._voice_choices.isVisible()


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
    window = SettingsWindow(
        GazeSettings(selection_pause_ms=200, dwell_ms=250, smoothing=0.15),
        SpeechSettings(speed=310, letters_per_group=11),
    )
    qtbot.addWidget(window)
    assert window.windowTitle() == "Postavke"
    assert window._general_tab_button.text() == "Aplikacija"
    assert window._gaze_tab_button.text() == "Pogled i odabir"
    assert window._speech_tab_button.text() == "Govor i tastatura"
    gaze_updates = []
    speech_updates = []
    window.gaze_settings_changed.connect(gaze_updates.append)
    window.speech_settings_changed.connect(speech_updates.append)
    window.show()

    qtbot.mouseClick(window._gaze_tab_button, Qt.LeftButton)
    window._gaze_page.show_tab(1)
    qtbot.mouseClick(window._gaze_page._move_pointer_button, Qt.LeftButton)
    qtbot.mouseClick(window._gaze_page._precision_zoom_checkbox, Qt.LeftButton)
    for _ in range(2):
        window._adjust_selection_pause(-100)
        window._adjust_dwell_ms(-100)
        window._adjust_smoothing(-0.1)
        assert gaze_updates[-1].selection_pause_ms == 100
        assert gaze_updates[-1].dwell_ms == 150
        assert gaze_updates[-1].smoothing == 0.05
    qtbot.mouseClick(window._speech_tab_button, Qt.LeftButton)
    for _ in range(2):
        window._adjust_speech_speed(10)
        window._adjust_letters_per_group(1)
        assert speech_updates[-1].speed == 320
        assert speech_updates[-1].letters_per_group == 12
    window._speech_page._voice_buttons["human_like"].click()

    assert window._stack.currentIndex() == 2
    assert gaze_updates[-1].move_mouse is False
    assert gaze_updates[-1].use_precision_zoom is False
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

    for tab, controls in (
        (
            0,
            (
                window._general_page._startup_checkbox,
                window._general_page._launcher_window_checkbox,
            ),
        ),
        (
            1,
            (
                window._gaze_page._move_pointer_button,
                window._gaze_page._gaze_bubble_button,
                window._gaze_page._precision_zoom_checkbox,
                window._gaze_page._calibration_button,
                window._gaze_page._gaze_check_button,
            ),
        ),
        (
            2,
            (
                window._speech_page._test_speech_button,
                window._speech_page._saved_audio_button,
                window._speech_page._learned_words_button,
            ),
        ),
    ):
        window._select_tab(tab)
        if tab == 1:
            window._gaze_page.show_tab(1)
        qtbot.wait(1)
        for button in (window._exit_button, window._gaze_tab_button):
            rect = QRect(button.mapTo(window, QPoint()), button.size())
            assert window.rect().contains(rect), button.text()
            assert button.height() >= 58
        columns = _assert_action_cells(qtbot, window, controls)
        assert columns


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
    if len(rects) == 3:
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
    script_rect = QRect(
        window._speech_page._script_combo.mapTo(window, QPoint()),
        window._speech_page._script_combo.size(),
    )
    voice = (
        window._speech_page._arabic_voice
        if script == "arabic"
        else window._speech_page._voice_choices
    )
    voice_rect = QRect(voice.mapTo(window, QPoint()), voice.size())
    assert script_rect.height() == 58
    assert voice_rect.height() >= 58
    assert script_rect.bottom() < voice_rect.top()
    original_columns = None
    for speed, letters in ((80, 1), (155, 5), (320, 12)):
        window.update_speech_settings(
            SpeechSettings(keyboard_script=script, speed=speed, letters_per_group=letters)
        )
        qtbot.wait(1)
        values = (
            (window._speech_page._letters_group_value,)
            if script == "arabic"
            else (window._speech_page._speed_value, window._speech_page._letters_group_value)
        )
        columns = [_assert_speech_row(window, value) for value in values]
        assert all(column == columns[0] for column in columns)
        assert original_columns is None or columns[0] == original_columns
        original_columns = columns[0]
    assert window._speech_page._speed_row.isVisible() == (script != "arabic")
    if script != "arabic":
        assert voice_rect.bottom() < window._speech_page._speed_value.mapTo(window, QPoint()).y()
        speed_row = window._speech_page._speed_value.parentWidget().layout()
        speed_row.itemAtPosition(0, 1).widget().click()
        assert window._speech_settings.speed == 315
    letters_row = window._speech_page._letters_group_value.parentWidget().layout()
    letters_row.itemAtPosition(0, 1).widget().click()
    assert window._speech_settings.letters_per_group == 11


def _assert_speech_row(window, value):
    row = value.parentWidget()
    controls = tuple(row.layout().itemAtPosition(0, column).widget() for column in (1, 2, 3))
    rects = [QRect(control.mapTo(window, QPoint()), control.size()) for control in controls]
    assert all(rect.height() == 58 and window.rect().contains(rect) for rect in rects)
    assert len({rect.top() for rect in rects}) == 1
    assert rects[0].width() == rects[2].width() == 84
    assert rects[1].width() == 184
    assert rects[0].right() + 13 == rects[1].left()
    assert rects[1].right() + 13 == rects[2].left()
    assert row.mapTo(window, QPoint()).x() + row.width() - rects[2].right() - 1 <= 1
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
    now = freeze_monotonic(monkeypatch, 1.0)
    window.handle_eye_status(True, True)

    for at in (1.0, 1.249):
        now[0] = at
        window.handle_gaze(QPoint(center))

    assert progress == []
    assert window._stack.currentIndex() == 0

    for at in (1.25, 1.45):
        now[0] = at
        window.handle_gaze(QPoint(center))

    assert progress == [0.0, 1.0]

    window.pause_gaze_interaction()
    now[0] = 3.0
    window.handle_gaze(QPoint(center))

    assert progress == [0.0, 1.0]
    assert window._stack.currentIndex() == 1

    now[0] = 4.0
    window.handle_gaze(QPoint(center))

    assert progress == [0.0, 1.0]
