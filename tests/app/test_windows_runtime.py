from __future__ import annotations

import pytest

from pogled_assist.windows import windows_keyboard, windows_startup


def test_windows_keyboard_candidates_and_fallback(monkeypatch):
    monkeypatch.setattr(windows_keyboard.sys, "platform", "win32")
    attempts = []

    def shell_execute(target):
        attempts.append(target)
        if len(attempts) == 1:
            raise windows_keyboard.WindowsKeyboardError("blocked")

    monkeypatch.setattr(windows_keyboard, "_shell_execute", shell_execute)

    label = windows_keyboard.open_windows_keyboard()

    assert label == "Windows on-screen keyboard"
    assert len(attempts) == 2
    targets = [target.lower() for _label, target in windows_keyboard._keyboard_candidates()]
    assert len(targets) == len(set(targets))


def test_windows_keyboard_rejects_other_platforms(monkeypatch):
    monkeypatch.setattr(windows_keyboard.sys, "platform", "linux")
    with pytest.raises(windows_keyboard.WindowsKeyboardError, match="only available on Windows"):
        windows_keyboard.open_windows_keyboard()


def test_frozen_startup_launcher_is_next_to_executable(monkeypatch, tmp_path):
    executable = tmp_path / "PogledAssist.exe"
    monkeypatch.setattr(windows_startup.sys, "frozen", True, raising=False)
    monkeypatch.setattr(windows_startup.sys, "executable", str(executable))

    assert windows_startup.launcher_script_path() == tmp_path / "start_gaze_mouse.ps1"
