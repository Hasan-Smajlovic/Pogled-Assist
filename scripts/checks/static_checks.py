"""Python source checks shared by dev.ps1, pull request CI and release verification."""

from __future__ import annotations

import shutil
import subprocess
import sys
import sysconfig
import time
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON = "python"
# Each stage names its launcher: this interpreter, or a console script installed beside it.
STAGES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Ruff lint", PYTHON, ("-m", "ruff", "check", ".")),
    ("Ruff format", PYTHON, ("-m", "ruff", "format", "--check", ".")),
    (
        "Python compilation",
        PYTHON,
        ("-B", "-m", "compileall", "-q", "pogled_assist", "scripts", "tests", "run_gaze_mouse.py"),
    ),
    ("Types", PYTHON, ("-m", "basedpyright", "--pythonpath", sys.executable)),
    ("Import contracts", "lint-imports", ("--no-cache",)),
    (
        "Workflow security",
        "zizmor",
        ("--offline", "--config", ".github/zizmor.yml", "--min-severity", "low", ".github"),
    ),
)


def _command(launcher: str, arguments: Sequence[str]) -> list[str] | None:
    if launcher == PYTHON:
        return [sys.executable, *arguments]
    # PATH can point at another environment, so look only beside this interpreter.
    tool = shutil.which(launcher, path=sysconfig.get_path("scripts"))
    return None if tool is None else [tool, *arguments]


def run_stages(stages: Sequence[tuple[str, str, Sequence[str]]], root: Path) -> list[str]:
    """Run every stage, even after a failure, and return the names that failed."""
    failed = []
    for name, launcher, arguments in stages:
        print(f"Starting: {name}", flush=True)
        started = time.monotonic()
        command = _command(launcher, arguments)
        if command is None:
            print(
                f"{launcher} is not installed for {sys.executable}; install requirements-dev.txt."
            )
            exit_code = 1
        else:
            exit_code = subprocess.run(command, cwd=root, check=False).returncode
        status = "passed" if exit_code == 0 else f"FAILED with exit code {exit_code}"
        print(f"Finished: {name} ({status}, {time.monotonic() - started:.1f}s)", flush=True)
        if exit_code != 0:
            failed.append(name)
    return failed


def main() -> int:
    failed = run_stages(STAGES, REPO_ROOT)
    if failed:
        print("Failed static checks: " + ", ".join(failed))
        return 1
    print("Static checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
