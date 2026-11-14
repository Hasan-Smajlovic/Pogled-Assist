"""Controls and value rendering for the general Settings page."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout

from ..speech.selection_sound import SELECTION_SOUND_LEVELS
from .release_update_row import ReleaseUpdateRow
from .settings_controls import action_grid, content_layout, cycle_choice, setting_row, styled_label

SELECTION_SOUND_HINT = (
    "Kratak zvuk potvrđuje odabir pogledom u Govoru. Izgovori i alarm imaju svoj zvuk."
)


class GeneralSettingsPage(QFrame):
    request_quit = Signal()
    toggle_start_with_windows = Signal()
    toggle_show_launcher_window = Signal()
    selection_sound_combo_changed = Signal(str)
    status_changed = Signal(str)
    update_requested = Signal(object)
    restart_confirmed = Signal()
    install_cancelled = Signal()

    def __init__(self, controls, update_manager=None, parent=None):
        super().__init__(parent)
        self._controls = controls
        self._update_manager = update_manager
        self._build()

    def _build(self):
        page = self
        layout = content_layout(page)

        header = QGridLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setHorizontalSpacing(16)
        header.setVerticalSpacing(4)
        header.setColumnStretch(0, 1)
        title = styled_label("Aplikacija", "sectionTitle", page)
        description = styled_label(
            "Pokretanje, zvuk i ažuriranje aplikacije.", "sectionDescription", page
        )
        header.addWidget(title, 0, 0, Qt.AlignVCenter | Qt.AlignLeft)
        header.addWidget(description, 1, 0, Qt.AlignVCenter | Qt.AlignLeft)
        self._quit_button = self._controls.button(
            "Isključi aplikaciju", self.request_quit.emit, QSize(154, 58), "fa5s.power-off"
        )
        self._quit_button.setObjectName("dangerButton")
        header.addWidget(self._quit_button, 0, 1, 2, 1, Qt.AlignVCenter | Qt.AlignRight)
        layout.addLayout(header)

        layout.addWidget(styled_label("Pokretanje", "groupLabel", page))
        self._startup_checkbox = self._controls.checkbox(
            "Pokreni uz Windows", self.toggle_start_with_windows.emit, QSize(240, 58)
        )
        self._launcher_window_checkbox = self._controls.checkbox(
            "Prikaži PowerShell", self.toggle_show_launcher_window.emit, QSize(240, 58)
        )
        layout.addLayout(action_grid((self._startup_checkbox, self._launcher_window_checkbox)))

        layout.addWidget(styled_label("Zvuk", "groupLabel", page))
        self._selection_sound_combo = self._controls.choice(
            SELECTION_SOUND_LEVELS,
            lambda index: self.selection_sound_combo_changed.emit(
                self._selection_sound_combo.itemData(index)
            ),
            lambda: cycle_choice(self._selection_sound_combo),
            "Zvuk pri odabiru",
        )
        sound_row, sound_grid, _hint = setting_row(page, "Zvuk pri odabiru", SELECTION_SOUND_HINT)
        sound_grid.addWidget(self._selection_sound_combo, 0, 1, 2, 1)
        layout.addWidget(sound_row)

        layout.addWidget(styled_label("VERZIJA APLIKACIJE", "groupLabel", page))
        self._update_row = ReleaseUpdateRow(self._controls, self._update_manager, page)
        self._update_row.status_changed.connect(self.status_changed.emit)
        self._update_row.update_requested.connect(self.update_requested)
        self._update_row.restart_confirmed.connect(self.restart_confirmed)
        self._update_row.install_cancelled.connect(self.install_cancelled)
        layout.addWidget(self._update_row)
        layout.addStretch(1)

    def refresh(self, settings, startup_desired, speech_settings):
        self._startup_checkbox.setChecked(
            settings.start_with_windows if startup_desired is None else startup_desired
        )
        self._launcher_window_checkbox.setChecked(settings.show_launcher_window)
        with QSignalBlocker(self._selection_sound_combo):
            self._selection_sound_combo.setCurrentIndex(
                max(0, self._selection_sound_combo.findData(speech_settings.selection_sound))
            )

    def start_updates(self) -> None:
        self._update_row.start()

    def show_update_error(self, message: str) -> None:
        self._update_row.show_error(message)

    def confirm_update_restart(self) -> None:
        self._update_row.confirm_restart()
