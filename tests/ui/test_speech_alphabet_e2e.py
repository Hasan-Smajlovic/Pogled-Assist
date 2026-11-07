from __future__ import annotations

from dataclasses import replace

import pytest
from _speech_fixtures import make_speech_window as make_speech_window
from _ui_fakes import FakeLibraryStore, FakeSpeech
from PySide6.QtCore import QPoint, QRect, Qt

from pogled_assist import diagnostics
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.ui.speech_window import BOSNIAN_LETTERS

pytestmark = pytest.mark.e2e


def _alphabet_buttons(window):
    return [window._action_buttons[window._action(f"letter:{index}")] for index in range(30)]


def _open_alphabet(qtbot, make_speech_window, **settings):
    speech = FakeSpeech()
    speech._settings = SpeechSettings(**settings)
    window = make_speech_window(speech, library_store=FakeLibraryStore())
    window.resize(1280, 720)
    window.show()
    qtbot.waitUntil(window.isVisible)
    qtbot.wait(1)
    return window


@pytest.mark.parametrize("editor", [False, True])
def test_all_bosnian_letters_fit_one_page_in_alphabetical_rows(qtbot, make_speech_window, editor):
    window = _open_alphabet(qtbot, make_speech_window)
    if editor:
        window._phrases_button.click()
        window._add_item_button.click()
        qtbot.wait(1)

    buttons = _alphabet_buttons(window)
    assert len(window._main_dynamic_actions) == 30
    assert [button.text() for button in buttons] == BOSNIAN_LETTERS
    assert window._action("letters:close") not in window._action_buttons
    assert window._page_label.isHidden()
    assert (window.width(), window.height()) == (1280, 720)
    rows = [buttons[start : start + 10] for start in range(0, 30, 10)]
    for row in rows:
        assert len({button.mapTo(window, QPoint()).y() for button in row}) == 1
        lefts = [button.mapTo(window, QPoint()).x() for button in row]
        assert lefts == sorted(lefts)
    assert rows[0][0].mapTo(window, QPoint()).y() < rows[1][0].mapTo(window, QPoint()).y()
    for button in buttons:
        rect = QRect(button.mapTo(window, QPoint()), button.size())
        assert window.rect().contains(rect), button.text()
        assert rect.bottom() < window._space_button.mapTo(window, QPoint()).y()
        assert button.height() >= 72, button.text()
        # The narrow app-control column leaves near-square keys at 1280 x 720.
        assert button.width() >= 95, button.text()
    if editor:
        assert window._save_item_button.isVisible()
        assert window._status_label.text() == "Unesite tekst, zatim odaberite Sačuvaj."


def test_one_gaze_selection_types_each_letter_and_keeps_keys_in_place(qtbot, make_speech_window):
    window = _open_alphabet(qtbot, make_speech_window)
    buttons = _alphabet_buttons(window)
    assert window._input.placeholderText() == "Odaberite slovo…"

    for letter in ("DŽ", "A", "LJ", "NJ"):
        window.handle_gaze_action(window._action(f"letter:{BOSNIAN_LETTERS.index(letter)}"))
    assert window._input.text() == "DŽALJNJ"
    assert _alphabet_buttons(window) == buttons
    assert window._active_group_index is None
    assert window._keyboard_departure_bounds is None

    window._backspace_button.click()
    assert window._input.text() == "DŽALJ"
    qtbot.keyClick(window, Qt.Key_Escape)
    assert _alphabet_buttons(window) == buttons
    assert window._input.text() == "DŽALJ"


def test_symbols_return_to_the_alphabet(qtbot, make_speech_window):
    window = _open_alphabet(qtbot, make_speech_window)
    window._keyboard_toggle_button.click()
    assert window._keyboard_toggle_button.text() == "Slova"
    window._keyboard_toggle_button.click()
    assert window._keyboard_toggle_button.text() == "Brojevi i znakovi"
    assert [button.text() for button in _alphabet_buttons(window)] == BOSNIAN_LETTERS


def test_group_choice_and_arabic_keep_the_group_keyboard(qtbot, make_speech_window):
    window = _open_alphabet(qtbot, make_speech_window, letter_layout="groups")
    assert window._action("group:0") in window._action_buttons
    assert window._action("letter:0") not in window._action_buttons
    assert window._input.placeholderText() == "Odaberite grupu slova…"

    window.update_settings(replace(window._speech_settings, letter_layout="all"))
    assert [button.text() for button in _alphabet_buttons(window)] == BOSNIAN_LETTERS
    assert window._action("group:0") not in window._action_buttons

    window._script_button.click()
    qtbot.waitUntil(lambda: window._speech_settings.keyboard_script == "arabic")
    assert window._speech_settings.letter_layout == "all"
    assert window._action("group:0") in window._action_buttons
    assert window._action("letter:0") not in window._action_buttons
    window._script_button.click()
    qtbot.waitUntil(lambda: window._speech_settings.keyboard_script == "latin")
    assert [button.text() for button in _alphabet_buttons(window)] == BOSNIAN_LETTERS


def _left(window, widget):
    return widget.mapTo(window, QPoint()).x()


def _app_controls(window):
    return [
        window._action_buttons[window._action(name)]
        for name in ("alarm:start", "sleep:start", "exit")
    ]


def test_all_letters_narrow_the_app_controls_and_groups_keep_them_wide(qtbot, make_speech_window):
    window = _open_alphabet(qtbot, make_speech_window)
    alarm, sleep, exit_button = _app_controls(window)
    last_letter = _alphabet_buttons(window)[9]

    assert [button.text() for button in (alarm, sleep, exit_button)] == ["Alarm", "Odmor", "Izlaz"]
    assert 150 <= alarm.width() <= 240
    assert alarm.width() > last_letter.width()
    # Aligned with the script button below, and separated from the keys by a line in the gap.
    assert (_left(window, window._script_button), window._script_button.width()) == (
        _left(window, alarm),
        alarm.width(),
    )
    letters_end = _left(window, last_letter) + last_letter.width()
    divider = window._system_divider
    assert divider.isVisible() and divider.width() == 1
    assert letters_end < _left(window, divider) < _left(window, alarm)
    assert _left(window, alarm) - letters_end == 12
    assert divider.height() >= alarm.height() * 3

    # The column follows the saved layout, not the open view.
    window._phrases_button.click()
    qtbot.wait(1)
    assert alarm.width() <= 240

    window.update_settings(replace(window._speech_settings, letter_layout="groups"))
    qtbot.wait(1)
    assert alarm.width() >= 280
    assert alarm.text() == "Alarm\nPozovi pomoć"
    assert window._script_button.width() == alarm.width()
    assert divider.isVisible()

    window.update_settings(replace(window._speech_settings, letter_layout="all"))
    window._script_button.click()
    qtbot.waitUntil(lambda: window._speech_settings.keyboard_script == "arabic")
    qtbot.wait(1)
    # Arabic always uses groups, so its app controls stay wide.
    assert alarm.width() >= 280
    assert exit_button.text() == "Izlaz\nIzađi ili ugasi aplikaciju"


def test_alphabet_diagnostics_never_name_the_selected_letter(qtbot, make_speech_window):
    window = _open_alphabet(qtbot, make_speech_window)
    action = window._action(f"letter:{BOSNIAN_LETTERS.index('DŽ')}")
    assert diagnostics.control_role(action) == "letter"
    assert diagnostics.safe_action(action) == "content_target"
    token = window._diagnostic_context.token(action)
    assert len(token) == 32 and int(token, 16) >= 0  # Random ID, not the letter or index.
