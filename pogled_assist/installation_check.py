"""Read-only setup diagnostics; never starts gaze tracking or installs drivers."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .speech.bundle_check import verify_bundled_speech
from .tracking.tobii_calibration import _best_tobii_launch_target
from .tracking.tobii_stream_engine import _stream_engine_candidates
from .tracking.tobii_stream_engine_bridge_backend import verify_bundled_bridge

TOBII_DOWNLOAD_URL = (
    "https://help.tobii.com/hc/en-us/articles/360002918474-Which-app-do-I-need-for-my-device"
)
DEVICE_QUERY = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$devices = @(Get-PnpDevice -PresentOnly -ErrorAction Stop | Where-Object {
    $_.FriendlyName -match 'Tobii|EyeChip'
} | Select-Object FriendlyName, Status)
ConvertTo-Json -InputObject $devices -Compress
"""


@dataclass(frozen=True)
class InstallationItem:
    key: str
    title: str
    state: str
    detail: str


def check_tobii_device() -> InstallationItem:
    windows = Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
    powershell = windows / "System32/WindowsPowerShell/v1.0/powershell.exe"
    completed = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-Command", DEVICE_QUERY],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        errors="replace",
        timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    devices = json.loads(completed.stdout)
    if not isinstance(devices, list):
        raise ValueError("Unexpected device report")
    if not devices:
        return InstallationItem(
            "device",
            "Tobii uređaj",
            "Nije prepoznat",
            "Povežite uređaj, instalirajte drajvere i ponovite provjeru.",
        )
    names = ", ".join(str(device.get("FriendlyName", "Tobii")) for device in devices)
    healthy = any(str(device.get("Status", "")).casefold() == "ok" for device in devices)
    return InstallationItem(
        "device",
        "Tobii uređaj",
        "Prepoznat" if healthy else "Potrebna provjera",
        f"Windows prijavljuje: {names}. Praćenje pogleda nije provjereno.",
    )


def check_installation(root: Path) -> list[InstallationItem]:
    results = []
    for key, title, verify, detail in (
        (
            "speech",
            "Govor",
            verify_bundled_speech,
            "Standardni glas radi bez interneta. Prirodni glas zahtijeva internet.",
        ),
        (
            "bridge",
            "Tobii most",
            verify_bundled_bridge,
            "Uključeno je 32-bitno okruženje za povezivanje.",
        ),
    ):
        try:
            verify(root)
            results.append(InstallationItem(key, title, "Spremno", detail))
        except Exception:
            results.append(
                InstallationItem(
                    key, title, "Nije spremno", "Ponovo instalirajte kompletan Pogled Assist paket."
                )
            )
    try:
        software_found = _best_tobii_launch_target() is not None or any(
            path.is_file() for path in _stream_engine_candidates()
        )
        results.append(
            InstallationItem(
                "software",
                "Tobii softver",
                "Pronađen" if software_found else "Potrebna instalacija",
                "Pronađene su Tobii komponente; njihova ispravnost nije potvrđena."
                if software_found
                else "Preuzmite službeni softver za svoj model uređaja.",
            )
        )
    except Exception:
        results.append(
            InstallationItem(
                "software",
                "Tobii softver",
                "Nije provjereno",
                "Provjera nije uspjela. Otvorite Tobii softver ili ponovite provjeru.",
            )
        )
    try:
        results.append(check_tobii_device())
    except Exception:
        results.append(
            InstallationItem(
                "device",
                "Tobii uređaj",
                "Nije provjereno",
                "Windows provjera nije uspjela. Provjerite uređaj u Tobii softveru.",
            )
        )
    results.append(
        InstallationItem(
            "calibration",
            "Kalibracija",
            "Potrebna provjera",
            "Pokrenite kalibraciju u Tobii softveru. Ova provjera ne potvrđuje praćenje pogleda.",
        )
    )
    return results
