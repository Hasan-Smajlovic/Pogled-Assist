"""Controls, layout, and modal presentation for the speech window."""

from __future__ import annotations

import math
from collections.abc import Iterable

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..keyboard_layouts import switch_label
from .gaze_feedback import set_gaze_feedback
from .speech_buttons import WrappedButton, button_bounds

SPEECH_WINDOW_ACTION_PREFIX = "speech_window:"
KEY_GRID_MAX_COLUMNS = 8
KEY_GRID_MAX_ROWS = 8
GROUP_BUTTON_MIN_HEIGHT = 72
LIST_ACTION_MIN_HEIGHT = 80
LIST_ACTION_MIN_WIDTH = 160
DIALOG_ACTION_MIN_HEIGHT = 128


class SpeechSurface(QWidget):
    """Present speech controls and emit the actions selected with a mouse."""

    interaction_context_changed = Signal()
    mouse_action_started = Signal()
    action_requested = Signal(str)
    dialog_closed = Signal(QDialog)

    def __init__(self, parent: QWidget | None, keyboard_script: str) -> None:
        super().__init__(parent)
        self.setObjectName("speechWindow")
        self.setWindowTitle("Govor")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self._action_buttons: dict[str, QPushButton] = {}
        self._main_dynamic_actions: set[str] = set()
        self._letter_dialog_actions: set[str] = set()
        self._dialog_actions: set[str] = set()
        self._active_dialog: QDialog | None = None
        self._gaze_target_action: str | None = None
        self._build_ui(keyboard_script)
        self._build_dialogs()

    def _build_ui(self, keyboard_script: str) -> None:
        self.setStyleSheet(SPEECH_STYLE)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(10)
        root.addLayout(self._build_topbar())
        root.addLayout(self._build_predictions())
        root.addLayout(self._build_workspace(), 1)
        root.addLayout(self._build_utility_row(keyboard_script))
        self._modal_backdrop = QFrame(self)
        self._modal_backdrop.setObjectName("modalBackdrop")
        self._modal_backdrop.hide()

    def _build_topbar(self) -> QHBoxLayout:
        topbar = QHBoxLayout()
        topbar.setContentsMargins(0, 0, 0, 0)
        topbar.setSpacing(10)
        self._clear_button = self._make_button("Obriši", "clear", "clearButton", minimum_height=86)
        self._categories_button = self._make_button(
            "Kategorije", "categories", "topButton", minimum_height=86, checkable=True
        )

        message_box = self._build_message_box()

        self._play_button = self._make_button(
            "Izgovori", "play", "primaryButton", minimum_height=86
        )
        self._phrases_button = self._make_button(
            "Fraze", "phrases", "topButton", minimum_height=86, checkable=True
        )
        topbar.addWidget(self._clear_button, 8)
        topbar.addWidget(self._categories_button, 10)
        topbar.addWidget(message_box, 40)
        topbar.addWidget(self._play_button, 10)
        topbar.addWidget(self._phrases_button, 9)

        return topbar

    def _build_message_box(self) -> QWidget:
        message_box = QWidget(self)
        message_layout = QVBoxLayout(message_box)
        message_layout.setContentsMargins(0, 0, 0, 0)
        message_layout.setSpacing(4)
        self._message_label = QLabel("Vaša poruka", message_box)
        self._message_label.setObjectName("messageLabel")
        self._status_label = QLabel("", message_box)
        self._status_label.setObjectName("statusLabel")
        self._status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        message_header = QHBoxLayout()
        message_header.setContentsMargins(0, 0, 0, 0)
        message_header.addWidget(self._message_label)
        message_header.addWidget(self._status_label, 1)
        self._input = QLineEdit(message_box)
        self._input.setObjectName("speechInput")
        self._input.setAlignment(Qt.AlignCenter)
        self._input.setMinimumHeight(62)
        self._input.setPlaceholderText("Odaberite grupu slova…")
        message_layout.addLayout(message_header)
        message_layout.addWidget(self._input, 1)

        return message_box

    def _build_predictions(self) -> QVBoxLayout:
        predictions = QVBoxLayout()
        predictions.setContentsMargins(0, 0, 0, 0)
        predictions.setSpacing(6)
        self._prediction_label = QLabel("Brzi izbor", self)
        self._prediction_label.setObjectName("sectionLabel")
        self._prediction_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        predictions.addWidget(self._prediction_label)
        prediction_row = QHBoxLayout()
        prediction_row.setContentsMargins(0, 0, 0, 0)
        prediction_row.setSpacing(10)
        self._prediction_buttons = []
        for index in range(5):
            button = self._make_button(
                "·", f"suggestion:{index}", "predictionButton", minimum_height=66
            )
            button.setEnabled(False)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            self._prediction_buttons.append(button)
            prediction_row.addWidget(button, 1)
        self._undo_word_button = self._make_button(
            "Poništi riječ", "suggestion-undo", "utilityButton", minimum_height=66
        )
        self._undo_word_button.setFixedWidth(170)
        self._undo_word_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._undo_word_button.setEnabled(False)
        prediction_row.addWidget(self._undo_word_button)
        predictions.addLayout(prediction_row)

        return predictions

    def _build_workspace(self) -> QHBoxLayout:
        workspace = QHBoxLayout()
        workspace.setContentsMargins(0, 0, 0, 0)
        workspace.setSpacing(10)
        workspace.addWidget(self._build_main_panel(), 3)
        workspace.addWidget(self._build_system_panel(), 1)
        return workspace

    def _build_main_panel(self) -> QWidget:
        main_panel = QWidget(self)
        main_layout = QVBoxLayout(main_panel)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)
        view_header = self._build_view_header(main_panel)

        self._key_grid_host = QWidget(main_panel)
        self._key_grid_host.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._key_grid = QGridLayout(self._key_grid_host)
        self._key_grid.setContentsMargins(0, 0, 0, 0)
        self._key_grid.setHorizontalSpacing(10)
        self._key_grid.setVerticalSpacing(10)

        paging = self._build_paging(main_panel)
        main_layout.addLayout(view_header)
        main_layout.addWidget(self._key_grid_host, 1)
        main_layout.addLayout(paging)

        return main_panel

    def _build_view_header(self, main_panel: QWidget) -> QHBoxLayout:
        view_header = QHBoxLayout()
        view_header.setContentsMargins(0, 0, 0, 0)
        view_header.setSpacing(8)
        self._view_title = QLabel("Odaberite grupu slova", main_panel)
        self._view_title.setObjectName("sectionLabel")
        self._back_button = self._make_button(
            "Nazad",
            "list:back",
            "headerActionButton",
            minimum_height=LIST_ACTION_MIN_HEIGHT,
        )
        self._add_item_button = self._make_button(
            "Dodaj",
            "list:add",
            "headerActionButton",
            minimum_height=LIST_ACTION_MIN_HEIGHT,
        )
        self._delete_mode_button = self._make_button(
            "Obriši",
            "list:delete-mode",
            "headerActionButton",
            minimum_height=LIST_ACTION_MIN_HEIGHT,
            checkable=True,
        )
        self._cancel_editor_button = self._make_button(
            "Odustani",
            "editor:cancel",
            "headerActionButton",
            minimum_height=LIST_ACTION_MIN_HEIGHT,
        )
        self._save_item_button = self._make_button(
            "Sačuvaj", "editor:save", "primaryButton", minimum_height=LIST_ACTION_MIN_HEIGHT
        )
        for button in (
            self._back_button,
            self._add_item_button,
            self._delete_mode_button,
            self._cancel_editor_button,
            self._save_item_button,
        ):
            button.setMinimumWidth(LIST_ACTION_MIN_WIDTH)
        view_header.addWidget(self._view_title, 1)
        view_header.addWidget(self._back_button)
        view_header.addWidget(self._add_item_button)
        view_header.addWidget(self._delete_mode_button)
        view_header.addWidget(self._cancel_editor_button)
        view_header.addWidget(self._save_item_button)

        return view_header

    def _build_paging(self, main_panel: QWidget) -> QHBoxLayout:
        paging = QHBoxLayout()
        paging.setContentsMargins(0, 0, 0, 0)
        paging.setSpacing(8)
        self._previous_page_button = self._make_button(
            "Prethodna",
            "list:page:previous",
            "headerActionButton",
            minimum_height=LIST_ACTION_MIN_HEIGHT,
        )
        self._page_label = QLabel("", main_panel)
        self._page_label.setObjectName("sectionLabel")
        self._page_label.setAlignment(Qt.AlignCenter)
        self._next_page_button = self._make_button(
            "Sljedeća",
            "list:page:next",
            "headerActionButton",
            minimum_height=LIST_ACTION_MIN_HEIGHT,
        )
        self._previous_page_button.setMinimumWidth(LIST_ACTION_MIN_WIDTH)
        self._next_page_button.setMinimumWidth(LIST_ACTION_MIN_WIDTH)
        paging.addStretch(1)
        paging.addWidget(self._previous_page_button)
        paging.addWidget(self._page_label)
        paging.addWidget(self._next_page_button)
        paging.addStretch(1)
        return paging

    def _build_system_panel(self) -> QWidget:
        system_panel = QWidget(self)
        system_panel.setMinimumWidth(280)
        system_panel.setMaximumWidth(480)
        system_layout = QVBoxLayout(system_panel)
        system_layout.setContentsMargins(0, 0, 0, 0)
        system_layout.setSpacing(8)
        controls_label = QLabel("Kontrole", system_panel)
        controls_label.setObjectName("sectionLabel")
        system_layout.addWidget(controls_label)
        for title, subtitle, command, object_name in (
            ("Alarm", "Pozovi pomoć", "alarm:start", "systemAlarm"),
            ("Sleep", "Odmori oči", "sleep:start", "systemSleep"),
            ("Izlaz", "Izađi ili ugasi aplikaciju", "exit", "systemExit"),
        ):
            button = self._make_button(
                f"{title}\n{subtitle}",
                command,
                object_name,
                parent=system_panel,
                minimum_height=100,
            )
            system_layout.addWidget(button, 1)

        return system_panel

    def _build_utility_row(self, keyboard_script: str) -> QHBoxLayout:
        utility_row = QHBoxLayout()
        utility_row.setContentsMargins(0, 0, 0, 0)
        utility_row.setSpacing(10)
        self._space_button = self._make_button(
            "Razmak", "space", "utilityButton", minimum_height=76
        )
        self._backspace_button = self._make_button(
            "Obriši slovo", "backspace", "utilityButton", minimum_height=76
        )
        self._keyboard_toggle_button = self._make_button(
            "Brojevi i znakovi", "keyboard-toggle", "utilityButton", minimum_height=76
        )
        utility_row.addWidget(self._space_button, 14)
        utility_row.addWidget(self._backspace_button, 10)
        utility_row.addWidget(self._keyboard_toggle_button, 10)
        self._script_button = self._make_button(
            switch_label(keyboard_script),
            "script-toggle",
            "utilityButton",
            minimum_height=76,
        )
        utility_row.addWidget(self._script_button, 8)

        return utility_row

    def _build_dialogs(self) -> None:
        self._build_letter_dialog()
        self._build_confirm_dialog()
        self._build_exit_dialog()
        self._build_alarm_dialog()
        self._build_sleep_dialog()

    def _build_letter_dialog(self) -> None:
        self._letter_dialog = self._new_dialog()
        letter_layout = QVBoxLayout(self._letter_dialog)
        letter_layout.setContentsMargins(32, 30, 32, 32)
        letter_layout.setSpacing(24)
        self._letter_dialog_title = QLabel("Odaberite slovo", self._letter_dialog)
        self._letter_dialog_title.setObjectName("dialogTitle")
        self._letter_grid_host = QWidget(self._letter_dialog)
        self._letter_grid = QGridLayout(self._letter_grid_host)
        self._letter_grid.setContentsMargins(0, 0, 0, 0)
        self._letter_grid.setHorizontalSpacing(16)
        self._letter_grid.setVerticalSpacing(16)
        letter_layout.addWidget(self._letter_dialog_title)
        letter_layout.addWidget(self._letter_grid_host, 1)
        self._letter_dialog.finished.connect(
            lambda _result, dialog=self._letter_dialog: self._dialog_finished(dialog)
        )

    def _build_confirm_dialog(self) -> None:
        self._confirm_dialog = self._new_dialog()
        confirm_layout = QVBoxLayout(self._confirm_dialog)
        confirm_layout.setContentsMargins(32, 30, 32, 32)
        confirm_layout.setSpacing(24)
        self._confirm_title = QLabel("Potvrda", self._confirm_dialog)
        self._confirm_title.setObjectName("dialogTitle")
        self._confirm_copy = QLabel("Cijela poruka bit će obrisana.", self._confirm_dialog)
        self._confirm_copy.setObjectName("dialogCopy")
        self._confirm_copy.setWordWrap(True)
        confirm_actions = QHBoxLayout()
        confirm_actions.setContentsMargins(0, 0, 0, 0)
        confirm_actions.setSpacing(24)
        cancel = self._make_button(
            "Odustani",
            "confirm:cancel",
            "dialogCancelButton",
            parent=self._confirm_dialog,
            minimum_height=DIALOG_ACTION_MIN_HEIGHT,
        )
        self._confirm_button = self._make_button(
            "Potvrdi",
            "confirm:accept",
            "dialogConfirmButton",
            parent=self._confirm_dialog,
            minimum_height=DIALOG_ACTION_MIN_HEIGHT,
        )
        confirm_actions.addWidget(cancel, 1)
        confirm_actions.addWidget(self._confirm_button, 1)
        confirm_layout.addWidget(self._confirm_title)
        confirm_layout.addWidget(self._confirm_copy)
        confirm_layout.addStretch(1)
        confirm_layout.addLayout(confirm_actions)
        self._confirm_dialog.finished.connect(
            lambda _result, dialog=self._confirm_dialog: self._dialog_finished(dialog)
        )

    def _build_exit_dialog(self) -> None:
        self._exit_dialog = self._new_dialog()
        exit_layout = QVBoxLayout(self._exit_dialog)
        exit_layout.setContentsMargins(32, 30, 32, 32)
        exit_layout.setSpacing(24)
        exit_title = QLabel("Izaći iz govornog načina?", self._exit_dialog)
        exit_title.setObjectName("dialogTitle")
        exit_copy = QLabel(
            "Možete se vratiti na razgovor, izaći iz govornog načina ili ugasiti cijelu aplikaciju.",
            self._exit_dialog,
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
            parent=self._exit_dialog,
            minimum_height=DIALOG_ACTION_MIN_HEIGHT,
        )
        leave_speech = self._make_button(
            "Izađi",
            "exit:leave-speech",
            "dialogCancelButton",
            parent=self._exit_dialog,
            minimum_height=DIALOG_ACTION_MIN_HEIGHT,
        )
        quit_app = self._make_button(
            "Ugasi aplikaciju",
            "exit:quit-app",
            "dialogConfirmButton",
            parent=self._exit_dialog,
            minimum_height=DIALOG_ACTION_MIN_HEIGHT,
        )
        exit_actions.addWidget(cancel_exit, 1)
        exit_actions.addWidget(leave_speech, 1)
        exit_actions.addWidget(quit_app, 1)
        exit_layout.addWidget(exit_title)
        exit_layout.addWidget(exit_copy)
        exit_layout.addStretch(1)
        exit_layout.addLayout(exit_actions)
        self._exit_dialog.finished.connect(
            lambda _result, dialog=self._exit_dialog: self._dialog_finished(dialog)
        )

    def _build_alarm_dialog(self) -> None:
        self._alarm_dialog = self._new_dialog()
        alarm_layout = QVBoxLayout(self._alarm_dialog)
        alarm_layout.setContentsMargins(32, 30, 32, 32)
        alarm_layout.setSpacing(24)
        alarm_title = QLabel("Alarm je uključen", self._alarm_dialog)
        alarm_title.setObjectName("dialogTitle")
        self._alarm_copy = QLabel(
            "Zvučni signal se ponavlja dok ga ne zaustavite.", self._alarm_dialog
        )
        self._alarm_copy.setObjectName("dialogCopy")
        self._alarm_copy.setWordWrap(True)
        stop_alarm = self._make_button(
            "Zaustavi alarm",
            "alarm:stop",
            "dialogConfirmButton",
            parent=self._alarm_dialog,
            minimum_height=140,
        )
        alarm_layout.addWidget(alarm_title)
        alarm_layout.addWidget(self._alarm_copy)
        alarm_layout.addStretch(1)
        alarm_layout.addWidget(stop_alarm)
        self._alarm_dialog.finished.connect(
            lambda _result, dialog=self._alarm_dialog: self._dialog_finished(dialog)
        )

    def _build_sleep_dialog(self) -> None:
        self._sleep_dialog = self._new_dialog(object_name="sleepDialog")
        sleep_layout = QVBoxLayout(self._sleep_dialog)
        sleep_layout.setContentsMargins(32, 32, 32, 56)
        sleep_layout.addStretch(1)
        self._wake_button = self._make_button(
            "Nastavi",
            "sleep:wake",
            "wakeButton",
            parent=self._sleep_dialog,
            minimum_height=140,
        )
        self._wake_button.setMinimumWidth(320)
        self._wake_button.setMaximumWidth(420)
        sleep_layout.addWidget(self._wake_button, 0, Qt.AlignHCenter)
        self._sleep_dialog.finished.connect(
            lambda _result, dialog=self._sleep_dialog: self._dialog_finished(dialog)
        )

    def event(self, event: QEvent) -> bool:
        handled = super().event(event)
        if event.type() == QEvent.Type.WindowActivate:
            # Qt restores its previous focus widget after sending this event.
            QTimer.singleShot(0, self, self._restore_input_focus)
        return handled

    def _restore_input_focus(self) -> None:
        if not self.isVisible() or QApplication.activeWindow() is not self:
            return
        if self._active_dialog is not None:
            return
        if QApplication.activeModalWidget() is not None:
            return
        if QApplication.activePopupWidget() is not None:
            return
        self._input.setFocus(Qt.FocusReason.OtherFocusReason)

    def _correct_input_text(self, previous: str, corrected: str) -> None:
        cursor = self._input.cursorPosition()
        selection_start = self._input.selectionStart()
        selection_length = _utf16_length(self._input.selectedText())
        self._input.setText(corrected)
        if selection_start >= 0:
            self._input.setSelection(selection_start, selection_length)
            return
        if corrected == f"{previous} ":
            cursor += 1
        self._input.setCursorPosition(min(cursor, _utf16_length(corrected)))

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._context_changed()
        self._modal_backdrop.setGeometry(self.rect())
        if self._active_dialog is not None:
            if self._active_dialog is self._sleep_dialog:
                self._position_sleep_dialog()
            else:
                self._position_dialog(self._active_dialog)

    def action_center_at_global_point(self, action: str, point: QPoint) -> QPoint | None:
        rect = self.action_bounds(action)
        return rect.center() if rect is not None and rect.contains(point) else None

    def action_bounds(self, action: str) -> QRect | None:
        if not self.isVisible():
            return None
        button = self._available_button(action)
        return button_bounds(button) if button is not None else None

    def _available_button(self, action: str) -> QPushButton | None:
        if self._active_dialog is not None and action not in self._dialog_actions:
            return None
        button = self._action_buttons.get(action)
        if button is None:
            return None
        if not button.isVisible() or not button.isEnabled():
            return None
        return button

    def _action_at_point(self, actions: Iterable[str], point: QPoint) -> str | None:
        for action in tuple(actions):
            button = self._available_button(action)
            if button is not None and button_bounds(button).contains(point):
                return action
        return None

    def cancel_gaze_interaction(self) -> None:
        self._set_gaze_target_action(None)

    def set_gaze_target_action(self, action: str | None) -> None:
        self._set_gaze_target_action(action)

    def _new_dialog(self, *, object_name: str = "speechDialog") -> QDialog:
        dialog = QDialog(self)
        dialog.setObjectName(object_name)
        dialog.setModal(True)
        dialog.setWindowModality(Qt.ApplicationModal)
        dialog.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        return dialog

    def _position_sleep_dialog(self) -> None:
        top_left = self.mapToGlobal(QPoint(0, 0))
        self._sleep_dialog.setGeometry(QRect(top_left, self.size()))

    def _open_dialog(self, dialog: QDialog, height: int) -> None:
        self._context_changed()
        self._active_dialog = dialog
        self._modal_backdrop.setGeometry(self.rect())
        self._modal_backdrop.show()
        self._modal_backdrop.raise_()
        available_width = max(320, self.width() - 64)
        width = min(1280, max(680, round(self.width() * 0.68)), available_width)
        dialog.resize(width, min(height, max(320, self.height() - 64)))
        self._position_dialog(dialog)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _position_dialog(self, dialog: QDialog) -> None:
        center = self.mapToGlobal(self.rect().center())
        dialog.move(center.x() - dialog.width() // 2, center.y() - dialog.height() // 2)

    def _close_dialog(self) -> None:
        if self._active_dialog is not None:
            self._active_dialog.done(0)

    def _dialog_finished(self, dialog: QDialog) -> None:
        if dialog is not self._active_dialog:
            return
        self._active_dialog = None
        self.dialog_closed.emit(dialog)
        self._dialog_actions.clear()
        self._modal_backdrop.hide()
        self._context_changed()
        QTimer.singleShot(0, self, self._restore_input_focus)

    def _clear_main_grid(self) -> None:
        self._set_gaze_target_action(None)
        for action in self._main_dynamic_actions:
            self._action_buttons.pop(action, None)
        self._main_dynamic_actions.clear()
        self._clear_layout(self._key_grid)
        self._set_grid_stretch(0, 1)

    def _clear_letter_dialog(self) -> None:
        for action in self._letter_dialog_actions:
            self._action_buttons.pop(action, None)
        self._letter_dialog_actions.clear()
        self._clear_layout(self._letter_grid)

    def _clear_layout(self, layout: QGridLayout | QHBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()

    def _set_grid_stretch(self, item_count: int, columns: int) -> None:
        for column in range(KEY_GRID_MAX_COLUMNS):
            self._key_grid.setColumnStretch(column, 0)
        for row in range(KEY_GRID_MAX_ROWS):
            self._key_grid.setRowStretch(row, 0)
        rows = max(1, math.ceil(max(1, item_count) / max(1, columns)))
        # Tighten gaps for five-row grids without shrinking gaze targets.
        self._key_grid.setVerticalSpacing(6 if rows >= 5 else 10)
        for column in range(columns):
            self._key_grid.setColumnStretch(column, 1)
        for row in range(rows):
            self._key_grid.setRowStretch(row, 1)

    def _make_dynamic_button(self, text: str, action: str, object_name: str) -> QPushButton:
        button = self._make_button(
            text,
            action,
            object_name,
            parent=self._key_grid_host,
            minimum_height=GROUP_BUTTON_MIN_HEIGHT,
        )
        self._main_dynamic_actions.add(action)
        return button

    def _make_button(
        self,
        text: str,
        command: str,
        object_name: str,
        *,
        parent: QWidget | None = None,
        minimum_height: int,
        checkable: bool = False,
    ) -> QPushButton:
        button_type = (
            WrappedButton
            if object_name
            in (
                "groupButton",
                "phraseButton",
                "deleteItemButton",
                "predictionButton",
                "systemAlarm",
                "systemSleep",
                "systemExit",
            )
            else QPushButton
        )
        button = button_type(text, self if parent is None else parent)
        button.setObjectName(object_name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if button.window() is self:
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCheckable(checkable)
        button.setMinimumHeight(minimum_height)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        if isinstance(button, WrappedButton):
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        action = (
            self._action(command)
            if not command.startswith(SPEECH_WINDOW_ACTION_PREFIX)
            else command
        )
        self._register_button(action, button)
        return button

    def _register_button(self, action: str, button: QPushButton) -> None:
        self._action_buttons[action] = button
        button.setProperty("gazeTarget", False)
        button.setProperty("gazePulse", "")
        button.pressed.connect(self.mouse_action_started.emit)
        button.clicked.connect(lambda _checked=False, item=action: self.action_requested.emit(item))

    def _set_gaze_target_action(self, action: str | None) -> None:
        if action == self._gaze_target_action:
            return
        self._show_gaze_feedback(self._gaze_target_action, False)
        self._gaze_target_action = action
        self._show_gaze_feedback(action, True)

    def _show_gaze_feedback(self, action: str | None, selected: bool) -> None:
        if action is None:
            return
        button = self._action_buttons.get(action)
        if button is not None:
            set_gaze_feedback(button, selected)

    def _context_changed(self) -> None:
        self._set_gaze_target_action(None)
        self.interaction_context_changed.emit()

    def _action(self, name: str) -> str:
        return f"{SPEECH_WINDOW_ACTION_PREFIX}{name}"


def _utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


SPEECH_STYLE = """
            QWidget#speechWindow {
                background: #111318;
                color: #f6f7fb;
                font-family: Segoe UI, Arial, sans-serif;
                font-size: 15px;
            }
            QLabel#sectionLabel, QLabel#messageLabel, QLabel#statusLabel {
                color: #bac5d4;
                font-weight: 500;
            }
            QLabel#sectionLabel { font-size: 16px; }
            QLabel#messageLabel, QLabel#statusLabel { font-size: 13px; }
            QLineEdit#speechInput {
                background: #0b0d11;
                border: 2px solid #465268;
                border-radius: 8px;
                color: #ffffff;
                font-size: 30px;
                padding: 8px 16px;
                placeholder-text-color: #a0adbf;
                selection-background-color: #245f9f;
            }
            QPushButton {
                border: 1px solid #303747;
                border-radius: 8px;
                background: #1c2029;
                color: #eef2f8;
                font-size: 20px;
                font-weight: 700;
                padding: 8px;
            }
            QPushButton:hover { background: #262c38; border-color: #4c5970; }
            QPushButton:pressed, QPushButton:checked {
                background: #245f9f;
                border-color: #67b7dc;
            }
            QPushButton:disabled {
                background: #171a22;
                border-color: #2a303d;
                color: #667184;
            }
            QPushButton#clearButton {
                border-color: #67b7dc;
                background: #252b36;
                color: #ffe58a;
            }
            QPushButton#primaryButton {
                background: #2d68a8;
                border-color: #67b7dc;
                color: #ffffff;
                font-size: 23px;
            }
            QPushButton#primaryButton:disabled {
                background: #171a22;
                border-color: #2a303d;
                color: #667184;
            }
            QPushButton#predictionButton {
                background: #173447;
                border-color: #366c8d;
                color: #eef2f8;
                font-size: 22px;
            }
            QPushButton#predictionButton:disabled { color: #667184; background: #171a22; }
            QPushButton#groupButton {
                background: #1c2029;
                font-size: 29px;
                letter-spacing: 2px;
            }
            QPushButton#symbolButton { font-size: 32px; }
            QPushButton#utilityButton { font-size: 22px; }
            QPushButton#systemAlarm {
                background: #552326;
                border-color: #94434a;
                color: #ffd5d7;
                font-size: 27px;
            }
            QPushButton#systemSleep {
                background: #202538;
                border-color: #5b658c;
                color: #e0e5ff;
                font-size: 27px;
            }
            QPushButton#systemExit {
                background: #1c2029;
                border-color: #303747;
                color: #eef2f8;
                font-size: 27px;
            }
            QPushButton#phraseButton {
                font-size: 19px;
            }
            QPushButton#deleteItemButton {
                background: #4b2224;
                border-color: #7d383e;
                color: #fecaca;
                font-size: 19px;
            }
            QPushButton#headerActionButton { font-size: 18px; }
            QFrame#modalBackdrop { background: rgba(0, 0, 0, 190); }
            QDialog#speechDialog {
                background: #111318;
                border: 2px solid #67b7dc;
                border-radius: 12px;
                color: #eef2f8;
            }
            QDialog#speechDialog QLabel#dialogTitle {
                color: #eef2f8;
                font-size: 30px;
                font-weight: 500;
            }
            QDialog#speechDialog QLabel#dialogCopy { color: #dce6f3; font-size: 22px; }
            QDialog#speechDialog QPushButton#dialogLetterButton {
                font-size: 38px;
                min-height: 120px;
            }
            QDialog#speechDialog QPushButton#dialogBackButton {
                font-size: 22px;
                min-height: 120px;
            }
            QDialog#speechDialog QPushButton#dialogCompactLetterButton {
                font-size: 38px;
                min-height: 100px;
            }
            QDialog#speechDialog QPushButton#dialogCompactBackButton {
                font-size: 22px;
                min-height: 100px;
            }
            QDialog#speechDialog QPushButton#dialogConfirmButton {
                background: #552326;
                border-color: #94434a;
                color: #ffd5d7;
                font-size: 22px;
                min-height: 128px;
            }
            QDialog#speechDialog QPushButton#dialogCancelButton {
                font-size: 22px;
                min-height: 128px;
            }
            QDialog#sleepDialog { background: #000000; }
            QDialog#sleepDialog QPushButton#wakeButton {
                background: #08090b;
                border-color: #2b3038;
                color: #7f8794;
                font-size: 28px;
                min-height: 140px;
            }
            QDialog#sleepDialog QPushButton#wakeButton:hover {
                background: #111318;
                border-color: #657084;
                color: #bac5d4;
            }
            QWidget#speechWindow QPushButton[gazeTarget="true"][gazePulse="0"],
            QWidget#speechWindow QDialog#speechDialog QPushButton[gazeTarget="true"][gazePulse="0"] {
                background: #f0c84a;
                border: 4px solid #ffe58a;
                color: #111318;
            }
            QWidget#speechWindow QPushButton[gazeTarget="true"][gazePulse="1"],
            QWidget#speechWindow QDialog#speechDialog QPushButton[gazeTarget="true"][gazePulse="1"] {
                background: #16a34a;
                border: 4px solid #86efac;
                color: #ffffff;
            }
            """
