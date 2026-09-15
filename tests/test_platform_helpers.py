from __future__ import annotations

import ctypes
import os
import subprocess
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QRect

from gaze_mouse.appbar import (
    ABE_BOTTOM,
    ABE_LEFT,
    ABE_RIGHT,
    ABE_TOP,
    _apply_edge_size,
    _edge_rect,
)
from gaze_mouse.interaction_overlay import _compact_label
from gaze_mouse.quick_action_menu import CANCEL_QUICK_ACTION, QuickActionRadialMenu
from gaze_mouse.quick_action_zoom import _centered_square, _square_around
from gaze_mouse.tobii_calibration import _looks_like_uri, _target_score, _unique_paths
from gaze_mouse.tobii_stream_engine import (
    _decode_char_array,
    _device_create_arg_counts,
    _stream_engine_candidates,
)
from gaze_mouse.tobii_stream_engine_bridge_backend import _prepend_pythonpath
from gaze_mouse.toolbar import _tracker_dot_state
from gaze_mouse.windows_input import (
    MOUSEEVENTF_LEFTDOWN,
    MOUSEEVENTF_LEFTUP,
    MOUSEEVENTF_RIGHTDOWN,
    MOUSEEVENTF_RIGHTUP,
    _button_flags,
    _key_code,
    _utf16_code_units,
)
from gaze_mouse.windows_startup import (
    _completed_output,
    _disable_script,
    _enable_script,
    _ps_quote,
)


class Rect:
    def __init__(self, left, top, right, bottom):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom

    def values(self):
        return self.left, self.top, self.right, self.bottom


@pytest.mark.parametrize(
    ("edge", "expected"),
    [
        (ABE_LEFT, (10, 20, 40, 220)),
        (ABE_RIGHT, (280, 20, 310, 220)),
        (ABE_TOP, (10, 20, 310, 50)),
        (ABE_BOTTOM, (10, 190, 310, 220)),
    ],
)
def test_appbar_edge_rects(edge, expected):
    monitor = Rect(10, 20, 310, 220)
    assert _edge_rect(Rect, monitor, edge, 30).values() == expected


@pytest.mark.parametrize("edge", [ABE_LEFT, ABE_RIGHT, ABE_TOP, ABE_BOTTOM])
def test_appbar_applies_shell_adjusted_edge_size(edge):
    rect = Rect(10, 20, 310, 220)
    _apply_edge_size(rect, edge, 25)
    if edge == ABE_LEFT:
        assert rect.right == 35
    elif edge == ABE_RIGHT:
        assert rect.left == 285
    elif edge == ABE_BOTTOM:
        assert rect.top == 195
    else:
        assert rect.bottom == 45


def test_zoom_squares_stay_inside_screen_bounds():
    bounds = QRect(100, 200, 800, 600)

    assert _square_around(QPoint(100, 200), 180, bounds) == QRect(100, 200, 180, 180)
    assert _square_around(QPoint(899, 799), 180, bounds) == QRect(720, 620, 180, 180)
    assert _centered_square(bounds, 540) == QRect(130, 30, 540, 540)


def test_radial_menu_maps_each_direction_to_an_action(qapp):
    menu = QuickActionRadialMenu()
    menu._center_global = QPoint(500, 500)

    assert menu._action_for_global_point(QPoint(500, 300)) == "left_click"
    assert menu._action_for_global_point(QPoint(700, 500)) == "right_click"
    assert menu._action_for_global_point(QPoint(500, 700)) == "double_left_click"
    assert menu._action_for_global_point(QPoint(300, 500)) == CANCEL_QUICK_ACTION
    assert menu._action_for_global_point(QPoint(500, 500)) is None
    assert menu._action_for_global_point(QPoint(500, 500), allow_center=True) == CANCEL_QUICK_ACTION


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Double click", "Double click"),
        ("Double left click", "Double left c"),
        ("Quick action", "Quick action"),
        ("Zoom target", "Zoom target"),
        ("Settings", "Settings"),
    ],
)
def test_interaction_labels_are_compact(label, expected):
    assert _compact_label(label) == expected


def test_windows_input_helpers_validate_buttons_keys_and_unicode():
    assert _button_flags("left") == (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)
    assert _button_flags("right") == (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP)
    assert _key_code(" ENTER ") == 0x0D
    assert _utf16_code_units("A") == [0x41]
    assert _utf16_code_units("😀") == [0xD83D, 0xDE00]
    with pytest.raises(ValueError):
        _button_flags("middle")
    with pytest.raises(ValueError):
        _key_code("unknown")


def test_startup_scripts_quote_paths_and_select_window_style(tmp_path):
    launcher = tmp_path / "Hasan's app" / "start.ps1"
    hidden = _enable_script(launcher, show_launcher_window=False)
    visible = _enable_script(launcher, show_launcher_window=True)

    assert _ps_quote("Hasan's") == "'Hasan''s'"
    assert "-WindowStyle Hidden -NoProfile" in hidden
    assert "-WindowStyle Hidden" not in visible
    assert "Hasan''s app" in hidden
    assert "Unregister-ScheduledTask" in _disable_script()


def test_completed_output_combines_stdout_and_stderr():
    completed = subprocess.CompletedProcess([], 1, stdout=" out \n", stderr=" err \n")
    assert _completed_output(completed) == "out\nerr"


def test_tobii_target_scoring_prefers_config_ui_and_rejects_services():
    calibration = Path("Tobii Eye Tracking/Calibration/Tobii.EyeX.Config.exe")
    service = Path("Tobii/Service/Tobii.Service.exe")

    assert _target_score(calibration) > _target_score(service)
    assert _looks_like_uri("tobii://calibration") is True
    assert _looks_like_uri("ms-settings:display") is True
    assert _looks_like_uri("C:/Tobii/app.exe") is False
    assert _unique_paths([Path("A/Test.exe"), Path("a/test.exe")]) == [Path("A/Test.exe")]


def test_stream_engine_candidates_honor_configured_path(monkeypatch, tmp_path):
    configured = tmp_path / "sdk"
    configured.mkdir()
    first = configured / "tobii_stream_engine.dll"
    second = configured / "StreamEngineClient.dll"
    first.touch()
    second.touch()
    monkeypatch.setenv("TOBII_STREAM_ENGINE_DLL", str(configured))

    candidates = _stream_engine_candidates()

    assert candidates[:2] == [first, second]


def test_stream_engine_argument_order_and_decode(monkeypatch):
    monkeypatch.delenv("TOBII_STREAM_ENGINE_DEVICE_CREATE_ARGS", raising=False)
    assert _device_create_arg_counts() == ["4", "3"]
    monkeypatch.setenv("TOBII_STREAM_ENGINE_DEVICE_CREATE_ARGS", "3")
    assert _device_create_arg_counts() == ["3"]

    value = (ctypes.c_char * 8)(*b"Tobii\0\0\0")
    assert _decode_char_array(value) == "Tobii"


def test_bridge_pythonpath_prepends_project_path():
    assert _prepend_pythonpath("project", "") == "project"
    assert _prepend_pythonpath("project", "existing") == f"project{os.pathsep}existing"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("Tracking with Tobii Eye Tracker 4C.", "green"),
        ("Trying Stream Engine.", "yellow"),
        ("Tracker not found", "red"),
        ("idle", "yellow"),
    ],
)
def test_tracker_dot_state(status, expected):
    assert _tracker_dot_state(status) == expected
