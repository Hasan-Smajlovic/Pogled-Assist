"""Right-side AppBar panels that send input to the window the user was working in."""

from __future__ import annotations

import logging
import sys
import time
from typing import ClassVar

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication
from PySide6.QtWidgets import QToolButton, QWidget

from ..windows.appbar import ABE_RIGHT, WindowsAppBar
from ..windows.windows_input import WindowsInputController
from .gaze_feedback import set_gaze_feedback

SIDEBAR_WIDTH = 380
MIN_SIDEBAR_WIDTH = 320
MAX_SIDEBAR_WIDTH_FRACTION = 0.36


class SidebarPanel(QWidget):
    """Place a panel on the right edge and type into the remembered target window."""

    closed = Signal()
    status_changed = Signal(str)
    interaction_context_changed = Signal()
    mouse_action_started = Signal()
    keyboard_script_changed = Signal(str)

    log_name: ClassVar[str]
    full_height_status: ClassVar[str]
    reserved_status: ClassVar[str]
    unreserved_status: ClassVar[str]
    input_unavailable_status: ClassVar[str]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(_sidebar_window_flags())
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)
        self._logger = logging.getLogger(type(self).__module__)
        self._action_buttons: dict[str, QToolButton] = {}
        self._dynamic_actions: set[str] = set()
        self._gaze_target_action: str | None = None
        self._appbar = WindowsAppBar()
        self._input: WindowsInputController | None = None
        self._target_window: int | None = None
        self._full_height = False
        self._reserved_top_height = 0

    def show_sidebar(self, *, full_height: bool = False) -> None:
        self._full_height = bool(full_height)
        self._ensure_input_controller()
        self._remember_foreground_target()
        if self._full_height:
            self._appbar.unregister()
        self._position_on_primary_screen()
        self.show()
        self.raise_()
        self._register_appbar()
        self._restore_target_window()
        self._logger.info("%s sidebar shown.", self.log_name)

    def hide_sidebar(self) -> None:
        self._set_gaze_target_action(None)
        self._appbar.unregister()
        self.hide()
        self._logger.info("%s sidebar hidden.", self.log_name)

    def set_full_height(self, full_height: bool) -> None:
        full_height = bool(full_height)
        if self._full_height == full_height:
            return

        self._full_height = full_height
        if not self.isVisible():
            return

        if self._full_height:
            self._appbar.unregister()
        self._position_on_primary_screen()
        self._register_appbar()
        mode = "full screen height" if self._full_height else "available work area height"
        self._logger.info("%s sidebar resized to %s.", self.log_name, mode)

    def set_reserved_top_height(self, height: int) -> None:
        height = max(0, int(height))
        if height == self._reserved_top_height:
            return

        self._reserved_top_height = height
        if self.isVisible() and not self._full_height:
            self._position_on_primary_screen()
            self._register_appbar()

    def set_target_window(self, hwnd: int | None) -> None:
        if hwnd is None:
            return
        if hwnd == self._target_window:
            return

        self._target_window = hwnd
        self._logger.info("%s target window set externally: hwnd=%s.", self.log_name, hwnd)

    def action_at_global_point(self, point: QPoint) -> str | None:
        for action in self._action_buttons:
            rect = self.action_bounds(action)
            if rect is not None and rect.contains(point):
                return action

        return None

    def action_center_at_global_point(self, action: str, point: QPoint) -> QPoint | None:
        rect = self.action_bounds(action)
        return rect.center() if rect is not None and rect.contains(point) else None

    def action_bounds(self, action: str) -> QRect | None:
        if not self.isVisible():
            return None
        button = self._action_buttons.get(action)
        if button is None or not _is_selectable(button):
            return None
        return QRect(button.mapToGlobal(QPoint(0, 0)), button.size())

    def contains_global_point(self, point: QPoint) -> bool:
        if not self.isVisible():
            return False

        top_left = self.mapToGlobal(QPoint(0, 0))
        return QRect(top_left, self.size()).contains(point)

    def cancel_gaze_interaction(self) -> None:
        self._set_gaze_target_action(None)

    def set_gaze_target_action(self, action: str | None) -> None:
        self._set_gaze_target_action(action)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._logger.info("%s sidebar close event received.", self.log_name)
        self.hide_sidebar()
        self.closed.emit()
        super().closeEvent(event)

    def _type_key_label(self, label: str) -> None:
        if label == "Potvrdi":
            self._press_key("enter")
        else:
            self._type_text(label)

    def _type_text(self, text: str) -> None:
        self._ensure_input_controller()
        if self._input is None:
            self._emit_status("Unos putem tastature nije dostupan.")
            return

        try:
            self._restore_target_window()
            self._input.type_text(text)
            self._emit_status(f"Uneseno je {text!r}.")
        except Exception:
            self._logger.exception("%s text input failed.", self.log_name)
            self._emit_status("Unos putem tastature nije uspio.")

    def _press_key(self, key: str) -> None:
        self._ensure_input_controller()
        if self._input is None:
            self._emit_status("Unos putem tastature nije dostupan.")
            return

        try:
            self._restore_target_window()
            self._input.press_key(key)
            key_name = {"backspace": "brisanje", "enter": "potvrda"}.get(key, key)
            self._emit_status(f"Pritisnuta je tipka za {key_name}.")
        except Exception:
            self._logger.exception("%s key press failed.", self.log_name)
            self._emit_status("Pritisak tipke nije uspio.")

    def _ensure_input_controller(self) -> None:
        if self._input is not None:
            return

        try:
            self._input = WindowsInputController()
        except Exception:
            self._logger.exception("Could not initialize %s input backend.", self.log_name.lower())
            self._emit_status(self.input_unavailable_status)

    def _emit_status(self, text: str) -> None:
        self._logger.info("%s sidebar status: %s", self.log_name, text)
        self.setToolTip(text)
        self.status_changed.emit(text)

    def _remember_foreground_target(self) -> None:
        if self._input is None:
            return

        hwnd = self._input.foreground_window()
        if hwnd is None:
            return
        if self._input.belongs_to_current_process(hwnd):
            self._logger.info(
                "%s foreground target is an app window; keeping previous target.", self.log_name
            )
            return

        self._target_window = hwnd
        self._logger.info("%s target window captured: hwnd=%s.", self.log_name, hwnd)

    def _restore_target_window(self) -> bool:
        if self._input is None:
            return False

        current = self._input.foreground_window()
        if current is not None and not self._input.belongs_to_current_process(current):
            self._target_window = current
            return True

        if not self._target_window_is_valid():
            return False

        if current == self._target_window:
            return True

        restored = self._input.set_foreground_window(self._target_window)
        if restored:
            time.sleep(0.01)
        else:
            self._logger.warning(
                "Could not restore %s target window: hwnd=%s.",
                self.log_name.lower(),
                self._target_window,
            )
        return restored

    def _target_window_is_valid(self) -> bool:
        assert self._input is not None
        if self._target_window is None:
            self._logger.warning("%s has no external target window to restore.", self.log_name)
            return False

        if not self._input.is_window(self._target_window):
            self._logger.warning(
                "%s target window is no longer valid: hwnd=%s.", self.log_name, self._target_window
            )
            self._target_window = None
            return False
        return True

    def _set_gaze_target_action(self, action: str | None) -> None:
        if action == self._gaze_target_action:
            return

        if self._gaze_target_action is not None:
            previous = self._action_buttons.get(self._gaze_target_action)
            if previous is not None:
                set_gaze_feedback(previous, False)

        self._gaze_target_action = action

        if self._gaze_target_action is not None:
            current = self._action_buttons.get(self._gaze_target_action)
            if current is not None:
                set_gaze_feedback(current, True)

    def _position_on_primary_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        geometry = screen.geometry() if self._full_height else screen.availableGeometry()
        if not self._full_height and self._reserved_top_height > 0:
            screen_geometry = screen.geometry()
            top = max(geometry.top(), screen_geometry.top() + self._reserved_top_height)
            geometry = QRect(
                geometry.left(),
                top,
                geometry.width(),
                max(1, geometry.bottom() - top + 1),
            )
        width = min(
            SIDEBAR_WIDTH,
            max(MIN_SIDEBAR_WIDTH, int(geometry.width() * MAX_SIDEBAR_WIDTH_FRACTION)),
        )
        self.setGeometry(
            geometry.right() - width + 1,
            geometry.top(),
            width,
            geometry.height(),
        )

    def _register_appbar(self) -> None:
        if self._full_height:
            self._appbar.unregister()
            self._emit_status(self.full_height_status)
            return

        if self._appbar.register(int(self.winId()), self.width(), edge=ABE_RIGHT):
            self._emit_status(self.reserved_status)
        elif sys.platform == "win32":
            self._emit_status(self.unreserved_status)


def _is_selectable(button: QToolButton) -> bool:
    return button.isVisible() and button.isEnabled()


def _sidebar_window_flags() -> Qt.WindowFlags:
    flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
    no_focus = getattr(Qt, "WindowDoesNotAcceptFocus", None)
    if no_focus is None:
        no_focus = getattr(Qt.WindowType, "WindowDoesNotAcceptFocus", None)
    if no_focus is not None:
        flags |= no_focus
    return flags
