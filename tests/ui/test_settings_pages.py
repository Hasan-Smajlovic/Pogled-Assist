import pytest
from PySide6.QtWidgets import QWidget

from pogled_assist.ui.gaze_settings_page import GazeSettingsPage
from pogled_assist.ui.general_settings_page import GeneralSettingsPage
from pogled_assist.ui.settings_controls import SettingsControls
from pogled_assist.ui.speech_settings_page import SpeechSettingsPage
from pogled_assist.ui.support_settings_page import SupportSettingsPage

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize(
    "page_type, button_name, signal_name",
    [
        (GazeSettingsPage, "_move_pointer_button", "toggle_move_pointer"),
        (GeneralSettingsPage, "_startup_checkbox", "toggle_start_with_windows"),
        (SpeechSettingsPage, "_test_speech_button", "request_speech_test"),
        (SupportSettingsPage, "_logging_checkbox", "toggle_logging_enabled"),
    ],
)
def test_pages_support_mouse_and_gaze_without_a_settings_window(
    qtbot, page_type, button_name, signal_name
):
    parent = QWidget()
    qtbot.addWidget(parent)
    controls = SettingsControls(parent, lambda: None)
    page = page_type(controls, parent=parent)
    button = getattr(page, button_name)
    signal = getattr(page, signal_name)
    with qtbot.waitSignal(signal):
        button.click()
    with qtbot.waitSignal(signal):
        controls._actions[button]()


@pytest.mark.parametrize(
    "page_type, combo_name, signal_name",
    [
        (GazeSettingsPage, "_policy_combo", "select_eye_tracking_policy"),
        (GeneralSettingsPage, "_selection_sound_combo", "selection_sound_combo_changed"),
        (SpeechSettingsPage, "_script_combo", "script_combo_changed"),
        (SpeechSettingsPage, "_letter_layout_combo", "letter_layout_combo_changed"),
    ],
)
def test_pages_publish_choice_values_and_gaze_cycles_the_same_control(
    qtbot, page_type, combo_name, signal_name
):
    parent = QWidget()
    qtbot.addWidget(parent)
    controls = SettingsControls(parent, lambda: None)
    page = page_type(controls, parent=parent)
    combo = getattr(page, combo_name)
    signal = getattr(page, signal_name)
    with qtbot.waitSignal(signal) as selected:
        combo.setCurrentIndex(1)
    assert selected.args == [combo.itemData(1)]
    with qtbot.waitSignal(signal) as cycled:
        controls._actions[combo]()
    assert cycled.args == [combo.currentData()]
