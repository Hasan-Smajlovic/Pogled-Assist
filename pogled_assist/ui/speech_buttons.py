"""Text wrapping and global bounds for speech keyboard buttons."""

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QPaintEvent, QPalette
from PySide6.QtWidgets import QPushButton, QStyle, QStyleOptionButton, QStylePainter


class WrappedButton(QPushButton):
    """Keep long phrases and letter groups inside their allotted grid cell."""

    def paintEvent(self, event: QPaintEvent) -> None:
        option = QStyleOptionButton()
        self.initStyleOption(option)
        text = option.text
        option.text = ""
        painter = QStylePainter(self)
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)
        rect = self.style().subElementRect(QStyle.SubElement.SE_PushButtonContents, option, self)
        painter.drawItemText(
            rect,
            int(Qt.AlignmentFlag.AlignCenter)
            | int(
                Qt.TextFlag.TextWrapAnywhere
                if self.objectName() == "predictionButton"
                else Qt.TextFlag.TextWordWrap
            ),
            option.palette,
            self.isEnabled(),
            text,
            QPalette.ColorRole.ButtonText,
        )


def button_bounds(button: QPushButton) -> QRect:
    return QRect(button.mapToGlobal(QPoint(0, 0)), button.size())
