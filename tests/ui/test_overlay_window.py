from types import SimpleNamespace

import pytest
from _clock import freeze_monotonic
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from pogled_assist.ui import overlay_window
from pogled_assist.windows import windows_z_order


def test_stacking_uses_existing_clock_and_stops_work_while_hidden(qtbot, monkeypatch):
    now = freeze_monotonic(monkeypatch, 10.0)
    calls = []
    window = QWidget()
    qtbot.addWidget(window)
    monkeypatch.setattr(
        overlay_window, "force_window_topmost", lambda *a, **k: calls.append((a, k))
    )
    stacking = overlay_window.OverlayStacking(window)
    stacking.refresh_if_due()
    assert calls == []
    window.show()
    stacking.refresh(force=True)
    now[0] += 0.032
    stacking.refresh_if_due()
    assert len(calls) == 1
    now[0] += 0.002
    stacking.refresh_if_due()
    assert len(calls) == 2
    assert calls[0] == ((window,), {"show": True, "aggressive": True})
    window.hide()
    now[0] += 1
    stacking.refresh_if_due()
    assert len(calls) == 2
    stacking.reset()
    window.show()
    stacking.refresh_if_due()
    assert len(calls) == 3


def test_click_through_retries_until_applied_without_reapplying_on_reset(qtbot, monkeypatch):
    window = QWidget()
    qtbot.addWidget(window)
    calls = []
    results = iter((False, True))

    def apply(candidate):
        calls.append(candidate)
        return next(results)

    monkeypatch.setattr(overlay_window, "make_window_click_through", apply)
    stacking = overlay_window.OverlayStacking(window)
    stacking.apply_click_through()
    stacking.apply_click_through()
    stacking.reset()
    stacking.apply_click_through()
    assert calls == [window, window]


@pytest.mark.parametrize("click_through", [False, True])
def test_passive_feedback_and_interactive_overlays_keep_distinct_input_flags(click_through):
    flags = overlay_window.overlay_window_flags(click_through=click_through)
    assert flags & Qt.WindowDoesNotAcceptFocus
    assert flags & Qt.WindowStaysOnTopHint
    assert bool(flags & Qt.WindowTransparentForInput) is click_through


@pytest.mark.parametrize("pointer_bytes", [4, 8])
def test_native_click_through_preserves_existing_styles(monkeypatch, pointer_bytes):
    calls = []
    existing_style = windows_z_order.WS_EX_TOOLWINDOW

    def get_style(hwnd, index):
        assert (hwnd.value, index) == (123, windows_z_order.GWL_EXSTYLE)
        return existing_style

    def set_style(hwnd, index, style):
        calls.append((hwnd.value, index, style.value))

    api = SimpleNamespace(
        GetWindowLongW=get_style,
        SetWindowLongW=set_style,
        GetWindowLongPtrW=get_style,
        SetWindowLongPtrW=set_style,
    )
    native_types = windows_z_order.ctypes
    monkeypatch.setattr(windows_z_order, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(
        windows_z_order,
        "ctypes",
        SimpleNamespace(
            sizeof=lambda _: pointer_bytes,
            c_void_p=native_types.c_void_p,
            c_long=native_types.c_long,
            c_longlong=native_types.c_longlong,
        ),
    )
    monkeypatch.setattr(windows_z_order, "_load_user32", lambda: api)
    assert windows_z_order.make_window_click_through(SimpleNamespace(winId=lambda: 123))
    expected = existing_style | 0x00080000 | 0x00000020 | 0x08000000
    assert calls == [(123, -20, expected)]
