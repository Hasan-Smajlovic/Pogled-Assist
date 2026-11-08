from __future__ import annotations

import ctypes
import os
from pathlib import Path

import pytest

from pogled_assist.tracking import tobii_calibration
from pogled_assist.tracking import tobii_stream_engine_bridge_backend as bridge_backend
from pogled_assist.tracking.tobii_calibration import (
    EXPERIENCE_TARGET,
    _looks_like_uri,
    _target_score,
    _unique_paths,
)
from pogled_assist.tracking.tobii_stream_engine import (
    APP_ROOT_ENV,
    _decode_char_array,
    _device_create_arg_count,
    _stream_engine_candidates,
)
from pogled_assist.tracking.tobii_stream_engine_bridge_backend import _prepend_pythonpath


def test_tobii_target_scoring_prefers_config_ui_and_rejects_services():
    calibration = Path("Tobii Eye Tracking/Calibration/Tobii.EyeX.Config.exe")
    service = Path("Tobii/Service/Tobii.Service.exe")

    assert _target_score(calibration) > _target_score(service)
    assert _looks_like_uri("tobii://calibration") is True
    assert _looks_like_uri("ms-settings:display") is True
    assert _looks_like_uri("C:/Tobii/app.exe") is False
    assert _looks_like_uri(EXPERIENCE_TARGET) is True
    assert _unique_paths([Path("A/Test.exe"), Path("a/test.exe")]) == [Path("A/Test.exe")]


def test_ranked_targets_skip_headless_tobii_executables(monkeypatch):
    headless = Path("Tobii/Experience/Tobii.Experience.Headless.exe")
    experience = Path("Tobii/Experience/TobiiExperience.exe")
    monkeypatch.setattr(tobii_calibration, "_start_menu_shortcuts", lambda: [])
    monkeypatch.setattr(
        tobii_calibration, "_installed_tobii_executables", lambda: [headless, experience]
    )
    assert tobii_calibration._ranked_tobii_launch_targets() == [experience]


@pytest.mark.parametrize(
    "target,working_dir",
    [(EXPERIENCE_TARGET, None), ("C:/Tobii/TobiiExperience.exe", str(Path("C:/Tobii")))],
)
def test_shell_targets_open_without_a_working_directory(monkeypatch, target, working_dir):
    calls = []

    def shell_execute(*args):
        calls.append(args)
        return 42

    shell32 = type("Shell32", (), {"ShellExecuteW": staticmethod(shell_execute)})
    monkeypatch.setattr(ctypes, "windll", type("WinDll", (), {"shell32": shell32}), raising=False)
    assert tobii_calibration._shell_execute(target, []) is True
    assert calls[0][2:5] == (target, None, working_dir)


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


def test_stream_engine_candidates_use_packaged_app_root(monkeypatch, tmp_path):
    bundled_dll = tmp_path / "tools" / "tobii" / "tobii_stream_engine.dll"
    bundled_dll.parent.mkdir(parents=True)
    bundled_dll.touch()
    monkeypatch.delenv("TOBII_STREAM_ENGINE_DLL", raising=False)
    monkeypatch.setenv(APP_ROOT_ENV, str(tmp_path))

    assert bundled_dll in _stream_engine_candidates()


def test_stream_engine_argument_order_and_decode(monkeypatch):
    monkeypatch.delenv("TOBII_STREAM_ENGINE_DEVICE_CREATE_ARGS", raising=False)
    assert _device_create_arg_count((4, 25, 0, 3)) == 4
    assert _device_create_arg_count((1, 1, 1, 1741)) == 3
    monkeypatch.setenv("TOBII_STREAM_ENGINE_DEVICE_CREATE_ARGS", "3")
    assert _device_create_arg_count() == 3

    value = (ctypes.c_char * 8)(*b"Tobii\0\0\0")
    assert _decode_char_array(value) == "Tobii"


def test_bridge_pythonpath_prepends_project_path():
    assert _prepend_pythonpath("project", "") == "project"
    assert _prepend_pythonpath("project", "existing") == f"project{os.pathsep}existing"


def test_bridge_python_discovery_prefers_configured_runtime(monkeypatch, tmp_path):
    configured = tmp_path / "python.exe"
    configured.touch()
    monkeypatch.setenv(bridge_backend.X86_PYTHON_ENV, str(configured))
    monkeypatch.setattr(bridge_backend, "_py_launcher_candidates", lambda: ["launcher-python"])
    monkeypatch.setattr(bridge_backend, "_common_python_candidates", lambda: ["common-python"])
    checked = []
    monkeypatch.setattr(
        bridge_backend,
        "_is_x86_python",
        lambda candidate: checked.append(candidate) or candidate == str(configured),
    )

    assert bridge_backend._find_x86_python() == str(configured)
    assert checked == [str(configured)]


@pytest.mark.parametrize(
    ("new_runtime", "valid_runtimes", "expected"),
    [
        ("", {"legacy-python"}, "legacy-python"),
        ("new-python", {"new-python", "legacy-python"}, "new-python"),
        ("invalid-new", {"legacy-python"}, "legacy-python"),
    ],
)
def test_bridge_python_discovery_accepts_old_custom_path(
    monkeypatch, new_runtime, valid_runtimes, expected
):
    monkeypatch.setenv("POGLED_ASSIST_X86_PYTHON", new_runtime)
    monkeypatch.setenv("TOBII_GAZE_MOUSE_X86_PYTHON", "legacy-python")
    monkeypatch.setattr(bridge_backend, "_py_launcher_candidates", lambda: [])
    monkeypatch.setattr(bridge_backend, "_common_python_candidates", lambda: [])
    monkeypatch.setattr(
        bridge_backend, "_is_x86_python", lambda candidate: candidate in valid_runtimes
    )

    assert bridge_backend._find_x86_python() == expected


def test_bridge_python_discovery_skips_invalid_old_custom_path(monkeypatch):
    monkeypatch.delenv(bridge_backend.X86_PYTHON_ENV, raising=False)
    monkeypatch.setenv(bridge_backend.LEGACY_X86_PYTHON_ENV, "invalid-legacy")
    monkeypatch.setattr(bridge_backend, "_py_launcher_candidates", lambda: ["launcher-python"])
    monkeypatch.setattr(bridge_backend, "_common_python_candidates", lambda: [])
    monkeypatch.setattr(
        bridge_backend, "_is_x86_python", lambda candidate: candidate == "launcher-python"
    )

    assert bridge_backend._find_x86_python() == "launcher-python"


def test_bridge_python_discovery_reports_missing_runtime(monkeypatch):
    monkeypatch.delenv(bridge_backend.X86_PYTHON_ENV, raising=False)
    monkeypatch.delenv("TOBII_GAZE_MOUSE_X86_PYTHON", raising=False)
    monkeypatch.setattr(bridge_backend, "_py_launcher_candidates", lambda: ["launcher-python"])
    monkeypatch.setattr(bridge_backend, "_common_python_candidates", lambda: ["common-python"])
    monkeypatch.setattr(bridge_backend, "_is_x86_python", lambda _candidate: False)

    with pytest.raises(bridge_backend.TobiiStreamEngineBridgeError, match=r"32-bit Python 3\.10"):
        bridge_backend._find_x86_python()
