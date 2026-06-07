"""Windows input helpers using user32 APIs."""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import time
from dataclasses import dataclass
from ctypes import wintypes

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

INPUT_KEYBOARD = 1

VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_F10 = 0x79
VK_BACK = 0x08
VK_RETURN = 0x0D
VK_SPACE = 0x20
VK_TAB = 0x09
VK_MENU = 0x12

SM_CXSCREEN = 0
SM_CYSCREEN = 1
MONITOR_DEFAULTTOPRIMARY = 1
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
logger = logging.getLogger(__name__)

_KEY_CODES = {
    "ctrl": VK_CONTROL,
    "control": VK_CONTROL,
    "shift": VK_SHIFT,
    "f10": VK_F10,
    "backspace": VK_BACK,
    "enter": VK_RETURN,
    "return": VK_RETURN,
    "space": VK_SPACE,
    "tab": VK_TAB,
}


@dataclass(frozen=True)
class ScreenRect:
    left: int
    top: int
    width: int
    height: int


class WindowsInputController:
    """Move the pointer, click, and send shortcuts through Windows user32."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Windows input control is only available on Windows.")

        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._extra_info_type = (
            ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
        )
        self._configure_signatures()
        logger.info(
            "Windows input controller initialized: input_size=%s pointer_size=%s.",
            ctypes.sizeof(_INPUT),
            ctypes.sizeof(ctypes.c_void_p),
        )

    def primary_screen_rect(self) -> ScreenRect:
        rect = self._primary_monitor_rect()
        if rect is not None:
            return rect

        width = int(self._user32.GetSystemMetrics(SM_CXSCREEN))
        height = int(self._user32.GetSystemMetrics(SM_CYSCREEN))
        return ScreenRect(0, 0, max(1, width), max(1, height))

    def move_to(self, x: int, y: int) -> None:
        ctypes.set_last_error(0)
        if self._user32.SetCursorPos(int(x), int(y)):
            return

        error_code = ctypes.get_last_error()
        if error_code == 0:
            logger.debug(
                "SetCursorPos returned false without a Windows error at x=%s y=%s.",
                x,
                y,
            )
            return

        raise ctypes.WinError(error_code)

    def click(
        self,
        x: int,
        y: int,
        *,
        button: str = "left",
        clicks: int = 1,
        interval: float = 0.04,
    ) -> None:
        self.move_to(x, y)
        down_flag, up_flag = _button_flags(button)

        for click_index in range(max(1, clicks)):
            self._mouse_event(down_flag)
            time.sleep(0.005)
            self._mouse_event(up_flag)
            if click_index < clicks - 1:
                time.sleep(interval)

    def click_current(
        self,
        *,
        button: str = "left",
        clicks: int = 1,
        interval: float = 0.04,
    ) -> None:
        x, y = self.cursor_position()
        self.click(x, y, button=button, clicks=clicks, interval=interval)

    def scroll(self, units: int) -> None:
        self._mouse_event(MOUSEEVENTF_WHEEL, int(units) * WHEEL_DELTA)

    def cursor_position(self) -> tuple[int, int]:
        point = wintypes.POINT()
        ctypes.set_last_error(0)
        if self._user32.GetCursorPos(ctypes.byref(point)):
            return int(point.x), int(point.y)

        error_code = ctypes.get_last_error()
        if error_code == 0:
            logger.debug("GetCursorPos returned false without a Windows error.")
            return 0, 0

        raise ctypes.WinError(error_code)

    def hotkey(self, *keys: str) -> None:
        key_codes = [_key_code(key) for key in keys]
        inputs: list[_INPUT] = []
        inputs.extend(_keyboard_input(key_code, 0, 0) for key_code in key_codes)
        inputs.extend(
            _keyboard_input(key_code, 0, KEYEVENTF_KEYUP)
            for key_code in reversed(key_codes)
        )
        self._send_keyboard_inputs(*inputs)

    def press_key(self, key: str) -> None:
        key_code = _key_code(key)
        self._send_keyboard_inputs(
            _keyboard_input(key_code, 0, 0),
            _keyboard_input(key_code, 0, KEYEVENTF_KEYUP),
        )

    def type_text(self, text: str) -> None:
        for character in text:
            try:
                self._send_unicode_character(character)
            except OSError as exc:
                logger.warning(
                    "Unicode SendInput failed for %r; trying keyboard-layout fallback: %s",
                    character,
                    exc,
                )
                if not self._send_character_via_keyboard_layout(character):
                    raise
            time.sleep(0.002)

    def foreground_window(self) -> int | None:
        hwnd = int(self._user32.GetForegroundWindow() or 0)
        return hwnd or None

    def is_window(self, hwnd: int | None) -> bool:
        if not hwnd:
            return False
        return bool(self._user32.IsWindow(wintypes.HWND(hwnd)))

    def set_foreground_window(self, hwnd: int | None) -> bool:
        if not self.is_window(hwnd):
            return False
        target = wintypes.HWND(hwnd)
        if self._user32.SetForegroundWindow(target):
            return True
        return self._force_foreground_window(target)

    def belongs_to_current_process(self, hwnd: int | None) -> bool:
        if not self.is_window(hwnd):
            return False

        process_id = wintypes.DWORD(0)
        self._user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(process_id))
        return int(process_id.value) == os.getpid()

    def _configure_signatures(self) -> None:
        self._user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self._user32.SetCursorPos.restype = wintypes.BOOL

        self._user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        self._user32.GetCursorPos.restype = wintypes.BOOL

        self._user32.mouse_event.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            self._extra_info_type,
        ]
        self._user32.mouse_event.restype = None

        self._user32.keybd_event.argtypes = [
            ctypes.c_ubyte,
            ctypes.c_ubyte,
            wintypes.DWORD,
            self._extra_info_type,
        ]
        self._user32.keybd_event.restype = None

        self._user32.SendInput.argtypes = [
            wintypes.UINT,
            ctypes.POINTER(_INPUT),
            ctypes.c_int,
        ]
        self._user32.SendInput.restype = wintypes.UINT

        self._user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
        self._user32.VkKeyScanW.restype = ctypes.c_short

        self._user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        self._user32.GetSystemMetrics.restype = ctypes.c_int

        self._user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        self._user32.MonitorFromPoint.restype = wintypes.HMONITOR

        self._user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.c_void_p]
        self._user32.GetMonitorInfoW.restype = wintypes.BOOL

        self._user32.GetForegroundWindow.argtypes = []
        self._user32.GetForegroundWindow.restype = wintypes.HWND

        self._user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self._user32.SetForegroundWindow.restype = wintypes.BOOL

        self._user32.IsWindow.argtypes = [wintypes.HWND]
        self._user32.IsWindow.restype = wintypes.BOOL

        self._user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._user32.GetWindowThreadProcessId.restype = wintypes.DWORD

        self._kernel32.GetCurrentThreadId.argtypes = []
        self._kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        self._user32.AttachThreadInput.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.BOOL,
        ]
        self._user32.AttachThreadInput.restype = wintypes.BOOL

        self._user32.BringWindowToTop.argtypes = [wintypes.HWND]
        self._user32.BringWindowToTop.restype = wintypes.BOOL

        self._user32.SetFocus.argtypes = [wintypes.HWND]
        self._user32.SetFocus.restype = wintypes.HWND

    def _mouse_event(self, flags: int, data: int = 0) -> None:
        mouse_data = int(data) & 0xFFFFFFFF
        self._user32.mouse_event(flags, 0, 0, mouse_data, self._extra_info_type(0))

    def _keybd_event(self, key_code: int, flags: int) -> None:
        self._user32.keybd_event(key_code, 0, flags, self._extra_info_type(0))

    def _send_unicode_character(self, character: str) -> None:
        for code_unit in _utf16_code_units(character):
            self._send_keyboard_inputs(
                _keyboard_input(0, code_unit, KEYEVENTF_UNICODE),
                _keyboard_input(0, code_unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
            )

    def _send_character_via_keyboard_layout(self, character: str) -> bool:
        scan = int(self._user32.VkKeyScanW(character))
        if scan == -1:
            return False

        vk = scan & 0xFF
        shift_state = (scan >> 8) & 0xFF
        modifiers: list[int] = []
        if shift_state & 1:
            modifiers.append(VK_SHIFT)
        if shift_state & 2:
            modifiers.append(VK_CONTROL)
        if shift_state & 4:
            modifiers.append(VK_MENU)

        inputs: list[_INPUT] = []
        inputs.extend(_keyboard_input(modifier, 0, 0) for modifier in modifiers)
        inputs.append(_keyboard_input(vk, 0, 0))
        inputs.append(_keyboard_input(vk, 0, KEYEVENTF_KEYUP))
        inputs.extend(
            _keyboard_input(modifier, 0, KEYEVENTF_KEYUP)
            for modifier in reversed(modifiers)
        )
        self._send_keyboard_inputs(*inputs)
        return True

    def _send_keyboard_inputs(self, *items: "_INPUT") -> None:
        inputs = (_INPUT * len(items))(*items)
        sent = self._user32.SendInput(
            len(inputs),
            inputs,
            ctypes.sizeof(_INPUT),
        )
        if sent != len(inputs):
            raise ctypes.WinError(ctypes.get_last_error())

    def _force_foreground_window(self, hwnd: wintypes.HWND) -> bool:
        current_thread = int(self._kernel32.GetCurrentThreadId())
        target_thread = self._window_thread_id(hwnd)
        foreground = self.foreground_window()
        foreground_thread = (
            self._window_thread_id(wintypes.HWND(foreground)) if foreground else 0
        )

        attached_target = False
        attached_foreground = False
        try:
            if target_thread and target_thread != current_thread:
                attached_target = bool(
                    self._user32.AttachThreadInput(current_thread, target_thread, True)
                )
            if (
                foreground_thread
                and foreground_thread != current_thread
                and foreground_thread != target_thread
            ):
                attached_foreground = bool(
                    self._user32.AttachThreadInput(
                        current_thread,
                        foreground_thread,
                        True,
                    )
                )

            self._user32.BringWindowToTop(hwnd)
            self._user32.SetFocus(hwnd)
            if self._user32.SetForegroundWindow(hwnd):
                return True
            return self.foreground_window() == int(hwnd.value)
        finally:
            if attached_foreground:
                self._user32.AttachThreadInput(current_thread, foreground_thread, False)
            if attached_target:
                self._user32.AttachThreadInput(current_thread, target_thread, False)

    def _window_thread_id(self, hwnd: wintypes.HWND) -> int:
        process_id = wintypes.DWORD(0)
        thread_id = self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        return int(thread_id)

    def _primary_monitor_rect(self) -> ScreenRect | None:
        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        monitor = self._user32.MonitorFromPoint(wintypes.POINT(0, 0), MONITOR_DEFAULTTOPRIMARY)
        if not monitor:
            return None

        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not self._user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None

        width = max(1, int(info.rcMonitor.right - info.rcMonitor.left))
        height = max(1, int(info.rcMonitor.bottom - info.rcMonitor.top))
        return ScreenRect(int(info.rcMonitor.left), int(info.rcMonitor.top), width, height)


def _button_flags(button: str) -> tuple[int, int]:
    if button == "left":
        return MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
    if button == "right":
        return MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP

    raise ValueError(f"Unsupported mouse button: {button}")


def _key_code(key: str) -> int:
    normalized = key.strip().lower()
    if normalized not in _KEY_CODES:
        raise ValueError(f"Unsupported shortcut key: {key}")

    return _KEY_CODES[normalized]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", _INPUTUNION),
    ]


def _keyboard_input(vk_code: int, scan_code: int, flags: int) -> _INPUT:
    item = _INPUT()
    item.type = INPUT_KEYBOARD
    item.union.ki = _KEYBDINPUT(vk_code, scan_code, flags, 0, 0)
    return item


def _utf16_code_units(character: str) -> list[int]:
    encoded = character.encode("utf-16-le")
    return [
        encoded[index] | (encoded[index + 1] << 8)
        for index in range(0, len(encoded), 2)
    ]
