"""Speech tracking notifications that cannot receive mouse, keyboard or gaze input."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import ClassVar

from PySide6.QtCore import QEasingCurve, QObject, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QStyle, QWidget

from .. import diagnostics
from ..tracking.feedback import TrackingFeedbackState, TrackingNotice
from ..tracking.status import TrackingState, TrackingStatus


class TrackingFeedback(QObject):
    changed = Signal(object)

    def __init__(
        self, parent: QObject, active: Callable[[], bool], *, enabled: bool = True
    ) -> None:
        super().__init__(parent)
        self._active = active
        self._enabled = enabled
        self._state = TrackingFeedbackState()
        self._status = TrackingStatus(TrackingState.STOPPED)
        self._eyes: tuple[bool, bool] | None = None
        self._gaze_at: float | None = None
        self.notice: TrackingNotice | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    def set_enabled(self, enabled: bool) -> None:
        if self._enabled != bool(enabled):
            self._enabled = bool(enabled)
            self._state.reset()
        self.refresh()

    def handle_status(self, status: TrackingStatus) -> None:
        self._status = status
        if status.state != TrackingState.CONNECTED:
            self._gaze_at = None
            if status.state != TrackingState.WAITING:
                self._eyes = None
        self.refresh()

    def handle_eyes(self, left: bool, right: bool) -> None:
        self._eyes = bool(left), bool(right)
        if not all(self._eyes):
            self._gaze_at = None
        self.refresh()

    def handle_gaze(self, _x: float, _y: float, _timestamp: object) -> None:
        if self._status.state == TrackingState.CONNECTED and self._eyes == (True, True):
            self._gaze_at = time.monotonic()
        self.refresh()

    def refresh(self) -> None:
        notice = self._state.update(
            self._status,
            self._eyes,
            self._gaze_at,
            time.monotonic(),
            active=self._enabled and self._active(),
        )
        if notice != self.notice:
            self.notice = notice
            diagnostics.emit(
                "tracking_notice",
                tone=notice.tone if notice is not None else None,
                eyes=notice.eyes if notice is not None else None,
                tracking_state=self._status.state.value,
                enabled=self._enabled,
            )
            self.changed.emit(notice)

    def stop(self) -> None:
        self._timer.stop()
        self._state.reset()


class TrackingNoticeWidget(QWidget):
    """Paint one plain-text line sliding within its owner's existing header."""

    progress_changed = Signal(float)
    COLORS: ClassVar = {
        "warning": ("#342e1e", "#816e36", "#ffe58a"),
        "quiet": ("#232c38", "#53677d", "#dce6f3"),
        "error": ("#3b2429", "#94515b", "#ffa0a8"),
        "ready": ("#173326", "#3e8260", "#86efac"),
    }

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("trackingNotice")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.NoFocus)
        self.notice: TrackingNotice | None = None
        self._shown = False
        self.progress = 0.0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(180)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.valueChanged.connect(self._animate)
        self._animation.finished.connect(self._finished)
        self.hide()

    def set_notice(self, notice: TrackingNotice | None, *, immediate: bool = False) -> None:
        immediate = immediate or not self.style().styleHint(QStyle.SH_Widget_Animate, None, self)
        shown = notice is not None
        if notice is not None:
            self.notice = notice
            eyes = ""
            if notice.eyes is not None:
                eyes = ". " + ". ".join(
                    f"{name} oko: {'prati se' if valid else 'ne prati se'}"
                    for name, valid in zip(("Lijevo", "Desno"), notice.eyes, strict=True)
                )
            self.setAccessibleName(notice.text + eyes)
            self.setToolTip(notice.text)
        if shown == self._shown and not immediate:
            self.update()
            return
        self._shown = shown
        self._animation.stop()
        if shown:
            self.show()
            self.raise_()
        if immediate:
            self._animate(float(shown))
            self._finished()
        else:
            self._animation.setStartValue(self.progress)
            self._animation.setEndValue(float(shown))
            self._animation.start()
        self.update()

    def _animate(self, value: object) -> None:
        self.progress = float(value)
        self.progress_changed.emit(self.progress)
        self.update()

    def _finished(self) -> None:
        if not self._shown:
            self.hide()
            self.setAccessibleName("")
            self.setToolTip("")
            self.notice = None

    def paintEvent(self, _event) -> None:
        if self.notice is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setOpacity(self.progress)
        painter.translate(0, round((self.progress - 1) * self.height()))
        background, border, text = self.COLORS[self.notice.tone]
        painter.setPen(QPen(QColor(border), 1))
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 6, 6)
        x = 10
        if self.notice.eyes is not None:
            for name, valid in zip(("Lijevo", "Desno"), self.notice.eyes, strict=True):
                color = QColor("#70dfa1" if valid else "#ffd36a")
                painter.setPen(QPen(color, 1.5, Qt.SolidLine if valid else Qt.DashLine))
                painter.setBrush(Qt.NoBrush)
                center = self.height() / 2
                eye = QPainterPath()
                eye.moveTo(x, center)
                eye.cubicTo(x + 5, center - 9, x + 17, center - 9, x + 22, center)
                eye.cubicTo(x + 17, center + 9, x + 5, center + 9, x, center)
                painter.drawPath(eye)
                painter.setBrush(color)
                painter.drawEllipse(QRectF(x + 8, center - 3, 6, 6))
                eye_font = QFont("Segoe UI")
                eye_font.setPixelSize(11)
                painter.setFont(eye_font)
                painter.drawText(QRectF(x + 25, 0, 35, self.height()), Qt.AlignVCenter, name)
                x += 66
        else:
            painter.setPen(QColor(text))
            painter.setFont(QFont("Segoe UI", 12, QFont.Bold))
            painter.drawText(QRectF(x, 0, 22, self.height()), Qt.AlignVCenter, "!")
            x += 24
        painter.setPen(QColor(text))
        font = QFont("Segoe UI")
        font.setPixelSize(16)
        font.setWeight(QFont.DemiBold)
        detail_font = QFont("Segoe UI")
        detail_font.setPixelSize(14)
        detail = f" · {self.notice.detail}" if self.notice.detail else ""
        available = max(0, self.width() - x - 10)
        while (
            font.pixelSize() > 12
            and QFontMetrics(font).horizontalAdvance(self.notice.title)
            + QFontMetrics(detail_font).horizontalAdvance(detail)
            > available
        ):
            font.setPixelSize(font.pixelSize() - 1)
            detail_font.setPixelSize(detail_font.pixelSize() - 1)
        painter.setFont(font)
        title = QFontMetrics(font).elidedText(self.notice.title, Qt.ElideRight, available)
        painter.drawText(QRectF(x, 0, available, self.height()), Qt.AlignVCenter, title)
        if title == self.notice.title and detail:
            title_width = QFontMetrics(font).horizontalAdvance(title)
            painter.setFont(detail_font)
            painter.setPen(QColor("#d1d7e1"))
            line = QFontMetrics(detail_font).elidedText(
                detail, Qt.ElideRight, available - title_width
            )
            painter.drawText(
                QRectF(x + title_width, 0, available - title_width, self.height()),
                Qt.AlignVCenter,
                line,
            )


class MessageTrackingHeader(QWidget):
    """Use the existing message header; restore its height after the slide ends."""

    def __init__(self, label: QLabel, status: QLabel, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedHeight(18)
        self._label, self._status = label, status
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label)
        layout.addWidget(status, 1)
        self.notice = TrackingNoticeWidget(self)
        self.notice.progress_changed.connect(self._progress)

    def _progress(self, progress: float) -> None:
        self.setFixedHeight(18 + round(20 * progress))
        self._label.setVisible(progress == 0)
        self._status.setVisible(progress == 0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.notice.setGeometry(0, 0, self.width(), 38)


def dialog_tracking_header(title: QLabel, parent: QWidget) -> tuple[QWidget, TrackingNoticeWidget]:
    header = QWidget(parent)
    header.setFixedHeight(60)
    layout = QHBoxLayout(header)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)
    notice = TrackingNoticeWidget(header)
    layout.addWidget(title)
    layout.addWidget(notice, 1)
    return header, notice
