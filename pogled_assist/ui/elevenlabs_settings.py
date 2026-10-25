"""Caregiver setup and saved-audio controls for Efendija."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QProgressBar,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
)

from ..settings_limits import (
    ELEVENLABS_PERCENT_RANGE,
    ELEVENLABS_SIMILARITY_DEFAULT,
    ELEVENLABS_STABILITY_DEFAULT,
    ELEVENLABS_STABILITY_STEPS,
)
from ..speech.eleven_account import AccountState, ElevenAccount
from ..speech.elevenlabs import env_override
from ..speech.voice_state import (
    ACTIVE_PLAYBACK_STATES,
    CREDITS_UNAVAILABLE,
    FALLBACK_NOTE,
    PLAYBACK_LABELS,
    VOICE_TEST_TEXT,
)
from .settings_controls import (
    SettingsControls,
    busy_indicator,
    content_layout,
    retain_size_when_hidden,
    setting_row,
    styled_label,
)


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
        layout.setSpacing(12)
        self._layout = layout
        self._build_header()
        self._build_key_row()
        self._groups = QBoxLayout(QBoxLayout.LeftToRight)
        self._groups.setSpacing(16)
        voice_group = QGroupBox("Glas i način izgovora", self)
        voice_layout = QVBoxLayout(voice_group)
        voice_layout.setContentsMargins(16, 24, 16, 16)
        voice_layout.setSpacing(16)
        self._layout = voice_layout
        self._build_choices()
        self._build_stability()
        voice_layout.addStretch(1)
        preview_group = QFrame(self)
        preview_group.setObjectName("settingsGroup")
        self._layout = QVBoxLayout(preview_group)
        self._layout.setContentsMargins(16, 16, 16, 16)
        self._layout.setSpacing(12)
        self._layout.addWidget(styled_label("Proba i potrošnja", "settingTitle", self))
        self._build_credits()
        self._build_test_row()
        self._build_privacy()
        self._groups.addWidget(voice_group, 6)
        self._groups.addWidget(preview_group, 5)
        self._layout = layout
        layout.addLayout(self._groups)
        layout.addStretch(1)
        self._reflow_controls(False)
        self.refresh(account.state)

    def _build_header(self):
        self._header = QGridLayout()
        self._header.setHorizontalSpacing(12)
        self._header.setVerticalSpacing(12)
        self._back_button = self._controls.button("Nazad", self._back, QSize(120, 58))
        self._title = styled_label("ElevenLabs · Efendija", "sectionTitle", self)
        self.check_button = self._controls.button(
            "Provjeri vezu", self._check_connection, QSize(150, 58)
        )
        self.connection_help = self._controls.info_button(
            "O provjeri veze",
            "Provjera čita podatke o računu, glasovima i modelima. "
            "Ne izgovara tekst i ne troši kredite za govor. "
            "Za probu glasa odaberite Isprobaj Efendiju.",
        )
        self._layout.addLayout(self._header)

    def _build_key_row(self):
        row, grid, _hint = setting_row(self, "API ključ")
        self._key_grid = grid
        self._key_title = grid.itemAtPosition(0, 0).widget()
        self.key_input = QLineEdit(row)
        self.key_input.setAccessibleName("ElevenLabs API ključ")
        self.key_input.setEchoMode(QLineEdit.Password)
        self.key_input.setMaxLength(1280)
        self.key_input.setMinimumWidth(100)
        self.key_input.setFixedHeight(58)
        self.key_input.setPlaceholderText("Unesite ključ")
        self.show_key = self._controls.toggle_button("Prikaži", self._toggle_key, QSize(100, 58))
        self.save_key = self._controls.button("Sačuvaj ključ", self._save_key, QSize(150, 58))
        self.saved_key = styled_label("Ključ je sačuvan", "settingHint", row)
        self.replace_key = self._controls.button(
            "Zamijeni ključ", self._replace_key, QSize(150, 58)
        )
        self.remove_key = self._controls.button("Ukloni ključ", self._remove_key, QSize(150, 58))
        self.cancel_key = self._controls.button("Odustani", self.clear_input, QSize(120, 58))
        grid.addWidget(self.saved_key, 0, 1, 2, 1)
        grid.addWidget(self.key_input, 0, 1, 2, 1)
        grid.setColumnStretch(1, 2)
        grid.addWidget(self.show_key, 0, 2, 2, 1)
        grid.addWidget(self.replace_key, 0, 2, 2, 1)
        grid.addWidget(self.save_key, 0, 3, 2, 1)
        grid.addWidget(self.remove_key, 0, 3, 2, 1)
        grid.addWidget(self.cancel_key, 0, 4, 2, 1)
        self._layout.addWidget(row)
        self.connection = styled_label("", "settingHint", self)
        self.connection.setTextFormat(Qt.PlainText)
        self.connection.setWordWrap(True)
        self._layout.addWidget(self.connection)

    def _build_choices(self):
        self.voice = self._controls.choice(
            (), self._selection, lambda: self._cycle(self.voice), "ElevenLabs glas"
        )
        self.model = self._controls.choice(
            (), self._selection, lambda: self._cycle(self.model), "ElevenLabs model"
        )
        choices_layout = QHBoxLayout()
        for title, combo in (("Moji glasovi", self.voice), ("Model", self.model)):
            column = QVBoxLayout()
            column.setSpacing(8)
            column.addWidget(styled_label(title, "settingTitle", self))
            combo.setMinimumWidth(100)
            combo.setMaximumWidth(16777215)
            combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            column.addWidget(combo)
            choices_layout.addLayout(column, 1)
        self._layout.addLayout(choices_layout)

    def _build_stability(self):
        tuning = QGridLayout()
        self._stability_value = ELEVENLABS_STABILITY_DEFAULT
        self.stability_buttons = {}
        tuning.addWidget(styled_label("Stabilnost", "settingTitle", self), 0, 0)
        choices = QHBoxLayout()
        for value, label in zip(
            ELEVENLABS_STABILITY_STEPS, ("Kreativno", "Prirodno", "Stabilno"), strict=True
        ):
            button = self._controls.toggle_button(
                label, lambda step=value: self._set_stability(step), QSize(100, 58)
            )
            button.setAccessibleName(f"ElevenLabs Stabilnost: {label}")
            choices.addWidget(button)
            self.stability_buttons[value] = button
        tuning.addLayout(choices, 1, 0)
        self._layout.addLayout(tuning)
        similarity = QGridLayout()
        self.similarity, self.similarity_value = self._tuning_control(
            similarity, 0, "Sličnost glasa", ELEVENLABS_SIMILARITY_DEFAULT
        )
        self._layout.addLayout(similarity)

    def _build_credits(self):
        self.credits_label = styled_label(CREDITS_UNAVAILABLE, "settingTitle", self)
        self._layout.addWidget(self.credits_label)
        self.credits = QProgressBar(self)
        self.credits.setAccessibleName("Preostali ElevenLabs krediti")
        self.credits.setRange(0, 100)
        self.credits.setTextVisible(False)
        self.credits.setFixedHeight(8)
        self._layout.addWidget(self.credits)
        self.credits_note = styled_label("", "settingHint", self)
        self.credits_note.setWordWrap(True)
        self._layout.addWidget(self.credits_note)

    def _build_test_row(self):
        self._layout.addSpacing(8)
        self._layout.addWidget(styled_label(VOICE_TEST_TEXT, "settingTitle", self))
        warning = styled_label(
            "Proba troši ElevenLabs kredite. Priprema može trajati do 30 sekundi.",
            "settingHint",
            self,
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #efd092;")
        self._layout.addWidget(warning)
        actions = QHBoxLayout()
        self.test_button = self._controls.button(
            "Isprobaj Efendiju", self._test_voice, QSize(150, 58), "fa5s.play"
        )
        self.test_button.setObjectName("primaryButton")
        actions.addWidget(self.test_button, 1)
        self.stop_button = self._controls.button(
            "Zaustavi", self.stop_requested.emit, QSize(150, 58), "fa5s.stop"
        )
        actions.addWidget(self.stop_button, 1)
        self._layout.addLayout(actions)
        self.playback_progress = busy_indicator(self)
        self._layout.addWidget(self.playback_progress)
        retain_size_when_hidden(self.stop_button)

    def _build_privacy(self):
        note = styled_label(
            "Dozvole: izgovor, čitanje glasova i modela; podaci o računu za kredite.\n"
            "Izgovor šalje tekst ElevenLabsu. ElevenLabs može sačuvati poslani tekst; rad bez čuvanja postoji samo za Enterprise. "
            + FALLBACK_NOTE,
            "settingHint",
            self,
        )
        note.setWordWrap(True)
        self._layout.addWidget(note)
        self._layout.addStretch(1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        direction = QBoxLayout.TopToBottom if self.width() < 820 else QBoxLayout.LeftToRight
        if direction != self._groups.direction():
            self._controls.interrupt_gaze()
            self._groups.setDirection(direction)
            self._reflow_controls(direction == QBoxLayout.TopToBottom)

    def _reflow_controls(self, narrow):
        header_widgets = (self._back_button, self._title, self.check_button, self.connection_help)
        key_widgets = (
            self._key_title,
            self.key_input,
            self.saved_key,
            self.show_key,
            self.save_key,
            self.cancel_key,
            self.replace_key,
            self.remove_key,
        )
        for layout, widgets in ((self._header, header_widgets), (self._key_grid, key_widgets)):
            for widget in widgets:
                layout.removeWidget(widget)
            for column in range(layout.columnCount()):
                layout.setColumnStretch(column, 0)
                layout.setColumnMinimumWidth(column, 0)
        # Explicit spacer columns keep gaps when hidden controls span different cells.
        self._key_grid.setHorizontalSpacing(0)
        for column in range(1, 11 if narrow else 9, 2):
            self._key_grid.setColumnMinimumWidth(column, 12)
        if narrow:
            header_positions = ((0, 0, 1, 1), (0, 1, 1, 2), (1, 1, 1, 1), (1, 2, 1, 1))
            key_positions = (
                (0, 0, 1, 11),
                (1, 0, 1, 11),
                (1, 0, 1, 11),
                (2, 0, 1, 3),
                (2, 4, 1, 3),
                (2, 8, 1, 3),
                (2, 0, 1, 5),
                (2, 6, 1, 5),
            )
            self._header.setColumnStretch(1, 1)
            for column in range(0, 11, 2):
                self._key_grid.setColumnStretch(column, 1)
        else:
            header_positions = tuple((0, column, 1, 1) for column in range(4))
            key_positions = tuple((0, column, 2, 1) for column in (0, 2, 2, 4, 6, 8, 4, 6))
            self._header.setColumnStretch(1, 1)
            self._key_grid.setColumnStretch(0, 1)
            self._key_grid.setColumnStretch(2, 2)
        for layout, widgets, positions in (
            (self._header, header_widgets, header_positions),
            (self._key_grid, key_widgets, key_positions),
        ):
            for widget, position in zip(widgets, positions, strict=True):
                layout.addWidget(widget, *position)
        self._align_key_actions(narrow)

    def _align_key_actions(self, narrow):
        self._key_grid.setContentsMargins(12, 0, 12 if narrow else 0, 0)
        # A hidden Cancel must not leave its preceding spacer at the right edge.
        self._key_grid.setColumnMinimumWidth(
            7, 12 if narrow or not self.cancel_key.isHidden() else 0
        )

    def configure(self, settings) -> None:
        self._settings = settings
        self._stability_value = settings.elevenlabs_stability
        for value, button in self.stability_buttons.items():
            button.setChecked(value == self._stability_value)
        with QSignalBlocker(self.similarity):
            self.similarity.setValue(settings.elevenlabs_similarity)
        self.similarity_value.setText(f"{settings.elevenlabs_similarity}%")
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
        slider.setToolTip("Sličnost odabranom glasu")
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
        self.tuning_changed.emit(self._stability_value, self.similarity.value())

    def _set_stability(self, value) -> None:
        self._stability_value = value
        for step, button in self.stability_buttons.items():
            button.setChecked(step == value)
        self._tuning_changed(value)

    def set_playback_state(self, state: str) -> None:
        self._playback_state = state
        self.refresh(self.account.state)

    def refresh(self, state: AccountState) -> None:
        self.connection.setText(state.message)
        self._refresh_key(state)
        self._render_credits(state)
        self._render_playback(state)
        self._render_choices(state)

    def _render_credits(self, state):
        subscription = state.subscription
        self.credits_note.setText(state.credits_message)
        self.credits.setVisible(subscription is not None)
        if subscription is None:
            self.credits_label.setText(CREDITS_UNAVAILABLE)
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
            color = "#e48c80" if percent < 10 else "#edc779" if percent < 20 else "#a3d5ba"
            self.credits.setStyleSheet(
                f"QProgressBar {{ background: #394959; border: 0; border-radius: 4px; }} QProgressBar::chunk {{ background: {color}; border-radius: 4px; }}"
            )

    def _render_playback(self, state):
        active = self._playback_state in ACTIVE_PLAYBACK_STATES
        self.stop_button.setVisible(True)
        self.stop_button.setEnabled(active)
        self.playback_progress.setVisible(active)
        label = PLAYBACK_LABELS.get(self._playback_state, "Isprobaj Efendiju")
        self.test_button.setText(label)
        self._controls.rename(self.test_button, label)
        self.check_button.setEnabled(state.has_key and not state.busy)
        self.test_button.setEnabled(not active and self.account.can_test_voice)

    def _render_choices(self, state):
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
            self._populate_choice(combo, choices, current, state.options is not None)
            combo.setEnabled(_choice_enabled(choices, state.busy, variable))

    def _populate_choice(self, combo, choices, current, checked):
        with QSignalBlocker(combo):
            combo.clear()
            if combo is self.voice:
                combo.setPlaceholderText(
                    "Odaberite glas"
                    if choices
                    else "Nema glasova"
                    if checked
                    else "Provjerite vezu"
                )
            else:
                combo.addItem("Provjerite vezu", "")
            for identifier, name in choices:
                combo.addItem(name, identifier)
            if _missing_model_choice(combo is self.voice, combo.findData(current), current):
                combo.addItem(current, current)
            index = combo.findData(current)
            combo.setCurrentIndex(index if combo is self.voice else max(0, index))

    def clear_input(self) -> None:
        self._editing_key = False
        self.key_input.clear()
        self.key_input.setEchoMode(QLineEdit.Password)
        self.show_key.setChecked(False)
        self.show_key.setText("Prikaži")
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
        self._align_key_actions(self._groups.direction() == QBoxLayout.TopToBottom)

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
        self.show_key.setText("Sakrij" if visible else "Prikaži")

    def _save_key(self) -> None:
        value = self.key_input.text()
        if not value.strip():
            self.connection.setText("Unesite API ključ prije čuvanja.")
            return
        self.key_input.setEchoMode(QLineEdit.Password)
        self.show_key.setChecked(False)
        self.show_key.setText("Prikaži")
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
        if _can_cycle(combo):
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
                "Brisanje ili izmjena teksta uklanja njegove snimke. Promjena glasa, modela ili postavki čuva prethodne snimke za povratak na isti izbor, do ograničenja prostora.",
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


def _can_cycle(combo):
    if combo.count() > 1:
        return True
    return combo.count() == 1 and combo.currentIndex() < 0


def _choice_enabled(choices, busy, variable):
    if busy or not choices:
        return False
    return not env_override(variable)


def _missing_model_choice(is_voice, index, current):
    if is_voice:
        return False
    return bool(current) and index < 0
