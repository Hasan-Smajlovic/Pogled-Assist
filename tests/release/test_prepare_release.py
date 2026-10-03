from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "release" / "prepare_release.py"


def run_git(directory: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=directory,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def release_repository(tmp_path: Path) -> Path:
    remote = tmp_path / "origin.git"
    work = tmp_path / "work"
    run_git(tmp_path, "init", "--bare", str(remote))
    run_git(tmp_path, "clone", str(remote), str(work))
    run_git(work, "config", "user.name", "Release Test")
    run_git(work, "config", "user.email", "release-test@example.invalid")
    run_git(work, "config", "commit.gpgsign", "false")
    run_git(work, "switch", "-c", "master")
    (work / "VERSION").write_text("0.4.7\n", encoding="utf-8")
    (work / "feature.txt").write_text("first release\n", encoding="utf-8")
    run_git(work, "add", "VERSION", "feature.txt")
    run_git(work, "commit", "-m", "First release")
    run_git(work, "switch", "-c", "development")
    (work / "history.txt").write_text("already released\n", encoding="utf-8")
    run_git(work, "add", "history.txt")
    run_git(work, "commit", "-m", "fix: previous release")
    run_git(work, "switch", "master")
    run_git(work, "merge", "--no-ff", "-m", "Previous release", "development")
    run_git(work, "tag", "v0.4.7")
    run_git(work, "push", "origin", "master", "v0.4.7")
    run_git(work, "switch", "development")
    (work / "feature.txt").write_text("first release\nsecond release\n", encoding="utf-8")
    run_git(work, "commit", "-am", "feat: second release")
    run_git(work, "push", "origin", "development")
    run_git(work, "switch", "master")
    return work


def run_prepare(work: Path, bump: str, body_file: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), bump, "--body-file", str(body_file)],
        cwd=work,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@pytest.mark.parametrize(
    ("bump", "version"), [("patch", "0.4.8"), ("minor", "0.5.0"), ("major", "1.0.0")]
)
def test_prepared_branch_contains_both_parents_and_can_be_reused(
    release_repository: Path, bump: str, version: str
) -> None:
    work = release_repository
    body_file = work.parent / "release-pr.md"

    first = run_prepare(work, bump, body_file)

    assert first.returncode == 0, first.stderr
    branch = f"release/v{version}"
    assert first.stdout.strip() == branch
    assert run_git(work, "show", f"origin/{branch}:VERSION") == version
    assert len(run_git(work, "rev-list", "--parents", "-n", "1", f"{branch}~1").split()) == 3
    assert run_git(work, "merge-base", "--is-ancestor", "origin/master", branch) == ""
    assert run_git(work, "merge-base", "--is-ancestor", "origin/development", branch) == ""
    assert "feat: second release" in body_file.read_text(encoding="utf-8")
    assert run_git(work, "show", "origin/master:VERSION") == "0.4.7"
    assert run_git(work, "show", "origin/development:VERSION") == "0.4.7"

    run_git(work, "switch", "master")
    second = run_prepare(work, bump, body_file)
    assert second.returncode == 0, second.stderr
    assert run_git(work, "rev-parse", f"origin/{branch}") == run_git(work, "rev-parse", branch)


def test_existing_tag_or_stale_branch_cannot_be_reused(release_repository: Path) -> None:
    work = release_repository
    body_file = work.parent / "release-pr.md"
    run_git(work, "tag", "v0.5.0")
    run_git(work, "push", "origin", "v0.5.0")
    tagged = run_prepare(work, "minor", body_file)
    assert tagged.returncode != 0
    assert "Tag v0.5.0 already exists" in tagged.stderr

    run_git(work, "push", "origin", "master:refs/heads/release/v1.0.0")
    stale = run_prepare(work, "major", body_file)
    assert stale.returncode != 0
    assert "stale or has different content" in stale.stderr
    assert not body_file.exists()


def test_retry_from_an_old_master_cannot_prepare_another_version(release_repository: Path) -> None:
    work = release_repository
    body_file = work.parent / "release-pr.md"
    dispatched_master = run_git(work, "rev-parse", "HEAD")
    prepared = run_prepare(work, "minor", body_file)
    assert prepared.returncode == 0, prepared.stderr

    run_git(work, "switch", "master")
    run_git(work, "merge", "--no-ff", "-m", "Release v0.5.0", "release/v0.5.0")
    run_git(work, "push", "origin", "master")
    run_git(work, "switch", "--detach", dispatched_master)

    retried = run_prepare(work, "minor", body_file)

    assert retried.returncode != 0
    assert "latest master commit" in retried.stderr
    assert not run_git(work, "ls-remote", "origin", "refs/heads/release/v0.6.0")
