from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="dev.ps1 uses Windows PowerShell")

DEV_SCRIPT = Path(__file__).resolve().parents[2] / "dev.ps1"
PACKAGE_SCRIPT = DEV_SCRIPT.parent / "scripts" / "release" / "build_windows_package.ps1"


def _run_dev_script(tmp_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    shutil.copy2(DEV_SCRIPT, tmp_path / "dev.ps1")
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "dev.ps1",
            *arguments,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )


def test_lint_reports_broken_virtual_environment_before_running_checks(tmp_path: Path) -> None:
    python_path = tmp_path / ".venv" / "Scripts" / "python.exe"
    python_path.parent.mkdir(parents=True)
    python_path.write_bytes(b"not a Python executable")

    result = _run_dev_script(tmp_path, "lint")

    assert result.returncode != 0
    assert "Development environment is broken or unsupported" in result.stderr
    assert python_path.read_bytes() == b"not a Python executable"


def test_setup_rejects_missing_base_without_moving_existing_environment(tmp_path: Path) -> None:
    python_path = tmp_path / ".venv" / "Scripts" / "python.exe"
    python_path.parent.mkdir(parents=True)
    python_path.write_bytes(b"not a Python executable")

    result = _run_dev_script(tmp_path, "setup", "-BasePython", str(tmp_path / "missing.exe"))

    assert result.returncode != 0
    assert "Base Python was not found" in result.stderr
    assert python_path.read_bytes() == b"not a Python executable"
    assert not (tmp_path / ".dev-tools").exists()


def test_python_probe_works_with_legacy_powershell_argument_passing(tmp_path: Path) -> None:
    shutil.copy2(DEV_SCRIPT, tmp_path / "dev.ps1")
    script_path = str(tmp_path / "dev.ps1").replace("'", "''")
    python_path = sys.executable.replace("'", "''")
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            f". '{script_path}' help | Out-Null; Get-PythonVersion -Executable '{python_path}'",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == f"{sys.version_info.major}.{sys.version_info.minor}"


def test_base_python_probe_resolves_the_interpreter_behind_a_venv(tmp_path: Path) -> None:
    shutil.copy2(DEV_SCRIPT, tmp_path / "dev.ps1")
    script_path = str(tmp_path / "dev.ps1").replace("'", "''")
    python_path = sys.executable.replace("'", "''")
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            f". '{script_path}' help | Out-Null; Get-PythonBaseExecutable -Executable '{python_path}'",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert Path(result.stdout.strip()).resolve() == Path(sys._base_executable).resolve()


@pytest.mark.parametrize(
    ("current_version", "same_base", "should_recreate"),
    [("3.10", True, False), ("3.10", False, True), ("3.12", True, True)],
)
def test_setup_uses_the_requested_base_interpreter(
    tmp_path: Path, current_version: str, same_base: bool, should_recreate: bool
) -> None:
    shutil.copy2(DEV_SCRIPT, tmp_path / "dev.ps1")
    python_path = tmp_path / ".venv" / "Scripts" / "python.exe"
    python_path.parent.mkdir(parents=True)
    python_path.write_bytes(b"old environment")
    requested_path = tmp_path / "requested-python.exe"
    requested_path.write_bytes(b"requested base")
    analyzer_path = (
        tmp_path / ".dev-tools" / "PSScriptAnalyzer" / "1.25.0" / "PSScriptAnalyzer.psd1"
    )
    analyzer_path.parent.mkdir(parents=True)
    analyzer_path.write_text("test", encoding="utf-8")
    check_script = tmp_path / "scripts" / "checks" / "check_github_actions.ps1"
    check_script.parent.mkdir(parents=True)
    check_script.write_text("", encoding="utf-8")
    driver = tmp_path / "run-setup.ps1"
    driver.write_text(
        """
. (Join-Path $PSScriptRoot "dev.ps1") help | Out-Null
$BasePython = Join-Path $PSScriptRoot "requested-python.exe"
$script:ProbeVersion = "CURRENT_VERSION"
$script:SameBase = $SAME_BASE
$script:EnvironmentCreated = $false
$script:CommandLog = Join-Path $PSScriptRoot "commands.txt"
function Resolve-BasePython { return $BasePython }
function Get-PythonVersion {
    param([string]$Executable)
    if ($script:EnvironmentCreated) { return "3.10" }
    return $script:ProbeVersion
}
function Get-PythonBaseExecutable {
    param([string]$Executable)
    if ($Executable -eq $PythonPath -or $script:SameBase) { return "C:\\python-a\\python.exe" }
    return "C:\\python-b\\python.exe"
}
function Invoke-ExternalCommand {
    param([string]$FilePath, [string[]]$ArgumentList)
    Add-Content -LiteralPath $script:CommandLog -Value "$FilePath $($ArgumentList -join ' ')"
    if ($ArgumentList[1] -eq "venv") {
        $script:EnvironmentCreated = $true
        New-Item -ItemType Directory -Path (Split-Path -Parent $PythonPath) -Force | Out-Null
        Set-Content -LiteralPath $PythonPath -Value "new environment"
    }
}
Install-DevEnvironment
""".replace("CURRENT_VERSION", current_version).replace(
            "$SAME_BASE", "$true" if same_base else "$false"
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(driver)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    commands = (tmp_path / "commands.txt").read_text(encoding="utf-8")
    backups = list((tmp_path / ".dev-tools" / "venv-backups").glob("*/Scripts/python.exe"))
    if should_recreate:
        assert "-m venv" in commands
        assert python_path.read_text(encoding="utf-8").strip() == "new environment"
        assert len(backups) == 1
        assert backups[0].read_bytes() == b"old environment"
    else:
        assert "-m venv" not in commands
        assert python_path.read_bytes() == b"old environment"
        assert backups == []
    assert "-m pip install" in commands


@pytest.mark.skipif(
    sys.version_info[:2] != (3, 10) or sys.maxsize <= 2**32,
    reason="The release package requires 64-bit Python 3.10",
)
def test_package_probe_accepts_python_310_with_legacy_powershell_argument_passing() -> None:
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PACKAGE_SCRIPT),
            "-PythonPath",
            sys.executable,
            "-OutputDirectory",
            str(DEV_SCRIPT.parent.parent),
        ],
        cwd=DEV_SCRIPT.parent,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "OutputDirectory must be inside the repository" in result.stderr


@pytest.mark.skipif(sys.version_info[:2] == (3, 10), reason="This Python can build releases")
def test_package_rejects_newer_python_before_using_output_directory(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PACKAGE_SCRIPT),
            "-PythonPath",
            sys.executable,
            "-OutputDirectory",
            str(tmp_path),
        ],
        cwd=DEV_SCRIPT.parent,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Windows packaging requires 64-bit Python 3.10" in result.stderr
    assert not list(tmp_path.iterdir())
