"""Prepare pinned speech assets at build time, never on the user's machine."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from importlib.metadata import version
from pathlib import Path

EDGE_TTS_VERSION = "7.2.8"
BRIDGE_PYTHON_URL = "https://www.python.org/ftp/python/3.10.11/python-3.10.11-embed-win32.zip"
BRIDGE_PYTHON_SHA256 = "0987a9d85ccf1ba17c3dbdcadc39835f183843604da18c9af4bd677dc84adf7d"
ESPEAK_MSI_URL = "https://github.com/espeak-ng/espeak-ng/releases/download/1.52.0/espeak-ng.msi"
ESPEAK_MSI_SHA256 = "7f673c709ea5dd579d3b5ebb98688cc575328a6ab7438d2bc405b88cedaeafb9"
SOURCE_ASSETS = (
    (
        "espeak-ng-1.52.0.tar.gz",
        "https://codeload.github.com/espeak-ng/espeak-ng/tar.gz/refs/tags/1.52.0",
        "bb4338102ff3b49a81423da8a1a158b420124b055b60fa76cfb4b18677130a23",
        "espeak-ng-1.52.0/COPYING",
        "espeak-ng-LICENSE.txt",
    ),
    (
        "edge_tts-7.2.8.tar.gz",
        "https://files.pythonhosted.org/packages/3f/60/"
        "afbf548b43c78355e03926c6b1fff7500303a2da4d84db9e1324119e21ae/edge_tts-7.2.8.tar.gz",
        "fcf185a0d527a0d2d003f9d5841facc1d5e0e7b3b88d5df9c32990402c6b8cd0",
        "edge_tts-7.2.8/LICENSE",
        "edge-tts-LICENSE.txt",
    ),
)


def checked_download(url: str, target: Path, expected_sha256: str) -> Path:
    """Reject corrupt cached files and downloads before executing or extracting."""
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".part")
        try:
            with (
                urllib.request.urlopen(url, timeout=120) as response,
                temporary.open("wb") as out,
            ):
                shutil.copyfileobj(response, out)
            verify_checksum(temporary, expected_sha256)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    verify_checksum(target, expected_sha256)
    return target


def verify_checksum(path: Path, expected: str) -> None:
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f"SHA-256 mismatch for {path.name}: {actual}")


def prepare_speech_bundle(destination: Path, cache: Path) -> None:
    if version("edge-tts") != EDGE_TTS_VERSION:
        raise ValueError("Installed edge-tts must match the pinned source archive version")
    destination.mkdir(parents=True, exist_ok=True)
    msi = checked_download(ESPEAK_MSI_URL, cache / "espeak-ng-1.52.0.msi", ESPEAK_MSI_SHA256)
    # Administrative extraction copies files only; it does not install or register SAPI.
    with tempfile.TemporaryDirectory(prefix="espeak-extract-", dir=cache) as temporary:
        subprocess.run(
            ["msiexec.exe", "/a", str(msi), "/qn", f"TARGETDIR={temporary}"],
            check=True,
            timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        roots = list(Path(temporary).rglob("espeak-ng.exe"))
        if len(roots) != 1:
            raise ValueError("eSpeak MSI must contain exactly one espeak-ng.exe")
        shutil.copytree(roots[0].parent, destination / "espeak-ng")

    licenses = destination / "licenses"
    licenses.mkdir()
    for name, url, checksum, license_member, license_name in SOURCE_ASSETS:
        archive = checked_download(url, cache / name, checksum)
        shutil.copy2(archive, licenses / name)
        with tarfile.open(archive, "r:gz") as source:
            member = source.extractfile(license_member)
            if member is None:
                raise ValueError(f"Missing license: {license_member}")
            with member:
                (licenses / license_name).write_bytes(member.read())
    (licenses / "README.txt").write_text(
        "Unmodified eSpeak NG 1.52.0 and edge-tts 7.2.8 are distributed as separate tools.\n"
        "Their matching source archives and licenses are included in this directory.\n"
        "Edge dependency metadata and licenses are in edge/_internal/*.dist-info.\n"
        "Python's license is in edge/_internal/licenses/python/LICENSE.txt.\n"
        "https://github.com/espeak-ng/espeak-ng/tree/1.52.0\n"
        "https://github.com/rany2/edge-tts\n",
        encoding="utf-8",
    )


def prepare_bridge_bundle(destination: Path, cache: Path) -> None:
    archive = checked_download(
        BRIDGE_PYTHON_URL, cache / "python-3.10.11-embed-win32.zip", BRIDGE_PYTHON_SHA256
    )
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            if not (destination / member.filename).resolve().is_relative_to(destination.resolve()):
                raise ValueError("Python archive contains an unsafe path")
        source.extractall(destination)
    # The embedded interpreter ignores PYTHONPATH. Explicitly expose only our
    # packaged bridge sources; keep site packages and user Python paths disabled.
    (destination / "python310._pth").write_text(
        "python310.zip\n.\n../../_internal\n", encoding="utf-8"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--bridge-destination", type=Path, required=True)
    arguments = parser.parse_args()
    prepare_speech_bundle(arguments.destination.resolve(), arguments.cache.resolve())
    prepare_bridge_bundle(arguments.bridge_destination.resolve(), arguments.cache.resolve())
