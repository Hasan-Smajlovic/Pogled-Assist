from __future__ import annotations

import json
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


def test_package_rejects_newer_python_before_using_output_directory(tmp_path: Path) -> None:
    probe = tmp_path / "unsupported-python.ps1"
    probe.write_text(
        'param([string]$c)\n$global:LASTEXITCODE = 0\nWrite-Output "3.12"\n', encoding="utf-8"
    )
    output = tmp_path / "output"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_bytes(b"existing output")
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PACKAGE_SCRIPT),
            "-PythonPath",
            str(probe),
            "-OutputDirectory",
            str(output),
        ],
        cwd=DEV_SCRIPT.parent,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Windows packaging requires 64-bit Python 3.10" in result.stderr
    assert "OutputDirectory must be inside the repository" not in result.stderr
    assert list(output.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b"existing output"


def _run_dev_driver(tmp_path: Path, body: str) -> subprocess.CompletedProcess[str]:
    shutil.copy2(DEV_SCRIPT, tmp_path / "dev.ps1")
    driver = tmp_path / "driver.ps1"
    driver.write_text(
        '. (Join-Path $PSScriptRoot "dev.ps1") help | Out-Null\n' + body,
        encoding="utf-8",
    )
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(driver)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("workers", "coverage", "expected", "pytest_options"),
    [
        (1, False, "0", "--ignore=tests/tooling --cov-fail-under=0"),
        (2, False, "2", None),
        (2, True, "2", "--ignore=tests/tooling --cov-fail-under=0"),
        (0, False, "2", "--ignore=tests/tooling --cov-fail-under=0"),
        (0, True, "0", None),
    ],
)
def test_test_command_uses_process_workers_and_restores_environment(
    tmp_path, workers, coverage, expected, pytest_options
):
    result = _run_dev_driver(
        tmp_path,
        """
function Get-DevPython { return "python-from-venv.exe" }
function Invoke-ExternalCommand {
    param([string]$FilePath, [string[]]$ArgumentList)
    [PSCustomObject]@{
        executable = $FilePath; arguments = $ArgumentList
        qt = $env:QT_QPA_PLATFORM; pytest_options = $env:PYTEST_ADDOPTS
    } |
        ConvertTo-Json -Compress | Set-Content -LiteralPath (Join-Path $PSScriptRoot "command.json")
}
$env:QT_QPA_PLATFORM = "original-platform"
$env:PYTEST_ADDOPTS = PYTEST_OPTIONS
Invoke-TestSuite -WorkerCount WORKERS -WithCoverage:$COVERAGE
if ($env:QT_QPA_PLATFORM -ne "original-platform") { throw "Qt environment leaked" }
if ($env:PYTEST_ADDOPTS -ne PYTEST_OPTIONS) { throw "Pytest environment leaked" }
""".replace("WORKERS", str(workers))
        .replace("$COVERAGE", "$true" if coverage else "$false")
        .replace("PYTEST_OPTIONS", f'"{pytest_options}"' if pytest_options else "$null"),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    command = json.loads((tmp_path / "command.json").read_text(encoding="utf-8-sig"))
    assert command["executable"] == "python-from-venv.exe"
    assert command["qt"] == "offscreen"
    assert command["pytest_options"] == (None if coverage else pytest_options)
    args = command["arguments"]
    assert args[args.index("-n") + 1] == expected
    assert ("--dist=loadfile" in args) == (expected == "2")
    assert ("--cov=pogled_assist" in args) == coverage


@pytest.mark.parametrize("coverage", [False, True])
def test_test_failure_restores_environment_and_reports_failed_stage(tmp_path, coverage):
    result = _run_dev_driver(
        tmp_path,
        """
function Get-DevPython { return "python-from-venv.exe" }
function Invoke-ExternalCommand {
    [PSCustomObject]@{ pytest_options = $env:PYTEST_ADDOPTS } |
        ConvertTo-Json -Compress | Set-Content -LiteralPath (Join-Path $PSScriptRoot "command.json")
    throw "test failed"
}
$env:QT_QPA_PLATFORM = "original-platform"
$env:PYTEST_ADDOPTS = "--ignore=tests/tooling --cov-fail-under=0"
try {
    Invoke-CheckStage -Name "Regression tests" -Command { Invoke-TestSuite -WithCoverage:$COVERAGE }
}
catch {
    if ($env:QT_QPA_PLATFORM -ne "original-platform") { throw "Qt environment leaked" }
    if ($env:PYTEST_ADDOPTS -ne "--ignore=tests/tooling --cov-fail-under=0") {
        throw "Pytest environment leaked"
    }
    if ($StageTimings[0].Status -ne "FAILED") { throw "Failure timing missing" }
    throw
}
""".replace("$COVERAGE", "$true" if coverage else "$false"),
    )

    assert result.returncode != 0
    assert "Regression tests (FAILED," in result.stdout
    assert "test failed" in result.stderr
    assert "environment leaked" not in result.stderr
    command = json.loads((tmp_path / "command.json").read_text(encoding="utf-8-sig"))
    assert command["pytest_options"] == (
        None if coverage else "--ignore=tests/tooling --cov-fail-under=0"
    )


@pytest.mark.parametrize(
    ("count", "full_suite", "workers", "expected_workers"),
    [
        (1, False, 0, 1),
        (4, False, 0, 2),
        (1, True, 0, 2),
        (0, False, 0, 0),
        (0, True, 0, 2),
        (1, False, 2, 2),
        (4, False, 1, 1),
        (1, True, 1, 1),
    ],
)
def test_fast_check_honors_selection_without_coverage_or_package(
    tmp_path,
    count,
    full_suite,
    workers,
    expected_workers,
):
    result = _run_dev_driver(
        tmp_path,
        """
$script:IsFullSuite = $FULL
$script:SelectedCount = COUNT
$Workers = REQUESTED_WORKERS
function Get-FastCheckPlan {
    $paths = @(for ($i = 0; $i -lt $script:SelectedCount; $i++) { "tests/test_$i.py" })
    return [PSCustomObject]@{ full_suite = $script:IsFullSuite; test_paths = $paths }
}
function Invoke-LintChecks { param($Plan); Write-Host "FAST-LINT" }
function Invoke-TestSuite {
    param([string[]]$Paths, [int]$WorkerCount, [switch]$WithCoverage)
    if ($WithCoverage) { throw "Unexpected coverage" }
    Write-Host "TEST-WORKERS:$WorkerCount PATH-COUNT:$($Paths.Count)"
}
function Invoke-PackageBuild { throw "Unexpected package" }
Invoke-FastCheck
""".replace("$FULL", "$true" if full_suite else "$false")
        .replace("COUNT", str(count), 1)
        .replace("REQUESTED_WORKERS", str(workers)),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "FAST-LINT" in result.stdout
    if expected_workers:
        assert f"TEST-WORKERS:{expected_workers}" in result.stdout
        assert f"PATH-COUNT:{0 if full_suite else count}" in result.stdout
    else:
        assert "TEST-WORKERS:" not in result.stdout
    assert "Coverage and Windows package: skipped" in result.stdout


def test_full_check_rejects_manual_partial_test_selection(tmp_path):
    result = _run_dev_script(tmp_path, "check", "-TestPaths", "tests/gaze")

    assert result.returncode != 0
    assert "coverage and check always run the full suite" in result.stderr


@pytest.mark.parametrize("selected", ["valid.ps1", "broken.ps1", "../outside.ps1"])
def test_powershell_focused_check_parses_only_selected_paths_and_rejects_escape(tmp_path, selected):
    checks = tmp_path / "repo" / "scripts" / "checks"
    checks.mkdir(parents=True)
    checker = checks / "check_powershell.ps1"
    shutil.copy2(DEV_SCRIPT.parent / "scripts" / "checks" / checker.name, checker)
    (tmp_path / "repo" / "valid.ps1").write_text('Write-Output "valid"\n', encoding="utf-8")
    (tmp_path / "repo" / "broken.ps1").write_text("function Broken {", encoding="utf-8")
    (tmp_path / "outside.ps1").write_text('Write-Output "outside"\n', encoding="utf-8")
    shutil.copy2(DEV_SCRIPT.parent / "PSScriptAnalyzerSettings.psd1", tmp_path / "repo")

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(checker),
            "-Paths",
            selected,
        ],
        cwd=tmp_path / "repo",
        capture_output=True,
        text=True,
        check=False,
    )

    if selected == "valid.ps1":
        assert result.returncode == 0, result.stdout + result.stderr
        assert "passed for 1 script(s)" in result.stdout
    else:
        assert result.returncode != 0
        if selected.startswith(".."):
            assert "must be a script inside the repository" in result.stderr
        else:
            assert "Missing closing" in result.stderr
