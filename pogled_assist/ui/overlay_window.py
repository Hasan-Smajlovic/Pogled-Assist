"""Shared window flags and timed stacking for desktop overlays."""

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from ..windows.windows_z_order import force_window_topmost, make_window_click_through

TOPMOST_REFRESH_INTERVAL_MS = 33


def overlay_window_flags(*, click_through: bool = False) -> Qt.WindowFlags:
    flags = Qt.FramelessWindowHint | Qt.Window | Qt.WindowStaysOnTopHint
    flags |= Qt.WindowDoesNotAcceptFocus
    if click_through:
        flags |= Qt.WindowTransparentForInput
    return flags


class OverlayStacking:
    """Use an overlay's existing timer without creating another Qt timer."""

    def __init__(self, window: QWidget) -> None:
        self._window = window
        self._click_through_applied = False
        self.reset()

    def apply_click_through(self) -> None:
        if not self._click_through_applied:
            self._click_through_applied = make_window_click_through(self._window)

    def reset(self) -> None:
        self._last_refresh_ms = 0.0

    def refresh_if_due(self) -> None:
        if not self._window.isVisible():
            return
        now_ms = time.monotonic() * 1000
        if now_ms - self._last_refresh_ms >= TOPMOST_REFRESH_INTERVAL_MS:
            self.refresh(now_ms=now_ms)

    def refresh(self, *, force: bool = False, now_ms: float | None = None) -> None:
        if not force and not self._window.isVisible():
            return
        force_window_topmost(self._window, show=True, aggressive=True)
        self._last_refresh_ms = now_ms if now_ms is not None else time.monotonic() * 1000
