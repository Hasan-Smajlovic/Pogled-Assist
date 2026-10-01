from __future__ import annotations

import copy
import logging
from dataclasses import replace

import pytest
from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal

from pogled_assist.interaction.mouse_controller import (
    CONTROLLER,
    KEYBOARD,
    LEFT_CLICK,
    QUICK_ACTIONS,
    SETTINGS,
    SPEECH,
    GazeSettings,
)
from pogled_assist.speech.speech_library import (
    CategoryRecord,
    PhraseRecord,
    SpeechLibrary,
    default_categories,
)
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.ui.controller_window import (
    CONTROLLER_WINDOW_ACTION_PREFIX,
    ControllerWindow,
)
from pogled_assist.ui.keyboard_window import KEYBOARD_WINDOW_ACTION_PREFIX, KeyboardWindow
from pogled_assist.ui.settings_window import SettingsWindow
from pogled_assist.ui.speech_window import (
    BOSNIAN_LETTERS,
    SPEECH_WINDOW_ACTION_PREFIX,
    SpeechWindow,
)
from pogled_assist.windows.windows_startup import StartupTaskResult


def test_installation_summary_offers_download_and_calibration_only_on_request(
    qtbot, tmp_path, monkeypatch
):
    from pogled_assist.installation_check import TOBII_DOWNLOAD_URL, InstallationItem
    from pogled_assist.ui import installation_window

    opened = []
    monkeypatch.setattr(
        installation_window.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toString()) or True,
    )
    window = installation_window.InstallationWindow(tmp_path, auto_check=False)
    qtbot.addWidget(window)
    window._show_results([InstallationItem("software", "Tobii softver", "Pronađen", "")])
    window._finished()
    assert window.calibrate_button.isEnabled()
    assert opened == []
    window.download_button.click()
    assert opened == [TOBII_DOWNLOAD_URL]
    actions = []
    monkeypatch.setattr(window, "_start", lambda action, result: actions.append(action))
    window.calibrate_button.click()
    assert actions == [installation_window.launch_tobii_guest_calibration]
    window._show_results(
        [InstallationItem("software", "Tobii softver", "Potrebna instalacija", "")]
    )
    window._finished()
    assert not window.calibrate_button.isEnabled()


class FakeSpeech:
    def __init__(self):
        self._settings = SpeechSettings()
        self.requests = []
        self.stop_calls = 0

    @property
    def settings(self):
        return replace(self._settings)

    def speak(self, text, settings=None):
        self.requests.append((text, replace(settings) if settings is not None else self.settings))
        return True

    def stop(self):
        self.stop_calls += 1


@pytest.mark.parametrize("source", ["gaze", "button", "keyboard"])
def test_speech_playback_logs_input_source_without_message(qtbot, caplog, source):
    speech = FakeSpeech()
    window = SpeechWindow(speech, library_store=FakeLibraryStore())
    qtbot.addWidget(window)
    window.show()
    window._input.setText("SYNTHETIC PRIVATE MESSAGE")
    with caplog.at_level(logging.INFO):
        if source == "gaze":
            window.handle_gaze_action(f"{SPEECH_WINDOW_ACTION_PREFIX}play")
        elif source == "button":
            qtbot.mouseClick(window._play_button, Qt.LeftButton)
        else:
            qtbot.keyClick(window._input, Qt.Key_Return)
    assert len(speech.requests) == 1
    assert f"Speech playback requested: source={source}." in caplog.text
    assert "SYNTHETIC PRIVATE MESSAGE" not in caplog.text


class FakeAlarmSound(QObject):
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.start_calls = 0
        self.stop_calls = 0
        self.start_result = True
        self.last_error = None

    def start(self):
        self.start_calls += 1
        return self.start_result

    def stop(self):
        self.stop_calls += 1


class FakeLibraryStore:
    def __init__(self, library=None):
        self.library = copy.deepcopy(library or SpeechLibrary(categories=default_categories()))
        self.saved = []
        self.fail_saves = False

    def load(self):
        return copy.deepcopy(self.library)

    def save(self, library):
        if self.fail_saves:
            return False
        self.library = copy.deepcopy(library)
        self.saved.append(copy.deepcopy(library))
        return True


def click_speech_action(qtbot, window, command):
    button = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}{command}"]
    qtbot.waitUntil(button.isVisible)
    button.click()


class FakeKeyboardInput:
    def __init__(self):
        self.typed = []
        self.pressed = []

    def foreground_window(self):
        return 50

    def belongs_to_current_process(self, _hwnd):
        return False

    def type_text(self, text):
        self.typed.append(text)

    def press_key(self, key):
        self.pressed.append(key)

    def is_window(self, _hwnd):
        return True

    def set_foreground_window(self, _hwnd):
        return True


class FakeControllerInput(FakeKeyboardInput):
    def __init__(self):
        super().__init__()
        self.clicks = []
        self.scrolls = []

    def click(self, x, y, **options):
        self.clicks.append((x, y, options))

    def click_current(self, **options):
        self.clicks.append((None, None, options))

    def scroll(self, units):
        self.scrolls.append(units)


@pytest.mark.e2e
def test_speech_keyboard_entry_playback_and_phrase_workflow(qtbot):
    store = FakeLibraryStore()
    speech = FakeSpeech()
    window = SpeechWindow(speech, library_store=store)
    qtbot.addWidget(window)
    window.show()

    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:1"].click()
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}letter:1:1"].click()
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}space"].click()
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"].click()
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:0"].click()
    window._play_button.click()

    assert window._input.text() == "DŽ A"
    assert speech.requests[0][0] == "DŽ A"

    window._phrases_button.click()
    window._add_item_button.click()
    window._input.setText("  Trebam   pomoć ")
    window._save_item_button.click()

    assert store.saved[-1].phrases == [PhraseRecord("TREBAM POMOĆ", 0)]
    assert window._input.text() == "DŽ A"

    phrase_button = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}list:select:0"]
    qtbot.waitUntil(phrase_button.isVisible)
    phrase_button.click()
    assert window._input.text() == "DŽ A TREBAM POMOĆ "
    assert store.saved[-1].phrases == [PhraseRecord("TREBAM POMOĆ", 1)]


@pytest.mark.e2e
def test_speech_message_does_not_silently_truncate_long_saved_phrases(qtbot):
    long_phrase = "Vrlo duga poruka " * 30
    store = FakeLibraryStore(
        SpeechLibrary(categories=default_categories(), phrases=[PhraseRecord(long_phrase)])
    )
    window = SpeechWindow(FakeSpeech(), library_store=store)
    qtbot.addWidget(window)
    window.show()
    window._input.setText("Početak")

    window._append_phrase_to_input(long_phrase)

    assert window._input.text() == f"POČETAK {long_phrase.strip().upper()} "


@pytest.mark.e2e
def test_speech_categories_answers_and_shared_editor_preserve_message(qtbot):
    store = FakeLibraryStore()
    window = SpeechWindow(FakeSpeech(), library_store=store)
    qtbot.addWidget(window)
    window.show()
    window._input.setText("Moja poruka")

    window._categories_button.click()
    assert window._view_mode == "categories"
    assert window._categories_button.text() == "Tastatura"
    assert window._page_label.text() == "1 / 1"
    category_button = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}list:select:0"]
    assert category_button.text().startswith("TREBAM\n")
    click_speech_action(qtbot, window, "list:select:0")
    assert window._view_mode == "answers"
    assert window._view_title.text() == "TREBAM"
    assert window._back_button.isVisible()
    answer_button = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}list:select:0"]
    assert answer_button.text() == "TREBAM VODE"

    click_speech_action(qtbot, window, "list:select:0")
    assert window._input.text() == "MOJA PORUKA TREBAM VODE "

    window._add_item_button.click()
    assert window._editor.kind == "answer"
    assert window._input.text() == ""
    assert not window._categories_button.isEnabled()
    assert not window._phrases_button.isEnabled()
    window._input.setText("Sedmi odgovor")
    window._save_item_button.click()

    assert window._view_mode == "answers"
    assert window._list_page == 1
    assert window._page_label.text() == "2 / 2"
    assert window._input.text() == "MOJA PORUKA TREBAM VODE "
    assert store.library.categories[0].answers[-1] == "SEDMI ODGOVOR"

    window._add_item_button.click()
    window._input.setText("   ")
    window._save_item_button.click()
    assert window._editor is not None
    assert window._input.text() == "   "
    assert window._status_label.text() == "Prvo unesite tekst."

    window._input.setText("sedmi   odgovor")
    window._save_item_button.click()
    assert window._editor is not None
    assert window._input.text() == "SEDMI   ODGOVOR"
    assert "već postoji" in window._status_label.text()
    window._cancel_editor_button.click()
    assert window._view_mode == "answers"
    assert window._list_page == 1
    assert window._input.text() == "MOJA PORUKA TREBAM VODE "


@pytest.mark.e2e
def test_speech_list_and_dialog_controls_are_large_gaze_targets(qtbot):
    window = SpeechWindow(FakeSpeech(), library_store=FakeLibraryStore())
    qtbot.addWidget(window)
    window.resize(1440, 900)
    window.show()
    qtbot.waitUntil(window.isVisible)

    window._categories_button.click()
    qtbot.waitUntil(window._add_item_button.isVisible)

    list_controls = (
        window._add_item_button,
        window._delete_mode_button,
        window._previous_page_button,
        window._next_page_button,
    )
    assert all(button.width() >= 160 for button in list_controls)
    assert all(button.height() >= 80 for button in list_controls)
    alarm = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}alarm:start"]
    assert window._key_grid_host.width() >= alarm.width() * 2
    assert f"{SPEECH_WINDOW_ACTION_PREFIX}close" not in window._action_buttons

    window._input.setText("Poruka")
    window._clear_button.click()
    qtbot.waitUntil(lambda: window._active_dialog is window._confirm_dialog)

    cancel = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:cancel"]
    confirm = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:accept"]
    assert window._confirm_dialog.width() >= 900
    assert window._confirm_dialog.height() >= 440
    assert cancel.height() >= 128
    assert confirm.height() >= 128


@pytest.mark.e2e
def test_speech_add_and_cancel_category_answer_and_phrase_editors(qtbot):
    phrases = [PhraseRecord(f"Fraza {index}") for index in range(7)]
    store = FakeLibraryStore(SpeechLibrary(categories=default_categories(), phrases=phrases))
    window = SpeechWindow(FakeSpeech(), library_store=store)
    qtbot.addWidget(window)
    window.show()
    window._input.setText("Razgovor")

    window._categories_button.click()
    window._add_item_button.click()
    window._input.setText("Nova kategorija")
    window._save_item_button.click()
    assert store.library.categories[-1] == CategoryRecord("NOVA KATEGORIJA")
    assert window._input.text() == "RAZGOVOR"

    window._add_item_button.click()
    window._input.setText("Odbačena kategorija")
    window._cancel_editor_button.click()
    assert all(item.name != "ODBAČENA KATEGORIJA" for item in store.library.categories)
    assert window._input.text() == "RAZGOVOR"

    click_speech_action(qtbot, window, "list:select:0")
    window._add_item_button.click()
    window._input.setText("Odbačeni odgovor")
    window._cancel_editor_button.click()
    assert "ODBAČENI ODGOVOR" not in store.library.categories[0].answers
    assert window._view_mode == "answers"
    assert window._input.text() == "RAZGOVOR"

    window._phrases_button.click()
    window._next_page_button.click()
    assert window._list_page == 1
    window._add_item_button.click()
    window._input.setText("ZZZ nova fraza")
    window._save_item_button.click()
    assert any(item.text == "ZZZ NOVA FRAZA" for item in store.library.phrases)
    assert window._list_page == 1
    assert window._input.text() == "RAZGOVOR"

    window._add_item_button.click()
    window._input.setText("Odbačena fraza")
    window._cancel_editor_button.click()
    assert all(item.text != "ODBAČENA FRAZA" for item in store.library.phrases)
    assert window._view_mode == "phrases"
    assert window._list_page == 1
    assert window._input.text() == "RAZGOVOR"


@pytest.mark.e2e
def test_speech_deletion_confirmation_clear_and_save_failures(qtbot):
    store = FakeLibraryStore(
        SpeechLibrary(
            categories=default_categories(),
            phrases=[PhraseRecord("Sačuvana fraza", 3)],
        )
    )
    window = SpeechWindow(FakeSpeech(), library_store=store)
    qtbot.addWidget(window)
    window.show()
    window._input.setText("Poruka ostaje")

    window._categories_button.click()
    window._delete_mode_button.click()
    click_speech_action(qtbot, window, "list:select:0")
    qtbot.waitUntil(lambda: window._active_dialog is window._confirm_dialog)
    assert "svi njeni odgovori" in window._confirm_copy.text()
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:cancel"].click()
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert len(store.library.categories) == 4

    click_speech_action(qtbot, window, "list:select:0")
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:accept"].click()
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert [category.name for category in store.library.categories] == [
        "Brzi odgovor",
        "Kako se osjećam",
        "Ljudi",
    ]
    assert window._deletion_mode is True

    window._delete_mode_button.click()
    click_speech_action(qtbot, window, "list:select:0")
    window._delete_mode_button.click()
    click_speech_action(qtbot, window, "list:select:0")
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:accept"].click()
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert store.library.categories[0].answers == [
        "Ne",
        "Možda",
        "Hvala",
        "Molim te",
        "Nisam razumio",
    ]

    window._phrases_button.click()
    window._add_item_button.click()
    window._input.setText("Privremeni unos")
    window._clear_button.click()
    qtbot.waitUntil(lambda: window._active_dialog is window._confirm_dialog)
    assert "samo novi unos" in window._confirm_copy.text()
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:accept"].click()
    assert window._input.text() == ""
    window._cancel_editor_button.click()
    assert window._input.text() == "PORUKA OSTAJE"

    window._delete_mode_button.click()
    click_speech_action(qtbot, window, "list:select:0")
    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:accept"].click()
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert store.library.phrases == []
    window._delete_mode_button.click()

    store.fail_saves = True
    window._add_item_button.click()
    window._input.setText("Neuspjela fraza")
    window._save_item_button.click()
    assert window._editor is not None
    assert window._input.text() == "NEUSPJELA FRAZA"
    assert window._status_label.text() == "Spremanje nije uspjelo. Novi unos nije sačuvan."
    assert all(item.text != "NEUSPJELA FRAZA" for item in store.library.phrases)


@pytest.mark.e2e
def test_speech_modal_blocks_background_and_supports_gaze(qtbot):
    speech = FakeSpeech()
    window = SpeechWindow(speech, library_store=FakeLibraryStore())
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(window.isVisible)

    assert len(window._letter_groups) == 6
    assert all(len(group) == 5 for group in window._letter_groups)
    assert [letter for group in window._letter_groups for letter in group] == BOSNIAN_LETTERS

    group_action = f"{SPEECH_WINDOW_ACTION_PREFIX}group:1"
    qtbot.mouseClick(window._action_buttons[group_action], Qt.LeftButton)
    qtbot.waitUntil(lambda: window._active_dialog is window._letter_dialog)
    assert window._modal_backdrop.isVisible()

    qtbot.mouseClick(window._play_button, Qt.LeftButton)
    qtbot.mouseClick(window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}space"], Qt.LeftButton)
    assert speech.requests == []
    assert window._input.text() == ""

    letter_action = f"{SPEECH_WINDOW_ACTION_PREFIX}letter:1:1"
    letter = window._action_buttons[letter_action]
    qtbot.waitUntil(letter.isVisible)
    qtbot.mouseClick(letter, Qt.LeftButton)
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert window._input.text() == "DŽ"
    assert not window._modal_backdrop.isVisible()

    gaze_group_action = f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"
    group = window._action_buttons[gaze_group_action]
    group_center = group.mapToGlobal(group.rect().center())
    assert window.action_at_global_point(group_center) == gaze_group_action
    window.handle_gaze_action(gaze_group_action)
    qtbot.waitUntil(lambda: window._active_dialog is window._letter_dialog)

    space_center = window._space_button.mapToGlobal(window._space_button.rect().center())
    assert window.action_at_global_point(space_center) is None
    window.handle_gaze_action(f"{SPEECH_WINDOW_ACTION_PREFIX}space")
    assert window._input.text() == "DŽ"

    gaze_letter_action = f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:0"
    gaze_letter = window._action_buttons[gaze_letter_action]
    qtbot.waitUntil(gaze_letter.isVisible)
    letter_center = gaze_letter.mapToGlobal(gaze_letter.rect().center())
    assert window.action_at_global_point(letter_center) == gaze_letter_action
    window.handle_gaze_action(gaze_letter_action)
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert window._input.text() == "DŽA"


@pytest.mark.e2e
def test_twelve_letter_dialog_fits_150_percent_display_and_accepts_gaze(qtbot):
    window = SpeechWindow(FakeSpeech(), letters_per_group=12, library_store=FakeLibraryStore())
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    qtbot.waitUntil(window.isVisible)

    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"].click()
    qtbot.waitUntil(lambda: window._active_dialog is window._letter_dialog)
    dialog = window._letter_dialog
    assert dialog.height() <= window.height() - 64
    assert dialog.width() <= window.width() - 64

    bounds = dialog.rect()
    for action in window._letter_dialog_actions:
        button = window._action_buttons[action]
        rect = QRect(button.mapTo(dialog, QPoint(0, 0)), button.size())
        assert bounds.contains(rect), action
        assert button.width() >= 140, action
        assert button.height() >= 110, action
        assert window.action_at_global_point(button.mapToGlobal(button.rect().center())) == action

    last_letter = f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:11"
    window.handle_gaze_action(last_letter)
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert window._input.text() == window._letter_groups[0][-1]


@pytest.mark.e2e
def test_single_letter_groups_fit_150_percent_display(qtbot):
    window = SpeechWindow(FakeSpeech(), letters_per_group=1, library_store=FakeLibraryStore())
    qtbot.addWidget(window)
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
def test_speech_symbols_backspace_clear_and_play(qtbot):
    speech = FakeSpeech()
    window = SpeechWindow(speech, library_store=FakeLibraryStore())
    qtbot.addWidget(window)
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
    qtbot.waitUntil(lambda: window._active_dialog is window._confirm_dialog)
    qtbot.mouseClick(
        window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:cancel"], Qt.LeftButton
    )
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert window._input.text() == "TREBAM POMOĆ"

    qtbot.mouseClick(window._clear_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window._active_dialog is window._confirm_dialog)
    qtbot.mouseClick(
        window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:accept"], Qt.LeftButton
    )
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert window._input.text() == ""

    qtbot.mouseClick(window._clear_button, Qt.LeftButton)
    assert window._active_dialog is None


@pytest.mark.e2e
def test_speech_alarm_stops_speech_blocks_background_and_reports_failure(qtbot):
    speech = FakeSpeech()
    alarm = FakeAlarmSound()
    window = SpeechWindow(speech, library_store=FakeLibraryStore(), alarm_sound=alarm)
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    window._input.setText("Poruka ostaje")

    alarm_action = f"{SPEECH_WINDOW_ACTION_PREFIX}alarm:start"
    stop_action = f"{SPEECH_WINDOW_ACTION_PREFIX}alarm:stop"
    window._action_buttons[alarm_action].click()
    qtbot.waitUntil(lambda: window._active_dialog is window._alarm_dialog)

    assert speech.stop_calls == 1
    assert alarm.start_calls == 1
    assert window._alarm_copy.text() == "Zvučni signal se ponavlja dok ga ne zaustavite."
    space_center = window._space_button.mapToGlobal(window._space_button.rect().center())
    assert window.action_at_global_point(space_center) is None
    assert window._input.text() == "PORUKA OSTAJE"

    window.handle_gaze_action(stop_action)
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert alarm.stop_calls >= 1
    assert window._input.text() == "PORUKA OSTAJE"

    window.handle_gaze_action(alarm_action)
    qtbot.waitUntil(lambda: window._active_dialog is window._alarm_dialog)
    window._action_buttons[stop_action].click()
    qtbot.waitUntil(lambda: window._active_dialog is None)

    alarm.start_result = False
    alarm.last_error = "Audio uređaj nije dostupan."
    window._action_buttons[alarm_action].click()
    qtbot.waitUntil(lambda: window._active_dialog is window._alarm_dialog)
    assert window._alarm_copy.text() == "Audio uređaj nije dostupan."
    assert window._status_label.text() == "Audio uređaj nije dostupan."

    alarm.failed.emit("Zvuk je prekinut.")
    assert window._alarm_copy.text() == "Zvuk je prekinut."
    window._action_buttons[stop_action].click()


@pytest.mark.e2e
def test_speech_sleep_preserves_unfinished_entry_and_supports_mouse_and_gaze(qtbot):
    phrases = [PhraseRecord(f"Fraza {index}") for index in range(7)]
    speech = FakeSpeech()
    window = SpeechWindow(
        speech,
        library_store=FakeLibraryStore(
            SpeechLibrary(categories=default_categories(), phrases=phrases)
        ),
        alarm_sound=FakeAlarmSound(),
    )
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    window._input.setText("Razgovor")
    window._phrases_button.click()
    window._next_page_button.click()
    window._add_item_button.click()
    window._input.setText("Nedovršena fraza")
    editor = window._editor

    sleep_action = f"{SPEECH_WINDOW_ACTION_PREFIX}sleep:start"
    wake_action = f"{SPEECH_WINDOW_ACTION_PREFIX}sleep:wake"
    window.handle_gaze_action(sleep_action)
    qtbot.waitUntil(lambda: window._active_dialog is window._sleep_dialog)

    assert speech.stop_calls == 1
    assert window._sleep_dialog.geometry() == QRect(window.mapToGlobal(QPoint(0, 0)), window.size())
    assert window._sleep_dialog.isVisible()
    assert window._input.text() == "NEDOVRŠENA FRAZA"
    assert window._editor is editor
    assert window._list_page == 1
    assert window._view_mode == "editor"
    assert editor is not None and editor.message == "RAZGOVOR"
    space_center = window._space_button.mapToGlobal(window._space_button.rect().center())
    assert window.action_at_global_point(space_center) is None

    qtbot.mouseClick(window._wake_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert window._input.text() == "NEDOVRŠENA FRAZA"
    assert window._editor is editor
    assert window._list_page == 1

    window._action_buttons[sleep_action].click()
    qtbot.waitUntil(lambda: window._active_dialog is window._sleep_dialog)
    wake_center = window._wake_button.mapToGlobal(window._wake_button.rect().center())
    assert window.action_at_global_point(wake_center) == wake_action
    window.handle_gaze_action(wake_action)
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert window._input.text() == "NEDOVRŠENA FRAZA"
    assert window._editor is editor


@pytest.mark.e2e
def test_speech_exit_offers_cancel_leave_speech_and_normal_app_shutdown(qtbot):
    speech = FakeSpeech()
    alarm = FakeAlarmSound()
    window = SpeechWindow(speech, library_store=FakeLibraryStore(), alarm_sound=alarm)
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    window._input.setText("Poruka")
    window._categories_button.click()
    click_speech_action(qtbot, window, "list:select:0")
    preserved_state = (
        window._input.text(),
        window._view_mode,
        window._category_index,
        window._list_page,
    )
    quit_requests = []
    window.quit_requested.connect(lambda: quit_requests.append(True))

    exit_action = f"{SPEECH_WINDOW_ACTION_PREFIX}exit"
    cancel_action = f"{SPEECH_WINDOW_ACTION_PREFIX}exit:cancel"
    leave_action = f"{SPEECH_WINDOW_ACTION_PREFIX}exit:leave-speech"
    quit_action = f"{SPEECH_WINDOW_ACTION_PREFIX}exit:quit-app"
    window._action_buttons[exit_action].click()
    qtbot.waitUntil(lambda: window._active_dialog is window._exit_dialog)

    cancel_button = window._action_buttons[cancel_action]
    leave_button = window._action_buttons[leave_action]
    quit_button = window._action_buttons[quit_action]
    cancel_rect = QRect(cancel_button.mapToGlobal(QPoint(0, 0)), cancel_button.size())
    leave_rect = QRect(leave_button.mapToGlobal(QPoint(0, 0)), leave_button.size())
    quit_rect = QRect(quit_button.mapToGlobal(QPoint(0, 0)), quit_button.size())
    assert leave_button.text() == "Izađi"
    assert quit_button.text() == "Ugasi aplikaciju"
    assert all(button.height() >= 128 for button in (cancel_button, leave_button, quit_button))
    assert not cancel_rect.intersects(leave_rect)
    assert not cancel_rect.intersects(quit_rect)
    assert not leave_rect.intersects(quit_rect)
    window.handle_gaze_action(cancel_action)
    qtbot.waitUntil(lambda: window._active_dialog is None)
    assert (
        window._input.text(),
        window._view_mode,
        window._category_index,
        window._list_page,
    ) == preserved_state
    assert quit_requests == []

    window.handle_gaze_action(exit_action)
    qtbot.waitUntil(lambda: window._active_dialog is window._exit_dialog)
    qtbot.mouseClick(leave_button, Qt.LeftButton)
    qtbot.waitUntil(window.isHidden)

    assert quit_requests == []
    assert speech.stop_calls == 1
    assert alarm.stop_calls >= 1

    window.show_full_screen()
    qtbot.waitUntil(window.isVisible)
    assert window._input.text() == "PORUKA"
    window.handle_gaze_action(exit_action)
    qtbot.waitUntil(lambda: window._active_dialog is window._exit_dialog)
    window.handle_gaze_action(quit_action)

    assert quit_requests == [True]
    assert speech.stop_calls == 2
    assert alarm.stop_calls >= 1


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
def test_settings_fit_150_percent_display_with_calibration_visible(qtbot, monkeypatch):
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    window = SettingsWindow(GazeSettings(), SpeechSettings())
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    qtbot.waitUntil(window.isVisible)
    window._select_tab(1)

    assert window.size().width() <= 1280
    assert window.size().height() <= 720
    bounds = QRect(0, 0, 1280, 720)
    for button in (window._exit_button, window._gaze_tab_button, window._calibration_button):
        rect = QRect(button.mapTo(window, QPoint(0, 0)), button.size())
        assert bounds.contains(rect), button.text()
        assert button.height() >= 58


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


@pytest.mark.e2e
def test_controller_routes_shortcuts_keyboard_and_quick_settings(qtbot, monkeypatch):
    window = ControllerWindow(GazeSettings(), SpeechSettings())
    qtbot.addWidget(window)
    assert window.windowTitle() == "Upravljač"
    assert [button.text() for button in window._tab_buttons.values()] == [
        "Opće",
        "Tastatura",
        "Govor",
        "Postavke",
    ]
    fake_input = FakeControllerInput()
    window._input = fake_input
    window.set_target_cursor_position((300, 400))
    settings = []
    speech_requests = []
    window.gaze_settings_changed.connect(settings.append)
    window.speech_requested.connect(lambda: speech_requests.append(True))

    window._trigger_action(f"{CONTROLLER_WINDOW_ACTION_PREFIX}left_click", source="mouse")
    window._trigger_action(f"{CONTROLLER_WINDOW_ACTION_PREFIX}double_left_click", source="gaze")
    window._trigger_action(f"{CONTROLLER_WINDOW_ACTION_PREFIX}enter")
    window._trigger_action(f"{CONTROLLER_WINDOW_ACTION_PREFIX}scroll_up")
    window._trigger_action(f"{CONTROLLER_WINDOW_ACTION_PREFIX}tab:keyboard")
    window._trigger_action(f"{CONTROLLER_WINDOW_ACTION_PREFIX}keyboard_group:0")
    window._trigger_action(f"{CONTROLLER_WINDOW_ACTION_PREFIX}keyboard_letter:0:0")
    window._trigger_action(f"{CONTROLLER_WINDOW_ACTION_PREFIX}tab:settings")
    window._trigger_action(f"{CONTROLLER_WINDOW_ACTION_PREFIX}settings:precision_zoom")
    window._trigger_action(f"{CONTROLLER_WINDOW_ACTION_PREFIX}settings:gaze_cursor")
    window._trigger_action(f"{CONTROLLER_WINDOW_ACTION_PREFIX}tab:speech")

    assert fake_input.clicks[0] == (300, 400, {"button": "left", "clicks": 1, "interval": 0.04})
    assert fake_input.clicks[1] == (None, None, {"button": "left", "clicks": 2, "interval": 0.04})
    assert fake_input.pressed == ["enter"]
    assert fake_input.scrolls == [3]
    assert fake_input.typed == ["A"]
    assert settings[-1].use_precision_zoom is False
    assert settings[-1].show_gaze_bubble is False
    assert speech_requests == [True]


class FakeAppBar:
    supported = False

    def register(self, *_args, **_kwargs):
        return False

    def unregister(self):
        return None

    def set_position(self, *_args):
        return None


class FakeHotbarInput(FakeControllerInput):
    def cursor_position(self):
        return 600, 500


class FakeSpeechService(FakeSpeech):
    available = True

    def update_settings(self, settings):
        self._settings = replace(settings)

    def stop(self):
        return None


@pytest.mark.e2e
def test_hotbar_coordinates_primary_ui_surfaces(qtbot, monkeypatch):
    from pogled_assist import toolbar
    from pogled_assist.ui import controller_window, keyboard_window, settings_window

    monkeypatch.setattr(toolbar, "WindowsAppBar", FakeAppBar)
    monkeypatch.setattr(toolbar, "WindowsInputController", FakeHotbarInput)
    monkeypatch.setattr(toolbar, "SpeechService", FakeSpeechService)
    monkeypatch.setattr(toolbar, "load_app_settings", lambda: (GazeSettings(), SpeechSettings()))
    monkeypatch.setattr(toolbar, "save_app_settings", lambda *_settings: None)
    monkeypatch.setattr(keyboard_window, "WindowsAppBar", FakeAppBar)
    monkeypatch.setattr(keyboard_window, "WindowsInputController", FakeHotbarInput)
    monkeypatch.setattr(controller_window, "WindowsAppBar", FakeAppBar)
    monkeypatch.setattr(controller_window, "WindowsInputController", FakeHotbarInput)
    monkeypatch.setattr(settings_window, "is_windows_startup_enabled", lambda: False)

    window = toolbar.HotbarWindow()
    qtbot.addWidget(window)
    quit_requests = []
    window._quit_application = lambda: quit_requests.append(True)

    assert window._hide_button.text() == "Sakrij"
    assert window._settings_button.text() == "Postavke"
    assert window._quick_actions_button.text() == "Brze radnje"
    assert window._foreground_input is not None
    assert window._last_external_foreground_window == 50
    assert window._last_external_cursor_position == (600, 500)

    window._run_toolbar_action(LEFT_CLICK, checked=True, source="mouse")
    assert window._mouse.active_mode == LEFT_CLICK

    window._run_toolbar_action(QUICK_ACTIONS, checked=True, source="mouse")
    assert window._mouse.quick_actions_enabled is True
    assert window._buttons[LEFT_CLICK].isHidden()

    window._run_toolbar_action(KEYBOARD, checked=True, source="mouse")
    assert window._keyboard_window is not None and window._keyboard_window.isVisible()

    window._run_toolbar_action(CONTROLLER, checked=True, source="mouse")
    assert window._keyboard_window.isHidden()
    assert window._controller_window is not None and window._controller_window.isVisible()

    window._run_toolbar_action(SPEECH, source="mouse")
    assert window._speech_window is not None and window._speech_window.isVisible()
    window._speech_window.quit_requested.emit()
    assert quit_requests == [True]

    window._run_toolbar_action(SETTINGS, source="mouse")
    assert window._controller_window.isHidden()
    assert window._settings_window is not None and window._settings_window.isVisible()


@pytest.fixture(params=[(1920, 1080), (1280, 720)])
def hotbar_gaze(qtbot, monkeypatch, request):
    from pogled_assist import toolbar
    from pogled_assist.ui import keyboard_window
    from scripts.ui.capture_ui import PreviewSuggestionService

    monkeypatch.setattr(toolbar, "WindowsAppBar", FakeAppBar)
    monkeypatch.setattr(toolbar, "WindowsInputController", FakeHotbarInput)
    monkeypatch.setattr(toolbar, "SpeechService", FakeSpeechService)
    monkeypatch.setattr(toolbar, "SuggestionService", PreviewSuggestionService)
    monkeypatch.setattr(toolbar, "speech_library_store", lambda _root: FakeLibraryStore())
    monkeypatch.setattr(toolbar, "load_app_settings", lambda: (GazeSettings(), SpeechSettings()))
    monkeypatch.setattr(toolbar.HotbarWindow, "_start_services", lambda _self: None)
    monkeypatch.setattr(keyboard_window, "WindowsAppBar", FakeAppBar)
    monkeypatch.setattr(keyboard_window, "WindowsInputController", FakeHotbarInput)
    hotbar = toolbar.HotbarWindow(simulate_gaze=True)
    qtbot.addWidget(hotbar)
    width, height = request.param
    hotbar.show()
    hotbar.setGeometry(0, 0, width, hotbar.BAR_HEIGHT)
    qtbot.wait(1)
    controller = hotbar._mouse
    controller._logical_screen_rect = (0, 0, width, height)
    controller._physical_screen_rect = (0, 0, 1920, 1080)
    controller.handle_eye_status(True, True)
    now = [10.0]
    monkeypatch.setattr("pogled_assist.interaction.mouse_controller.time.monotonic", lambda: now[0])
    actions = []
    progress = []
    controller.toolbar_action_requested.connect(actions.append)
    controller.interaction_progress_changed.connect(
        lambda _point, value, _label: progress.append(value)
    )

    def feed(point, milliseconds):
        now[0] = 10.0 + milliseconds / 1000
        controller.handle_gaze(point.x() / (width - 1), point.y() / (height - 1), milliseconds)

    return hotbar, controller, feed, actions, progress


@pytest.fixture
def speech_gaze(hotbar_gaze, qtbot):
    hotbar, controller, feed, actions, progress = hotbar_gaze
    hotbar._open_speech()
    window = hotbar._speech_window
    window.showNormal()
    window.setGeometry(*controller._logical_screen_rect)
    qtbot.waitUntil(window.isVisible)
    qtbot.wait(1)
    return window, controller, hotbar._speech, feed, actions, progress


@pytest.mark.e2e
@pytest.mark.parametrize("action", [SPEECH, KEYBOARD, SETTINGS])
@pytest.mark.parametrize("y", [0, 1])
def test_hotbar_gaze_acquires_buttons_at_top_edge(hotbar_gaze, monkeypatch, action, y):
    hotbar, _controller, feed, actions, _progress = hotbar_gaze
    from pogled_assist.ui import settings_window

    monkeypatch.setattr(settings_window, "is_windows_startup_enabled", lambda: False)
    point = hotbar._buttons[action].mapToGlobal(QPoint(50, 0))
    point.setY(y)
    assert hotbar.action_at_global_point(point) == action
    feed(point, 0)
    feed(point, 800)
    assert hotbar._buttons[action].property("gazeTarget") is True
    feed(point, 1001)
    assert actions == [action]
    opened = {
        SPEECH: hotbar._speech_window,
        KEYBOARD: hotbar._keyboard_window,
        SETTINGS: hotbar._settings_window,
    }[action]
    assert opened is not None and opened.isVisible()


@pytest.mark.e2e
def test_hotbar_top_edge_has_distinct_targets_and_neutral_gaps(hotbar_gaze):
    hotbar, _controller, _feed, _actions, _progress = hotbar_gaze
    bounds = [(action, hotbar.action_bounds(action)) for action in hotbar._buttons]
    bounds = [(action, rect) for action, rect in bounds if rect is not None]
    for x in range(hotbar.width()):
        point = QPoint(x, 0)
        matches = [action for action, rect in bounds if rect.contains(point)]
        assert len(matches) <= 1
        assert hotbar.action_at_global_point(point) == (matches[0] if matches else None)
    hotbar._buttons[SPEECH].setEnabled(False)
    assert hotbar.action_bounds(SPEECH) is None
    hotbar.hide()
    assert hotbar.action_at_global_point(QPoint(50, 0)) is None


@pytest.fixture(params=["hotbar", "keyboard"])
def edge_surface(hotbar_gaze, qtbot, request):
    hotbar, controller, feed, actions, progress = hotbar_gaze
    if request.param == "hotbar":
        window = hotbar
        action = QUICK_ACTIONS
        button = hotbar._buttons[action]
    else:
        hotbar._show_keyboard_sidebar()
        window = hotbar._keyboard_window
        _, _, width, height = controller._logical_screen_rect
        window.setGeometry(width - 380, hotbar.BAR_HEIGHT, 380, height - hotbar.BAR_HEIGHT)
        qtbot.wait(1)
        action = f"{KEYBOARD_WINDOW_ACTION_PREFIX}space"
        button = window._space_button
    center = button.mapToGlobal(button.rect().center())
    outside = button.mapToGlobal(QPoint(button.width() + 2, button.height() // 2))
    return window, controller, feed, actions, progress, action, center, outside


@pytest.mark.e2e
def test_hotbar_and_keyboard_hold_progress_without_selecting_outside(edge_surface):
    _window, _controller, feed, actions, progress, action, center, outside = edge_surface
    feed(center, 0)
    feed(center, 800)
    feed(outside, 820)
    feed(outside, 860)
    assert progress[-1] == pytest.approx(0.6)
    assert actions == []
    feed(center, 900)
    feed(center, 1099)
    assert actions == []
    feed(center, 1101)
    assert actions == [action]
    feed(outside, 1120)
    feed(center, 1160)
    feed(center, 2500)
    assert actions == [action]


@pytest.mark.e2e
@pytest.mark.parametrize("reset", ["eye", "long-departure", "hide", "resize"])
def test_hotbar_and_keyboard_discard_progress_after_interruption(edge_surface, reset):
    window, controller, feed, actions, _progress, _action, center, outside = edge_surface
    feed(center, 0)
    feed(center, 800)
    feed(outside, 820)
    if reset == "eye":
        controller.handle_eye_status(True, False)
        controller.handle_eye_status(True, True)
    elif reset == "long-departure":
        feed(outside, 950)
    elif reset == "hide":
        if hasattr(window, "_hide_hotbar"):
            window._hide_hotbar()
        else:
            window.hide_sidebar()
    else:
        window.resize(window.width() - 1, window.height())
    feed(center, 980)
    feed(center, 1200)
    assert actions == []


@pytest.mark.e2e
def test_keyboard_letter_entry_survives_brief_edge_jitter(hotbar_gaze, qtbot):
    hotbar, controller, feed, actions, _progress = hotbar_gaze
    hotbar._show_keyboard_sidebar()
    window = hotbar._keyboard_window
    _, _, width, height = controller._logical_screen_rect
    window.setGeometry(width - 380, 76, 380, height - 76)
    window._show_letter_group(0)
    qtbot.wait(1)
    action = f"{KEYBOARD_WINDOW_ACTION_PREFIX}letter:0:0"
    button = window._action_buttons[action]
    center = button.mapToGlobal(button.rect().center())
    outside = button.mapToGlobal(QPoint(button.width() + 2, button.height() // 2))
    feed(center, 0)
    feed(center, 800)
    feed(outside, 820)
    feed(center, 900)
    feed(center, 1101)
    assert actions == [action]
    assert window._input.typed == ["A"]
    assert window._active_group_index is None


@pytest.mark.e2e
@pytest.mark.parametrize("command", ["group:0", "letter:0:0", "suggestion:0", "play"])
def test_speech_gaze_keeps_progress_through_brief_edge_excursion(speech_gaze, qtbot, command):
    window, _controller, speech, feed, actions, progress = speech_gaze
    window._input.setText("ŽELIM ")
    if command.startswith("letter:"):
        click_speech_action(qtbot, window, "group:0")
    button = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}{command}"]
    center = button.mapToGlobal(button.rect().center())
    outside = button.mapToGlobal(QPoint(button.width() + 4, button.height() // 2))
    expected_word = button.text()

    feed(center, 0)
    feed(center, 800)
    assert progress[-1] == pytest.approx(0.6)
    feed(outside, 820)
    feed(outside, 840)
    feed(center, 860)
    assert progress[-1] == pytest.approx(0.6)
    feed(center, 1040)
    assert actions == []
    feed(center, 1061)

    assert actions == [f"{SPEECH_WINDOW_ACTION_PREFIX}{command}"]
    if command == "letter:0:0":
        assert window._input.text() == "ŽELIM A"
    elif command == "suggestion:0":
        assert window._input.text() == f"ŽELIM {expected_word} "
    elif command == "play":
        assert speech.requests[0][0] == "ŽELIM"
    else:
        assert window._active_dialog is window._letter_dialog


@pytest.mark.e2e
@pytest.mark.parametrize("near_edge", [True, False])
def test_speech_gaze_switches_letters_without_transferring_progress(speech_gaze, qtbot, near_edge):
    window, _controller, _speech, feed, actions, _progress = speech_gaze
    click_speech_action(qtbot, window, "group:0")
    first = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:0"]
    second = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:1"]
    first_center = first.mapToGlobal(first.rect().center())
    second_point = second.mapToGlobal(
        QPoint(2, second.height() // 2) if near_edge else second.rect().center()
    )
    assert window.action_at_global_point(second_point) == f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:1"
    feed(first_center, 0)
    feed(first_center, 980)
    feed(second_point, 1000)
    feed(second_point, 1100)
    assert actions == []
    feed(second_point, 1121)
    finish = 2122 if near_edge else 2001
    feed(second_point, finish - 2)
    assert actions == []
    feed(second_point, finish)
    assert window._input.text() == "B"
    assert actions == [f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:1"]


@pytest.mark.e2e
def test_speech_gaze_can_return_from_neighbor_without_selecting_it(speech_gaze, qtbot):
    window, _controller, _speech, feed, actions, progress = speech_gaze
    click_speech_action(qtbot, window, "group:0")
    first = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:0"]
    second = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:1"]
    center = first.mapToGlobal(first.rect().center())
    neighbor = second.mapToGlobal(QPoint(2, second.height() // 2))
    feed(center, 0)
    feed(center, 980)
    feed(neighbor, 1000)
    feed(neighbor, 1060)
    assert actions == []
    assert progress[-1] == pytest.approx(0.96)
    feed(center, 1080)
    assert actions == []
    feed(center, 1101)
    assert window._input.text() == "A"


@pytest.mark.e2e
@pytest.mark.parametrize("cancel", ["eye_loss", "mouse", "resize", "disable"])
def test_speech_gaze_discards_held_progress_when_context_is_lost(speech_gaze, qtbot, cancel):
    window, controller, _speech, feed, actions, _progress = speech_gaze
    button = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"]
    center = button.mapToGlobal(button.rect().center())
    outside = button.mapToGlobal(QPoint(button.width() + 4, button.height() // 2))
    feed(center, 0)
    feed(center, 800)
    feed(outside, 820)
    if cancel == "eye_loss":
        controller.handle_eye_status(True, False)
        feed(center, 840)
        controller.handle_eye_status(True, True)
    elif cancel == "mouse":
        click_speech_action(qtbot, window, "group:1")
        click_speech_action(qtbot, window, "letters:close")
    elif cancel == "resize":
        window.resize(window.width() - 20, window.height())
        qtbot.wait(1)
    else:
        button.setEnabled(False)
        feed(center, 840)
        button.setEnabled(True)
    center = button.mapToGlobal(button.rect().center())
    feed(center, 860)
    feed(center, 1061)
    assert actions == []
    if cancel in {"mouse", "resize"}:
        other = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:1"]
        feed(other.mapToGlobal(other.rect().center()), 1080)
        feed(center, 1100)
    feed(center, 2101)
    assert actions == [f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"]


@pytest.mark.e2e
@pytest.mark.parametrize("during_hold", [False, True])
def test_speech_gaze_changed_suggestion_requires_confirmed_departure(speech_gaze, during_hold):
    window, _controller, _speech, feed, actions, _progress = speech_gaze
    button = window._prediction_buttons[0]
    center = button.mapToGlobal(button.rect().center())
    outside = button.mapToGlobal(QPoint(button.width() + 4, button.height() // 2))
    feed(center, 0)
    feed(center, 800)
    if during_hold:
        feed(outside, 820)
    window._input.setText("ŽELIM ")
    feed(center, 860)
    feed(center, 2000)
    assert actions == []
    feed(outside, 2020)
    feed(center, 2060)
    feed(center, 3500)
    assert actions == []
    other = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"]
    feed(other.mapToGlobal(other.rect().center()), 3520)
    feed(center, 3540)
    feed(center, 4541)
    assert window._input.text() == "ŽELIM VODU "


@pytest.mark.e2e
def test_speech_gaze_switch_during_cooldown_waits_before_starting_selection(speech_gaze):
    window, _controller, _speech, feed, actions, _progress = speech_gaze
    window._input.setText("ŽELIM ")
    play = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}play"]
    group = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"]
    play_center = play.mapToGlobal(play.rect().center())
    group_center = group.mapToGlobal(group.rect().center())
    feed(play_center, 0)
    feed(play_center, 1001)
    feed(group_center, 1020)
    feed(group_center, 1340)
    feed(group_center, 1360)
    feed(group_center, 2359)
    assert actions == [f"{SPEECH_WINDOW_ACTION_PREFIX}play"]
    assert window._active_dialog is None
    feed(group_center, 2361)
    assert actions == [
        f"{SPEECH_WINDOW_ACTION_PREFIX}play",
        f"{SPEECH_WINDOW_ACTION_PREFIX}group:0",
    ]
    assert window._active_dialog is window._letter_dialog


@pytest.mark.e2e
@pytest.mark.parametrize("command", ["play", "suggestion:0"])
def test_speech_gaze_edge_jitter_cannot_repeat_completed_action(speech_gaze, command):
    window, _controller, _speech, feed, actions, _progress = speech_gaze
    window._input.setText("ŽELIM ")
    button = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}{command}"]
    center = button.mapToGlobal(button.rect().center())
    outside = button.mapToGlobal(QPoint(button.width() + 4, button.height() // 2))
    feed(center, 0)
    feed(center, 1001)
    assert len(actions) == 1
    feed(outside, 1020)
    feed(center, 1060)
    feed(center, 2400)
    feed(outside, 2420)
    feed(center, 2460)
    feed(center, 3800)
    assert len(actions) == 1
    feed(outside, 3820)
    feed(outside, 3941)
    feed(center, 3960)
    feed(center, 4961)
    assert len(actions) == 2


@pytest.mark.e2e
@pytest.mark.parametrize("command", ["play", "suggestion:0"])
@pytest.mark.parametrize("during_cooldown", [False, True])
def test_speech_gaze_can_repeat_after_departure_with_no_expiry_sample(
    speech_gaze, command, during_cooldown
):
    window, _controller, _speech, feed, actions, _progress = speech_gaze
    window._input.setText("ŽELIM ")
    button = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}{command}"]
    center = button.mapToGlobal(button.rect().center())
    outside = button.mapToGlobal(QPoint(button.width() + 4, button.height() // 2))
    feed(center, 0)
    feed(center, 1001)
    feed(center, 1010 if during_cooldown else 1400)
    assert len(actions) == 1
    feed(outside, 1020 if during_cooldown else 1420)
    # Return after the 120 ms hold, without another sample while outside.
    feed(center, 1160 if during_cooldown else 1560)
    start = 1360 if during_cooldown else 1560
    feed(center, start)
    feed(center, start + 999)
    assert len(actions) == 1
    feed(center, start + 1001)
    assert len(actions) == 2
