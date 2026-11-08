"""Text wrapping and global bounds for speech keyboard buttons."""

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPaintEvent, QPalette
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
        if self.objectName() == "categoryButton":
            self._draw_category_text(painter, rect, option.palette, text)
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
        if not subtitle:
            painter.setFont(title_font)
            painter.drawItemText(
                rect, Qt.AlignCenter, palette, self.isEnabled(), title, QPalette.ButtonText
            )
            return
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

    def _draw_category_text(self, painter, rect, palette, text) -> None:
        """Draw a wrapping category name above its smaller answer count."""
        name, _, count = text.partition("\n")
        name_font = self.font()
        count_font = QFont(name_font)
        count_font.setPixelSize(16)
        count_font.setWeight(QFont.Normal)
        flags = int(Qt.AlignHCenter | Qt.AlignTop) | int(Qt.TextFlag.TextWordWrap)
        name_height = QFontMetrics(name_font).boundingRect(rect, flags, name).height()
        count_height = QFontMetrics(count_font).height()
        top = rect.center().y() - (name_height + 6 + count_height) // 2
        name_rect = QRect(rect.left(), top, rect.width(), name_height)
        count_rect = QRect(rect.left(), name_rect.bottom() + 7, rect.width(), count_height)
        painter.setFont(name_font)
        painter.drawItemText(name_rect, flags, palette, self.isEnabled(), name, QPalette.ButtonText)
        painter.setFont(count_font)
        # The muted count keeps 8 : 1 contrast on the navigation tone.
        painter.setPen(
            QColor("#c9d4df")
            if self.isEnabled()
            else palette.color(QPalette.Disabled, QPalette.ButtonText)
        )
        painter.drawText(count_rect, int(Qt.AlignCenter), count)


def button_bounds(button: QPushButton) -> QRect:
    return QRect(button.mapToGlobal(QPoint(0, 0)), button.size())
