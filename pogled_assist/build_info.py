"""One process-wide source identity, resolved before UI work or on a file worker."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

_identity: dict | None = None


def build_identity() -> dict:
    """Return cached primitives only; never run Git or access disk on a Qt callback."""
    return dict(
        _identity or {"app_version": "unknown", "build_revision": None, "build_dirty": None}
    )


def resolve_build_identity(root: Path | None = None) -> dict:
    global _identity
    if _identity is not None and root is None:
        return build_identity()
    root = root or (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[1]
    )
    result = {"app_version": "unknown", "build_revision": None, "build_dirty": None}
    try:
        result["app_version"] = (root / "VERSION").read_text(encoding="utf-8").strip()[:64]
        if getattr(sys, "frozen", False):
            payload = json.loads((root / "BUILD_INFO.json").read_text(encoding="utf-8"))
            revision, dirty = payload.get("build_revision"), payload.get("build_dirty")
            if payload.get("app_version") != result["app_version"]:
                raise ValueError("Build version mismatch")
            if revision is not None and not re.fullmatch(r"[0-9a-f]{40,64}", revision):
                raise ValueError("Invalid build revision")
            if dirty is not None and type(dirty) is not bool:
                raise ValueError("Invalid build state")
            result.update(build_revision=revision, build_dirty=dirty)
        else:
            options = dict(cwd=root, capture_output=True, text=True, timeout=2, check=True)
            if sys.platform == "win32":
                options["creationflags"] = subprocess.CREATE_NO_WINDOW
            revision = subprocess.run(["git", "rev-parse", "HEAD"], **options).stdout.strip()
            changed = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=normal"], **options
            ).stdout
            if re.fullmatch(r"[0-9a-f]{40,64}", revision):
                result.update(build_revision=revision, build_dirty=bool(changed.strip()))
    except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError):
        pass
    _identity = result
    return build_identity()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.write.write_text(
        json.dumps(resolve_build_identity(), indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
