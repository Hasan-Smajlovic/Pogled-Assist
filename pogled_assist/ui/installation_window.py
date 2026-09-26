"""Post-install readiness summary, operated by the person setting up the device."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGridLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
)

from ..installation_check import TOBII_DOWNLOAD_URL, check_installation
from ..speech.speech_service import _application_root
from ..tracking.tobii_calibration import launch_tobii_guest_calibration
from ..windows.dpi import enable_windows_dpi_awareness


class _SetupWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, action, parent=None):
        super().__init__(parent)
        self.action = action

    def run(self):
        try:
            self.completed.emit(self.action())
        except Exception as error:
            self.failed.emit(str(error))


class InstallationWindow(QDialog):
    def __init__(self, root: Path, parent=None, *, auto_check: bool = True):
        super().__init__(parent)
        self.root = root
        self._worker = None
        self._closing = False
        self._can_calibrate = False
        self.setWindowTitle("Provjera instalacije — Pogled Assist")
        self.resize(900, 650)
        self.setStyleSheet(
            "QDialog, QWidget { background: #1c2029; color: #eef2f8; font-size: 18px; }"
            "QPushButton { padding: 14px; border: 1px solid #394253; border-radius: 8px; }"
            "QPushButton:focus { border: 2px solid #8bd5f5; }"
            "QPushButton:disabled { color: #7c8491; }"
        )
        layout = QVBoxLayout(self)
        heading = QLabel("Provjera instalacije")
        heading.setStyleSheet("font-size: 28px; font-weight: bold;")
        layout.addWidget(heading)
        intro = QLabel("Provjerite spremnost programa i dovršite podešavanje Tobii uređaja.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.results = QLabel("Provjeravam…")
        self.results.setTextFormat(Qt.TextFormat.PlainText)
        self.results.setWordWrap(True)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.results)
        layout.addWidget(scroll)
        actions = QGridLayout()
        self.download_button = QPushButton("Preuzmi Tobii softver")
        self.calibrate_button = QPushButton("Pokreni kalibraciju")
        self.refresh_button = QPushButton("Ponovi provjeru")
        self.close_button = QPushButton("Zatvori")
        for index, button in enumerate(
            (self.download_button, self.calibrate_button, self.refresh_button, self.close_button)
        ):
            button.setMinimumHeight(64)
            actions.addWidget(button, index // 2, index % 2)
        layout.addLayout(actions)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.calibrate_button.setEnabled(False)
        self.download_button.clicked.connect(self._open_download)
        self.calibrate_button.clicked.connect(self._calibrate)
        self.refresh_button.clicked.connect(self.refresh)
        self.close_button.clicked.connect(self.close)
        if auto_check:
            QTimer.singleShot(0, self.refresh)

    def _start(self, action, on_result):
        if self._worker is not None:
            return
        self.download_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.calibrate_button.setEnabled(False)
        self._worker = _SetupWorker(action, self)
        self._worker.completed.connect(on_result)
        self._worker.failed.connect(self.status.setText)
        self._worker.finished.connect(self._finished)
        self._worker.start()

    def _finished(self):
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        if self._closing:
            self.close()
            return
        self.download_button.setEnabled(True)
        self.refresh_button.setEnabled(True)
        self.calibrate_button.setEnabled(self._can_calibrate)

    def refresh(self):
        self.status.setText("Provjeravam…")
        self._start(lambda: check_installation(self.root), self._show_results)

    def _show_results(self, results):
        self.results.setText(
            "\n\n".join(f"{item.title} — {item.state}\n{item.detail}" for item in results)
        )
        self._can_calibrate = any(
            item.key == "software" and item.state == "Pronađen" for item in results
        )
        self.status.setText("Provjera je završena. Kalibraciju potvrdite u Tobii softveru.")

    def _open_download(self):
        if not QDesktopServices.openUrl(QUrl(TOBII_DOWNLOAD_URL)):
            self.status.setText(f"Otvorite službenu stranicu: {TOBII_DOWNLOAD_URL}")

    def _calibrate(self):
        self.status.setText("Otvaram Tobii kalibraciju…")
        self._start(launch_tobii_guest_calibration, self.status.setText)

    def closeEvent(self, event: QCloseEvent):
        if self._worker is not None:
            self._closing = True
            self.status.setText("Završavam provjeru prije zatvaranja…")
            event.ignore()
            return
        super().closeEvent(event)


def show_installation_check() -> int:
    enable_windows_dpi_awareness()
    application = QApplication.instance() or QApplication(["PogledAssist", "--installation-check"])
    window = InstallationWindow(_application_root())
    window.show()
    return application.exec()
