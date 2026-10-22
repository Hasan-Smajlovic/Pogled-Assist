"""Passive recording status inside existing control geometry."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QLabel


class RecordingBadge(QLabel):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet(
            "QLabel { background: #4b2224; color: #ffb4b4; border: none; border-radius: 3px; font-size: 9px; padding: 0 3px; }"
        )
        parent.installEventFilter(self)
        self.hide()

    def set_status(self, status):
        active = status and status.get("busy")
        if active:
            seconds = int(status.get("remaining_seconds", 0))
            self.setText(
                "● …"
                if status.get("state") == "finishing"
                else f"● {seconds // 60:02}:{seconds % 60:02}"
            )
            description = (
                "Završavam snimak…"
                if status.get("state") == "finishing"
                else "Dijagnostičko snimanje " + self.text()
            )
            self.setToolTip(description)
            self.setAccessibleName(description)
            self.adjustSize()
            self._position()
        self.setVisible(bool(active))

    def _position(self):
        self.move(max(0, self.parentWidget().width() - self.width() - 1), 2)
        self.raise_()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Resize:
            self._position()
        return False
