"""Windows z-order helpers for always-on-top overlays."""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes


logger = logging.getLogger(__name__)

HWND_TOPMOST = wintypes.HWND(-1)
GWL_EXSTYLE = -20
GWLP_HWNDPARENT = -8
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
SWP_NOOWNERZORDER = 0x0200
SWP_ASYNCWINDOWPOS = 0x4000

_user32 = None


def force_window_topmost(
    window: object,
    *,
    show: bool = False,
    aggressive: bool = False,
) -> bool:
    """Push a Qt top-level window to the Win32 topmost z-order band."""

    if sys.platform != "win32":
        return False

    hwnd_value = _window_handle(window)
    if hwnd_value is None:
        return False

    flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER
    if aggressive:
        flags = (
            SWP_NOMOVE
            | SWP_NOSIZE
            | SWP_NOACTIVATE
            | SWP_FRAMECHANGED
            | SWP_ASYNCWINDOWPOS
        )
    if show:
        flags |= SWP_SHOWWINDOW

    try:
        user32 = _load_user32()
        if aggressive:
            _detach_owner(user32, hwnd_value)
            _apply_overlay_exstyle(user32, hwnd_value)
        ok = user32.SetWindowPos(
            wintypes.HWND(hwnd_value),
            HWND_TOPMOST,
            0,
            0,
            0,
            0,
            flags,
        )
    except Exception:
        logger.exception("Could not force window to Win32 topmost z-order.")
        return False

    if ok:
        return True

    error_code = ctypes.get_last_error()
    if error_code:
        logger.debug("SetWindowPos(HWND_TOPMOST) failed with error %s.", error_code)
    return False


def _detach_owner(user32, hwnd_value: int) -> None:
    """Detach a Qt-owned tool window so shell UI cannot keep it below its owner."""

    try:
        _get_window_long, set_window_long, long_ptr = _window_long_functions(user32)
        set_window_long(wintypes.HWND(hwnd_value), GWLP_HWNDPARENT, long_ptr(0))
    except Exception:
        logger.debug("Could not detach overlay owner hwnd=%s.", hwnd_value, exc_info=True)


def _apply_overlay_exstyle(user32, hwnd_value: int) -> None:
    try:
        hwnd = wintypes.HWND(hwnd_value)
        get_window_long, set_window_long, long_ptr = _window_long_functions(user32)
        style = int(get_window_long(hwnd, GWL_EXSTYLE))
        style |= WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        set_window_long(hwnd, GWL_EXSTYLE, long_ptr(style))
    except Exception:
        logger.debug("Could not apply overlay extended styles hwnd=%s.", hwnd_value, exc_info=True)


def _window_long_functions(user32):
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        return user32.GetWindowLongPtrW, user32.SetWindowLongPtrW, ctypes.c_longlong
    return user32.GetWindowLongW, user32.SetWindowLongW, ctypes.c_long


def _window_handle(window: object) -> int | None:
    try:
        win_id = getattr(window, "winId")()
    except Exception:
        return None

    try:
        hwnd_value = int(win_id)
    except (TypeError, ValueError):
        return None

    return hwnd_value or None


def _load_user32():
    global _user32
    if _user32 is not None:
        return _user32

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        long_ptr = ctypes.c_longlong
    else:
        long_ptr = ctypes.c_long

    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = long_ptr
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, long_ptr]
        user32.SetWindowLongPtrW.restype = long_ptr
    else:
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongW.restype = long_ptr
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, long_ptr]
        user32.SetWindowLongW.restype = long_ptr
    _user32 = user32
    return user32
