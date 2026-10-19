from __future__ import annotations

import sys

import pytest
from _powershell import powershell_literal, run_powershell_cases

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell is required")


@pytest.fixture(scope="module")
def batch_results(tmp_path_factory):
    root = tmp_path_factory.mktemp("batch space ' quote")
    cases = {
        "failure": {
            "body": """
$env:POGLED_ASSIST_TEST_BATCH_VALUE = "leaked"
function Synthetic-BatchMock { "leaked" }
Set-Location ..
throw "designated failure"
""",
        },
        "after-failure": {
            "body": """
if (Test-Path Env:POGLED_ASSIST_TEST_BATCH_VALUE) { throw "Environment leaked" }
if (Get-Command Synthetic-BatchMock -ErrorAction SilentlyContinue) { throw "Function leaked" }
if ((Split-Path -Leaf (Get-Location).Path) -ne "after-failure") { throw "Wrong directory" }
"continued"
""",
        },
        "streams": {
            "env": {"POGLED_ASSIST_TEST_BATCH_VALUE": "case value"},
            "body": """
Write-Warning "warning captured"
Write-Information "information captured" -InformationAction Continue
Write-Host "host captured"
$env:POGLED_ASSIST_TEST_BATCH_VALUE
"""
            + powershell_literal("ČĆ test's value"),
        },
    }
    return run_powershell_cases(root, cases)


@pytest.mark.parametrize("case", ["failure", "after-failure", "streams"])
def test_batch_keeps_case_results_and_state_independent(batch_results, case):
    result = batch_results[case]
    if case == "failure":
        assert result.returncode != 0
        assert "designated failure" in result.stderr
    elif case == "after-failure":
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout == "continued"
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        for expected in (
            "warning captured",
            "information captured",
            "host captured",
            "case value",
            "ČĆ test's value",
        ):
            assert expected in result.stdout
