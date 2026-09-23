"""Windows AppBar reservation for the top toolbar.

The AppBar API tells Windows that this application owns a strip of the
desktop. Maximized windows and normal work areas should then start below the
toolbar instead of hiding behind it.
"""

from __future__ import annotations

import logging
import sys
from typing import ClassVar

logger = logging.getLogger(__name__)

ABM_NEW = 0x00000000
ABM_REMOVE = 0x00000001
ABM_QUERYPOS = 0x00000002
ABM_SETPOS = 0x00000003

ABE_LEFT = 0
ABE_TOP = 1
ABE_RIGHT = 2
ABE_BOTTOM = 3
MONITOR_DEFAULTTONEAREST = 2
WM_APP = 0x8000


class WindowsAppBar:
    """Register and unregister a Windows AppBar edge reservation."""

    def __init__(self) -> None:
        self._hwnd: int | None = None
        self._registered = False
        self._edge = ABE_TOP

    @property
    def supported(self) -> bool:
        return sys.platform == "win32"

    def register(self, hwnd: int, logical_size: int, edge: int = ABE_TOP) -> bool:
        if not self.supported:
            logger.info("Windows AppBar is not supported on this platform.")
            return False

        logger.info(
            "Registering Windows AppBar for hwnd=%s edge=%s size=%s.",
            hwnd,
            edge,
            logical_size,
        )
        self.unregister()
        ctypes, _, APPBARDATA = _win_types()

        data = APPBARDATA()
        data.cbSize = ctypes.sizeof(APPBARDATA)
        data.hWnd = hwnd
        data.uCallbackMessage = WM_APP + 47

        result = ctypes.windll.shell32.SHAppBarMessage(ABM_NEW, ctypes.byref(data))
        if not result:
            logger.warning("SHAppBarMessage(ABM_NEW) returned failure.")
            return False

        self._hwnd = hwnd
        self._registered = True
        self._edge = edge
        self.set_position(logical_size)
        logger.info("Windows AppBar registered.")
        return True

    def set_position(self, logical_size: int) -> None:
        if not self.supported or self._hwnd is None or not self._registered:
            return

        ctypes, RECT, APPBARDATA = _win_types()

        monitor_rect = _monitor_rect_for_window(self._hwnd)
        dpi = _dpi_for_window(self._hwnd)
        physical_size = max(1, round(logical_size * dpi / 96))

        data = APPBARDATA()
        data.cbSize = ctypes.sizeof(APPBARDATA)
        data.hWnd = self._hwnd
        data.uEdge = self._edge
        data.rc = _edge_rect(RECT, monitor_rect, self._edge, physical_size)

        ctypes.windll.shell32.SHAppBarMessage(ABM_QUERYPOS, ctypes.byref(data))
        _apply_edge_size(data.rc, self._edge, physical_size)
        ctypes.windll.shell32.SHAppBarMessage(ABM_SETPOS, ctypes.byref(data))
        logger.info(
            "Windows AppBar positioned: edge=%s left=%s top=%s right=%s bottom=%s dpi=%s.",
            self._edge,
            data.rc.left,
            data.rc.top,
            data.rc.right,
            data.rc.bottom,
            dpi,
        )

    def unregister(self) -> None:
        if not self.supported or self._hwnd is None or not self._registered:
            return

        logger.info("Unregistering Windows AppBar.")
        ctypes, _, APPBARDATA = _win_types()

        data = APPBARDATA()
        data.cbSize = ctypes.sizeof(APPBARDATA)
        data.hWnd = self._hwnd

        ctypes.windll.shell32.SHAppBarMessage(ABM_REMOVE, ctypes.byref(data))
        self._registered = False
        self._hwnd = None
        logger.info("Windows AppBar unregistered.")


def _edge_rect(rect_type, monitor_rect, edge: int, physical_size: int):
    if edge == ABE_LEFT:
        return rect_type(
            monitor_rect.left,
            monitor_rect.top,
            monitor_rect.left + physical_size,
            monitor_rect.bottom,
        )
    if edge == ABE_RIGHT:
        return rect_type(
            monitor_rect.right - physical_size,
            monitor_rect.top,
            monitor_rect.right,
            monitor_rect.bottom,
        )
    if edge == ABE_BOTTOM:
        return rect_type(
            monitor_rect.left,
            monitor_rect.bottom - physical_size,
            monitor_rect.right,
            monitor_rect.bottom,
        )

    return rect_type(
        monitor_rect.left,
        monitor_rect.top,
        monitor_rect.right,
        monitor_rect.top + physical_size,
    )


def _apply_edge_size(rect, edge: int, physical_size: int) -> None:
    if edge == ABE_LEFT:
        rect.right = rect.left + physical_size
    elif edge == ABE_RIGHT:
        rect.left = rect.right - physical_size
    elif edge == ABE_BOTTOM:
        rect.top = rect.bottom - physical_size
    else:
        rect.bottom = rect.top + physical_size


def _win_types():
    import ctypes
    from ctypes import wintypes

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    class APPBARDATA(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hWnd", wintypes.HWND),
            ("uCallbackMessage", wintypes.UINT),
            ("uEdge", wintypes.UINT),
            ("rc", RECT),
            ("lParam", wintypes.LPARAM),
        ]

    return ctypes, RECT, APPBARDATA


def _monitor_rect_for_window(hwnd: int):
    ctypes, RECT, _ = _win_types()
    from ctypes import wintypes

    class MONITORINFO(ctypes.Structure):
        _fields_: ClassVar[list[tuple[str, type]]] = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    monitor = ctypes.windll.user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(info))
    return info.rcMonitor


def _dpi_for_window(hwnd: int) -> int:
    import ctypes

    try:
        return int(ctypes.windll.user32.GetDpiForWindow(hwnd))
    except Exception:
        return 96
