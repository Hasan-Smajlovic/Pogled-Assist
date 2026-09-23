"""Prepare a reviewed release branch without changing protected branches."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

VERSION_PATTERN = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"


def git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"git {' '.join(arguments)} failed: {detail}")
    return result


def version_parts(value: str) -> tuple[int, int, int]:
    match = VERSION_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError("Version must be MAJOR.MINOR.PATCH without a v prefix or suffix.")
    return tuple(int(part) for part in match.groups())


def remote_ref_exists(ref: str) -> bool:
    result = git("ls-remote", "--exit-code", "origin", ref, check=False)
    if result.returncode not in (0, 2):
        raise RuntimeError(f"Could not inspect remote ref {ref}: {result.stderr.strip()}")
    return result.returncode == 0


def is_ancestor(ancestor: str, descendant: str) -> bool:
    result = git("merge-base", "--is-ancestor", ancestor, descendant, check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError(
            f"Could not compare {ancestor} with {descendant}: {result.stderr.strip()}"
        )
    return result.returncode == 0


def prepare_release(version: str, body_file: Path) -> str:
    requested = version_parts(version)
    branch = f"release/v{version}"
    if git("status", "--porcelain").stdout.strip():
        raise RuntimeError("The checkout must be clean before preparing a release.")

    git("fetch", "origin", "--prune", "--tags")
    master = git("rev-parse", "origin/master").stdout.strip()
    if git("rev-parse", "HEAD").stdout.strip() != master:
        raise RuntimeError("Run this from the latest master commit, then retry.")

    current_version = git("show", "origin/master:VERSION").stdout.strip()
    if requested <= version_parts(current_version):
        raise ValueError(f"Version {version} must be newer than master ({current_version}).")
    if remote_ref_exists(f"refs/tags/v{version}"):
        raise ValueError(f"Tag v{version} already exists. Choose a new version.")
    if is_ancestor("origin/development", "origin/master"):
        raise RuntimeError("Development has no unreleased commits.")

    subjects = git("log", "--format=%s", "origin/master..origin/development").stdout.splitlines()
    remote_branch = f"refs/heads/{branch}"
    if remote_ref_exists(remote_branch):
        git("fetch", "origin", f"{remote_branch}:refs/remotes/origin/{branch}")
        prepared_ref = f"origin/{branch}"
        prepared_version = git("show", f"{prepared_ref}:VERSION").stdout.strip()
        if (
            prepared_version != version
            or not is_ancestor("origin/master", prepared_ref)
            or not is_ancestor("origin/development", prepared_ref)
        ):
            raise RuntimeError(
                f"{branch} exists but is stale or has different content. Review it manually."
            )
    else:
        git("switch", "-c", branch, "origin/master")
        git(
            "-c",
            f"user.name={BOT_NAME}",
            "-c",
            f"user.email={BOT_EMAIL}",
            "-c",
            "commit.gpgsign=false",
            "merge",
            "--no-ff",
            "-m",
            f"Merge development for v{version}",
            "origin/development",
        )
        Path("VERSION").write_text(f"{version}\n", encoding="utf-8")
        git("add", "--", "VERSION")
        git(
            "-c",
            f"user.name={BOT_NAME}",
            "-c",
            f"user.email={BOT_EMAIL}",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            f"chore(release): prepare v{version}",
        )
        git("push", "origin", f"HEAD:{remote_branch}")

    changes = "\n".join(f"- {subject}" for subject in reversed(subjects))
    body_file.write_text(
        f"## Outcome\n\nPrepare Pogled Assist v{version} from the reviewed development branch.\n\n"
        f"## Included changes\n\n{changes}\n\n"
        "## Compatibility and risk\n\nReview the merged diff and confirm installation, "
        "update, rollback, gaze, input, speech, and settings compatibility.\n\n"
        "## Verification\n\n"
        "- Automated: PR code-quality, tests, and windows-package checks pending.\n"
        "- Manual Windows: Not run. Record results before review is complete.\n"
        "- Manual Tobii hardware: Not run. Record results before review is complete.\n\n"
        "## Release review\n\n"
        "- [ ] Check the exact diff and version.\n"
        "- [ ] Record manual checks and known limitations.\n"
        "- [ ] Obtain an independent approval, then merge with a merge commit.\n",
        encoding="utf-8",
    )
    return branch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="New semantic version without the v prefix")
    parser.add_argument("--body-file", type=Path, required=True)
    args = parser.parse_args()
    print(prepare_release(args.version, args.body_file))


if __name__ == "__main__":
    main()
