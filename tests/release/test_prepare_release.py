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
    (work / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (work / "feature.txt").write_text("first release\n", encoding="utf-8")
    run_git(work, "add", "VERSION", "feature.txt")
    run_git(work, "commit", "-m", "First release")
    run_git(work, "switch", "-c", "development")
    (work / "history.txt").write_text("already released\n", encoding="utf-8")
    run_git(work, "add", "history.txt")
    run_git(work, "commit", "-m", "fix: previous release")
    run_git(work, "switch", "master")
    run_git(work, "merge", "--no-ff", "-m", "Previous release", "development")
    run_git(work, "tag", "v0.1.0")
    run_git(work, "push", "origin", "master", "v0.1.0")
    run_git(work, "switch", "development")
    (work / "feature.txt").write_text("first release\nsecond release\n", encoding="utf-8")
    run_git(work, "commit", "-am", "feat: second release")
    run_git(work, "push", "origin", "development")
    run_git(work, "switch", "master")
    return work


def run_prepare(work: Path, version: str, body_file: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), version, "--body-file", str(body_file)],
        cwd=work,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_prepared_branch_contains_both_parents_and_can_be_reused(release_repository: Path) -> None:
    work = release_repository
    body_file = work.parent / "release-pr.md"

    first = run_prepare(work, "0.2.0", body_file)

    assert first.returncode == 0, first.stderr
    assert first.stdout.strip() == "release/v0.2.0"
    assert run_git(work, "show", "origin/release/v0.2.0:VERSION") == "0.2.0"
    assert len(run_git(work, "rev-list", "--parents", "-n", "1", "release/v0.2.0~1").split()) == 3
    assert run_git(work, "merge-base", "--is-ancestor", "origin/master", "release/v0.2.0") == ""
    assert (
        run_git(work, "merge-base", "--is-ancestor", "origin/development", "release/v0.2.0") == ""
    )
    assert "feat: second release" in body_file.read_text(encoding="utf-8")
    assert run_git(work, "show", "origin/master:VERSION") == "0.1.0"
    assert run_git(work, "show", "origin/development:VERSION") == "0.1.0"

    run_git(work, "switch", "master")
    second = run_prepare(work, "0.2.0", body_file)
    assert second.returncode == 0, second.stderr
    assert run_git(work, "rev-parse", "origin/release/v0.2.0") == run_git(
        work, "rev-parse", "release/v0.2.0"
    )


def test_existing_tag_or_stale_branch_cannot_be_reused(release_repository: Path) -> None:
    work = release_repository
    body_file = work.parent / "release-pr.md"
    run_git(work, "tag", "v0.2.0")
    run_git(work, "push", "origin", "v0.2.0")
    tagged = run_prepare(work, "0.2.0", body_file)
    assert tagged.returncode != 0
    assert "Tag v0.2.0 already exists" in tagged.stderr

    run_git(work, "push", "origin", "master:refs/heads/release/v0.3.0")
    stale = run_prepare(work, "0.3.0", body_file)
    assert stale.returncode != 0
    assert "stale or has different content" in stale.stderr
    assert not body_file.exists()
