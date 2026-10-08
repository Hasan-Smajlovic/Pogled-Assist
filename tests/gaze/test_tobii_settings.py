from __future__ import annotations

from pathlib import Path

import pytest

from pogled_assist.tracking import tobii_calibration as calibration


def test_settings_launch_opens_core_without_guest_or_operator_calibration(monkeypatch):
    monkeypatch.setattr(calibration.sys, "platform", "win32")
    core = Path("Tobii.EyeX.Config.exe")
    monkeypatch.setattr(calibration, "_start_menu_shortcuts", lambda: [])
    monkeypatch.setattr(
        calibration, "_installed_tobii_executables", lambda: [Path("Calibration.exe"), core]
    )
    monkeypatch.setenv("TOBII_CALIBRATION_COMMAND", "operator guest command")
    launched = []
    monkeypatch.setattr(
        calibration, "_shell_execute", lambda path, _: launched.append(path) or True
    )

    def unexpected(*_args):
        raise AssertionError("Settings must not trigger Guest calibration")

    monkeypatch.setattr(calibration, "_send_calibration_shortcut", unexpected)
    monkeypatch.setattr(calibration, "_launch_configured_command", unexpected)
    assert "zatraženo" in calibration.launch_tobii_settings()
    assert launched == [str(core)]


def test_missing_settings_reports_manual_route_without_guest_fallback(monkeypatch):
    monkeypatch.setattr(calibration.sys, "platform", "win32")
    monkeypatch.setattr(
        calibration, "_start_menu_shortcuts", lambda: [Path("Guest calibration.lnk")]
    )
    monkeypatch.setattr(calibration, "_installed_tobii_executables", lambda: [])
    with pytest.raises(RuntimeError, match="ikonu pored sata"):
        calibration.launch_tobii_settings()


@pytest.mark.parametrize(
    "name",
    [
        "unins000.exe",
        "Updater.exe",
        "Tobii.Service.exe",
        "Uninstall.lnk",
        "Guest.lnk",
        "Tobii.Installation.exe",
        "Setup.exe",
        "Repair.lnk",
    ],
)
def test_settings_never_launches_maintenance_tools_from_a_high_ranked_folder(monkeypatch, name):
    monkeypatch.setattr(calibration.sys, "platform", "win32")
    candidate = Path("C:/Program Files/Tobii/Tobii EyeX Config") / name
    monkeypatch.setattr(calibration, "_start_menu_shortcuts", lambda: [])
    monkeypatch.setattr(calibration, "_installed_tobii_executables", lambda: [candidate])
    launched = []
    monkeypatch.setattr(
        calibration, "_shell_execute", lambda path, _: launched.append(path) or True
    )
    with pytest.raises(RuntimeError, match="ikonu pored sata"):
        calibration.launch_tobii_settings()
    assert launched == []
