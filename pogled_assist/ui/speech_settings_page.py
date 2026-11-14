"""General speech choices, tuning and test actions in Settings."""

from PySide6.QtCore import QSignalBlocker, QSize, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from ..keyboard_layouts import ARABIC_SCRIPT, KEYBOARD_SCRIPTS, LETTER_LAYOUTS
from ..speech.speech_service import VOICE_PRESET_DEFAULT, VOICE_PRESETS
from ..speech.voice_state import ACTIVE_PLAYBACK_STATES, FALLBACK_NOTE, PLAYBACK_LABELS
from .settings_controls import (
    CONTROL_HEIGHT,
    busy_indicator,
    content_layout,
    cycle_choice,
    retain_size_when_hidden,
    setting_row,
    styled_label,
)

LETTER_LAYOUT_HINT = (
    "Sva slova se biraju jednim pogledom. Grupe slova imaju veće tipke i trebaju dva odabira. "
    "Arapsko pismo uvijek koristi grupe."
)
BOSNIAN_VOICE_HINT = "Standardni radi bez interneta. Prirodni i Efendija trebaju internet."
ARABIC_VOICE_HINT = "Arapski koristi prirodni muški glas Hamed. Potreban je internet. Izbor bosanskog glasa ostaje sačuvan."


class SpeechSettingsPage(QFrame):
    script_combo_changed = Signal(str)
    adjust_speech_speed = Signal(int)
    letter_layout_combo_changed = Signal(str)
    adjust_letters_per_group = Signal(int)
    set_voice_preset = Signal(str)
    open_eleven = Signal()
    request_speech_test = Signal()
    open_learning = Signal()
    open_audio = Signal()
    speech_stop_requested = Signal()

    def __init__(self, controls, parent=None):
        super().__init__(parent)
        self._controls = controls
        self._build()

    def _build(self):
        page = self
        layout = content_layout(page)
        header = QVBoxLayout()
        header.setSpacing(4)
        header.addWidget(styled_label("Govor i tastatura", "sectionTitle", page))
        header.addWidget(
            styled_label(
                "Podesite glas i raspored tastature za komunikaciju.", "sectionDescription", page
            )
        )
        layout.addLayout(header)

        self._script_combo = self._controls.choice(
            KEYBOARD_SCRIPTS,
            lambda index: self.script_combo_changed.emit(self._script_combo.itemData(index)),
            lambda: cycle_choice(self._script_combo),
            "Pismo tastature",
        )
        script_row, script_layout, _hint = setting_row(self, "Pismo tastature")
        script_layout.addWidget(self._script_combo, 0, 1, 2, 1)
        layout.addWidget(script_row)

        self._build_voice_choices(layout)
        row, self._speed_value = self._controls.adjust_row(
            "Brzina govora",
            "Broj riječi u minuti koji koristi eSpeak NG.",
            self.adjust_speech_speed.emit,
            5,
        )
        layout.addWidget(row)
        self._speed_row = row
        self._letter_layout_combo = self._controls.choice(
            LETTER_LAYOUTS,
            lambda index: self.letter_layout_combo_changed.emit(
                self._letter_layout_combo.itemData(index)
            ),
            lambda: cycle_choice(self._letter_layout_combo),
            "Raspored slova u Govoru",
        )
        layout_row, layout_grid, _hint = setting_row(
            self, "Raspored slova u Govoru", LETTER_LAYOUT_HINT
        )
        layout_grid.addWidget(self._letter_layout_combo, 0, 1, 2, 1)
        layout.addWidget(layout_row)
        row, self._letters_group_value = self._controls.adjust_row(
            "Broj slova u grupi",
            "Grupe na Tastaturi, te u Govoru s grupama slova ili arapskim pismom.",
            self.adjust_letters_per_group.emit,
            1,
        )
        layout.addWidget(row)

        self._build_speech_actions(layout)

    def _build_voice_choices(self, layout):
        page = self
        voice_group = QWidget(page)
        voice_layout = QVBoxLayout(voice_group)
        voice_layout.setContentsMargins(0, 0, 0, 4)
        voice_layout.setSpacing(12)
        self._voice_choices = QWidget(page)
        voices = QHBoxLayout(self._voice_choices)
        voices.setContentsMargins(0, 0, 0, 0)
        voices.setSpacing(12)
        self._voice_buttons = {}
        for value, label in VOICE_PRESETS:
            button = self._controls.toggle_button(
                label, lambda preset=value: self.set_voice_preset.emit(preset), QSize(180, 58)
            )
            voices.addWidget(button, 1)
            self._voice_buttons[value] = button
        voice_layout.addWidget(self._voice_choices)
        self._voice_hint = styled_label(BOSNIAN_VOICE_HINT, "settingHint", page)
        self._voice_hint.setWordWrap(True)
        self._arabic_voice = QFrame(page)
        self._arabic_voice.setObjectName("settingRow")
        self._arabic_voice.setMinimumHeight(CONTROL_HEIGHT)
        arabic = QHBoxLayout(self._arabic_voice)
        copy = QVBoxLayout()
        copy.addWidget(styled_label("Glas za arapski", "settingTitle", page))
        copy.addWidget(styled_label("Koristi se uz internet.", "settingHint", page))
        arabic.addLayout(copy, 1)
        arabic.addWidget(styled_label("Prirodni · Hamed", "settingTitle", page))
        voice_layout.addWidget(self._arabic_voice)
        voice_layout.addWidget(self._voice_hint)
        layout.addWidget(voice_group)
        self._eleven_summary, grid, self._eleven_summary_hint = setting_row(
            self, "Efendija · ElevenLabs", FALLBACK_NOTE
        )
        self._eleven_button = self._controls.button(
            "Podesi ElevenLabs", self.open_eleven.emit, QSize(220, 58)
        )
        grid.addWidget(self._eleven_button, 0, 1, 2, 1)
        layout.addWidget(self._eleven_summary)

    def _build_speech_actions(self, layout):
        page = self
        self._test_speech_button = self._controls.button(
            "Isprobaj govor", self.request_speech_test.emit, QSize(240, 58), "fa5s.play"
        )
        self._test_speech_button.setObjectName("primaryButton")
        self._stop_speech_button = self._controls.button(
            "Zaustavi", self.speech_stop_requested.emit, QSize(120, 58), "fa5s.stop"
        )
        self._stop_speech_button.hide()
        self._learned_words_button = self._controls.button(
            "Naučene riječi", self.open_learning.emit, QSize(240, 58)
        )
        self._saved_audio_button = self._controls.button(
            "Sačuvani zvuk", self.open_audio.emit, QSize(220, 58)
        )
        actions = QGridLayout()
        actions.setHorizontalSpacing(12)
        actions.setVerticalSpacing(8)
        actions.addWidget(styled_label("Proba glasa", "settingTitle", page), 0, 0, 1, 2)
        actions.addWidget(styled_label("Biblioteka", "settingTitle", page), 0, 2, 1, 2)
        for column, button in enumerate(
            (
                self._test_speech_button,
                self._stop_speech_button,
                self._saved_audio_button,
                self._learned_words_button,
            )
        ):
            button.setMinimumWidth(120)
            actions.setColumnStretch(column, 1)
            actions.addWidget(button, 1, column)
        layout.addSpacing(12)
        layout.addLayout(actions)
        self._speech_test_progress = busy_indicator(page)
        layout.addWidget(self._speech_test_progress)
        retain_size_when_hidden(self._stop_speech_button)
        layout.addStretch(1)

    def refresh(self, settings, playback_state, account):
        self._speed_value.setText(f"{settings.speed} riječi/min")
        self._letters_group_value.setText(str(settings.letters_per_group))
        with QSignalBlocker(self._script_combo):
            self._script_combo.setCurrentIndex(
                max(0, self._script_combo.findData(settings.keyboard_script))
            )
        with QSignalBlocker(self._letter_layout_combo):
            self._letter_layout_combo.setCurrentIndex(
                max(0, self._letter_layout_combo.findData(settings.letter_layout))
            )
        arabic = settings.keyboard_script == ARABIC_SCRIPT
        self._voice_choices.setVisible(not arabic)
        self._arabic_voice.setVisible(arabic)
        for preset, button in self._voice_buttons.items():
            button.setChecked(preset == settings.voice_preset)
        efendija = settings.uses_efendija
        self._eleven_summary.setVisible(efendija)
        self._eleven_summary_hint.setText(account.state.message + "\n" + FALLBACK_NOTE)
        self._speed_row.setVisible(not arabic and settings.voice_preset == VOICE_PRESET_DEFAULT)
        self._saved_audio_button.setVisible(not arabic)
        active = playback_state in ACTIVE_PLAYBACK_STATES
        test_label = PLAYBACK_LABELS.get(
            playback_state, "Isprobaj Efendiju" if efendija else "Isprobaj govor"
        )
        self._stop_speech_button.setVisible(True)
        self._stop_speech_button.setEnabled(active)
        self._speech_test_progress.setVisible(active)
        self._test_speech_button.setText(test_label)
        self._controls.rename(self._test_speech_button, test_label)
        self._test_speech_button.setEnabled(not active and (not efendija or account.can_test_voice))
        self._voice_hint.setText(ARABIC_VOICE_HINT if arabic else BOSNIAN_VOICE_HINT)

    def playback_controls(self):
        return self._test_speech_button, self._stop_speech_button

    def check_voice(self, preset: str) -> None:
        self._voice_buttons[preset].setChecked(True)
