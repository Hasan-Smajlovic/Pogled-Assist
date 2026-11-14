"""Reject additional baseline entries relative to the change's Git base."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ".basedpyright/baseline.json"
# Initial inventory from PR #137, after integrating development. Git's immutable blob
# avoids copying that inventory or accepting each PR's own replacement as the reference.
# Used only until the target branch contains a baseline; changing it needs human review.
ADOPTION_BASELINE_BLOB = "41c4a1c9af141129b5ddfe7f935532bb8714b307"


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


def comparison_ref(root: Path, base_ref: str) -> str:
    if _git(root, "rev-parse", "--is-shallow-repository") != "false":
        raise ValueError("Type baseline comparison requires full Git history; fetch --unshallow.")
    base = _git(root, "merge-base", "--", "HEAD", base_ref)
    if _git(root, "ls-tree", "--name-only", base, "--", BASELINE):
        return f"{base}:{BASELINE}"
    return ADOPTION_BASELINE_BLOB


def check(root: Path, base_ref: str) -> list[str]:
    reference = comparison_ref(root, base_ref)
    previous = entries(_git(root, "show", reference))
    current = entries((root / BASELINE).read_text(encoding="utf-8"))
    additions = current - previous
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
