from __future__ import annotations

import sys
from pathlib import Path

import pytest
from _powershell import function_definitions, powershell_literal, run_powershell_cases

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


def test_package_timings_report_each_phase_and_restart_the_timer(tmp_path):
    build_script = CHECK_SCRIPT.with_name("build_windows_package.ps1")
    results = run_powershell_cases(
        tmp_path,
        {
            "timings": {
                "body": function_definitions(build_script)
                + r"""
$PhaseTimer = [pscustomobject]@{
    Elapsed = [pscustomobject]@{ TotalSeconds = 12.3 }
    Restarts = 0
}
$PhaseTimer | Add-Member ScriptMethod Restart {
    $this.Restarts++
    $this.Elapsed.TotalSeconds = 0.0
}
Write-PhaseTiming "ZIP archive"
if ($PhaseTimer.Elapsed.TotalSeconds -ne 0 -or $PhaseTimer.Restarts -ne 1) {
    throw "The next phase would include the archive time"
}
$PhaseTimer.Elapsed.TotalSeconds = 4.5
Write-PhaseTiming "ZIP extraction"
if ($PhaseTimer.Elapsed.TotalSeconds -ne 0 -or $PhaseTimer.Restarts -ne 2) {
    throw "The extraction timer was not restarted"
}
"""
            }
        },
    )

    result = results["timings"]
    assert result.returncode == 0, result.stdout + result.stderr
    # Decimal separators follow the Windows culture; each duration belongs to its phase.
    assert result.stdout.replace(",", ".").splitlines() == [
        "Package phase: ZIP archive (12.3s)",
        "Package phase: ZIP extraction (4.5s)",
    ]
