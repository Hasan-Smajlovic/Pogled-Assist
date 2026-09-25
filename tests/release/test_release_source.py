from __future__ import annotations

from pathlib import Path

import pytest

from pogled_assist import release_update
from pogled_assist.release_update import (
    RELEASE_API_URL,
    RELEASE_DOWNLOAD_ROOT,
    ReleaseUpdateError,
    StableVersion,
    _validate_release,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
OFFICIAL_REPOSITORY = "Hasan-Smajlovic/Pogled-Assist"
PREVIOUS_REPOSITORY = "Hasan-Smajlovic/TobiiEyeTrackerTool"
TAG = "v0.1.0"
ARTIFACT_NAME = f"PogledAssist-{TAG}-windows-x64.zip"


def test_release_publish_and_update_use_the_current_repository() -> None:
    api_url = f"https://api.github.com/repos/{OFFICIAL_REPOSITORY}/releases/latest"
    download_root = f"https://github.com/{OFFICIAL_REPOSITORY}/releases/download"

    assert api_url == RELEASE_API_URL
    assert download_root == RELEASE_DOWNLOAD_ROOT

    updater = (REPO_ROOT / "update_windows.ps1").read_text(encoding="utf-8")
    assert updater.count(api_url) == 2
    assert download_root in updater
    assert PREVIOUS_REPOSITORY not in updater

    workflow = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert f"github.repository == '{OFFICIAL_REPOSITORY}'" in workflow
    assert PREVIOUS_REPOSITORY not in workflow


def test_official_release_rejects_assets_from_the_previous_repository_name() -> None:
    accepted = _validate_release(
        _release_payload(RELEASE_DOWNLOAD_ROOT),
        release_api_url=RELEASE_API_URL,
    )
    assert accepted == StableVersion(0, 1, 0)

    previous_root = f"https://github.com/{PREVIOUS_REPOSITORY}/releases/download"
    with pytest.raises(ReleaseUpdateError, match="očekivanoj lokaciji"):
        _validate_release(
            _release_payload(previous_root),
            release_api_url=RELEASE_API_URL,
        )


def test_in_app_updater_starts_outside_install_folder(tmp_path, monkeypatch) -> None:
    install_root = tmp_path / "PogledAssist"
    install_root.mkdir()
    launched = {}
    monkeypatch.setattr(release_update, "is_update_supported", lambda _root: True)
    monkeypatch.setattr(release_update, "_powershell_executable", lambda: Path("powershell.exe"))

    def capture_launch(command, **options):
        launched["command"] = command
        launched["options"] = options

    monkeypatch.setattr(release_update.subprocess, "Popen", capture_launch)

    release_update.launch_release_update(install_root, process_id=42)

    assert launched["options"]["cwd"] == tmp_path
    assert str(install_root / "update_windows.ps1") in launched["command"]


def _release_payload(download_root: str) -> dict[str, object]:
    checksum_name = f"{ARTIFACT_NAME}.sha256"
    return {
        "draft": False,
        "prerelease": False,
        "tag_name": TAG,
        "assets": [
            {
                "name": ARTIFACT_NAME,
                "browser_download_url": f"{download_root}/{TAG}/{ARTIFACT_NAME}",
            },
            {
                "name": checksum_name,
                "browser_download_url": f"{download_root}/{TAG}/{checksum_name}",
            },
        ],
    }
