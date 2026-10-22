"""Shared recording feedback and passive, reserved display slots."""

import math

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent
from PySide6.QtWidgets import QApplication, QLabel

from .settings_controls import retain_size_when_hidden


class RecordingIndicator(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.text = ""
        self.compact_text = ""
        self.tone = "recording"
        self._key = None
        self._announced = None
        self._confirmation = QTimer(self)
        self._confirmation.setSingleShot(True)
        self._confirmation.setInterval(5000)
        self._confirmation.timeout.connect(self._clear)

    def set_status(self, status):
        if not status:
            self._key = None
            self._announced = None
            self._confirmation.stop()
            self._clear()
            return
        if status.get("busy"):
            if status.get("state") == "finishing":
                tone, text, compact = "finishing", "Završavam snimak…", "Čuvam…"
            else:
                seconds = math.ceil(max(0, status.get("remaining_seconds", 0)))
                compact = f"{seconds // 60:02}:{seconds % 60:02}"
                tone, text = "recording", f"Snimanje dijagnostike · {compact}"
        elif status.get("state") == "error" or status.get("reason") == "writer_error":
            tone, text, compact = "error", "Greška čuvanja snimka", "Greška"
        elif status.get("state") == "unreadable":
            tone, text, compact = "error", "Snimak nije čitljiv", "Nečitljivo"
        elif not status.get("complete"):
            tone, text, compact = "incomplete", "Snimak nije potpun", "Nepotpuno"
        else:
            tone, text, compact = "saved", "Snimak je sačuvan", "Sačuvano"
        key = status.get("id"), tone, "" if tone == "recording" else text
        if key != self._key:
            self._confirmation.stop()
            self._key = key
            if tone == "saved":
                self._confirmation.start()
        elif tone == "saved" and not self._confirmation.isActive():
            return
        if (self.tone, self.text, self.compact_text) != (tone, text, compact):
            self.tone, self.text, self.compact_text = tone, text, compact
            self.changed.emit()

    def _clear(self):
        self.text = self.compact_text = ""
        self.changed.emit()

    def announce(self, widget):
        if (
            self.text
            and self._announced != self._key
            and widget.isVisible()
            and widget.window() is QApplication.activeWindow()
        ):
            self._announced = self._key
            event = QAccessibleAnnouncementEvent(widget, widget.accessibleName())
            event.setPoliteness(QAccessible.AnnouncementPoliteness.Polite)
            QAccessible.updateAccessibility(event)


class RecordingBadge(QLabel):
    def __init__(self, parent, *, compact=False):
        super().__init__(parent)
        self._compact = compact
        self._indicator = None
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.NoFocus)
        self.setTextFormat(Qt.PlainText)
        self.setAlignment(Qt.AlignCenter if compact else Qt.AlignLeft | Qt.AlignVCenter)
        self.setFixedSize(parent.width() - 8 if compact else 264, 18 if compact else 30)
        retain_size_when_hidden(self)
        if compact:
            parent.installEventFilter(self)
            self._position()
        self.hide()

    def bind_indicator(self, indicator):
        if self._indicator is indicator:
            return
        if self._indicator is not None:
            self._indicator.changed.disconnect(self._refresh)
        self._indicator = indicator
        indicator.changed.connect(self._refresh)
        self._refresh()

    def set_status(self, status):
        if self._indicator is None:
            self.bind_indicator(RecordingIndicator(self))
        self._indicator.set_status(status)

    def _refresh(self):
        indicator = self._indicator
        symbol, color, background = {
            "recording": ("●", "#ffb4b4", "#4b2224"),
            "finishing": ("◷", "#f2ce76", "#43381d"),
            "saved": ("✓", "#91dfbc", "#1b2a23"),
            "incomplete": ("!", "#f2ce76", "#43381d"),
            "error": ("!", "#ffb4b4", "#4b2224"),
        }[indicator.tone]
        text = indicator.compact_text if self._compact else indicator.text
        self.setText(f"{symbol} {text}" if text else "")
        self.setToolTip(indicator.text)
        self.setAccessibleName(
            "Snimanje dijagnostike je u toku."
            if indicator.text and indicator.tone == "recording"
            else indicator.text
        )
        self.setStyleSheet(
            f"QLabel {{ background: {background}; color: {color}; border: none; "
            f"border-radius: 4px; font-size: {11 if self._compact else 14}px; padding: 0 4px; }}"
        )
        self.setVisible(bool(indicator.text))
        indicator.announce(self)

    def _position(self):
        parent = self.parentWidget()
        self.setFixedWidth(max(0, parent.width() - 8))
        self.move(4, parent.height() - self.height() - 2)
        self.raise_()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Resize:
            self._position()
        return False
