"""Caregiver setup and saved-audio controls for Efendija."""

from __future__ import annotations

import os

from PySide6.QtCore import QSignalBlocker, QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLineEdit, QProgressBar, QSlider

from ..settings_limits import ELEVENLABS_PERCENT_RANGE
from ..speech.eleven_account import AccountState, ElevenAccount
from ..speech.voice_state import VOICE_TEST_TEXT
from .settings_controls import SettingsControls, content_layout, setting_row, styled_label


class ElevenLabsPage(QFrame):
    back_requested = Signal()
    selection_changed = Signal(str, str)
    test_requested = Signal()
    stop_requested = Signal()
    tuning_changed = Signal(int, int)

    def __init__(self, controls: SettingsControls, account: ElevenAccount, parent) -> None:
        super().__init__(parent)
        self._controls, self.account = controls, account
        self._settings = None
        self._editing_key = False
        self._playback_state = "stopped"
        layout = content_layout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        header = QHBoxLayout()
        header.addWidget(controls.button("Nazad", self._back, QSize(120, 58)))
        header.addWidget(styled_label("ElevenLabs · Efendija", "sectionTitle", self), 1)
        self.check_button = controls.button("Provjeri vezu", self._check_connection, QSize(150, 58))
        header.addWidget(self.check_button)
        layout.addLayout(header)
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
        self.saved_key = styled_label("Ključ je sačuvan", "settingHint", row)
        self.replace_key = controls.button("Zamijeni ključ", self._replace_key, QSize(150, 58))
        self.remove_key = controls.button("Ukloni ključ", self._remove_key, QSize(150, 58))
        self.cancel_key = controls.button("Odustani", self.clear_input, QSize(120, 58))
        grid.addWidget(self.saved_key, 0, 1, 2, 1)
        grid.addWidget(self.key_input, 0, 1, 2, 1)
        grid.setColumnStretch(1, 2)
        grid.addWidget(self.show_key, 0, 2, 2, 1)
        grid.addWidget(self.replace_key, 0, 2, 2, 1)
        grid.addWidget(self.save_key, 0, 3, 2, 1)
        grid.addWidget(self.remove_key, 0, 3, 2, 1)
        grid.addWidget(self.cancel_key, 0, 4, 2, 1)
        layout.addWidget(row)
        self.connection = styled_label("", "settingHint", self)
        self.connection.setTextFormat(Qt.PlainText)
        self.connection.setWordWrap(True)
        layout.addWidget(self.connection)
        self.voice = controls.choice(
            (), self._selection, lambda: self._cycle(self.voice), "ElevenLabs glas"
        )
        self.model = controls.choice(
            (), self._selection, lambda: self._cycle(self.model), "ElevenLabs model"
        )
        choices_layout = QHBoxLayout()
        for title, combo in (("Moji glasovi", self.voice), ("Model", self.model)):
            row, grid, _hint = setting_row(self, title)
            grid.setHorizontalSpacing(6)
            grid.addWidget(combo, 0, 1, 2, 1)
            choices_layout.addWidget(row, 1)
        layout.addLayout(choices_layout)
        tuning = QGridLayout()
        self.stability, self.stability_value = self._tuning_control(tuning, 0, "Stabilnost", 65)
        self.similarity, self.similarity_value = self._tuning_control(
            tuning, 1, "Sličnost glasa", 80
        )
        layout.addLayout(tuning)
        self.credits_label = styled_label("Stanje kredita nije dostupno.", "settingTitle", self)
        layout.addWidget(self.credits_label)
        self.credits = QProgressBar(self)
        self.credits.setAccessibleName("Preostali ElevenLabs krediti")
        self.credits.setRange(0, 100)
        self.credits.setTextVisible(False)
        self.credits.setFixedHeight(8)
        layout.addWidget(self.credits)
        self.credits_note = styled_label("", "settingHint", self)
        self.credits_note.setWordWrap(True)
        layout.addWidget(self.credits_note)
        row, grid, _hint = setting_row(
            self,
            VOICE_TEST_TEXT,
            "Proba troši ElevenLabs kredite. Priprema može trajati do 30 sekundi.",
        )
        self.test_button = controls.button(
            "Isprobaj Efendiju", self._test_voice, QSize(200, 58), "fa5s.play"
        )
        self.test_button.setObjectName("primaryButton")
        grid.addWidget(self.test_button, 0, 1, 2, 1)
        self.stop_button = controls.button(
            "Zaustavi", self.stop_requested.emit, QSize(120, 58), "fa5s.stop"
        )
        grid.addWidget(self.stop_button, 0, 2, 2, 1)
        layout.addWidget(row)
        self.playback_progress = QProgressBar(self)
        self.playback_progress.setRange(0, 0)
        self.playback_progress.setFixedHeight(5)
        self.playback_progress.setTextVisible(False)
        self.playback_progress.setAccessibleName("Govor je aktivan")
        layout.addWidget(self.playback_progress)
        for control in (self.stop_button, self.playback_progress):
            policy = control.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            control.setSizePolicy(policy)
        note = styled_label(
            "Dozvole: izgovor, čitanje glasova i modela; podaci o računu za kredite.\n"
            "Izgovor šalje tekst ElevenLabsu. Starter ne garantuje obradu bez čuvanja podataka. "
            "Zamjenski glasovi: Prirodni → Standardni.",
            "settingHint",
            self,
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        account.changed.connect(self.refresh)
        self.refresh(account.state)

    def configure(self, settings) -> None:
        self._settings = settings
        for slider, label, value in (
            (self.stability, self.stability_value, settings.elevenlabs_stability),
            (self.similarity, self.similarity_value, settings.elevenlabs_similarity),
        ):
            with QSignalBlocker(slider):
                slider.setValue(value)
            label.setText(f"{value}%")
        self.refresh(self.account.state)

    def _tuning_control(self, grid, column, title, value):
        heading = styled_label(title, "settingTitle", self)
        label = styled_label(f"{value}%", "valueLabel", self)
        header = QHBoxLayout()
        header.addWidget(heading, 1)
        header.addWidget(label)
        grid.addLayout(header, 0, column)
        slider = QSlider(Qt.Horizontal, self)
        slider.setAccessibleName(f"ElevenLabs {title}")
        slider.setRange(*ELEVENLABS_PERCENT_RANGE)
        slider.setValue(value)
        slider.setTracking(False)
        slider.setFixedHeight(58)
        slider.setToolTip(
            "Niže: izražajnije · Više: ujednačenije"
            if title == "Stabilnost"
            else "Sličnost odabranom glasu"
        )
        row = QHBoxLayout()
        for text, delta in (("-", -5), ("+", 5)):
            button = self._controls.button(
                text, lambda step=delta: slider.setValue(slider.value() + step), QSize(58, 58)
            )
            button.setFixedWidth(58)
            self._controls.rename(button, f"{title}: {'manje' if delta < 0 else 'više'}")
            row.addWidget(button)
            if delta < 0:
                row.addWidget(slider, 1)
        slider.valueChanged.connect(lambda current: label.setText(f"{current}%"))
        slider.valueChanged.connect(self._tuning_changed)
        grid.addLayout(row, 1, column)
        return slider, label

    def _tuning_changed(self, _value) -> None:
        self._controls.interrupt_gaze()
        self.tuning_changed.emit(self.stability.value(), self.similarity.value())

    def set_playback_state(self, state: str) -> None:
        self._playback_state = state
        self.refresh(self.account.state)

    def refresh(self, state: AccountState) -> None:
        self._controls.interrupt_gaze()
        self.connection.setText(state.message)
        self._refresh_key(state)
        subscription = state.subscription
        self.credits_note.setText(state.credits_message)
        self.credits.setVisible(subscription is not None)
        if subscription is None:
            self.credits_label.setText("Stanje kredita nije dostupno.")
        else:
            percent = (
                min(100, 100 * subscription.remaining // subscription.limit)
                if subscription.limit
                else 0
            )

            def number(value):
                return f"{value:,}".replace(",", ".")

            self.credits_label.setText(
                f"Preostalo {number(subscription.remaining)} / {number(subscription.limit)} kredita ({percent}%)"
            )
            self.credits.setValue(percent)
            color = "#e48c80" if percent < 10 else "#edc779" if percent < 20 else "#91dec0"
            self.credits.setStyleSheet(
                f"QProgressBar {{ background: #343a36; border: 0; border-radius: 4px; }} QProgressBar::chunk {{ background: {color}; border-radius: 4px; }}"
            )
        active = self._playback_state in ("preparing", "speaking")
        self.stop_button.setVisible(active)
        self.playback_progress.setVisible(active)
        label = {"preparing": "Pripremam…", "speaking": "Izgovaram…"}.get(
            self._playback_state, "Isprobaj Efendiju"
        )
        self.test_button.setText(label)
        self._controls.rename(self.test_button, label)
        self.check_button.setEnabled(state.has_key and not state.busy)
        config = self.account.config if self._settings is not None else None
        for combo, choices, current, variable in (
            (
                self.voice,
                state.options.voices if state.options else (),
                config.voice if config else "",
                "ELEVENLABS_VOICE_ID",
            ),
            (
                self.model,
                state.options.models if state.options else (),
                config.model if config else "",
                "ELEVENLABS_MODEL_ID",
            ),
        ):
            with QSignalBlocker(combo):
                combo.clear()
                if combo is self.voice:
                    combo.setPlaceholderText(
                        "Odaberite sačuvani glas"
                        if choices
                        else "Nema glasova"
                        if state.options is not None
                        else "Odaberite nakon provjere veze"
                    )
                else:
                    combo.addItem("Odaberite nakon provjere veze", "")
                for identifier, name in choices:
                    combo.addItem(name, identifier)
                if combo is not self.voice and current and combo.findData(current) < 0:
                    combo.addItem(current, current)
                index = combo.findData(current)
                combo.setCurrentIndex(index if combo is self.voice else max(0, index))
            combo.setEnabled(
                bool(choices) and not state.busy and not os.environ.get(variable, "").strip()
            )
        self.test_button.setEnabled(not active and self.account.can_test_voice)

    def clear_input(self) -> None:
        self._editing_key = False
        self.key_input.clear()
        self.key_input.setEchoMode(QLineEdit.Password)
        self.show_key.setChecked(False)
        self._refresh_key(self.account.state)
        self.connection.setText(self.account.state.message)

    def _refresh_key(self, state: AccountState) -> None:
        editing = not state.environment_key and (not state.has_key or self._editing_key)
        self.key_input.setPlaceholderText(
            "Unesite novi API ključ" if state.has_key else "Unesite API ključ"
        )
        for control in (self.key_input, self.show_key, self.save_key):
            control.setVisible(editing)
        self.cancel_key.setVisible(editing and state.has_key)
        self.saved_key.setVisible(not editing)
        self.saved_key.setText(
            "Ključ je postavljen varijablom okruženja."
            if state.environment_key
            else "Ključ je sačuvan"
        )
        for control in (self.replace_key, self.remove_key):
            control.setVisible(state.has_key and not state.environment_key and not editing)

    def _replace_key(self) -> None:
        self._controls.interrupt_gaze()
        self.clear_input()
        self._editing_key = True
        self._refresh_key(self.account.state)
        self.key_input.setFocus()

    def _back(self) -> None:
        self.clear_input()
        self.back_requested.emit()

    def _toggle_key(self) -> None:
        visible = self.key_input.echoMode() == QLineEdit.Password
        self.key_input.setEchoMode(QLineEdit.Normal if visible else QLineEdit.Password)
        self.show_key.setChecked(visible)

    def _save_key(self) -> None:
        value = self.key_input.text()
        self.key_input.setEchoMode(QLineEdit.Password)
        self.show_key.setChecked(False)
        if self.account.save_key(value):
            self.clear_input()

    def _check_connection(self) -> None:
        if self._saved_key_ready("provjere veze"):
            self.account.check()

    def _test_voice(self) -> None:
        if self._saved_key_ready("probe glasa"):
            self.test_requested.emit()

    def _saved_key_ready(self, action: str) -> bool:
        if self._editing_key or self.key_input.text():
            self.connection.setText(f"Sačuvajte novi ključ ili odaberite Odustani prije {action}.")
            return False
        return True

    def _remove_key(self) -> None:
        if self.account.remove_key():
            self.clear_input()

    def _selection(self, _index: int) -> None:
        if self._settings is not None:
            self.selection_changed.emit(
                self.voice.currentData() or self._settings.elevenlabs_voice_id,
                self.model.currentData() or "",
            )

    @staticmethod
    def _cycle(combo) -> None:
        if combo.count() > 1 or (combo.count() == 1 and combo.currentIndex() < 0):
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
        layout.addWidget(
            styled_label(
                "Efendijin glas, dostupan i bez interneta",
                "settingTitle",
                self,
            )
        )
        for title, text in (
            (
                "Čuva se",
                "Snimak se čuva kada cijela poruka odgovara jednoj spremljenoj frazi ili odgovoru. Prvi izgovor troši kredite; ponavljanje koristi snimak.",
            ),
            (
                "Ne čuva se",
                "Slobodno napisane poruke i kombinacije više stavki. Kombinaciju možete posebno spremiti kao jednu frazu.",
            ),
            (
                "Nakon izmjene",
                "Brisanje ili izmjena stavke, glasa ili modela uklanja pripadajući snimak.",
            ),
        ):
            row, _grid, hint = setting_row(self, title, text)
            hint.setWordWrap(True)
            row.setMinimumHeight(90)
            layout.addWidget(row)
        self.clear_button = controls.button("Obriši sačuvani zvuk", self._clear, QSize(240, 58))
        self.clear_button.setObjectName("dangerButton")
        layout.addWidget(self.clear_button)
        self.status = styled_label(
            "Fraze i odgovori ostaju sačuvani. Novi snimci ponovo troše kredite.",
            "settingHint",
            self,
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch(1)

    def _clear(self) -> None:
        self.status.setText(
            "Sačuvani zvuk je obrisan. Fraze i odgovori ostaju sačuvani."
            if self._clear_audio()
            else "Dio zvuka nije obrisan. Pokušajte ponovo."
        )
