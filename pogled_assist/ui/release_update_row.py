"""Application version selection and explicit installation controls."""

from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QWidget

from ..release_update import ReleaseCheckResult, ReleaseUpdateManager, StableVersion
from .settings_controls import CONTROL_HEIGHT, SettingsControls, styled_label


class ReleaseUpdateRow(QFrame):
    status_changed = Signal(str)
    update_requested = Signal(object)
    restart_confirmed = Signal()
    install_cancelled = Signal()

    def __init__(
        self, controls: SettingsControls, manager: ReleaseUpdateManager | None, parent: QWidget
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settingRow")
        self._controls = controls
        self._manager = manager
        self._result: ReleaseCheckResult | None = None
        self._busy = False
        self._installed_label = styled_label(
            "Trenutna verzija nije dostupna.", "settingTitle", self
        )
        installed = manager.installed_version if manager else None
        if installed is not None:
            self._installed_label.setText(f"Trenutno koristite v{installed}")
        self._status_label = styled_label("Pripremam provjeru verzija.", "updateStatusLabel", self)
        self._status_label.setWordWrap(True)
        self._check_button = controls.button(
            "Provjeri verzije", self._check, QSize(290, CONTROL_HEIGHT), "fa5s.sync-alt"
        )
        self._version_combo = controls.choice(
            (), self._selection_changed, self._cycle, "Verzija za instalaciju"
        )
        self._version_combo.setEnabled(False)
        self._update_button = controls.button(
            "Instaliraj i ponovo pokreni",
            self._request_update,
            QSize(290, CONTROL_HEIGHT),
            "fa5s.download",
        )
        self._update_button.setEnabled(False)
        self._hint = styled_label(
            "Sačuvani podaci ostaju dostupni. Starija verzija može zahtijevati ručnu instalaciju za povratak.",
            "settingHint",
            self,
        )
        self._hint.setWordWrap(True)
        self._warning = styled_label(
            "Imate nesačuvanu poruku ili nedovršen unos. Ponovno pokretanje će odbaciti taj tekst. Sačuvani podaci ostaju dostupni.",
            "updateStatusLabel",
            self,
        )
        self._warning.setWordWrap(True)
        self._cancel_button = controls.button("Odustani", self._cancel, QSize(260, CONTROL_HEIGHT))
        self._confirm_button = controls.button(
            "Odbaci unos i ponovo pokreni", self.restart_confirmed.emit, QSize(290, CONTROL_HEIGHT)
        )
        layout = QGridLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(8)
        layout.setColumnStretch(0, 1)
        layout.addWidget(self._installed_label, 0, 0)
        layout.addWidget(self._status_label, 1, 0)
        layout.addWidget(self._check_button, 0, 1, 2, 1)
        choice = QHBoxLayout()
        choice.addWidget(styled_label("Verzija za instalaciju", "settingTitle", self))
        choice.addStretch()
        choice.addWidget(self._version_combo)
        layout.addLayout(choice, 2, 0)
        layout.addWidget(self._update_button, 2, 1)
        layout.addWidget(self._hint, 3, 0, 1, 2)
        layout.addWidget(self._warning, 4, 0, 1, 2)
        layout.addWidget(self._cancel_button, 5, 0)
        layout.addWidget(self._confirm_button, 5, 1)
        self._show_confirmation(False)

    def start(self) -> None:
        if self._manager is None or not self._manager.supported:
            self._check_button.setEnabled(False)
            self._status_label.setText(
                "Izbor verzije dostupan je u instaliranoj Windows aplikaciji."
            )
            return
        self._manager.check_started.connect(self._check_started)
        self._manager.check_completed.connect(self._check_completed)
        self._manager.check_failed.connect(self._check_failed)
        self._check()

    def show_error(self, message: str) -> None:
        self._busy = False
        self._show_confirmation(False)
        self._check_button.setEnabled(True)
        self._version_combo.setEnabled(self._result is not None)
        self._selection_changed()
        self._status_label.setText(message)
        self.status_changed.emit("Instalacija nije pokrenuta.")

    def confirm_restart(self) -> None:
        self._controls.interrupt_gaze()
        self._show_confirmation(True)
        self._status_label.setText("Paket je provjeren. Potvrdite ponovno pokretanje.")
        self.status_changed.emit("Nesačuvan unos.")

    def _show_confirmation(self, visible: bool) -> None:
        self._warning.setVisible(visible)
        self._cancel_button.setVisible(visible)
        self._confirm_button.setVisible(visible)

    def _check(self) -> None:
        if self._manager is not None and not self._busy:
            self._manager.check()

    def _check_started(self) -> None:
        self._controls.interrupt_gaze()
        self._result = None
        self._check_button.setEnabled(False)
        self._version_combo.setEnabled(False)
        self._update_button.setEnabled(False)
        self._status_label.setText("Provjeravam dostupne stabilne verzije...")
        self.status_changed.emit("Provjeravam verzije.")

    def _check_completed(self, result: object) -> None:
        if not isinstance(result, ReleaseCheckResult) or not result.versions:
            self._check_failed("GitHub nije vratio ispravnu listu verzija.")
            return
        self._controls.interrupt_gaze()
        self._result = result
        self._installed_label.setText(f"Trenutno koristite v{result.installed_version}")
        self._version_combo.blockSignals(True)
        self._version_combo.clear()
        for version in result.versions:
            self._version_combo.addItem(f"v{version}", version)
        self._version_combo.blockSignals(False)
        self._version_combo.setEnabled(True)
        self._check_button.setEnabled(True)
        self._selection_changed()
        if result.update_available:
            message = f"Dostupna je novija verzija v{result.latest_version}."
        elif result.installed_version == result.latest_version:
            message = "Koristite najnoviju stabilnu verziju."
        else:
            message = f"Najnovija objavljena stabilna verzija je v{result.latest_version}."
        self._status_label.setText(message)
        self.status_changed.emit(message)

    def _check_failed(self, message: str) -> None:
        self._result = None
        self._version_combo.setEnabled(False)
        self._check_button.setEnabled(True)
        self._update_button.setEnabled(False)
        self._status_label.setText(message)
        self.status_changed.emit("Provjera verzija nije uspjela.")

    def _selection_changed(self, _index: int = 0) -> None:
        self._controls.interrupt_gaze()
        selected = self._version_combo.currentData()
        self._update_button.setEnabled(
            not self._busy
            and self._result is not None
            and isinstance(selected, StableVersion)
            and selected != self._result.installed_version
        )

    def _cycle(self) -> None:
        count = self._version_combo.count()
        if count:
            self._version_combo.setCurrentIndex((self._version_combo.currentIndex() + 1) % count)

    def _request_update(self) -> None:
        selected = self._version_combo.currentData()
        if self._busy or self._result is None or selected == self._result.installed_version:
            return
        self._controls.interrupt_gaze()
        self._busy = True
        self._check_button.setEnabled(False)
        self._version_combo.setEnabled(False)
        self._update_button.setEnabled(False)
        self._cancel_button.show()
        self._status_label.setText(
            f"Preuzimam i provjeravam v{selected}. Aplikacija ostaje otvorena."
        )
        self.status_changed.emit("Pripremam instalaciju.")
        self.update_requested.emit(selected)

    def _cancel(self) -> None:
        self._controls.interrupt_gaze()
        self.install_cancelled.emit()
        self.show_error("Instalacija je otkazana. Trenutna verzija i unos ostaju dostupni.")
