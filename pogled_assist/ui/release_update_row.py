"""Settings row that checks for a newer stable release and starts the updater."""

from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QWidget

from ..release_update import ReleaseCheckResult, ReleaseUpdateManager
from .settings_controls import CONTROL_HEIGHT, SettingsControls, styled_label


class ReleaseUpdateRow(QFrame):
    """Show the installed and latest stable versions and offer the update."""

    status_changed = Signal(str)
    update_requested = Signal()

    def __init__(
        self,
        controls: SettingsControls,
        manager: ReleaseUpdateManager | None,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settingRow")
        self._controls = controls
        self._manager = manager
        layout = QGridLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(6)
        layout.setColumnStretch(0, 1)

        title = styled_label("Ažuriranja", "settingTitle", self)
        self._status_label = styled_label(
            "Pripremam provjeru ažuriranja.", "updateStatusLabel", self
        )
        self._status_label.setWordWrap(True)
        self._check_button = controls.button(
            "Provjeri ažuriranja", self._check, QSize(210, CONTROL_HEIGHT), "fa5s.sync-alt"
        )
        self._update_button = controls.button(
            "Ažuriraj i ponovo pokreni",
            self._request_update,
            QSize(250, CONTROL_HEIGHT),
            "fa5s.download",
        )
        self._update_button.hide()

        layout.addWidget(title, 0, 0)
        layout.addWidget(self._status_label, 1, 0)
        layout.addWidget(self._check_button, 0, 1, 2, 1)
        layout.addWidget(self._update_button, 0, 2, 2, 1)

    def start(self) -> None:
        if self._manager is None or not self._manager.supported:
            self._check_button.setEnabled(False)
            self._status_label.setText(
                "Provjera ažuriranja dostupna je u instaliranoj Windows verziji."
            )
            return

        self._manager.check_started.connect(self._check_started)
        self._manager.check_completed.connect(self._check_completed)
        self._manager.check_failed.connect(self._check_failed)
        self._check()

    def show_error(self, message: str) -> None:
        self._check_button.setEnabled(True)
        self._update_button.setEnabled(True)
        self._status_label.setText(message)
        self.status_changed.emit("Pokretanje ažuriranja nije uspjelo.")

    def _check(self) -> None:
        if self._manager is None:
            return
        self._check_started()
        self._manager.check()

    def _check_started(self) -> None:
        self._check_button.setEnabled(False)
        self._update_button.setEnabled(False)
        self._update_button.hide()
        self._status_label.setText("Provjeravam posljednje stabilno izdanje...")
        self.status_changed.emit("Provjeravam ažuriranja.")

    def _check_completed(self, result: object) -> None:
        if not isinstance(result, ReleaseCheckResult):
            self._check_failed("GitHub nije vratio ispravne podatke o izdanju.")
            return

        installed = str(result.installed_version)
        latest = str(result.latest_version)
        self._check_button.setEnabled(True)
        if result.update_available:
            self._status_label.setText(
                f"Dostupna je verzija v{latest}. Trenutno koristite v{installed}."
            )
            self._update_button.setText(f"Ažuriraj na v{latest}")
            self._update_button.setEnabled(True)
            self._update_button.show()
            self.status_changed.emit(f"Dostupno je ažuriranje na v{latest}.")
            return

        self._update_button.hide()
        if result.latest_version == result.installed_version:
            message = f"Koristite najnoviju verziju v{installed}."
        else:
            message = f"Instalirana verzija v{installed} novija je od stabilne v{latest}."
        self._status_label.setText(message)
        self.status_changed.emit(message)

    def _check_failed(self, message: str) -> None:
        self._check_button.setEnabled(True)
        self._update_button.setEnabled(False)
        self._update_button.hide()
        self._status_label.setText(message)
        self.status_changed.emit("Provjera ažuriranja nije uspjela.")

    def _request_update(self) -> None:
        self._controls.interrupt_gaze()
        self._check_button.setEnabled(False)
        self._update_button.setEnabled(False)
        self._status_label.setText(
            "Pokrećem updater. Aplikacija će se zatvoriti i pokrenuti nakon instalacije."
        )
        self.status_changed.emit("Pokrećem ažuriranje.")
        self.update_requested.emit()
