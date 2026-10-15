"""Caregiver setup and saved-audio controls for Efendija."""

from __future__ import annotations

import os

from PySide6.QtCore import QSignalBlocker, QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLineEdit

from ..speech.eleven_account import AccountState, ElevenAccount
from ..speech.voice_state import VOICE_TEST_TEXT
from .settings_controls import SettingsControls, content_layout, setting_row, styled_label


class ElevenLabsPage(QFrame):
    back_requested = Signal()
    selection_changed = Signal(str, str)
    test_requested = Signal()

    def __init__(self, controls: SettingsControls, account: ElevenAccount, parent) -> None:
        super().__init__(parent)
        self._controls, self.account = controls, account
        self._settings = None
        layout = content_layout(self)
        header = QHBoxLayout()
        header.addWidget(controls.button("Nazad", self._back, QSize(120, 58)))
        header.addWidget(styled_label("ElevenLabs · Efendija", "sectionTitle", self), 1)
        layout.addLayout(header)
        layout.addWidget(styled_label(
            "Ključ čuva Windows na ovom računaru. Ažuriranja ga zadržavaju.",
            "sectionDescription", self,
        ))
        row, grid, _hint = setting_row(self, "API ključ")
        self.key_input = QLineEdit(row)
        self.key_input.setAccessibleName("ElevenLabs API ključ")
        self.key_input.setEchoMode(QLineEdit.Password)
        self.key_input.setMaxLength(1280)
        self.key_input.setMinimumWidth(100)
        self.key_input.setFixedHeight(58)
        self.key_input.setPlaceholderText("Unesite ključ")
        self.show_key = controls.toggle_button("Prikaži", self._toggle_key, QSize(100, 58))
        self.save_key = controls.button("Sačuvaj ključ", self._save_key, QSize(150, 58))
        grid.addWidget(self.key_input, 0, 1, 2, 1)
        grid.setColumnStretch(1, 2)
        grid.addWidget(self.show_key, 0, 2, 2, 1)
        grid.addWidget(self.save_key, 0, 3, 2, 1)
        layout.addWidget(row)
        row, grid, _hint = setting_row(self, "Veza s ElevenLabsom")
        self.remove_key = controls.button("Ukloni ključ", self._remove_key, QSize(150, 58))
        self.check_button = controls.button("Provjeri vezu", account.check, QSize(150, 58))
        grid.addWidget(self.remove_key, 0, 1, 2, 1)
        grid.addWidget(self.check_button, 0, 2, 2, 1)
        layout.addWidget(row)
        self.connection = styled_label("", "settingHint", self)
        self.connection.setTextFormat(Qt.PlainText)
        self.connection.setWordWrap(True)
        layout.addWidget(self.connection)
        self.voice = controls.choice((), self._selection, lambda: self._cycle(self.voice), "ElevenLabs glas")
        self.model = controls.choice((), self._selection, lambda: self._cycle(self.model), "ElevenLabs model")
        for title, combo in (("Glas", self.voice), ("Model", self.model)):
            row, grid, _hint = setting_row(self, title)
            grid.addWidget(combo, 0, 1, 2, 1)
            layout.addWidget(row)
        row, grid, _hint = setting_row(self, VOICE_TEST_TEXT, "Proba troši ElevenLabs kredite.")
        self.test_button = controls.button("Isprobaj Efendiju", self.test_requested.emit, QSize(200, 58), "fa5s.play")
        self.test_button.setObjectName("primaryButton")
        grid.addWidget(self.test_button, 0, 1, 2, 1)
        layout.addWidget(row)
        note = styled_label(
            "Provjera veze ne troši kredite. Izgovor šalje tekst ElevenLabsu; "
            "Starter ne garantuje obradu bez čuvanja podataka.\n"
            "Ako Efendija nije dostupan: Prirodni → Standardni. Izbor Efendije ostaje sačuvan.\n"
            "Koriste se i ručne dopune kredita. Automatsku dopunu isključite na ElevenLabs računu.",
            "settingHint", self,
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        account.changed.connect(self.refresh)
        self.refresh(account.state)

    def configure(self, settings) -> None:
        self._settings = settings
        self.refresh(self.account.state)

    def refresh(self, state: AccountState) -> None:
        self._controls.interrupt_gaze()
        self.connection.setText(state.message)
        self.key_input.setPlaceholderText("Ključ je sačuvan" if state.has_key else "Unesite ključ")
        self.check_button.setEnabled(state.has_key and not state.busy)
        self.remove_key.setEnabled(state.has_key and not state.environment_key)
        self.save_key.setEnabled(not state.environment_key)
        self.key_input.setEnabled(not state.environment_key)
        config = self.account.config if self._settings is not None else None
        for combo, choices, current, variable in (
            (self.voice, state.options.voices if state.options else (), config.voice if config else "", "ELEVENLABS_VOICE_ID"),
            (self.model, state.options.models if state.options else (), config.model if config else "", "ELEVENLABS_MODEL_ID"),
        ):
            with QSignalBlocker(combo):
                combo.clear()
                combo.addItem("Odaberite nakon provjere veze", "")
                for identifier, name in choices:
                    combo.addItem(name, identifier)
                if current and combo.findData(current) < 0:
                    combo.addItem(current, current)
                combo.setCurrentIndex(max(0, combo.findData(current)))
            combo.setEnabled(bool(choices) and not state.busy and not os.environ.get(variable, "").strip())
        self.test_button.setEnabled(bool(
            state.has_key and state.options and config and config.voice
            and config.model and not state.busy
        ))

    def clear_input(self) -> None:
        self.key_input.clear()
        self.key_input.setEchoMode(QLineEdit.Password)
        self.show_key.setChecked(False)

    def _back(self) -> None:
        self.clear_input()
        self.back_requested.emit()

    def _toggle_key(self) -> None:
        visible = self.key_input.echoMode() == QLineEdit.Password
        self.key_input.setEchoMode(QLineEdit.Normal if visible else QLineEdit.Password)
        self.show_key.setChecked(visible)

    def _save_key(self) -> None:
        value = self.key_input.text()
        self.clear_input()
        self.account.save_key(value)

    def _remove_key(self) -> None:
        self.clear_input()
        self.account.remove_key()

    def _selection(self, _index: int) -> None:
        if self._settings is not None:
            self.selection_changed.emit(self.voice.currentData() or "", self.model.currentData() or "")

    @staticmethod
    def _cycle(combo) -> None:
        if combo.count() > 1:
            combo.setCurrentIndex((combo.currentIndex() + 1) % combo.count())


class SavedAudioPage(QFrame):
    back_requested = Signal()

    def __init__(self, controls: SettingsControls, clear_audio, parent) -> None:
        super().__init__(parent)
        self._clear_audio = clear_audio
        layout = content_layout(self)
        header = QHBoxLayout()
        header.addWidget(controls.button("Nazad", self.back_requested.emit, QSize(120, 58)))
        header.addWidget(styled_label("Sačuvani zvuk", "sectionTitle", self), 1)
        layout.addLayout(header)
        layout.addWidget(styled_label(
            "Efendijin glas, dostupan i bez interneta", "settingTitle", self,
        ))
        for title, text in (
            ("Čuva se", "Snimak se čuva kada cijela poruka odgovara jednoj spremljenoj frazi ili odgovoru. Prvi izgovor troši kredite; ponavljanje koristi snimak."),
            ("Ne čuva se", "Slobodno napisane poruke i kombinacije više stavki. Kombinaciju možete posebno spremiti kao jednu frazu."),
            ("Nakon izmjene", "Brisanje ili izmjena stavke, glasa ili modela uklanja pripadajući snimak."),
        ):
            row, _grid, hint = setting_row(self, title, text)
            hint.setWordWrap(True)
            row.setMinimumHeight(90)
            layout.addWidget(row)
        self.clear_button = controls.button("Obriši sačuvani zvuk", self._clear, QSize(240, 58))
        self.clear_button.setObjectName("dangerButton")
        layout.addWidget(self.clear_button)
        self.status = styled_label(
            "Fraze i odgovori ostaju sačuvani. Novi snimci ponovo troše kredite.", "settingHint", self,
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch(1)

    def _clear(self) -> None:
        self.status.setText(
            "Sačuvani zvuk je obrisan. Fraze i odgovori ostaju sačuvani."
            if self._clear_audio() else "Dio zvuka nije obrisan. Pokušajte ponovo."
        )
