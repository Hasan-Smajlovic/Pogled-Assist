from __future__ import annotations

import hashlib
import io
import subprocess
import wave
from pathlib import Path

import pytest

import pogled_assist.main as main_module
from pogled_assist.speech import bundle_check, speech_service
from scripts.release import prepare_speech_bundle as bundler


def test_bundle_discovery_precedes_external_tools_but_keeps_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv(speech_service.APP_ROOT_ENV, str(tmp_path))
    monkeypatch.setenv("ESPEAK_NG_EXE", str(tmp_path / "override-espeak.exe"))
    monkeypatch.setenv("EDGE_PLAYBACK_EXE", str(tmp_path / "override-edge.exe"))
    monkeypatch.setattr(speech_service.shutil, "which", lambda _: str(tmp_path / "external.exe"))

    assert speech_service._candidate_paths()[:3] == [
        tmp_path / "override-espeak.exe",
        tmp_path / "speech/espeak-ng/espeak-ng.exe",
        tmp_path / "external.exe",
    ]
    assert speech_service._edge_playback_candidate_paths()[:3] == [
        tmp_path / "override-edge.exe",
        tmp_path / "speech/edge/edge-playback.exe",
        tmp_path / "external.exe",
    ]


def _write_wave(command):
    if "-w" in command:
        with wave.open(command[command.index("-w") + 1], "wb") as audio:
            audio.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
            audio.writeframes(b"\0\0" * 100)


def test_bundle_check_uses_local_bosnian_synthesis_and_both_edge_tools(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("ESPEAK_DATA_PATH", str(tmp_path / "external-data"))

    def run(command, **options):
        calls.append((command, options))
        _write_wave(command)

    monkeypatch.setattr(bundle_check.subprocess, "run", run)
    bundle_check.verify_bundled_speech(tmp_path)

    assert [Path(command[0]).name for command, _ in calls] == [
        "espeak-ng.exe",
        "edge-tts.exe",
        "edge-playback.exe",
    ]
    assert calls[0][0][1:3] == ["-v", "bs"]
    for command, options in calls:
        assert Path(command[0]).is_relative_to(tmp_path / "speech")
        assert "ESPEAK_DATA_PATH" not in options["env"]
        assert options["check"] is True
        assert options["timeout"] == 15
    assert all(command[1:] == ["--help"] for command, _ in calls[1:])


@pytest.mark.parametrize("failed_tool", ["espeak-ng.exe", "edge-tts.exe", "edge-playback.exe"])
def test_bundle_check_rejects_a_broken_tool(monkeypatch, tmp_path, failed_tool):
    def run(command, **_options):
        if Path(command[0]).name == failed_tool:
            raise subprocess.CalledProcessError(1, command)
        _write_wave(command)

    monkeypatch.setattr(bundle_check.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        bundle_check.verify_bundled_speech(tmp_path)


def test_bundle_check_rejects_empty_synthesis(monkeypatch, tmp_path):
    def run(command, **_options):
        with wave.open(command[command.index("-w") + 1], "wb") as audio:
            audio.setparams((1, 2, 22050, 0, "NONE", "not compressed"))

    monkeypatch.setattr(bundle_check.subprocess, "run", run)
    with pytest.raises(ValueError, match="empty WAV"):
        bundle_check.verify_bundled_speech(tmp_path)


def test_frozen_smoke_fails_when_bundled_speech_is_missing(monkeypatch, tmp_path):
    report = tmp_path / "smoke.txt"
    monkeypatch.setenv(main_module.PACKAGE_SMOKE_REPORT_ENV, str(report))
    monkeypatch.setattr(main_module.sys, "frozen", True, raising=False)

    def missing_bundle(_root):
        raise FileNotFoundError("missing bundled speech")

    monkeypatch.setattr(bundle_check, "verify_bundled_speech", missing_bundle)
    assert main_module.package_smoke_test() == 1
    assert "missing bundled speech" in report.read_text(encoding="utf-8")


def test_download_rejects_corrupt_cache_without_network(monkeypatch, tmp_path):
    asset = tmp_path / "speech.msi"
    asset.write_bytes(b"corrupted")

    def unexpected_network(*_args, **_kwargs):
        pytest.fail("A cached file should be verified before downloading")

    monkeypatch.setattr(bundler.urllib.request, "urlopen", unexpected_network)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        bundler.checked_download("https://example.invalid/asset", asset, "0" * 64)


def test_bundle_rejects_edge_version_without_matching_source(monkeypatch, tmp_path):
    monkeypatch.setattr(bundler, "version", lambda _name: "0.0.0")
    with pytest.raises(ValueError, match="pinned source archive version"):
        bundler.prepare_speech_bundle(tmp_path / "speech", tmp_path / "cache")
    assert not (tmp_path / "speech").exists()


@pytest.mark.parametrize("valid", [True, False])
def test_download_checks_new_bytes_before_publishing_cache(monkeypatch, tmp_path, valid):
    data = b"speech asset"
    asset = tmp_path / "speech.msi"
    expected = hashlib.sha256(data).hexdigest() if valid else "0" * 64
    monkeypatch.setattr(
        bundler.urllib.request, "urlopen", lambda *_args, **_kwargs: io.BytesIO(data)
    )
    if valid:
        assert bundler.checked_download("https://example.invalid/asset", asset, expected) == asset
        assert asset.read_bytes() == data
    else:
        with pytest.raises(ValueError, match="SHA-256 mismatch"):
            bundler.checked_download("https://example.invalid/asset", asset, expected)
        assert not asset.exists()
    assert not asset.with_suffix(".msi.part").exists()
