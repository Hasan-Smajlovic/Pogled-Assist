"""Native checkbox behavior with a left-aligned switch and adjacent label."""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QCheckBox


class SettingsSwitch(QCheckBox):
    def sizeHint(self) -> QSize:
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 82, 58)

    def hitButton(self, point) -> bool:
        return self.rect().contains(point)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        border = "#84c5d9" if self.hasFocus() or self.property("gazeTarget") else "#71869b"
        painter.setPen(QPen(QColor(border), 2 if self.property("gazeTarget") else 1))
        painter.setBrush(QColor("#283442" if self.underMouse() else "#1d242d"))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 8, 8)
        track = QRectF(14, self.height() / 2 - 10, 38, 20)
        painter.setPen(QPen(QColor(border), 1))
        painter.setBrush(QColor("#2e6478" if self.isChecked() else "#15191f"))
        painter.drawRoundedRect(track, 10, 10)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#edf2f7" if self.isEnabled() else "#8595a6"))
        painter.drawEllipse(
            QPointF(track.left() + (28 if self.isChecked() else 10), track.center().y()), 7, 7
        )
        painter.setPen(QColor("#edf2f7" if self.isEnabled() else "#8595a6"))
        painter.drawText(
            self.rect().adjusted(64, 0, -10, 0), Qt.AlignLeft | Qt.AlignVCenter, self.text()
        )
