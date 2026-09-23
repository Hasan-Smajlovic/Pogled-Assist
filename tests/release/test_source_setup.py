from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="Source setup uses Windows PowerShell"
)

SETUP_SCRIPT = Path(__file__).resolve().parents[2] / "setup_windows.ps1"

# Exercise the real copy function without starting the elevated setup flow.
COPY_RUNNER = r"""
param([string]$SetupScript, [string]$SourcePath, [string]$TargetPath)

$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $SetupScript, [ref]$tokens, [ref]$errors
)
if ($errors.Count -gt 0) { throw "Could not parse setup script." }
$copyFunction = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Copy-ProjectToLocalInstallRoot"
}, $false)
if ($null -eq $copyFunction) { throw "Source copy function was not found." }
. ([scriptblock]::Create($copyFunction.Extent.Text))

function Write-Step { param([string]$Message) }
function Write-Info { param([string]$Message) }
function Write-Success { param([string]$Message) }
function Write-WarningLog { param([string]$Message) }

Copy-ProjectToLocalInstallRoot -SourcePath $SourcePath -TargetPath $TargetPath
"""


@pytest.mark.parametrize("legacy_user_data", [False, True])
def test_source_setup_replaces_old_package_without_losing_user_data(
    tmp_path: Path, legacy_user_data: bool
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "installed"
    (source / "pogled_assist").mkdir(parents=True)
    (source / "pogled_assist" / "__init__.py").write_text("# new package\n", encoding="utf-8")
    (source / "run_gaze_mouse.py").write_text("# new launcher\n", encoding="utf-8")
    (target / "gaze_mouse").mkdir(parents=True)
    (target / "gaze_mouse" / "__init__.py").write_text("# old package\n", encoding="utf-8")
    (target / "gaze_mouse" / "main.py").write_text("# old app\n", encoding="utf-8")
    if legacy_user_data:
        (target / "gaze_mouse" / "data").mkdir()
        (target / "gaze_mouse" / "data" / "speech_learning.json").write_bytes(b"legacy data")
    (target / "data").mkdir()
    (target / "logs").mkdir()
    (target / "data" / "speech_learning.json").write_bytes(b'{"keep":true}')
    (target / "logs" / "latest.txt").write_bytes(b"keep log\n")
    runner = tmp_path / "copy-source.ps1"
    runner.write_text(COPY_RUNNER, encoding="utf-8")

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(runner),
            "-SetupScript",
            str(SETUP_SCRIPT),
            "-SourcePath",
            str(source),
            "-TargetPath",
            str(target),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (target / "pogled_assist" / "__init__.py").read_text(encoding="utf-8") == (
        "# new package\n"
    )
    assert (target / "gaze_mouse").exists() is legacy_user_data
    if legacy_user_data:
        assert (target / "gaze_mouse" / "data" / "speech_learning.json").read_bytes() == (
            b"legacy data"
        )
    assert (target / "data" / "speech_learning.json").read_bytes() == b'{"keep":true}'
    assert (target / "logs" / "latest.txt").read_bytes() == b"keep log\n"
