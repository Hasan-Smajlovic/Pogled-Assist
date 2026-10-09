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


@pytest.mark.parametrize("program_files", ["ProgramFiles", "ProgramFiles(x86)"])
def test_core_settings_retries_executable_after_broken_shortcut(
    monkeypatch, tmp_path, program_files
):
    monkeypatch.setattr(calibration.sys, "platform", "win32")
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData", "ProgramData", "AppData"):
        monkeypatch.delenv(variable, raising=False)
    installation = tmp_path / "programs"
    core = installation / "Tobii" / "Tobii EyeX Config" / "Tobii.EyeX.Config.exe"
    core.parent.mkdir(parents=True)
    core.touch()
    (core.parent / "Updater.exe").touch()
    menu = (
        tmp_path
        / "common"
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Tobii Eye Tracking"
        / "Calibration"
    )
    menu.mkdir(parents=True)
    shortcut = menu / "Tobii EyeX Config Settings.lnk"
    shortcut.touch()
    monkeypatch.setenv(program_files, str(installation))
    monkeypatch.setenv("ProgramData", str(tmp_path / "common"))
    attempted = []

    def launch(path, _errors):
        attempted.append(path)
        return path == str(core)

    monkeypatch.setattr(calibration, "_shell_execute", launch)
    assert "zatraženo" in calibration.launch_tobii_settings()
    assert attempted == [str(shortcut), str(core)]


def test_failed_settings_targets_report_manual_route_without_calibration(monkeypatch):
    monkeypatch.setattr(calibration.sys, "platform", "win32")
    shortcut = Path("Tobii EyeX Config Settings.lnk")
    core = Path("Tobii.EyeX.Config.exe")
    monkeypatch.setattr(calibration, "_start_menu_shortcuts", lambda: [shortcut])
    monkeypatch.setattr(calibration, "_installed_tobii_executables", lambda: [core])
    attempted = []
    monkeypatch.setattr(
        calibration, "_shell_execute", lambda path, _: attempted.append(path) or False
    )

    def unexpected(*_args):
        raise AssertionError("A failed settings launch must never become a calibration")

    monkeypatch.setattr(calibration, "_send_calibration_shortcut", unexpected)
    monkeypatch.setattr(calibration, "_launch_configured_command", unexpected)
    monkeypatch.setattr(calibration, "_first_working_protocol", unexpected)
    with pytest.raises(RuntimeError, match="ikonu pored sata"):
        calibration.launch_tobii_settings()
    assert attempted == [str(shortcut), str(core)]


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
@pytest.mark.parametrize("settings_only", [True, False])
def test_settings_and_calibration_reject_maintenance_tools_before_ranking(
    monkeypatch, name, settings_only
):
    monkeypatch.setattr(calibration.sys, "platform", "win32")
    candidate = Path("C:/Program Files/Tobii/Tobii EyeX Config") / name
    monkeypatch.setattr(calibration, "_start_menu_shortcuts", lambda: [])
    monkeypatch.setattr(calibration, "_installed_tobii_executables", lambda: [candidate])
    launched = []
    monkeypatch.setattr(
        calibration, "_shell_execute", lambda path, _: launched.append(path) or True
    )
    if settings_only:
        with pytest.raises(RuntimeError, match="ikonu pored sata"):
            calibration.launch_tobii_settings()
    else:
        # A calibration fallback must not start an updater or installer either.
        # Guest is a valid target only for the explicit legacy calibration action.
        expected = candidate if name == "Guest.lnk" else None
        assert calibration._best_tobii_launch_target() == expected
    assert launched == []
