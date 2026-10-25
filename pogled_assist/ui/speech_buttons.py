"""Text wrapping and global bounds for speech keyboard buttons."""

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QFont, QFontMetrics, QPaintEvent, QPalette
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
        if self.objectName() in ("systemAlarm", "systemSleep", "systemExit"):
            self._draw_system_text(painter, rect, option.palette, text)
            return
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

    def _draw_system_text(self, painter, rect, palette, text) -> None:
        title, _, subtitle = text.partition("\n")
        title_font = self.font()
        subtitle_font = QFont(title_font)
        subtitle_font.setPixelSize(15)
        subtitle_font.setWeight(QFont.Normal)
        title_height = QFontMetrics(title_font).height()
        subtitle_height = QFontMetrics(subtitle_font).height()
        top = rect.center().y() - (title_height + 7 + subtitle_height) // 2
        for label, font, y, height in (
            (title, title_font, top, title_height),
            (subtitle, subtitle_font, top + title_height + 7, subtitle_height),
        ):
            painter.setFont(font)
            line = rect.adjusted(0, 0, 0, 0)
            line.setTop(y)
            line.setHeight(height)
            painter.drawItemText(
                line, Qt.AlignCenter, palette, self.isEnabled(), label, QPalette.ButtonText
            )


def button_bounds(button: QPushButton) -> QRect:
    return QRect(button.mapToGlobal(QPoint(0, 0)), button.size())
