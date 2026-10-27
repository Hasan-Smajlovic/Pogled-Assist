"""Own the speech dialogs, their backdrop, and modal presentation."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import diagnostics
from .recording_badge import RecordingBadge
from .tracking_feedback import dialog_tracking_header

DIALOG_ACTION_MIN_HEIGHT = 128


class SpeechDialogs(QObject):
    closed = Signal(QDialog)

    def __init__(
        self,
        parent: QWidget,
        make_button: Callable[..., QPushButton],
        context_changed: Callable[[], None],
        restore_focus: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self._parent = parent
        self._make_button = make_button
        self._context_changed = context_changed
        self._restore_focus = restore_focus
        self.active: QDialog | None = None
        self.actions: set[str] = set()
        self.recording_badges: list[RecordingBadge] = []
        self.backdrop = QFrame(parent)
        self.backdrop.setObjectName("modalBackdrop")
        self.backdrop.hide()
        self._build_dialogs()
        self.tracking_notices = {
            self.confirm: self.confirm_notice,
        }

    def open(self, dialog: QDialog, height: int) -> None:
        self._context_changed()
        self.active = dialog
        self.backdrop.setGeometry(self._parent.rect())
        self.backdrop.show()
        self.backdrop.raise_()
        available_width = max(320, self._parent.width() - 64)
        width = min(1280, max(680, round(self._parent.width() * 0.68)), available_width)
        if dialog is self.confirm:
            width = min(1000, available_width)
        dialog.resize(width, min(height, max(320, self._parent.height() - 64)))
        self._position_dialog(dialog)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        diagnostics.emit(
            "dialog_open",
            priority=True,
            context_id=self._context_id(),
            kind=self.kind(dialog),
            logical_geometry=(dialog.x(), dialog.y(), dialog.width(), dialog.height()),
            modal=dialog.isModal(),
        )

    def close(self) -> None:
        if self.active is not None:
            self.active.done(0)

    def resize(self) -> None:
        self.backdrop.setGeometry(self._parent.rect())
        if self.active is self.sleep:
            self.position_sleep()
        elif self.active is not None:
            self._position_dialog(self.active)

    def position_sleep(self) -> None:
        top_left = self._parent.mapToGlobal(QPoint(0, 0))
        self.sleep.setGeometry(QRect(top_left, self._parent.size()))

    def _position_dialog(self, dialog: QDialog) -> None:
        center = self._parent.mapToGlobal(self._parent.rect().center())
        dialog.move(center.x() - dialog.width() // 2, center.y() - dialog.height() // 2)

    def _dialog_finished(self, dialog: QDialog) -> None:
        if dialog is not self.active:
            return
        diagnostics.emit(
            "dialog_close",
            priority=True,
            context_id=self._context_id(),
            kind=self.kind(dialog),
        )
        self.active = None
        self.closed.emit(dialog)
        self.actions.clear()
        self.backdrop.hide()
        self._context_changed()
        QTimer.singleShot(0, self._parent, self._restore_focus)

    def kind(self, dialog: QDialog) -> str:
        for name in ("confirm", "exit", "alarm", "sleep"):
            if dialog is getattr(self, name):
                return name
        return "unknown"

    def _context_id(self) -> str | None:
        context = getattr(self._parent, "_diagnostic_context", None)
        return context.id if context is not None else None

    def _build_dialogs(self) -> None:
        self._build_confirm_dialog()
        self._build_exit_dialog()
        self._build_alarm_dialog()
        self._build_sleep_dialog()

    def _build_confirm_dialog(self) -> None:
        self.confirm = self._new_dialog()
        confirm_layout = QVBoxLayout(self.confirm)
        confirm_layout.setContentsMargins(32, 30, 32, 32)
        confirm_layout.setSpacing(24)
        self.confirm_title = QLabel("Potvrda", self.confirm)
        self.confirm_title.setObjectName("dialogTitle")
        self.confirm_copy = QLabel("Cijela poruka bit će obrisana.", self.confirm)
        self.confirm_copy.setObjectName("dialogCopy")
        self.confirm_copy.setWordWrap(True)
        confirm_actions = QHBoxLayout()
        confirm_actions.setContentsMargins(0, 0, 0, 0)
        confirm_actions.setSpacing(24)
        cancel = self._make_button(
            "Odustani",
            "confirm:cancel",
            "dialogCancelButton",
            parent=self.confirm,
            minimum_height=DIALOG_ACTION_MIN_HEIGHT,
        )
        self.confirm_button = self._make_button(
            "Potvrdi",
            "confirm:accept",
            "dialogConfirmButton",
            parent=self.confirm,
            minimum_height=DIALOG_ACTION_MIN_HEIGHT,
        )
        confirm_actions.addWidget(cancel, 1)
        confirm_actions.addWidget(self.confirm_button, 1)
        header, self.confirm_notice = dialog_tracking_header(
            self._recording_title(self.confirm_title, self.confirm), self.confirm
        )
        confirm_layout.addWidget(header)
        confirm_layout.addWidget(self.confirm_copy)
        confirm_layout.addStretch(1)
        confirm_layout.addLayout(confirm_actions)
        self.confirm.finished.connect(
            lambda _result, dialog=self.confirm: self._dialog_finished(dialog)
        )

    def _build_exit_dialog(self) -> None:
        self.exit = self._new_dialog()
        exit_layout = QVBoxLayout(self.exit)
        exit_layout.setContentsMargins(32, 30, 32, 32)
        exit_layout.setSpacing(24)
        exit_title = QLabel("Izaći iz govornog načina?", self.exit)
        exit_title.setObjectName("dialogTitle")
        exit_copy = QLabel(
            "Možete se vratiti na razgovor, izaći iz govornog načina ili ugasiti cijelu aplikaciju.",
            self.exit,
        )
        exit_copy.setObjectName("dialogCopy")
        exit_copy.setWordWrap(True)
        exit_actions = QHBoxLayout()
        exit_actions.setContentsMargins(0, 0, 0, 0)
        exit_actions.setSpacing(24)
        cancel_exit = self._make_button(
            "Odustani",
            "exit:cancel",
            "dialogCancelButton",
            parent=self.exit,
            minimum_height=DIALOG_ACTION_MIN_HEIGHT,
        )
        leave_speech = self._make_button(
            "Izađi",
            "exit:leave-speech",
            "dialogCancelButton",
            parent=self.exit,
            minimum_height=DIALOG_ACTION_MIN_HEIGHT,
        )
        quit_app = self._make_button(
            "Ugasi aplikaciju",
            "exit:quit-app",
            "dialogConfirmButton",
            parent=self.exit,
            minimum_height=DIALOG_ACTION_MIN_HEIGHT,
        )
        exit_actions.addWidget(cancel_exit, 1)
        exit_actions.addWidget(leave_speech, 1)
        exit_actions.addWidget(quit_app, 1)
        exit_layout.addWidget(self._recording_header(exit_title, self.exit))
        exit_layout.addWidget(exit_copy)
        exit_layout.addStretch(1)
        exit_layout.addLayout(exit_actions)
        self.exit.finished.connect(lambda _result, dialog=self.exit: self._dialog_finished(dialog))

    def _build_alarm_dialog(self) -> None:
        self.alarm = self._new_dialog()
        alarm_layout = QVBoxLayout(self.alarm)
        alarm_layout.setContentsMargins(32, 30, 32, 32)
        alarm_layout.setSpacing(24)
        alarm_title = QLabel("Alarm je uključen", self.alarm)
        alarm_title.setObjectName("dialogTitle")
        self.alarm_copy = QLabel("Zvučni signal se ponavlja dok ga ne zaustavite.", self.alarm)
        self.alarm_copy.setObjectName("dialogCopy")
        self.alarm_copy.setWordWrap(True)
        stop_alarm = self._make_button(
            "Zaustavi alarm",
            "alarm:stop",
            "dialogConfirmButton",
            parent=self.alarm,
            minimum_height=140,
        )
        alarm_layout.addWidget(self._recording_header(alarm_title, self.alarm))
        alarm_layout.addWidget(self.alarm_copy)
        alarm_layout.addStretch(1)
        alarm_layout.addWidget(stop_alarm)
        self.alarm.finished.connect(
            lambda _result, dialog=self.alarm: self._dialog_finished(dialog)
        )

    def _build_sleep_dialog(self) -> None:
        self.sleep = self._new_dialog(object_name="sleepDialog")
        sleep_layout = QVBoxLayout(self.sleep)
        sleep_layout.setContentsMargins(32, 32, 32, 56)
        sleep_layout.addStretch(1)
        self.wake_button = self._make_button(
            "Nastavi",
            "sleep:wake",
            "wakeButton",
            parent=self.sleep,
            minimum_height=140,
        )
        self.wake_button.setMinimumWidth(320)
        self.wake_button.setMaximumWidth(420)
        sleep_layout.addWidget(self.wake_button, 0, Qt.AlignHCenter)
        self.sleep.finished.connect(
            lambda _result, dialog=self.sleep: self._dialog_finished(dialog)
        )

    def _recording_title(self, title: QLabel, parent: QWidget) -> QWidget:
        heading = self._recording_header(title, parent)
        heading.setFixedHeight(36)
        return heading

    def _recording_header(self, title: QWidget, parent: QWidget) -> QWidget:
        header = QWidget(parent)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(title, 1)
        badge = RecordingBadge(header)
        self.recording_badges.append(badge)
        layout.addWidget(badge)
        return header

    def _new_dialog(self, *, object_name: str = "speechDialog") -> QDialog:
        dialog = QDialog(self._parent)
        dialog.setObjectName(object_name)
        dialog.setModal(True)
        dialog.setWindowModality(Qt.ApplicationModal)
        dialog.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        return dialog
