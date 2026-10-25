"""Controls and value rendering for the general Settings page."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QFrame, QGridLayout

from .release_update_row import ReleaseUpdateRow
from .settings_controls import action_grid, content_layout, styled_label


class GeneralSettingsPage(QFrame):
    def __init__(self, owner):
        super().__init__(owner)
        self._owner = owner
        self._controls = owner._controls
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
            "Pokretanje i ažuriranje aplikacije.", "sectionDescription", page
        )
        header.addWidget(title, 0, 0, Qt.AlignVCenter | Qt.AlignLeft)
        header.addWidget(description, 1, 0, Qt.AlignVCenter | Qt.AlignLeft)
        self._quit_button = self._controls.button(
            "Isključi aplikaciju", self._owner._request_quit, QSize(154, 58), "fa5s.power-off"
        )
        self._quit_button.setObjectName("dangerButton")
        header.addWidget(self._quit_button, 0, 1, 2, 1, Qt.AlignVCenter | Qt.AlignRight)
        layout.addLayout(header)

        layout.addWidget(styled_label("Pokretanje", "groupLabel", page))
        self._startup_checkbox = self._controls.checkbox(
            "Pokreni uz Windows", self._owner._toggle_start_with_windows, QSize(240, 58)
        )
        self._launcher_window_checkbox = self._controls.checkbox(
            "Prikaži PowerShell", self._owner._toggle_show_launcher_window, QSize(240, 58)
        )
        layout.addLayout(action_grid((self._startup_checkbox, self._launcher_window_checkbox)))

        layout.addWidget(styled_label("VERZIJA APLIKACIJE", "groupLabel", page))
        self._update_row = ReleaseUpdateRow(self._controls, self._owner._update_manager, page)
        self._update_row.status_changed.connect(self._owner._set_status)
        self._update_row.update_requested.connect(self._owner.update_requested)
        self._update_row.restart_confirmed.connect(self._owner.restart_confirmed)
        self._update_row.install_cancelled.connect(self._owner.install_cancelled)
        layout.addWidget(self._update_row)
        layout.addStretch(1)

    def refresh(self, settings, startup_desired):
        self._startup_checkbox.setChecked(
            settings.start_with_windows if startup_desired is None else startup_desired
        )
        self._launcher_window_checkbox.setChecked(settings.show_launcher_window)
