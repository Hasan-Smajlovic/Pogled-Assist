from __future__ import annotations

import ctypes
import os
from pathlib import Path

import pytest

from pogled_assist.tracking import tobii_stream_engine_bridge_backend as bridge_backend
from pogled_assist.tracking.tobii_calibration import _looks_like_uri, _target_score, _unique_paths
from pogled_assist.tracking.tobii_stream_engine import (
    APP_ROOT_ENV,
    _decode_char_array,
    _device_create_arg_counts,
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


def test_stream_engine_candidates_use_packaged_app_root(monkeypatch, tmp_path):
    bundled_dll = tmp_path / "tools" / "tobii" / "tobii_stream_engine.dll"
    bundled_dll.parent.mkdir(parents=True)
    bundled_dll.touch()
    monkeypatch.delenv("TOBII_STREAM_ENGINE_DLL", raising=False)
    monkeypatch.setenv(APP_ROOT_ENV, str(tmp_path))

    assert bundled_dll in _stream_engine_candidates()


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


def test_bridge_python_discovery_reports_missing_runtime(monkeypatch):
    monkeypatch.delenv(bridge_backend.X86_PYTHON_ENV, raising=False)
    monkeypatch.setattr(bridge_backend, "_py_launcher_candidates", lambda: ["launcher-python"])
    monkeypatch.setattr(bridge_backend, "_common_python_candidates", lambda: ["common-python"])
    monkeypatch.setattr(bridge_backend, "_is_x86_python", lambda _candidate: False)

    with pytest.raises(bridge_backend.TobiiStreamEngineBridgeError, match=r"32-bit Python 3\.10"):
        bridge_backend._find_x86_python()
