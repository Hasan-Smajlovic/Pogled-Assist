from __future__ import annotations

from pathlib import Path

import pytest

from pogled_assist.tracking import tobii_calibration as calibration


@pytest.fixture(autouse=True)
def no_installed_experience(monkeypatch):
    query = calibration._experience_is_installed
    monkeypatch.setattr(calibration, "_experience_is_installed", lambda: False)
    return query


@pytest.mark.parametrize("guest", [False, True])
@pytest.mark.parametrize("with_core", [False, True])
def test_eye_tracker_5_activates_experience_without_guest_shortcut(monkeypatch, guest, with_core):
    monkeypatch.setattr(calibration.sys, "platform", "win32")
    monkeypatch.setattr(calibration, "_experience_is_installed", lambda: True)
    monkeypatch.setattr(calibration, "_start_menu_shortcuts", lambda: [])
    core = Path("Tobii.EyeX.Config.exe")
    monkeypatch.setattr(
        calibration, "_installed_tobii_executables", lambda: [core] if with_core else []
    )
    monkeypatch.setattr(calibration.time, "sleep", lambda *_: None)
    monkeypatch.delenv(calibration.CALIBRATION_COMMAND_ENV, raising=False)
    launches = []
    monkeypatch.setattr(
        calibration, "_shell_execute", lambda target, _: launches.append(target) or True
    )
    monkeypatch.setattr(
        calibration,
        "_send_calibration_shortcut",
        lambda *_: pytest.fail("Experience must never receive the Core Guest shortcut"),
    )
    launch = (
        calibration.launch_tobii_guest_calibration if guest else calibration.launch_tobii_settings
    )
    assert "zatraženo" in launch(device_model="IS5_Large_Eyetracker_5")
    assert launches == [calibration.EXPERIENCE_TARGET]


def test_core_stays_first_when_experience_is_also_installed(monkeypatch):
    monkeypatch.setattr(calibration, "_experience_is_installed", lambda: True)
    monkeypatch.setattr(calibration, "_start_menu_shortcuts", lambda: [])
    core = Path("Tobii.EyeX.Config.exe")
    monkeypatch.setattr(calibration, "_installed_tobii_executables", lambda: [core])
    launches = []
    monkeypatch.setattr(
        calibration, "_shell_execute", lambda target, _: launches.append(target) or True
    )
    calibration.launch_tobii_settings(device_model="Tobii Eye Tracker 4C")
    assert launches == [str(core)]


@pytest.mark.parametrize("model", ["", "Tobii Eye Tracker 4C", "IS5_Large_Eyetracker_5"])
@pytest.mark.parametrize("name", ["TobiiExperience.exe", "Tobii Experience.lnk"])
def test_experience_file_target_never_sends_core_guest_shortcut(monkeypatch, model, name):
    monkeypatch.setattr(calibration.sys, "platform", "win32")
    target = Path(name)
    monkeypatch.setattr(calibration, "_start_menu_shortcuts", lambda: [target])
    monkeypatch.setattr(calibration, "_installed_tobii_executables", lambda: [])
    monkeypatch.delenv(calibration.CALIBRATION_COMMAND_ENV, raising=False)
    monkeypatch.setattr(calibration.time, "sleep", lambda *_: None)
    launches = []
    monkeypatch.setattr(
        calibration, "_shell_execute", lambda path, _: launches.append(path) or True
    )
    monkeypatch.setattr(
        calibration,
        "_send_calibration_shortcut",
        lambda *_: pytest.fail("Experience must never receive the Core Guest shortcut"),
    )
    monkeypatch.setattr(
        calibration, "_first_working_protocol", lambda *_: pytest.fail("Experience was found")
    )
    assert "postavki" in calibration.launch_tobii_guest_calibration(device_model=model)
    assert launches == [str(target)]


def test_failed_experience_activation_does_not_open_incompatible_core(monkeypatch):
    monkeypatch.setattr(calibration, "_experience_is_installed", lambda: True)
    monkeypatch.setattr(calibration, "_start_menu_shortcuts", lambda: [])
    core = Path("Tobii.EyeX.Config.exe")
    monkeypatch.setattr(calibration, "_installed_tobii_executables", lambda: [core])
    launches = []
    monkeypatch.setattr(
        calibration,
        "_shell_execute",
        lambda target, _: launches.append(target) or target == str(core),
    )
    with pytest.raises(RuntimeError, match="ikonu pored sata"):
        calibration.launch_tobii_settings(device_model="IS5_Large_Eyetracker_5")
    assert launches == [calibration.EXPERIENCE_TARGET]


def test_missing_experience_never_sends_core_shortcut_for_eye_tracker_5(monkeypatch):
    monkeypatch.setattr(calibration, "_start_menu_shortcuts", lambda: [])
    monkeypatch.setattr(calibration, "_installed_tobii_executables", lambda: [])
    monkeypatch.setattr(
        calibration, "_first_working_protocol", lambda *_: pytest.fail("No Core protocol for ET5")
    )
    monkeypatch.setattr(
        calibration,
        "_send_calibration_shortcut",
        lambda *_: pytest.fail("No Guest shortcut for ET5"),
    )
    with pytest.raises(RuntimeError, match="Experience"):
        calibration.launch_tobii_guest_calibration(device_model="IS5_Large_Eyetracker_5")


@pytest.mark.parametrize("status,count,expected", [(122, 1, True), (0, 0, False), (5, 1, False)])
def test_experience_package_query_requires_success_and_a_registered_package(
    monkeypatch, no_installed_experience, status, count, expected
):
    import ctypes
    from types import SimpleNamespace

    class Query:
        def __call__(self, family, count_ptr, names, _length_ptr, buffer):
            assert family == calibration.EXPERIENCE_FAMILY
            assert names is None and buffer is None
            ctypes.cast(count_ptr, ctypes.POINTER(ctypes.c_uint32)).contents.value = count
            return status

    query = Query()
    monkeypatch.setattr(calibration.sys, "platform", "win32")
    monkeypatch.setattr(
        calibration.ctypes,
        "WinDLL",
        lambda *_args, **_kwargs: SimpleNamespace(GetPackagesByPackageFamily=query),
        raising=False,
    )
    assert no_installed_experience() is expected


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
