"""Windows DPI helpers."""

from __future__ import annotations

import contextlib
import sys


def enable_windows_dpi_awareness() -> None:
    """Make Qt and PyAutoGUI use the same physical pixel coordinate space."""

    if sys.platform != "win32":
        return

    import ctypes

    with contextlib.suppress(Exception):
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return

    with contextlib.suppress(Exception):
        ctypes.windll.user32.SetProcessDPIAware()
