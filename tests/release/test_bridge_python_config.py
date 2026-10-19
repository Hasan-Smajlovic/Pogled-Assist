from __future__ import annotations

import sys
from pathlib import Path

import pytest
from _powershell import powershell_literal, run_powershell_cases

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell is required")

ROOT = Path(__file__).resolve().parents[2]
SOURCE_SETUP = ROOT / "setup_windows.ps1"
PACKAGE_LAUNCHER = ROOT / "packaging" / "windows" / "start_gaze_mouse.ps1"

SOURCE_DISCOVERY_RUNNER = r"""
param([string]$SetupScript, [string]$NewPath, [string]$LegacyPath)

$ErrorActionPreference = "Stop"
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $SetupScript, [ref]$tokens, [ref]$errors
)
if ($errors.Count -gt 0) { throw "Could not parse source setup." }
foreach ($statement in $ast.EndBlock.Statements) {
    if ($statement -is [System.Management.Automation.Language.FunctionDefinitionAst]) {
        . ([scriptblock]::Create($statement.Extent.Text))
    }
}

function Write-Step { param([string]$Message) }
function Write-Info { param([string]$Message) }
function Write-Success { param([string]$Message) }
function Test-Python310X86Executable {
    param([string]$PythonPath)
    if ($PythonPath -in @("new-python", "legacy-python")) { return $PythonPath }
    return $null
}

if ($NewPath -eq "NONE") {
    Remove-Item Env:POGLED_ASSIST_X86_PYTHON -ErrorAction SilentlyContinue
} else {
    $env:POGLED_ASSIST_X86_PYTHON = $NewPath
}
$env:TOBII_GAZE_MOUSE_X86_PYTHON = $LegacyPath
Get-Python310X86
"""

PACKAGE_DISCOVERY_RUNNER = r"""
param([string]$LauncherScript, [string]$NewPath, [string]$LegacyPath, [string]$Root)

$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $LauncherScript, [ref]$tokens, [ref]$errors
)
if ($errors.Count -gt 0) { throw "Could not parse package launcher." }
$finder = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Find-FirstFile"
}, $false)
$discovery = $ast.EndBlock.Statements | Where-Object {
    $_ -is [System.Management.Automation.Language.IfStatementAst] -and
        $_.Extent.Text.Contains('$env:POGLED_ASSIST_X86_PYTHON')
} | Select-Object -First 1
if ($null -eq $finder -or $null -eq $discovery) { throw "Package x86 discovery was not found." }
. ([scriptblock]::Create($finder.Extent.Text))

$env:LOCALAPPDATA = $Root
$AppRoot = $Root
$env:ProgramFiles = $Root
[Environment]::SetEnvironmentVariable("ProgramFiles(x86)", $Root)
if ($NewPath -eq "NONE") {
    Remove-Item Env:POGLED_ASSIST_X86_PYTHON -ErrorAction SilentlyContinue
} else {
    $env:POGLED_ASSIST_X86_PYTHON = $NewPath
}
$env:TOBII_GAZE_MOUSE_X86_PYTHON = $LegacyPath
. ([scriptblock]::Create($discovery.Extent.Text))
$env:POGLED_ASSIST_X86_PYTHON
"""


@pytest.fixture(scope="module")
def bridge_discovery_results(tmp_path_factory):
    root = tmp_path_factory.mktemp("bridge-discovery")
    results = {}
    for kind, source in [
        ("source", SOURCE_DISCOVERY_RUNNER),
        ("package", PACKAGE_DISCOVERY_RUNNER),
    ]:
        batch = root / kind
        batch.mkdir()
        runner = batch / "discovery.ps1"
        runner.write_text(source, encoding="utf-8")
        cases = {}
        expected = {}
        for name in ("missing", "invalid", "new"):
            directory = batch / name
            directory.mkdir()
            legacy = directory / "legacy-python.exe"
            legacy.touch()
            current = directory / "current-python.exe"
            current.touch()
            new = {
                "missing": "NONE",
                "invalid": "invalid-new",
                "new": "new-python" if kind == "source" else str(current),
            }[name]
            old = "legacy-python" if kind == "source" else str(legacy)
            expected[name] = new if name == "new" else old
            args = (
                {"SetupScript": str(SOURCE_SETUP)}
                if kind == "source"
                else {"LauncherScript": str(PACKAGE_LAUNCHER), "Root": str(directory)}
            )
            args.update(NewPath=new, LegacyPath=old)
            body = "& '../discovery.ps1' " + " ".join(
                f"-{key} {powershell_literal(value)}" for key, value in args.items()
            )
            cases[name] = {"body": body}
        results[kind] = (run_powershell_cases(batch, cases), expected)
    return results


@pytest.mark.parametrize("case", ["missing", "invalid", "new"])
def test_source_setup_accepts_old_bridge_runtime_path(bridge_discovery_results, case):
    results, expected = bridge_discovery_results["source"]
    result = results[case]
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().splitlines()[-1] == expected[case]


@pytest.mark.parametrize("case", ["missing", "invalid"])
def test_package_launcher_uses_old_bridge_runtime_path(bridge_discovery_results, case):
    results, expected = bridge_discovery_results["package"]
    result = results[case]
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().splitlines()[-1] == expected[case]


def test_package_launcher_keeps_new_bridge_runtime_path(bridge_discovery_results):
    results, expected = bridge_discovery_results["package"]
    result = results["new"]
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().splitlines()[-1] == expected["new"]
