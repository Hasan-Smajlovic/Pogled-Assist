from __future__ import annotations

import sys
from pathlib import Path

import pytest
from _powershell import powershell_literal, run_powershell_cases

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell is required")

CHECK_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "release" / "check_running_app_rejection.ps1"
)


@pytest.fixture(scope="module")
def rejection_results(tmp_path_factory):
    root = tmp_path_factory.mktemp("running-app-rejection")
    cases = {}
    for name, code, output in [
        (
            "wrapped",
            1,
            "Installation failed: Close Pogled Assist before inst\r\nalling or rolling back. Running process IDs: 1234",
        ),
        ("unexpected", 1, "Installation failed: Access denied"),
        ("success", 0, "Close Pogled Assist before installing"),
    ]:
        cases[name] = {
            "body": f"& {powershell_literal(CHECK_SCRIPT)} -ExitCode {code} -InstallerOutput {powershell_literal(output)}"
        }
    return run_powershell_cases(root, cases)


def test_running_app_check_accepts_word_wrapped_installer_error(rejection_results):
    result = rejection_results["wrapped"]
    assert result.returncode == 0, result.stdout + result.stderr


def test_running_app_check_rejects_unexpected_installer_failure(rejection_results):
    result = rejection_results["unexpected"]
    assert result.returncode != 0
    assert "unexpected reason" in result.stderr


def test_running_app_check_requires_failed_installer_exit(rejection_results):
    result = rejection_results["success"]
    assert result.returncode != 0
    assert "did not reject" in result.stderr
