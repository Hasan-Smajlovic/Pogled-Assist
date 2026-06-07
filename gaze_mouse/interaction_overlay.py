"""Animated overlay for active gaze interactions."""

from __future__ import annotations

import ctypes
import logging
import math
import sys
import time
from ctypes import wintypes

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .windows_z_order import force_window_topmost


logger = logging.getLogger(__name__)

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
MIN_PROGRESS_UPDATE_INTERVAL_MS = 20
MIN_PROGRESS_MOVE_DISTANCE_PX = 2
MIN_PROGRESS_DELTA = 0.015
TOPMOST_REFRESH_INTERVAL_MS = 33


class InteractionOverlayWindow(QWidget):
    """Click-through progress marker for a gaze dwell action."""

    OVERLAY_SIZE = 138
    FIRED_DURATION_MS = 360

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._enabled = True
        self._active = False
        self._mode = "progress"
        self._progress = 0.0
        self._label = ""
        self._phase = 0.0
        self._fired_started_ms = 0.0
        self._last_progress_point: QPoint | None = None
        self._last_progress_update_ms = 0.0
        self._last_raise_ms = 0.0
        self._last_topmost_ms = 0.0
        self._windows_click_through_applied = False

        self.setWindowTitle("Gaze Interaction Overlay")
        self.setWindowFlags(_overlay_window_flags())
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(self.OVERLAY_SIZE, self.OVERLAY_SIZE)

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def set_enabled(self, enabled: bool) -> None:
        if self._enabled == enabled:
            return

        self._enabled = enabled
        logger.info("Interaction overlay %s.", "enabled" if enabled else "disabled")
        if not enabled:
            self._hide_now()

    def show_progress(self, point: QPoint, progress: float, label: str) -> None:
        if not self._enabled:
            return

        clamped_progress = _clamp(progress, 0.0, 1.0)
        compact_label = _compact_label(label)
        now_ms = time.monotonic() * 1000
        if self._progress_update_skippable(point, clamped_progress, compact_label, now_ms):
            return

        self._active = True
        self._mode = "progress"
        self._progress = clamped_progress
        self._label = compact_label
        self._last_progress_point = QPoint(point)
        self._last_progress_update_ms = now_ms
        self._move_center_to(point)
        self._ensure_visible()
        self.update()

    def show_fired(self, point: QPoint, label: str) -> None:
        if not self._enabled:
            return

        self._active = True
        self._mode = "fired"
        self._progress = 1.0
        self._label = _compact_label(label)
        self._last_progress_point = QPoint(point)
        self._last_progress_update_ms = time.monotonic() * 1000
        self._fired_started_ms = time.monotonic() * 1000
        self._move_center_to(point)
        self._ensure_visible()
        self.update()

    def clear(self) -> None:
        if self._mode == "fired":
            return

        self._hide_now()

    def paintEvent(self, _event) -> None:
        if not self._active:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        pulse = (math.sin(self._phase) + 1.0) / 2.0
        fired = self._mode == "fired"
        base_rect = QRectF(15, 15, self.width() - 30, self.height() - 30)
        arc_rect = QRectF(21, 21, self.width() - 42, self.height() - 42)
        center = self.rect().center()

        if fired:
            fill = QColor(34, 197, 94, 48 + int(42 * pulse))
            outer = QColor(34, 197, 94, 150 + int(70 * pulse))
            arc = QColor(255, 255, 255, 235)
            text = "Done"
        else:
            fill = QColor(245, 158, 11, 34 + int(28 * pulse))
            outer = QColor(245, 158, 11, 125 + int(70 * pulse))
            arc = QColor(255, 255, 255, 235)
            text = self._label

        painter.setPen(QPen(outer, 5 + int(2 * pulse)))
        painter.setBrush(fill)
        painter.drawEllipse(base_rect)

        painter.setPen(QPen(QColor(15, 23, 42, 125), 10))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(arc_rect)

        painter.setPen(QPen(arc, 10, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(arc_rect, 90 * 16, int(-360 * 16 * self._progress))

        dot_radius = 10 + int(4 * pulse)
        painter.setPen(QPen(QColor(255, 255, 255, 220), 2))
        painter.setBrush(QColor(15, 23, 42, 185))
        painter.drawEllipse(center, dot_radius, dot_radius)

        if text:
            painter.setPen(QColor(255, 255, 255, 238))
            font = QFont("Segoe UI", 10)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(self.rect().adjusted(12, 92, -12, -12), Qt.AlignCenter, text)

    def _tick(self) -> None:
        self._phase += 0.24
        if self._mode == "fired":
            elapsed_ms = time.monotonic() * 1000 - self._fired_started_ms
            if elapsed_ms >= self.FIRED_DURATION_MS:
                self._hide_now()
                return

        self._refresh_windows_topmost_due()
        self.update()

    def _move_center_to(self, point: QPoint) -> None:
        self.move(point.x() - self.width() // 2, point.y() - self.height() // 2)

    def _progress_update_skippable(
        self,
        point: QPoint,
        progress: float,
        label: str,
        now_ms: float,
    ) -> bool:
        if not self._active or self._mode != "progress":
            return False

        if self._label != label:
            return False

        if abs(progress - self._progress) >= MIN_PROGRESS_DELTA:
            return False

        if self._last_progress_point is None:
            return False

        distance = (
            abs(point.x() - self._last_progress_point.x())
            + abs(point.y() - self._last_progress_point.y())
        )
        if distance >= MIN_PROGRESS_MOVE_DISTANCE_PX:
            return False

        return now_ms - self._last_progress_update_ms < MIN_PROGRESS_UPDATE_INTERVAL_MS

    def _ensure_visible(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

        if not self.isVisible() or self._raise_due():
            self.show()
            self._apply_windows_click_through()
            self.raise_()
            self._refresh_windows_topmost(force=True)
            self._last_raise_ms = time.monotonic() * 1000

    def _raise_due(self) -> bool:
        return time.monotonic() * 1000 - self._last_raise_ms >= 150

    def _hide_now(self) -> None:
        self._active = False
        self._mode = "progress"
        self._progress = 0.0
        self._label = ""
        self._last_progress_point = None
        self._last_progress_update_ms = 0.0
        self._last_topmost_ms = 0.0
        self._timer.stop()
        self.hide()

    def _refresh_windows_topmost_due(self) -> None:
        if not self.isVisible():
            return

        now_ms = time.monotonic() * 1000
        if now_ms - self._last_topmost_ms >= TOPMOST_REFRESH_INTERVAL_MS:
            self._refresh_windows_topmost(now_ms=now_ms)

    def _refresh_windows_topmost(
        self,
        *,
        force: bool = False,
        now_ms: float | None = None,
    ) -> None:
        if not force and not self.isVisible():
            return

        force_window_topmost(self, show=True, aggressive=True)
        self._last_topmost_ms = now_ms if now_ms is not None else time.monotonic() * 1000

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
            logger.info("Applied Windows click-through style to interaction overlay.")
        except Exception:
            logger.exception("Could not apply Windows click-through style to interaction overlay.")


def _overlay_window_flags() -> Qt.WindowFlags:
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


def _compact_label(label: str) -> str:
    normalized = " ".join(label.split())
    if len(normalized) <= 13:
        return normalized
    if normalized == "Double click":
        return "Double"
    if normalized == "Left click":
        return "Left"
    if normalized == "Right click":
        return "Right"
    return normalized[:13]


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))
