from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell is required")

CHECK_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "release" / "check_running_app_rejection.ps1"
)


def _check_rejection(exit_code: int, output: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(CHECK_SCRIPT),
            "-ExitCode",
            str(exit_code),
            "-InstallerOutput",
            output,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_running_app_check_accepts_word_wrapped_installer_error() -> None:
    output = (
        "Installation failed: Close Pogled Assist before inst\r\n"
        "alling or rolling back. Running process IDs: 1234"
    )

    result = _check_rejection(1, output)

    assert result.returncode == 0, result.stdout + result.stderr


def test_running_app_check_rejects_unexpected_installer_failure() -> None:
    result = _check_rejection(1, "Installation failed: Access denied")

    assert result.returncode != 0
    assert "unexpected reason" in result.stderr


def test_running_app_check_requires_failed_installer_exit() -> None:
    result = _check_rejection(0, "Close Pogled Assist before installing")

    assert result.returncode != 0
    assert "did not reject" in result.stderr
