from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest

from pogled_assist import installation_check
from pogled_assist.tracking import tobii_stream_engine_bridge_backend as bridge
from scripts.release import prepare_speech_bundle as bundler


def test_bundle_python_is_preferred_to_system_python(monkeypatch, tmp_path):
    monkeypatch.setenv(bridge.APP_ROOT_ENV, str(tmp_path))
    monkeypatch.delenv(bridge.X86_PYTHON_ENV, raising=False)
    monkeypatch.delenv(bridge.LEGACY_X86_PYTHON_ENV, raising=False)
    monkeypatch.setattr(bridge, "_py_launcher_candidates", lambda: ["external"])
    expected = tmp_path / "runtime/python-x86/python.exe"
    monkeypatch.setattr(bridge, "_is_x86_python", lambda candidate: candidate == str(expected))
    assert bridge._find_x86_python() == str(expected)


def test_embedded_python_uses_relative_isolated_bridge_sources(monkeypatch, tmp_path):
    archive = tmp_path / "python.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("python.exe", "placeholder")
        bundle.writestr("python310._pth", "old")
    monkeypatch.setattr(bundler, "checked_download", lambda *args: archive)
    destination = tmp_path / "release/runtime/python-x86"
    bundler.prepare_bridge_bundle(destination, tmp_path / "cache")
    assert (destination / "python310._pth").read_text().splitlines() == [
        "python310.zip",
        ".",
        "../../_internal",
    ]
    assert (destination / "../../_internal").resolve() == tmp_path / "release/_internal"


def test_embedded_python_rejects_archive_escape(monkeypatch, tmp_path):
    archive = tmp_path / "python.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../outside.txt", "unexpected")
    monkeypatch.setattr(bundler, "checked_download", lambda *args: archive)
    with pytest.raises(ValueError, match="unsafe path"):
        bundler.prepare_bridge_bundle(tmp_path / "runtime", tmp_path / "cache")
    assert not (tmp_path / "outside.txt").exists()


@pytest.mark.parametrize(
    "device_json, state",
    [
        ("[]", "Nije prepoznat"),
        ('[{"FriendlyName":"Tobii 4C","Status":"OK"}]', "Prepoznat"),
        ('[{"FriendlyName":"Tobii 4C","Status":"Error"}]', "Potrebna provjera"),
    ],
)
def test_device_status_reports_presence_without_claiming_tracking(monkeypatch, device_json, state):
    monkeypatch.setattr(
        installation_check.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, device_json, ""),
    )
    assert installation_check.check_tobii_device().state == state


def test_failed_diagnostics_are_not_reported_as_missing_device(monkeypatch, tmp_path):
    def failed(*args):
        raise OSError("probe failed")

    monkeypatch.setattr(installation_check, "verify_bundled_speech", lambda root: None)
    monkeypatch.setattr(installation_check, "verify_bundled_bridge", failed)
    monkeypatch.setattr(installation_check, "_best_tobii_launch_target", lambda: None)
    monkeypatch.setattr(installation_check, "_stream_engine_candidates", lambda: [])
    monkeypatch.setattr(installation_check, "check_tobii_device", failed)
    result = {item.key: item for item in installation_check.check_installation(tmp_path)}
    assert result["speech"].state == "Spremno"
    assert result["bridge"].state == "Nije spremno"
    assert result["software"].state == "Potrebna instalacija"
    assert result["device"].state == "Nije provjereno"
    assert result["calibration"].state == "Potrebna provjera"


def test_bridge_smoke_checks_the_bundled_interpreter_and_entrypoint(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(bridge.subprocess, "run", lambda *args, **kwargs: calls.append(args[0]))
    bridge.verify_bundled_bridge(tmp_path)
    assert Path(calls[0][0]) == tmp_path / "runtime/python-x86/python.exe"
    assert calls[0][1:3] == ["-I", "-B"]
    assert calls[0][-1] == "--check"
