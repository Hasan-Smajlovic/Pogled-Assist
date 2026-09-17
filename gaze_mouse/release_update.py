"""Stable release discovery and updater launch support."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from .logging_setup import get_project_root

RELEASE_API_URL = (
    "https://api.github.com/repos/Hasan-Smajlovic/TobiiEyeTrackerTool/releases/latest"
)
RELEASE_DOWNLOAD_ROOT = (
    "https://github.com/Hasan-Smajlovic/TobiiEyeTrackerTool/releases/download"
)
UPDATE_CHECK_TIMEOUT_SECONDS = 10
_STABLE_VERSION_PATTERN = re.compile(
    r"^(?:v)?(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)$"
)


class ReleaseUpdateError(RuntimeError):
    """Raised when release discovery or updater launch cannot continue."""


@dataclass(frozen=True, order=True)
class StableVersion:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str, *, label: str) -> StableVersion:
        match = _STABLE_VERSION_PATTERN.fullmatch(value.strip())
        if match is None:
            raise ReleaseUpdateError(
                f"{label} mora biti stabilna verzija poput 0.2.0."
            )
        return cls(*(int(match.group(name)) for name in ("major", "minor", "patch")))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class ReleaseCheckResult:
    installed_version: StableVersion
    latest_version: StableVersion

    @property
    def update_available(self) -> bool:
        return self.latest_version > self.installed_version


def check_latest_release(
    app_root: Path | None = None,
    *,
    release_api_url: str = RELEASE_API_URL,
    timeout: float = UPDATE_CHECK_TIMEOUT_SECONDS,
) -> ReleaseCheckResult:
    root = (app_root or get_project_root()).resolve()
    installed_version = _read_installed_version(root)

    request = urllib.request.Request(
        release_api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "PogledAssist",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise ReleaseUpdateError(
            "Provjera ažuriranja nije uspjela. Provjerite internet vezu i pokušajte ponovo."
        ) from error

    latest_version = _validate_release(payload, release_api_url=release_api_url)
    return ReleaseCheckResult(installed_version, latest_version)


def is_update_supported(app_root: Path | None = None) -> bool:
    root = (app_root or get_project_root()).resolve()
    return (
        sys.platform == "win32"
        and bool(getattr(sys, "frozen", False))
        and (root / "VERSION").is_file()
        and (root / "update_windows.ps1").is_file()
    )


def launch_release_update(
    app_root: Path | None = None,
    *,
    process_id: int | None = None,
) -> None:
    root = (app_root or get_project_root()).resolve()
    if not is_update_supported(root):
        raise ReleaseUpdateError(
            "Ažuriranje iz aplikacije dostupno je samo u instaliranoj Windows verziji."
        )

    powershell = _powershell_executable()
    updater = root / "update_windows.ps1"
    command = [
        str(powershell),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(updater),
        "-InstallRoot",
        str(root),
        "-Launch",
        "-NoPause",
        "-WaitForProcessId",
        str(process_id or os.getpid()),
    ]
    creation_flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    try:
        subprocess.Popen(
            command,
            cwd=root,
            close_fds=True,
            creationflags=creation_flags,
        )
    except OSError as error:
        raise ReleaseUpdateError(
            "Updater se nije mogao pokrenuti. Pokušajte ponovo ili pokrenite update_windows.ps1."
        ) from error


class ReleaseUpdateManager(QObject):
    check_started = Signal()
    check_completed = Signal(object)
    check_failed = Signal(str)

    def __init__(self, app_root: Path | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._app_root = (app_root or get_project_root()).resolve()
        self._checking = False

    @property
    def supported(self) -> bool:
        return is_update_supported(self._app_root)

    def check(self) -> None:
        if self._checking:
            return
        if not self.supported:
            self.check_failed.emit(
                "Provjera ažuriranja dostupna je samo u instaliranoj Windows verziji."
            )
            return

        self._checking = True
        self.check_started.emit()
        threading.Thread(target=self._run_check, daemon=True).start()

    def launch(self) -> None:
        launch_release_update(self._app_root)

    def _run_check(self) -> None:
        try:
            result = check_latest_release(self._app_root)
        except ReleaseUpdateError as error:
            self._checking = False
            self.check_failed.emit(str(error))
            return

        self._checking = False
        self.check_completed.emit(result)


def _read_installed_version(root: Path) -> StableVersion:
    version_path = root / "VERSION"
    try:
        version_text = version_path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ReleaseUpdateError("Instalirana verzija se ne može pročitati.") from error
    return StableVersion.parse(version_text, label="Instalirana verzija")


def _validate_release(payload: Any, *, release_api_url: str) -> StableVersion:
    if not isinstance(payload, dict):
        raise ReleaseUpdateError("GitHub nije vratio ispravne podatke o izdanju.")
    if payload.get("draft") is not False or payload.get("prerelease") is not False:
        raise ReleaseUpdateError("GitHub nije vratio posljednje stabilno izdanje.")

    tag = payload.get("tag_name")
    if not isinstance(tag, str):
        raise ReleaseUpdateError("GitHub izdanje nema ispravnu oznaku verzije.")
    version = StableVersion.parse(tag, label="Oznaka posljednjeg izdanja")
    normalized_tag = f"v{version}"
    if tag != normalized_tag:
        raise ReleaseUpdateError(f"Oznaka posljednjeg izdanja mora biti {normalized_tag}.")

    artifact_name = f"PogledAssist-{normalized_tag}-windows-x64.zip"
    required_assets = {
        artifact_name: f"{RELEASE_DOWNLOAD_ROOT}/{normalized_tag}/{artifact_name}",
        f"{artifact_name}.sha256": (
            f"{RELEASE_DOWNLOAD_ROOT}/{normalized_tag}/{artifact_name}.sha256"
        ),
    }
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise ReleaseUpdateError("GitHub izdanje nema ispravnu listu datoteka.")

    for name, expected_url in required_assets.items():
        matches = [asset for asset in assets if isinstance(asset, dict) and asset.get("name") == name]
        if len(matches) != 1:
            raise ReleaseUpdateError(f"Stabilnom izdanju nedostaje datoteka {name}.")
        if release_api_url == RELEASE_API_URL and matches[0].get("browser_download_url") != expected_url:
            raise ReleaseUpdateError(f"Datoteka {name} nije objavljena na očekivanoj lokaciji.")

    return version


def _powershell_executable() -> Path | str:
    discovered = shutil.which("powershell.exe")
    if discovered:
        return Path(discovered)

    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if candidate.is_file():
        return candidate
    return "powershell.exe"
