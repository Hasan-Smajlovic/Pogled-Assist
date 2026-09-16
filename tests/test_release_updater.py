from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import zipfile
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="The release updater uses Windows PowerShell and Windows process checks.",
)

REPO_ROOT = Path(__file__).resolve().parents[1]
UPDATER_SCRIPT = REPO_ROOT / "update_windows.ps1"
LATEST_VERSION = "0.2.0"
ARTIFACT_NAME = f"TobiiGazeMouse-v{LATEST_VERSION}-windows-x64.zip"

FAKE_INSTALLER = r"""[CmdletBinding()]
param(
    [string]$InstallRoot,
    [string]$ExpectedVersion,
    [switch]$NoDesktopShortcut,
    [switch]$Launch,
    [switch]$NoElevation
)
$ErrorActionPreference = "Stop"
$sourceRoot = Split-Path -Parent $PSCommandPath
if (-not [string]::IsNullOrWhiteSpace($env:FAKE_INSTALLER_SIGNAL)) {
    Set-Content -LiteralPath $env:FAKE_INSTALLER_SIGNAL -Value "started"
}
if ($env:FAKE_INSTALLER_SLEEP -eq "1") {
    Start-Sleep -Seconds 4
}
if ($env:FAKE_INSTALLER_FAIL -eq "1") {
    Write-Error "Forced fake installer failure"
    exit 9
}
$preserved = @("data", "logs", "install_info.json")
Get-ChildItem -LiteralPath $InstallRoot -Force | Where-Object {
    $_.Name -notin $preserved -and $_.Extension -ne ".log"
} | Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $sourceRoot -Force | Where-Object {
    $_.Name -notin $preserved -and $_.Extension -ne ".log"
} | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $InstallRoot -Recurse -Force
}
exit 0
"""


class _ReleaseServer(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), _ReleaseHandler)
        self.routes: dict[str, tuple[int, str, bytes]] = {}
        self.requests: list[str] = []


class _ReleaseHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        self.server.requests.append(path)
        status, content_type, body = self.server.routes.get(
            path,
            (404, "text/plain", b"not found"),
        )
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


@contextmanager
def _serve_release(archive: bytes, checksum: str | None = None):
    server = _ReleaseServer()
    base_url = f"http://127.0.0.1:{server.server_port}"
    checksum_text = checksum or f"{hashlib.sha256(archive).hexdigest()}  {ARTIFACT_NAME}"
    metadata = {
        "tag_name": f"v{LATEST_VERSION}",
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": ARTIFACT_NAME,
                "browser_download_url": f"{base_url}/{ARTIFACT_NAME}",
            },
            {
                "name": f"{ARTIFACT_NAME}.sha256",
                "browser_download_url": f"{base_url}/{ARTIFACT_NAME}.sha256",
            },
        ],
    }
    server.routes = {
        "/latest": (200, "application/json", json.dumps(metadata).encode()),
        f"/{ARTIFACT_NAME}": (200, "application/zip", archive),
        f"/{ARTIFACT_NAME}.sha256": (200, "text/plain", checksum_text.encode()),
    }
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"{base_url}/latest"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _release_archive(tmp_path: Path, *, installer: str = FAKE_INSTALLER) -> bytes:
    package = tmp_path / "package" / "TobiiGazeMouse"
    (package / "_internal").mkdir(parents=True)
    (package / "TobiiGazeMouse.exe").write_bytes(b"fake executable")
    (package / "install_windows.ps1").write_text(installer, encoding="utf-8")
    (package / "start_gaze_mouse.ps1").write_text("# fake launcher\n", encoding="utf-8")
    (package / "update_windows.ps1").write_text("# fake updater\n", encoding="utf-8")
    (package / "README.md").write_text("fake release\n", encoding="utf-8")
    (package / "VERSION").write_text(f"{LATEST_VERSION}\n", encoding="utf-8")
    (package / "new-app-file.txt").write_text("new application\n", encoding="utf-8")

    archive_path = tmp_path / ARTIFACT_NAME
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in package.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(package.parent))
    return archive_path.read_bytes()


def _installed_app(tmp_path: Path, *, version: str | None = "0.1.0") -> Path:
    install_root = tmp_path / "installed"
    (install_root / "data").mkdir(parents=True)
    (install_root / "logs").mkdir()
    (install_root / "data" / "app_settings.json").write_bytes(b'{"setting":"keep"}')
    (install_root / "logs" / "latest.txt").write_bytes(b"keep this log\r\n")
    (install_root / "install_info.json").write_bytes(b'{"source":"legacy"}')
    (install_root / "setup_windows.log").write_bytes(b"keep this setup log\r\n")
    (install_root / "old-app-file.txt").write_text("old application\n", encoding="utf-8")
    if version is not None:
        (install_root / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    return install_root


def _updater_command(install_root: Path, release_url: str) -> list[str]:
    return [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(UPDATER_SCRIPT),
        "-InstallRoot",
        str(install_root),
        "-ReleaseApiUrl",
        release_url,
        "-NoElevation",
        "-NoDesktopShortcut",
        "-NoPause",
    ]


def _updater_environment(**overrides: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PSMODULEPATH", None)
    environment["TOBII_GAZE_MOUSE_TESTING"] = "1"
    environment.update(overrides)
    return environment


def _run_updater(
    install_root: Path,
    release_url: str,
    *,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _updater_command(install_root, release_url),
        cwd=REPO_ROOT,
        env=environment or _updater_environment(),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_updater_installs_verified_release_and_preserves_user_files(tmp_path):
    install_root = _installed_app(tmp_path)
    archive = _release_archive(tmp_path)
    settings_before = (install_root / "data" / "app_settings.json").read_bytes()
    log_before = (install_root / "logs" / "latest.txt").read_bytes()
    metadata_before = (install_root / "install_info.json").read_bytes()
    setup_log_before = (install_root / "setup_windows.log").read_bytes()

    with _serve_release(archive) as (server, release_url):
        completed = _run_updater(install_root, release_url)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert (install_root / "VERSION").read_text(encoding="utf-8").strip() == LATEST_VERSION
    assert (install_root / "new-app-file.txt").is_file()
    assert not (install_root / "old-app-file.txt").exists()
    assert (install_root / "data" / "app_settings.json").read_bytes() == settings_before
    assert (install_root / "logs" / "latest.txt").read_bytes() == log_before
    assert (install_root / "install_info.json").read_bytes() == metadata_before
    assert (install_root / "setup_windows.log").read_bytes() == setup_log_before
    assert server.requests == [
        "/latest",
        f"/{ARTIFACT_NAME}",
        f"/{ARTIFACT_NAME}.sha256",
    ]


def test_updater_migrates_legacy_source_install_without_version(tmp_path):
    install_root = _installed_app(tmp_path, version=None)
    (install_root / "setup_windows.ps1").write_text("# legacy setup\n", encoding="utf-8")
    (install_root / "run_gaze_mouse.py").write_text("# legacy app\n", encoding="utf-8")
    (install_root / "gaze_mouse").mkdir()
    archive = _release_archive(tmp_path)

    with _serve_release(archive) as (_server, release_url):
        completed = _run_updater(install_root, release_url)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Migrating the existing source installation" in completed.stdout
    assert (install_root / "VERSION").read_text(encoding="utf-8").strip() == LATEST_VERSION
    assert (install_root / "data" / "app_settings.json").is_file()
    assert not (install_root / "run_gaze_mouse.py").exists()


def test_checksum_mismatch_stops_before_installer_runs(tmp_path):
    install_root = _installed_app(tmp_path)
    archive = _release_archive(tmp_path)

    with _serve_release(archive, checksum=f"{'0' * 64}  {ARTIFACT_NAME}") as (
        _server,
        release_url,
    ):
        completed = _run_updater(install_root, release_url)

    assert completed.returncode != 0
    assert "Checksum mismatch" in completed.stdout + completed.stderr
    assert (install_root / "VERSION").read_text(encoding="utf-8").strip() == "0.1.0"
    assert (install_root / "old-app-file.txt").is_file()
    assert not (install_root / "new-app-file.txt").exists()


def test_missing_release_asset_stops_before_download(tmp_path):
    install_root = _installed_app(tmp_path)
    archive = _release_archive(tmp_path)

    with _serve_release(archive) as (server, release_url):
        status, content_type, body = server.routes["/latest"]
        metadata = json.loads(body)
        metadata["assets"] = metadata["assets"][:1]
        server.routes["/latest"] = (status, content_type, json.dumps(metadata).encode())
        completed = _run_updater(install_root, release_url)

    assert completed.returncode != 0
    assert "must contain exactly one" in completed.stdout + completed.stderr
    assert server.requests == ["/latest"]
    assert (install_root / "VERSION").read_text(encoding="utf-8").strip() == "0.1.0"
    assert (install_root / "old-app-file.txt").is_file()


def test_unsupported_installed_version_stops_before_network_request(tmp_path):
    install_root = _installed_app(tmp_path, version="development")
    archive = _release_archive(tmp_path)

    with _serve_release(archive) as (server, release_url):
        completed = _run_updater(install_root, release_url)

    assert completed.returncode != 0
    assert "Installed VERSION must be a stable Semantic Version" in (
        completed.stdout + completed.stderr
    )
    assert server.requests == []
    assert (install_root / "VERSION").read_text(encoding="utf-8").strip() == "development"
    assert (install_root / "old-app-file.txt").is_file()


def test_installer_failure_leaves_previous_installation_usable(tmp_path):
    install_root = _installed_app(tmp_path)
    archive = _release_archive(tmp_path)
    environment = _updater_environment(FAKE_INSTALLER_FAIL="1")

    with _serve_release(archive) as (_server, release_url):
        completed = _run_updater(install_root, release_url, environment=environment)

    assert completed.returncode != 0
    assert "release installer failed" in (completed.stdout + completed.stderr).lower()
    assert (install_root / "VERSION").read_text(encoding="utf-8").strip() == "0.1.0"
    assert (install_root / "old-app-file.txt").is_file()
    assert (install_root / "data" / "app_settings.json").is_file()


def test_up_to_date_installation_does_not_download_assets(tmp_path):
    install_root = _installed_app(tmp_path, version=LATEST_VERSION)
    archive = _release_archive(tmp_path)

    with _serve_release(archive) as (server, release_url):
        completed = _run_updater(install_root, release_url)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "already up to date" in completed.stdout
    assert server.requests == ["/latest"]


def test_network_error_does_not_change_installation(tmp_path):
    install_root = _installed_app(tmp_path)
    server = _ReleaseServer()
    unavailable_url = f"http://127.0.0.1:{server.server_port}/latest"
    server.server_close()

    completed = _run_updater(install_root, unavailable_url)

    assert completed.returncode != 0
    assert "Could not query the latest stable release" in completed.stdout + completed.stderr
    assert (install_root / "VERSION").read_text(encoding="utf-8").strip() == "0.1.0"
    assert (install_root / "old-app-file.txt").is_file()


def test_concurrent_updater_is_rejected(tmp_path):
    install_root = _installed_app(tmp_path)
    archive = _release_archive(tmp_path)
    signal_path = tmp_path / "installer-started.txt"
    environment = _updater_environment(
        FAKE_INSTALLER_SIGNAL=str(signal_path),
        FAKE_INSTALLER_SLEEP="1",
    )

    with _serve_release(archive) as (_server, release_url):
        first = subprocess.Popen(
            _updater_command(install_root, release_url),
            cwd=REPO_ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        deadline = time.monotonic() + 15
        while not signal_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert signal_path.exists(), "First updater did not reach the fake installer"

        second = _run_updater(install_root, release_url)
        first_stdout, first_stderr = first.communicate(timeout=15)

    assert first.returncode == 0, first_stdout + first_stderr
    assert second.returncode != 0
    assert "already in progress" in second.stdout + second.stderr
