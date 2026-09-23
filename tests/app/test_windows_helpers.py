from __future__ import annotations

import subprocess

import pytest

from pogled_assist.windows.appbar import (
    ABE_BOTTOM,
    ABE_LEFT,
    ABE_RIGHT,
    ABE_TOP,
    _apply_edge_size,
    _edge_rect,
)
from pogled_assist.windows.windows_input import (
    MOUSEEVENTF_LEFTDOWN,
    MOUSEEVENTF_LEFTUP,
    MOUSEEVENTF_RIGHTDOWN,
    MOUSEEVENTF_RIGHTUP,
    _button_flags,
    _key_code,
    _utf16_code_units,
)
from pogled_assist.windows.windows_startup import (
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
