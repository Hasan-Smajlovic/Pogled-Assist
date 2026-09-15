"""Transparent gaze position marker overlay."""

from __future__ import annotations

import ctypes
import logging
import sys
import time
from ctypes import wintypes

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .windows_z_order import force_window_topmost

logger = logging.getLogger(__name__)

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
MIN_MOVE_INTERVAL_MS = 20
MIN_MOVE_DISTANCE_PX = 2
TOPMOST_REFRESH_INTERVAL_MS = 33


class GazeBubbleWindow(QWidget):
    """Small click-through overlay that follows the latest gaze point."""

    BUBBLE_SIZE = 46

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._enabled = True
        self._last_point: QPoint | None = None
        self._last_moved_point: QPoint | None = None
        self._last_move_ms = 0.0
        self._last_raise_ms = 0.0
        self._windows_click_through_applied = False
        self._topmost_timer = QTimer(self)
        self._topmost_timer.setInterval(TOPMOST_REFRESH_INTERVAL_MS)
        self._topmost_timer.timeout.connect(self._refresh_windows_topmost)

        self.setWindowTitle("Gaze Bubble")
        self.setWindowFlags(_bubble_window_flags())
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(self.BUBBLE_SIZE, self.BUBBLE_SIZE)
        self.hide()

    def set_enabled(self, enabled: bool) -> None:
        if self._enabled == enabled:
            return

        self._enabled = enabled
        logger.info("Gaze bubble %s.", "enabled" if enabled else "disabled")
        if not enabled:
            self._topmost_timer.stop()
            self.hide()
            return

        if self._last_point is not None:
            self._move_center_to(self._last_point)
            self._last_moved_point = QPoint(self._last_point)
            self._last_move_ms = time.monotonic() * 1000
            self._show_without_focus()

    def handle_gaze(self, point: QPoint) -> None:
        self._last_point = QPoint(point)
        if not self._enabled:
            return

        now_ms = time.monotonic() * 1000
        if self.isVisible() and not self._move_due(point, now_ms):
            return

        self._move_center_to(point)
        self._last_moved_point = QPoint(point)
        self._last_move_ms = now_ms
        if not self.isVisible() or self._raise_due():
            self._show_without_focus()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        outer_rect = self.rect().adjusted(3, 3, -3, -3)
        inner_rect = self.rect().adjusted(10, 10, -10, -10)
        center = self.rect().center()

        painter.setPen(QPen(QColor(18, 185, 255, 115), 5))
        painter.setBrush(QColor(18, 185, 255, 28))
        painter.drawEllipse(outer_rect)

        painter.setPen(QPen(QColor(235, 250, 255, 190), 2))
        painter.setBrush(QColor(18, 185, 255, 72))
        painter.drawEllipse(inner_rect)

        painter.setPen(QPen(QColor(5, 25, 38, 130), 1))
        painter.setBrush(QColor(255, 255, 255, 210))
        painter.drawEllipse(center, 4, 4)

    def _move_center_to(self, point: QPoint) -> None:
        self.move(point.x() - self.width() // 2, point.y() - self.height() // 2)

    def _move_due(self, point: QPoint, now_ms: float) -> bool:
        if self._last_moved_point is None:
            return True

        distance = abs(point.x() - self._last_moved_point.x()) + abs(
            point.y() - self._last_moved_point.y()
        )
        if distance >= MIN_MOVE_DISTANCE_PX:
            return True

        return now_ms - self._last_move_ms >= MIN_MOVE_INTERVAL_MS

    def _show_without_focus(self) -> None:
        self.show()
        self._apply_windows_click_through()
        self.raise_()
        self._refresh_windows_topmost()
        if not self._topmost_timer.isActive():
            self._topmost_timer.start()
        self._last_raise_ms = time.monotonic() * 1000

    def _raise_due(self) -> bool:
        return time.monotonic() * 1000 - self._last_raise_ms >= 250

    def _refresh_windows_topmost(self) -> None:
        if not self.isVisible():
            self._topmost_timer.stop()
            return

        force_window_topmost(self, show=True, aggressive=True)

    def _apply_windows_click_through(self) -> None:
        if self._windows_click_through_applied or sys.platform != "win32":
            return

        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            hwnd = wintypes.HWND(int(self.winId()))
            if ctypes.sizeof(ctypes.c_void_p) == 8:
                get_window_long = user32.GetWindowLongPtrW
                set_window_long = user32.SetWindowLongPtrW
                long_ptr = ctypes.c_longlong
            else:
                get_window_long = user32.GetWindowLongW
                set_window_long = user32.SetWindowLongW
                long_ptr = ctypes.c_long

            get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
            get_window_long.restype = long_ptr
            set_window_long.argtypes = [wintypes.HWND, ctypes.c_int, long_ptr]
            set_window_long.restype = long_ptr

            style = int(get_window_long(hwnd, GWL_EXSTYLE))
            style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
            set_window_long(hwnd, GWL_EXSTYLE, long_ptr(style))
            self._windows_click_through_applied = True
            logger.info("Applied Windows click-through style to gaze bubble.")
        except Exception:
            logger.exception("Could not apply Windows click-through style to gaze bubble.")


def _bubble_window_flags() -> Qt.WindowFlags:
    flags = Qt.FramelessWindowHint | Qt.Window | Qt.WindowStaysOnTopHint
    no_focus = getattr(Qt, "WindowDoesNotAcceptFocus", None)
    if no_focus is None:
        no_focus = getattr(Qt.WindowType, "WindowDoesNotAcceptFocus", None)
    if no_focus is not None:
        flags |= no_focus
    transparent_input = getattr(Qt, "WindowTransparentForInput", None)
    if transparent_input is None:
        transparent_input = getattr(Qt.WindowType, "WindowTransparentForInput", None)
    if transparent_input is not None:
        flags |= transparent_input
    return flags
