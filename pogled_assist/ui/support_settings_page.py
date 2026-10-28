"""Logging and caregiver support actions in Settings."""

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QFrame

from .settings_controls import content_layout, setting_row, styled_label


class SupportSettingsPage(QFrame):
    def __init__(self, owner):
        super().__init__(owner)
        layout = content_layout(self)
        layout.addWidget(styled_label("Podrška", "sectionTitle", self))
        description = styled_label(
            "Provjera pogleda, zapisivanje i dijagnostički snimci.", "sectionDescription", self
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        layout.addWidget(styled_label("Zapisivanje", "groupLabel", self))
        self._logging_checkbox = owner._controls.checkbox(
            "Uključi zapisivanje", owner._toggle_logging_enabled, QSize(300, 58)
        )
        layout.addWidget(self._logging_checkbox)
        note = styled_label(
            "Ručno pokrenuto dijagnostičko snimanje radi i kada je opće zapisivanje isključeno.",
            "settingHint",
            self,
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addSpacing(12)
        layout.addWidget(styled_label("Pomoć pri poteškoćama", "groupLabel", self))
        row, grid, _hint = setting_row(
            self, "Snimite problem s pogledom", "Kratak dijagnostički snimak i paket za podršku."
        )
        self._diagnostics_button = owner._controls.button(
            "Dijagnostičko snimanje", owner.diagnostics_requested.emit, QSize(270, 58)
        )
        grid.addWidget(self._diagnostics_button, 0, 1, 2, 1)
        layout.addWidget(row)
        row, grid, _hint = setting_row(
            self, "Provjerite pogled", "Položaj očiju, preciznost i proba odabira."
        )
        self._check_button = owner._controls.button(
            "Provjera pogleda", owner._request_gaze_check, QSize(270, 58)
        )
        grid.addWidget(self._check_button, 0, 1, 2, 1)
        layout.addWidget(row)
        layout.addStretch(1)

    def refresh(self, settings):
        self._logging_checkbox.setChecked(settings.logging_enabled)
