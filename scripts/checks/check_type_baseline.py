"""Reject additional baseline entries relative to the change's Git base."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ".basedpyright/baseline.json"
SCRIPT = "scripts/checks/check_type_baseline.py"
DECLARATION_START = "^REVIEWED_INVENTORY = "
DECLARATION = re.compile(DECLARATION_START + ".*$", re.MULTILINE)
# A commit that changes the next line declares the baseline it contains a reviewed inventory.
# Checks whose comparison base predates that commit, such as a release after a squash merge,
# compare with that inventory instead. Change the line only for the adoption or a tool upgrade
# that moves diagnostics, in the commit that regenerates the baseline, and get human review.
REVIEWED_INVENTORY = "basedpyright 1.40.2 adoption, #136"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    ).stdout.strip()


def _declaration(root: Path, revision: str | None) -> str | None:
    if revision is None:
        script = root / SCRIPT
        text = script.read_text(encoding="utf-8") if script.exists() else ""
    elif _git(root, "ls-tree", "--name-only", revision, "--", SCRIPT):
        text = _git(root, "show", f"{revision}:{SCRIPT}")
    else:
        text = ""
    match = DECLARATION.search(text)
    return match.group(0) if match else None


def entries(content: str) -> Counter[tuple[str, str]]:
    """Keep path, diagnostic shape and multiplicity; total counts alone lose replacements."""
    data = json.loads(content)
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        raise ValueError("Invalid type baseline: expected a files mapping")
    result: Counter[tuple[str, str]] = Counter()
    for path, findings in data["files"].items():
        if not isinstance(findings, list):
            raise ValueError(f"Invalid type baseline findings: {path}")
        for finding in findings:
            if not isinstance(finding, dict) or not {"code", "range"} <= finding.keys():
                raise ValueError(f"Invalid type baseline entry: {path}")
            result[path, json.dumps(finding, sort_keys=True)] += 1
    return result


def comparison_ref(root: Path, base_ref: str) -> str | None:
    """Name the inventory to compare with; None when uncommitted edits declare a new one."""
    if _git(root, "rev-parse", "--is-shallow-repository") != "false":
        raise ValueError("Type baseline comparison requires full Git history; fetch --unshallow.")
    base = _git(root, "merge-base", "--", "HEAD", base_ref)
    if _declaration(root, None) != _declaration(root, "HEAD"):
        return None
    declared = _git(
        root,
        "log",
        "-1",
        "--topo-order",
        "--format=%H",
        f"-G{DECLARATION_START}",
        f"{base}..HEAD",
        "--",
        SCRIPT,
    )
    if declared:
        return f"{declared}:{BASELINE}"
    if _git(root, "ls-tree", "--name-only", base, "--", BASELINE):
        return f"{base}:{BASELINE}"
    raise ValueError(
        f"{base_ref} has no type baseline and no commit since it declares a reviewed inventory"
    )


def check(root: Path, base_ref: str) -> list[str]:
    reference = comparison_ref(root, base_ref)
    current = entries((root / BASELINE).read_text(encoding="utf-8"))
    if reference is None:
        return []
    additions = current - entries(_git(root, "show", reference))
    return [
        f"{path}: {count} new baseline entry/entries: {finding}"
        for (path, finding), count in sorted(additions.items())
    ]


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", default="origin/development")
    args = parser.parse_args(arguments)
    try:
        errors = check(ROOT, args.base_ref)
    except subprocess.CalledProcessError as error:
        print(f"Cannot verify type baseline: {(error.stderr or '').strip() or error}")
        print(
            f"Fetch {args.base_ref} with full history, or pass --base-ref. "
            "See docs/DEVELOPMENT.md#type-baseline-comparison."
        )
        return 1
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Cannot verify type baseline: {error}")
        return 1
    for error in errors:
        print(error)
    if errors:
        print("Fix new errors instead of adding them to the baseline. See docs/DEVELOPMENT.md.")
    else:
        print("Type baseline contains no additional entries.")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
