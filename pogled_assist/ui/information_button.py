"""Optional help that can be opened without hovering."""

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QDialog, QLabel, QToolButton, QVBoxLayout, QWidget


class InformationButton(QToolButton):
    def __init__(self, title: str, text: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setText("ⓘ")
        self.setAccessibleName(title)
        self.setToolTip(title)
        self.setFixedSize(58, 58)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            "QToolButton { border: 1px solid #71869b; border-radius: 8px; "
            "background: #283442; color: #edf2f7; font-size: 22px; }"
            'QToolButton:focus, QToolButton[gazeTarget="true"] { border: 3px solid #84c5d9; }'
        )
        self.popup = QDialog(self, Qt.Popup)
        self.popup.setWindowTitle(title)
        self.popup.setAccessibleName(title)
        self.popup.setStyleSheet(
            "QDialog { background: #1d242d; border: 1px solid #84c5d9; }"
            "QLabel { color: #edf2f7; font-family: Segoe UI; font-size: 15px; }"
        )
        layout = QVBoxLayout(self.popup)
        layout.setContentsMargins(16, 16, 16, 16)
        heading = QLabel(title, self.popup)
        heading.setWordWrap(True)
        heading.setStyleSheet("font-weight: 600;")
        copy = QLabel(text, self.popup)
        copy.setTextFormat(Qt.PlainText)
        copy.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(copy)
        self.popup.finished.connect(lambda _result: QTimer.singleShot(0, self, self._restore_focus))
        self.clicked.connect(self.show_help)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.click()
            event.accept()
        else:
            super().keyPressEvent(event)

    def _restore_focus(self) -> None:
        if self.isVisible():
            self.window().activateWindow()
            self.setFocus(Qt.PopupFocusReason)

    def show_help(self) -> None:
        if self.popup.isVisible():
            self.popup.close()
            return
        bounds = self.window().rect()
        origin = self.window().mapToGlobal(bounds.topLeft())
        bounds.moveTopLeft(origin)
        self.popup.setFixedWidth(min(340, max(200, bounds.width() - 32)))
        self.popup.adjustSize()
        point = self.mapToGlobal(QPoint(self.width() - self.popup.width(), self.height() + 8))
        point.setX(max(bounds.left() + 8, min(point.x(), bounds.right() - self.popup.width() - 8)))
        point.setY(min(point.y(), bounds.bottom() - self.popup.height() - 8))
        self.popup.move(point)
        self.popup.show()
        self.popup.setFocus(Qt.PopupFocusReason)
