from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell is required")

ROOT = Path(__file__).resolve().parents[2]
SOURCE_SETUP = ROOT / "setup_windows.ps1"
PACKAGE_LAUNCHER = ROOT / "packaging" / "windows" / "start_gaze_mouse.ps1"

SOURCE_DISCOVERY_RUNNER = r"""
param([string]$SetupScript, [string]$NewPath, [string]$LegacyPath)

$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $SetupScript, [ref]$tokens, [ref]$errors
)
if ($errors.Count -gt 0) { throw "Could not parse source setup." }
$discovery = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Get-Python310X86"
}, $false)
if ($null -eq $discovery) { throw "Source x86 discovery was not found." }
. ([scriptblock]::Create($discovery.Extent.Text))

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


def _run_runner(tmp_path: Path, name: str, script: str, *args: str) -> str:
    runner = tmp_path / name
    runner.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(runner),
            *args,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip().splitlines()[-1]


@pytest.mark.parametrize(
    ("new_path", "expected"),
    [("NONE", "legacy-python"), ("invalid-new", "legacy-python"), ("new-python", "new-python")],
)
def test_source_setup_accepts_old_bridge_runtime_path(tmp_path, new_path, expected):
    found = _run_runner(
        tmp_path,
        "source-discovery.ps1",
        SOURCE_DISCOVERY_RUNNER,
        "-SetupScript",
        str(SOURCE_SETUP),
        "-NewPath",
        new_path,
        "-LegacyPath",
        "legacy-python",
    )
    assert found == expected


@pytest.mark.parametrize("new_path", ["NONE", "missing-python.exe"])
def test_package_launcher_uses_old_bridge_runtime_path(tmp_path, new_path):
    legacy = tmp_path / "legacy-python.exe"
    legacy.touch()
    found = _run_runner(
        tmp_path,
        "package-discovery.ps1",
        PACKAGE_DISCOVERY_RUNNER,
        "-LauncherScript",
        str(PACKAGE_LAUNCHER),
        "-NewPath",
        new_path,
        "-LegacyPath",
        str(legacy),
        "-Root",
        str(tmp_path),
    )
    assert found == str(legacy)


def test_package_launcher_keeps_new_bridge_runtime_path(tmp_path):
    current = tmp_path / "current-python.exe"
    current.touch()
    legacy = tmp_path / "legacy-python.exe"
    legacy.touch()
    found = _run_runner(
        tmp_path,
        "package-discovery.ps1",
        PACKAGE_DISCOVERY_RUNNER,
        "-LauncherScript",
        str(PACKAGE_LAUNCHER),
        "-NewPath",
        str(current),
        "-LegacyPath",
        str(legacy),
        "-Root",
        str(tmp_path),
    )
    assert found == str(current)
