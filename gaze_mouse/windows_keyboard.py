"""Helpers for opening Windows on-screen keyboard surfaces."""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from ctypes import wintypes
from pathlib import Path

logger = logging.getLogger(__name__)

SW_SHOWNORMAL = 1
SHELL_SUCCESS_MIN = 33

_SHELL_ERROR_MESSAGES = {
    0: "out of memory",
    2: "file not found",
    3: "path not found",
    5: "access denied",
    8: "out of memory",
    26: "sharing violation",
    27: "association incomplete",
    28: "DDE timeout",
    29: "DDE failed",
    30: "DDE busy",
    31: "no association",
    32: "DLL not found",
}


class WindowsKeyboardError(RuntimeError):
    """Raised when Windows on-screen keyboard surfaces cannot be opened."""


def open_windows_keyboard() -> str:
    """Open Windows OSK through ShellExecute so elevation manifests are honored."""

    if sys.platform != "win32":
        raise WindowsKeyboardError("Windows keyboard is only available on Windows.")

    errors: list[str] = []
    for label, target in _keyboard_candidates():
        try:
            _shell_execute(target)
            logger.info("Opened %s using ShellExecute target: %s", label, target)
            return label
        except WindowsKeyboardError as exc:
            logger.warning("Could not open %s using %s: %s", label, target, exc)
            errors.append(f"{label} ({target}): {exc}")

    raise WindowsKeyboardError("; ".join(errors) or "No keyboard launch targets were available.")


def _keyboard_candidates() -> list[tuple[str, str]]:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    program_files = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))

    candidates = [
        ("Windows on-screen keyboard", "osk.exe"),
        ("Windows on-screen keyboard", str(windir / "System32" / "osk.exe")),
        ("Windows on-screen keyboard", str(windir / "Sysnative" / "osk.exe")),
        (
            "Windows touch keyboard",
            str(program_files / "Common Files" / "Microsoft Shared" / "ink" / "TabTip.exe"),
        ),
    ]

    unique: list[tuple[str, str]] = []
    seen: set[str] = set()
    for label, target in candidates:
        key = target.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append((label, target))

    return unique


def _shell_execute(target: str) -> None:
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteW.argtypes = [
        wintypes.HWND,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.c_int,
    ]
    shell32.ShellExecuteW.restype = ctypes.c_void_p

    result = shell32.ShellExecuteW(None, "open", target, None, None, SW_SHOWNORMAL)
    code = int(result or 0)
    if code >= SHELL_SUCCESS_MIN:
        return

    message = _SHELL_ERROR_MESSAGES.get(code, f"ShellExecute error code {code}")
    last_error = ctypes.get_last_error()
    if last_error:
        message = f"{message}; last error {last_error}: {ctypes.WinError(last_error)}"
    raise WindowsKeyboardError(message)
