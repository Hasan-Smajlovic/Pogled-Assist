"""Stable release discovery and updater launch support."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from .logging_setup import get_project_root

RELEASE_API_URL = "https://api.github.com/repos/Hasan-Smajlovic/Pogled-Assist/releases/latest"
RELEASE_DOWNLOAD_ROOT = "https://github.com/Hasan-Smajlovic/Pogled-Assist/releases/download"
RELEASE_LIST_API_URL = RELEASE_API_URL.removesuffix("/latest")
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
            raise ReleaseUpdateError(f"{label} mora biti stabilna verzija poput 0.2.0.")
        return cls(*(int(match.group(name)) for name in ("major", "minor", "patch")))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class ReleaseCheckResult:
    installed_version: StableVersion
    latest_version: StableVersion
    versions: tuple[StableVersion, ...]

    @property
    def update_available(self) -> bool:
        return self.latest_version > self.installed_version


def check_available_releases(
    app_root: Path | None = None,
    *,
    release_api_url: str = RELEASE_LIST_API_URL,
    timeout: float = UPDATE_CHECK_TIMEOUT_SECONDS,
) -> ReleaseCheckResult:
    root = (app_root or get_project_root()).resolve()
    installed = _read_installed_version(root)
    versions: set[StableVersion] = set()
    page = 1
    while True:
        payload = _fetch_release_json(f"{release_api_url}?per_page=100&page={page}", timeout)
        if not isinstance(payload, list):
            raise ReleaseUpdateError("GitHub nije vratio ispravnu listu verzija.")
        for release in payload:
            try:
                versions.add(_validate_release(release, release_api_url=release_api_url))
            except ReleaseUpdateError:
                continue
        if len(payload) < 100:
            break
        page += 1
    if not versions:
        raise ReleaseUpdateError("Nema dostupnih stabilnih verzija s Windows paketom.")
    ordered = tuple(sorted(versions, reverse=True))
    return ReleaseCheckResult(installed, ordered[0], ordered)


def _fetch_release_json(url: str, timeout: float) -> Any:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "PogledAssist"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise ReleaseUpdateError(
            "Provjera verzija nije uspjela. Provjerite internet vezu i pokušajte ponovo."
        ) from error


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
    version: StableVersion | None = None,
    control_directory: Path | None = None,
) -> subprocess.Popen:
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
    if version is not None:
        command.extend(("-TargetVersion", str(version)))
    if control_directory is not None:
        command.extend(("-ControlDirectory", str(control_directory)))
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    try:
        return subprocess.Popen(
            command,
            cwd=root.parent,
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
    install_ready = Signal()
    install_failed = Signal(str)
    _prepare_done = Signal(object, object)

    def __init__(self, app_root: Path | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._app_root = (app_root or get_project_root()).resolve()
        self._checking = False
        self._installing = False
        self._control_directory: Path | None = None
        self._result: ReleaseCheckResult | None = None
        self._ready = False
        self._cancel_event: threading.Event | None = None
        self._prepare_done.connect(self._finish_prepare)

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def installed_version(self) -> StableVersion | None:
        try:
            return _read_installed_version(self._app_root)
        except ReleaseUpdateError:
            return None

    @property
    def supported(self) -> bool:
        return is_update_supported(self._app_root)

    def check(self) -> None:
        if self._checking or self._installing:
            return
        if not self.supported:
            self.check_failed.emit(
                "Provjera ažuriranja dostupna je samo u instaliranoj Windows verziji."
            )
            return

        self._checking = True
        self.check_started.emit()
        threading.Thread(target=self._run_check, daemon=True).start()

    def prepare(self, version: StableVersion) -> None:
        if self._installing:
            return
        if self._result is None or version not in self._result.versions:
            raise ReleaseUpdateError("Prvo osvježite listu i odaberite dostupnu verziju.")
        try:
            self._control_directory = Path(tempfile.mkdtemp(prefix="PogledAssistUpdateRequest_"))
        except OSError as error:
            raise ReleaseUpdateError(
                "Priprema instalacije nije uspjela. Provjerite slobodan prostor i pokušajte ponovo."
            ) from error
        self._installing = True
        self._ready = False
        self._cancel_event = threading.Event()
        threading.Thread(
            target=self._run_prepare,
            args=(version, self._control_directory, self._cancel_event),
            daemon=True,
        ).start()

    def cancel(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
        if self._control_directory is not None:
            with suppress(OSError):
                (self._control_directory / "cancel").touch()

    def _run_prepare(
        self, version: StableVersion, directory: Path, cancelled: threading.Event
    ) -> None:
        try:
            process = launch_release_update(
                self._app_root, version=version, control_directory=directory
            )
            deadline = time.monotonic() + 900
            notified = False
            while time.monotonic() < deadline:
                if (
                    cancelled.is_set()
                    or (directory / "cancel").exists()
                    or (directory / "install").exists()
                ):
                    return
                ready = directory / "ready.json"
                if ready.exists():
                    payload = json.loads(ready.read_text(encoding="utf-8-sig"))
                    if not isinstance(payload, dict):
                        raise ReleaseUpdateError("Updater nije vratio ispravan odgovor.")
                    if payload.get("ready") is not True:
                        raise ReleaseUpdateError(
                            "Instalacija nije pripremljena. " + str(payload.get("error", ""))
                        )
                    if not notified:
                        self._prepare_done.emit(directory, None)
                        notified = True
                if process.poll() not in (None, 0):
                    raise ReleaseUpdateError("Updater se nije mogao pokrenuti ili je otkazan.")
                time.sleep(0.1)
            raise ReleaseUpdateError("Priprema instalacije je istekla. Pokušajte ponovo.")
        except (OSError, ValueError, ReleaseUpdateError) as error:
            self._prepare_done.emit(directory, str(error))

    def _finish_prepare(self, directory: Path, error: str | None) -> None:
        if self._control_directory != directory or not self._installing:
            return
        if error is not None:
            self.finish_cancel()
            self.install_failed.emit(error)
        else:
            self._ready = True
            self.install_ready.emit()

    def authorize_restart(self) -> None:
        if not self._ready or self._control_directory is None:
            raise ReleaseUpdateError("Paket još nije spreman za instalaciju.")
        try:
            state = json.loads(
                (self._control_directory / "ready.json").read_text(encoding="utf-8-sig")
            )
            if not isinstance(state, dict) or state.get("ready") is not True:
                raise ReleaseUpdateError(
                    "Updater više nije spreman za instalaciju. Pokušajte ponovo."
                )
            (self._control_directory / "install").touch()
        except (OSError, ValueError) as error:
            raise ReleaseUpdateError(
                "Ponovno pokretanje nije potvrđeno. Pokušajte ponovo."
            ) from error

    def finish_cancel(self) -> None:
        self.cancel()
        self._installing = False
        self._ready = False
        self._control_directory = None

    def _run_check(self) -> None:
        try:
            result = check_available_releases(self._app_root)
        except ReleaseUpdateError as error:
            self._checking = False
            self.check_failed.emit(str(error))
            return

        self._result = result
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
    version = _release_version(payload)
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise ReleaseUpdateError("GitHub izdanje nema ispravnu listu datoteka.")

    for name, expected_url in _required_release_assets(version).items():
        _validate_release_asset(
            assets,
            name,
            expected_url,
            official=release_api_url in (RELEASE_API_URL, RELEASE_LIST_API_URL),
        )
    return version


def _release_version(payload: dict) -> StableVersion:
    if payload.get("draft") is not False or payload.get("prerelease") is not False:
        raise ReleaseUpdateError("GitHub nije vratio posljednje stabilno izdanje.")

    tag = payload.get("tag_name")
    if not isinstance(tag, str):
        raise ReleaseUpdateError("GitHub izdanje nema ispravnu oznaku verzije.")
    version = StableVersion.parse(tag, label="Oznaka posljednjeg izdanja")
    normalized_tag = f"v{version}"
    if tag != normalized_tag:
        raise ReleaseUpdateError(f"Oznaka posljednjeg izdanja mora biti {normalized_tag}.")
    return version


def _required_release_assets(version: StableVersion) -> dict[str, str]:
    normalized_tag = f"v{version}"
    artifact_name = f"PogledAssist-{normalized_tag}-windows-x64.zip"
    return {
        artifact_name: f"{RELEASE_DOWNLOAD_ROOT}/{normalized_tag}/{artifact_name}",
        f"{artifact_name}.sha256": (
            f"{RELEASE_DOWNLOAD_ROOT}/{normalized_tag}/{artifact_name}.sha256"
        ),
    }


def _validate_release_asset(assets: list, name: str, expected_url: str, *, official: bool) -> None:
    matches = [asset for asset in assets if isinstance(asset, dict) and asset.get("name") == name]
    if len(matches) != 1:
        raise ReleaseUpdateError(f"Stabilnom izdanju nedostaje datoteka {name}.")
    if official and matches[0].get("browser_download_url") != expected_url:
        raise ReleaseUpdateError(f"Datoteka {name} nije objavljena na očekivanoj lokaciji.")


def _powershell_executable() -> Path | str:
    discovered = shutil.which("powershell.exe")
    if discovered:
        return Path(discovered)

    system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    candidate = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if candidate.is_file():
        return candidate
    return "powershell.exe"
