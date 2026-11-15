"""Logging and caregiver support actions in Settings."""

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import QFrame

from .settings_controls import content_layout, setting_row, styled_label


class SupportSettingsPage(QFrame):
    toggle_logging_enabled = Signal()
    adjust_log_storage = Signal(int)
    diagnostics_requested = Signal()
    request_gaze_check = Signal()

    def __init__(self, controls, parent=None):
        super().__init__(parent)
        layout = content_layout(self)
        layout.addWidget(styled_label("Podrška", "sectionTitle", self))
        description = styled_label(
            "Provjera pogleda, zapisivanje i dijagnostički snimci.", "sectionDescription", self
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        layout.addWidget(styled_label("Zapisivanje", "groupLabel", self))
        self._logging_checkbox = controls.checkbox(
            "Uključi zapisivanje", self.toggle_logging_enabled.emit, QSize(300, 58)
        )
        layout.addWidget(self._logging_checkbox)
        note = styled_label(
            "Ručno pokrenuto dijagnostičko snimanje radi i kada je opće zapisivanje isključeno.",
            "settingHint",
            self,
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        row, self._budget_value = controls.adjust_row(
            "Prostor za logove",
            "Zajedno za opće logove i ručne snimke. Najstariji zatvoreni logovi brišu se automatski.",
            self.adjust_log_storage.emit,
            1,
        )
        layout.addWidget(row)
        note = styled_label(
            "1 do 10 GB · 1 GB = 1.000.000.000 bajtova. Aktivni snimci i izvori izvoza ostaju zaštićeni. "
            "ZIP-ovi i rezultati Provjere pogleda se ne brišu.",
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
        self._diagnostics_button = controls.button(
            "Dijagnostičko snimanje", self.diagnostics_requested.emit, QSize(270, 58)
        )
        grid.addWidget(self._diagnostics_button, 0, 1, 2, 1)
        layout.addWidget(row)
        row, grid, _hint = setting_row(
            self, "Provjerite pogled", "Položaj očiju, preciznost i proba odabira."
        )
        self._check_button = controls.button(
            "Provjera pogleda", self.request_gaze_check.emit, QSize(270, 58)
        )
        grid.addWidget(self._check_button, 0, 1, 2, 1)
        layout.addWidget(row)
        layout.addStretch(1)

    def refresh(self, settings):
        self._logging_checkbox.setChecked(settings.logging_enabled)
        self._budget_value.setText(f"{settings.log_storage_gb} GB")
