from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest

from pogled_assist import release_update as releases
from pogled_assist.release_update import ReleaseCheckResult, ReleaseUpdateError, StableVersion


def release(version, **changes):
    tag = f"v{version}"
    name = f"PogledAssist-{tag}-windows-x64.zip"
    payload = {
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": asset,
                "browser_download_url": f"{releases.RELEASE_DOWNLOAD_ROOT}/{tag}/{asset}",
            }
            for asset in (name, name + ".sha256")
        ],
    }
    return {**payload, **changes}


def test_catalogue_pages_filters_and_sorts_versions_numerically(tmp_path, monkeypatch):
    (tmp_path / "VERSION").write_text("0.3.5", encoding="utf-8")
    bad_url = release("0.9.0")
    bad_url["assets"][0]["browser_download_url"] = "https://example.invalid/package.zip"
    first = [
        release("0.3.5"),
        release("0.10.0"),
        release("0.4.0", prerelease=True),
        release("0.8.0", assets=[]),
        bad_url,
    ]
    first.extend([release("0.5.0", draft=True)] * (100 - len(first)))
    pages = [first, [release("0.1.0"), release("0.3.5")]]
    requests = []

    def fetch(request, **_options):
        requests.append(request.full_url)
        return io.BytesIO(json.dumps(pages.pop(0)).encode())

    monkeypatch.setattr(releases.urllib.request, "urlopen", fetch)
    result = releases.check_available_releases(tmp_path)
    assert result.versions == (
        StableVersion(0, 10, 0),
        StableVersion(0, 3, 5),
        StableVersion(0, 1, 0),
    )
    assert result.installed_version == StableVersion(0, 3, 5)
    assert result.update_available
    assert requests == [
        f"{releases.RELEASE_LIST_API_URL}?per_page=100&page={page}" for page in (1, 2)
    ]


@pytest.mark.parametrize("payload", [{}, [], [release("0.1.0", draft=True)]])
def test_failed_or_empty_catalogue_never_claims_app_is_current(tmp_path, monkeypatch, payload):
    (tmp_path / "VERSION").write_text("0.3.5", encoding="utf-8")
    monkeypatch.setattr(
        releases.urllib.request,
        "urlopen",
        lambda *_args, **_kw: io.BytesIO(json.dumps(payload).encode()),
    )
    with pytest.raises(ReleaseUpdateError):
        releases.check_available_releases(tmp_path)


def test_network_failure_keeps_installed_version_readable(tmp_path, monkeypatch):
    (tmp_path / "VERSION").write_text("0.3.5", encoding="utf-8")

    def offline(*_args, **_options):
        raise OSError("offline")

    monkeypatch.setattr(releases.urllib.request, "urlopen", offline)
    with pytest.raises(ReleaseUpdateError, match="internet"):
        releases.check_available_releases(tmp_path)
    assert releases.ReleaseUpdateManager(tmp_path).installed_version == StableVersion(0, 3, 5)


def test_preparation_waits_for_verified_package_and_needs_restart_authorization(
    qtbot, tmp_path, monkeypatch
):
    selected = StableVersion(0, 1, 0)
    manager = releases.ReleaseUpdateManager(tmp_path)
    manager._result = ReleaseCheckResult(
        StableVersion(0, 3, 5), StableVersion(0, 3, 5), (selected,)
    )
    directory = tmp_path / "request"
    directory.mkdir()
    monkeypatch.setattr(releases.tempfile, "mkdtemp", lambda **_options: str(directory))
    launched = []
    monkeypatch.setattr(
        releases,
        "launch_release_update",
        lambda *args, **options: launched.append(options) or SimpleNamespace(poll=lambda: None),
    )
    manager.prepare(selected)
    qtbot.waitUntil(lambda: len(launched) == 1)
    assert not manager.ready
    assert not (directory / "install").exists()
    with pytest.raises(ReleaseUpdateError, match="spreman"):
        manager.authorize_restart()
    (directory / "ready.json").write_text('{"ready":true}', encoding="utf-8")
    qtbot.waitUntil(lambda: manager.ready)
    assert launched[0]["version"] == selected
    assert not (directory / "install").exists()
    manager.authorize_restart()
    assert (directory / "install").exists()
    manager.finish_cancel()


def test_cancel_ignores_late_preparation_result(qtbot, tmp_path):
    manager = releases.ReleaseUpdateManager(tmp_path)
    manager._control_directory = tmp_path
    manager._installing = True
    notices = []
    manager.install_ready.connect(lambda: notices.append("ready"))
    manager.finish_cancel()
    manager._prepare_done.emit(tmp_path, None)
    assert notices == []
    assert not manager.ready
    assert (tmp_path / "cancel").exists()


def test_preparation_error_does_not_authorize_restart(qtbot, tmp_path):
    manager = releases.ReleaseUpdateManager(tmp_path)
    manager._control_directory = tmp_path
    manager._installing = True
    failures = []
    manager.install_failed.connect(failures.append)
    manager._prepare_done.emit(tmp_path, "Checksum mismatch")
    assert failures == ["Checksum mismatch"]
    assert not manager.ready
    assert not (tmp_path / "install").exists()


def test_preparation_directory_error_keeps_manager_available(qtbot, tmp_path, monkeypatch):
    selected = StableVersion(0, 1, 0)
    manager = releases.ReleaseUpdateManager(tmp_path)
    manager._result = ReleaseCheckResult(selected, selected, (selected,))

    def unavailable(**_options):
        raise OSError("disk full")

    monkeypatch.setattr(releases.tempfile, "mkdtemp", unavailable)
    with pytest.raises(ReleaseUpdateError, match="slobodan prostor"):
        manager.prepare(selected)
    assert not manager.ready
    assert not manager._installing
