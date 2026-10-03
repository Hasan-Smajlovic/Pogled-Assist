from __future__ import annotations

from ctypes import wintypes
from types import SimpleNamespace

import pytest

from pogled_assist.windows import appbar
from pogled_assist.windows.windows_input import WindowsInputController


class FakeShell:
    def __init__(self):
        self.calls = []
        self.accept_registration = True

    def SHAppBarMessage(self, message, pointer):
        data = pointer._obj
        self.calls.append((message, data.hWnd))
        if message == appbar.ABM_NEW:
            return int(self.accept_registration)
        if message == appbar.ABM_QUERYPOS:
            data.rc.top = 30
        if message == appbar.ABM_SETPOS:
            self.position = (data.rc.left, data.rc.top, data.rc.right, data.rc.bottom)
        return 1


@pytest.fixture
def shell_boundary(monkeypatch):
    ctypes_module, rect, data = appbar._win_types()
    shell = FakeShell()
    boundary = SimpleNamespace(
        sizeof=ctypes_module.sizeof,
        byref=ctypes_module.byref,
        windll=SimpleNamespace(shell32=shell),
    )
    monkeypatch.setattr(appbar, "_win_types", lambda: (boundary, rect, data))
    monkeypatch.setattr(appbar, "_monitor_rect_for_window", lambda _hwnd: rect(0, 0, 1920, 1080))
    monkeypatch.setattr(appbar, "_dpi_for_window", lambda _hwnd: 144)
    monkeypatch.setattr(appbar.WindowsAppBar, "supported", property(lambda _self: True))
    return shell


def test_appbar_keeps_shell_position_and_converts_logical_height(shell_boundary):
    bar = appbar.WindowsAppBar()

    assert bar.register(40, 76)
    assert shell_boundary.calls == [
        (appbar.ABM_NEW, 40),
        (appbar.ABM_QUERYPOS, 40),
        (appbar.ABM_SETPOS, 40),
    ]
    assert shell_boundary.position == (0, 30, 1920, 144)


def test_appbar_releases_old_reservation_before_replacing_it(shell_boundary):
    bar = appbar.WindowsAppBar()
    assert bar.register(40, 76)
    shell_boundary.calls.clear()

    assert bar.register(50, 76)
    bar.unregister()
    bar.unregister()

    assert shell_boundary.calls == [
        (appbar.ABM_REMOVE, 40),
        (appbar.ABM_NEW, 50),
        (appbar.ABM_QUERYPOS, 50),
        (appbar.ABM_SETPOS, 50),
        (appbar.ABM_REMOVE, 50),
    ]
    assert bar._hwnd is None
    assert not bar._registered


def test_appbar_failed_registration_does_not_position_or_remove(shell_boundary):
    shell_boundary.accept_registration = False
    bar = appbar.WindowsAppBar()

    assert not bar.register(40, 76)
    bar.set_position(76)
    bar.unregister()

    assert shell_boundary.calls == [(appbar.ABM_NEW, 40)]
    assert bar._hwnd is None
    assert not bar._registered


class FakeFocusApi:
    def __init__(self):
        self.links = []
        self.threads = {100: 30, 200: 20}
        self.foreground = 100
        self.attach_results = {20: True, 30: True}
        self.raise_on_focus = False
        self.accept_foreground = True

    def GetForegroundWindow(self):
        return self.foreground

    def GetWindowThreadProcessId(self, hwnd, _process):
        return self.threads.get(hwnd.value, 0)

    def AttachThreadInput(self, current, target, attach):
        self.links.append((current, target, attach))
        return self.attach_results[target]

    def BringWindowToTop(self, _hwnd):
        return True

    def SetFocus(self, _hwnd):
        if self.raise_on_focus:
            raise OSError("focus failed")
        return 0

    def SetForegroundWindow(self, _hwnd):
        return self.accept_foreground


@pytest.fixture
def focus_boundary():
    controller = object.__new__(WindowsInputController)
    api = FakeFocusApi()
    controller._user32 = api
    controller._kernel32 = SimpleNamespace(GetCurrentThreadId=lambda: 10)
    return controller, api


@pytest.mark.parametrize("raises", [False, True])
def test_foreground_focus_releases_links_on_success_and_exception(focus_boundary, raises):
    controller, api = focus_boundary
    api.raise_on_focus = raises

    if raises:
        with pytest.raises(OSError, match="focus failed"):
            controller._force_foreground_window(wintypes.HWND(200))
    else:
        assert controller._force_foreground_window(wintypes.HWND(200))

    assert api.links == [
        (10, 20, True),
        (10, 30, True),
        (10, 30, False),
        (10, 20, False),
    ]


def test_foreground_focus_releases_only_successful_links(focus_boundary):
    controller, api = focus_boundary
    api.attach_results[20] = False
    api.accept_foreground = False

    assert not controller._force_foreground_window(wintypes.HWND(200))
    assert api.links == [(10, 20, True), (10, 30, True), (10, 30, False)]


@pytest.mark.parametrize("target_thread", [10, 30])
def test_foreground_focus_never_attaches_the_same_thread_twice(focus_boundary, target_thread):
    controller, api = focus_boundary
    api.threads[200] = target_thread

    assert controller._force_foreground_window(wintypes.HWND(200))
    expected_thread = 30 if target_thread == 10 else target_thread
    assert api.links == [(10, expected_thread, True), (10, expected_thread, False)]
