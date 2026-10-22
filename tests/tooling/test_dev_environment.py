from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from _powershell import run_dev_driver as _run_dev_driver
from _powershell import run_powershell_cases

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="dev.ps1 uses Windows PowerShell")

FAST_CASES = [
    (1, False, 0, 1),
    (4, False, 0, 2),
    (1, True, 0, 2),
    (0, False, 0, 0),
    (0, True, 0, 2),
    (1, False, 2, 2),
    (4, False, 1, 1),
    (1, True, 1, 1),
]

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
        timeout=20,
    )


@pytest.fixture
def broken_python(tmp_path: Path) -> Path:
    python_path = tmp_path / ".venv" / "Scripts" / "python.exe"
    python_path.parent.mkdir(parents=True)
    python_path.write_bytes(b"not a Python executable")
    # Mark the fixture as downloaded to expose interactive shell warnings.
    Path(f"{python_path}:Zone.Identifier").write_text(
        "[ZoneTransfer]\nZoneId=3\n", encoding="ascii"
    )
    return python_path


def test_lint_reports_broken_virtual_environment_before_running_checks(
    tmp_path: Path, broken_python: Path
) -> None:
    result = _run_dev_script(tmp_path, "lint")

    assert result.returncode != 0
    assert "Development environment is broken or unsupported" in result.stderr
    assert broken_python.read_bytes() == b"not a Python executable"


def test_setup_rejects_missing_base_without_moving_existing_environment(
    tmp_path: Path, broken_python: Path
) -> None:
    result = _run_dev_script(tmp_path, "setup", "-BasePython", str(tmp_path / "missing.exe"))

    assert result.returncode != 0
    assert "Base Python was not found" in result.stderr
    assert broken_python.read_bytes() == b"not a Python executable"
    assert not (tmp_path / ".dev-tools").exists()


def test_python_probe_works_with_legacy_powershell_argument_passing(python_probe_results):
    result = python_probe_results["version"]
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == f"{sys.version_info.major}.{sys.version_info.minor}"


def test_base_python_probe_resolves_the_interpreter_behind_a_venv(python_probe_results):
    result = python_probe_results["base"]
    assert result.returncode == 0, result.stdout + result.stderr
    assert Path(result.stdout.strip()).resolve() == Path(sys._base_executable).resolve()


def _prepare_setup_environment(tmp_path):
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
    shutil.copy2(
        DEV_SCRIPT.parent / "scripts" / "checks" / "install_powershell_analyzer.ps1",
        check_script.parent,
    )
    driver = tmp_path / "run-setup.ps1"
    return python_path, driver


@pytest.mark.parametrize(
    ("current_version", "same_base", "should_recreate"),
    [("3.10", True, False), ("3.10", False, True), ("3.12", True, True)],
)
def test_setup_uses_the_requested_base_interpreter(
    tmp_path: Path, current_version: str, same_base: bool, should_recreate: bool
) -> None:
    python_path, driver = _prepare_setup_environment(tmp_path)
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


@pytest.mark.parametrize("registered", [False, True])
def test_analyzer_setup_registers_missing_gallery_and_reuses_download(tmp_path, registered):
    script = tmp_path / "scripts" / "checks" / "install_powershell_analyzer.ps1"
    script.parent.mkdir(parents=True)
    shutil.copy2(DEV_SCRIPT.parent / "scripts" / "checks" / script.name, script)
    result = run_powershell_cases(
        tmp_path,
        {
            "install": {
                "body": r"""
$script:Registered = REGISTERED
$script:Calls = [System.Collections.Generic.List[string]]::new()
function Get-PSRepository {
    param($Name, $ErrorAction)
    if ($script:Registered) { [pscustomobject]@{ Name = "PSGallery" } }
}
function Register-PSRepository {
    param([switch]$Default, $ErrorAction)
    if (-not $Default) { throw "Expected the default PowerShell repository" }
    $script:Calls.Add("register")
    $script:Registered = $true
}
function Save-Module {
    param($Name, $RequiredVersion, $Path, $Repository, [switch]$Force, $ErrorAction)
    if (-not $script:Registered) { throw "Unable to find repository 'PSGallery'" }
    if ($Name -ne "PSScriptAnalyzer" -or $RequiredVersion -ne "1.25.0" -or $Repository -ne "PSGallery") {
        throw "Unexpected analyzer source or version"
    }
    $script:Calls.Add("save")
    $directory = Join-Path $Path "$Name\$RequiredVersion"
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $directory "$Name.psd1") -Value "@{}"
}
$installer = Join-Path $PSScriptRoot "scripts\checks\install_powershell_analyzer.ps1"
& $installer
function Get-PSRepository { throw "A cached analyzer must not contact PSGallery" }
function Save-Module { throw "A cached analyzer must not be downloaded again" }
& $installer
$script:Calls -join ","
""".replace("REGISTERED", "$true" if registered else "$false")
            }
        },
    )["install"]

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ("save" if registered else "register,save")


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


@pytest.mark.parametrize(
    "case,expected", [("probe0", "quoted value"), ("probe1", "ok"), ("probe2", "<missing>")]
)
def test_python_probe_handles_output_and_exit_status(python_probe_results, case, expected):
    result = python_probe_results[case]
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == expected
    assert result.stderr == ""


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
Invoke-TestSuite -WorkerCount WORKERS -Coverage "$COVERAGE"
if ($env:QT_QPA_PLATFORM -ne "original-platform") { throw "Qt environment leaked" }
if ($env:PYTEST_ADDOPTS -ne PYTEST_OPTIONS) { throw "Pytest environment leaked" }
""".replace("WORKERS", str(workers))
        .replace("$COVERAGE", "Full" if coverage else "None")
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
    assert ("--durations=30" in args) == coverage


@pytest.fixture(scope="module")
def coverage_group_results(tmp_path_factory):
    root = tmp_path_factory.mktemp("coverage-groups")
    shutil.copy2(DEV_SCRIPT, root / "dev.ps1")
    return run_powershell_cases(
        root,
        {
            group: {
                "body": f'$CoverageGroup = "{group}"\n'
                + """
function Invoke-TestSuite {
    param([string]$Coverage, [string[]]$Paths = @(), [string[]]$IgnorePaths = @())
    [pscustomobject]@{ coverage = $Coverage; paths = @($Paths); ignore = @($IgnorePaths) } |
        ConvertTo-Json -Compress
}
Invoke-CoverageGroup
"""
            }
            for group in ("All", "Application", "Infrastructure")
        },
        prelude=DEV_PRELUDE,
    )


@pytest.mark.parametrize(
    "group,mode,paths,ignored",
    [
        ("All", "Full", [], []),
        ("Application", "Collect", [], ["tests/release", "tests/tooling"]),
        (
            "Infrastructure",
            "Collect",
            ["tests/release", "tests/tooling"],
            ["tests/release/test_windows_installer.py"],
        ),
    ],
)
def test_coverage_groups_partition_the_suite(coverage_group_results, group, mode, paths, ignored):
    result = coverage_group_results[group]
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"coverage": mode, "paths": paths, "ignore": ignored}


@pytest.mark.parametrize("defer_report", [False, True])
def test_coverage_can_append_a_deferred_test_file(tmp_path, defer_report):
    result = _run_dev_driver(
        tmp_path,
        """
function Get-DevPython { return "python-from-venv.exe" }
function Invoke-ExternalCommand {
    param([string]$FilePath, [string[]]$ArgumentList)
    $ArgumentList | ConvertTo-Json -Compress |
        Set-Content -LiteralPath (Join-Path $PSScriptRoot "arguments.json")
}
Invoke-TestSuite `
    -Coverage MODE `
    -IgnorePaths @("tests/release/test_windows_installer.py") `
    -Paths @("tests/release/test_windows_installer.py") `
    -WorkerCount 1
""".replace("MODE", "Collect" if defer_report else "Append"),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    arguments = json.loads((tmp_path / "arguments.json").read_text(encoding="utf-8-sig"))
    assert ("--cov-append" in arguments) != defer_report
    assert "--ignore=tests/release/test_windows_installer.py" in arguments
    assert arguments[-1] == "tests/release/test_windows_installer.py"
    assert ("--cov-report=" in arguments) == defer_report
    assert ("--cov-fail-under=0" in arguments) == defer_report
    assert any(arg.startswith("--cov-report=html:") for arg in arguments) != defer_report
    assert ("--cov-report=term-missing:skip-covered" in arguments) != defer_report


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
    Invoke-CheckStage -Name "Regression tests" -Command { Invoke-TestSuite -Coverage "$COVERAGE" }
}
catch {
    if ($env:QT_QPA_PLATFORM -ne "original-platform") { throw "Qt environment leaked" }
    if ($env:PYTEST_ADDOPTS -ne "--ignore=tests/tooling --cov-fail-under=0") {
        throw "Pytest environment leaked"
    }
    if ($StageTimings[0].Status -ne "FAILED") { throw "Failure timing missing" }
    throw
}
""".replace("$COVERAGE", "Full" if coverage else "None"),
    )

    assert result.returncode != 0
    assert "Regression tests (FAILED," in result.stdout
    assert "test failed" in result.stderr
    assert "environment leaked" not in result.stderr
    command = json.loads((tmp_path / "command.json").read_text(encoding="utf-8-sig"))
    assert command["pytest_options"] == (
        None if coverage else "--ignore=tests/tooling --cov-fail-under=0"
    )


@pytest.mark.parametrize("count,full_suite,workers,expected_workers", FAST_CASES)
def test_fast_check_honors_selection_without_coverage_or_package(
    fast_check_results, count, full_suite, workers, expected_workers
):
    result = fast_check_results[f"{count}-{full_suite}-{workers}"]
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


@pytest.mark.parametrize(
    "failed_action", ["none", "application", "infrastructure", "package", "installer", "report"]
)
def test_parallel_check_defers_installer_tests_until_package_finishes(tmp_path, failed_action):
    if failed_action == "installer":
        (tmp_path / "fail-installer-tests").write_text("fail", encoding="utf-8")
    (tmp_path / "child.ps1").write_text(
        """
param([string]$Action, [int]$Workers, [string]$CoverageGroup = "All")
if ($Workers -ne 2) { throw "Worker option was lost" }
if (($Action -eq "coverage") -eq ($CoverageGroup -eq "All")) {
    throw "Only coverage stages should select a test group"
}
$id = if ($Action -eq "coverage") { $CoverageGroup.ToLowerInvariant() } else { $Action }
if ($Action -eq "coverage") {
    if ([IO.Path]::GetFileName($env:COVERAGE_FILE) -ne "$id.coverage") {
        throw "Coverage stages must use separate data files"
    }
    Set-Content -LiteralPath $env:COVERAGE_FILE -Value $id
} elseif ($env:COVERAGE_FILE -ne "original-coverage") { throw "Coverage environment leaked" }
Set-Content -LiteralPath (Join-Path $PSScriptRoot "$id.started") -Value "started"
$deadline = [DateTime]::UtcNow.AddSeconds(10)
while (-not ((Test-Path (Join-Path $PSScriptRoot "application.started")) -and
             (Test-Path (Join-Path $PSScriptRoot "infrastructure.started")) -and
             (Test-Path (Join-Path $PSScriptRoot "package.started")))) {
    if ([DateTime]::UtcNow -gt $deadline) { throw "Stages did not overlap" }
    Start-Sleep -Milliseconds 20
}
[Console]::Out.WriteLine("$id output " + ('x' * 131072))
[Console]::Error.WriteLine("$id diagnostic " + ('y' * 131072))
$logRoot = @(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot "dist") -Directory)[0].FullName
foreach ($suffix in @("log", "stderr.log")) {
    $reader = [IO.File]::Open((Join-Path $logRoot "$id.$suffix"), "Open", "Read", "ReadWrite")
    $reader.Dispose()
}
Start-Sleep -Milliseconds 350
Set-Content -LiteralPath (Join-Path $PSScriptRoot "$id.finished") -Value "finished"
if ($id -eq 'FAILED_ACTION') { throw "Synthetic stage failure" }
""".replace("FAILED_ACTION", failed_action),
        encoding="utf-8",
    )
    result = _run_dev_driver(
        tmp_path,
        """
$Workers = 2
$env:COVERAGE_FILE = "original-coverage"
function Invoke-TestSuite {
    param([string]$Coverage, [string[]]$Paths)
    if ($Coverage -ne "Collect") { throw "Installer coverage must defer the report" }
    if ($Paths.Count -ne 1 -or $Paths[0] -ne "tests/release/test_windows_installer.py") {
        throw "Unexpected deferred test selection"
    }
    foreach ($action in @("application", "infrastructure", "package")) {
        if (-not (Test-Path (Join-Path $PSScriptRoot "$action.finished"))) {
            throw "Installer tests ran before $action finished"
        }
    }
    if ([IO.Path]::GetFileName($env:COVERAGE_FILE) -ne "installer.coverage") {
        throw "Installer coverage must use a separate data file"
    }
    Set-Content -LiteralPath $env:COVERAGE_FILE -Value "installer"
    Set-Content -LiteralPath (Join-Path $PSScriptRoot "installer-tests.finished") -Value "finished"
    if (Test-Path (Join-Path $PSScriptRoot "fail-installer-tests")) {
        throw "Synthetic installer test failure"
    }
}
function Merge-CheckCoverage {
    param([string[]]$Files)
    if ($env:COVERAGE_FILE -ne "original-coverage") { throw "Coverage environment leaked" }
    $contents = @($Files | ForEach-Object { (Get-Content -LiteralPath $_ -Raw).Trim() })
    if (($contents -join ',') -ne "application,infrastructure,installer") {
        throw "Combined report omitted test coverage"
    }
    if (-not (Test-Path (Join-Path $PSScriptRoot "installer-tests.finished"))) {
        throw "Report ran before installer tests"
    }
    if ("FAILED_ACTION" -eq "report") { throw "Synthetic report failure" }
}
try {
    Invoke-ParallelCheck -ScriptPath (Join-Path $PSScriptRoot "child.ps1") -StatusIntervalMilliseconds 100
} finally {
    $StageTimings | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot "timings.json")
}
""".replace("FAILED_ACTION", failed_action),
    )
    assert (result.returncode == 0) == (failed_action == "none"), result.stdout + result.stderr
    timings = json.loads((tmp_path / "timings.json").read_text(encoding="utf-8-sig"))
    statuses = {entry["Name"]: entry["Status"] for entry in timings}
    assert statuses == {
        "Application tests and coverage": "FAILED" if failed_action == "application" else "passed",
        "Release and tooling tests and coverage": (
            "FAILED" if failed_action == "infrastructure" else "passed"
        ),
        "Windows package and installer smoke tests": (
            "FAILED" if failed_action == "package" else "passed"
        ),
        "Installer integration tests and coverage": (
            "FAILED" if failed_action == "installer" else "passed"
        ),
        "Combined coverage report": "FAILED" if failed_action == "report" else "passed",
    }
    assert all(entry["Seconds"] > 0 for entry in timings)
    assert (tmp_path / "installer-tests.finished").exists()
    _assert_parallel_output(tmp_path, result)


def _assert_parallel_output(tmp_path, result):
    (log_root,) = (tmp_path / "dist").glob("check-*")
    for action in ("application", "infrastructure", "package"):
        assert (tmp_path / f"{action}.finished").exists()
        assert f"{action} output " in (log_root / f"{action}.log").read_text()
        assert f"{action} diagnostic " in (log_root / f"{action}.stderr.log").read_text()
    assert "Stages did not overlap" not in result.stderr
    status_lines = [line for line in result.stdout.splitlines() if line.startswith("Running:")]
    assert len(status_lines) >= 2
    assert any("Application tests and coverage (" in line for line in status_lines)
    assert any("Release and tooling tests and coverage (" in line for line in status_lines)
    assert any("Windows package and installer smoke tests (" in line for line in status_lines)
    assert all("elapsed)" in line and "/3 finished" in line for line in status_lines)


def test_parallel_option_is_rejected_outside_full_check(tmp_path):
    result = _run_dev_script(tmp_path, "test", "-Parallel")

    assert result.returncode != 0
    assert "-Parallel is supported only by check" in result.stderr


@pytest.mark.parametrize("selected", ["valid.ps1", "broken.ps1", "../outside.ps1"])
def test_powershell_focused_check_parses_only_selected_paths_and_rejects_escape(
    launch_check_results, selected
):
    result = launch_check_results[selected]
    if selected == "valid.ps1":
        assert result.returncode == 0, result.stdout + result.stderr
        assert "passed for 1 script(s)" in result.stdout
    else:
        assert result.returncode != 0
        assert (
            "must be a script inside the repository"
            if selected.startswith("..")
            else "Missing closing"
        ) in result.stderr


LAUNCH_CASES = [
    ("ordinary.ps1", 'Start-Process -FilePath "test.exe" -Wait', False),
    ("ordinary.ps1", 'saps -FilePath "test.exe"', False),
    ("ordinary.ps1", 'Microsoft.PowerShell.Management\\Start-Process "test.exe"', False),
    ("ordinary.ps1", '$p = @{FilePath="test.exe"}; Start-Process @p', False),
    ("ordinary.ps1", 'Start-Process "test.exe" -Verb Open', False),
    ("ordinary.ps1", 'Start-Process "powershell.exe" -Verb RunAs', True),
    ("ordinary.ps1", 'Start-Process "powershell.exe" -Verb:RunAs', True),
    ("dev.ps1", 'Start-Process -FilePath (Join-Path $outputRoot "index.html")', True),
    ("dev.ps1", 'Start-Process -FilePath (Join-Path $outputRoot "test.exe")', False),
    ("ordinary.ps1", 'Start-Process -FilePath (Join-Path $outputRoot "index.html")', False),
    (
        "ordinary.ps1",
        "$p = New-Object Diagnostics.ProcessStartInfo; $p.UseShellExecute = $false",
        True,
    ),
]


@pytest.fixture(scope="module")
def launch_check_results(tmp_path_factory):
    root = tmp_path_factory.mktemp("launch-check")
    (root / "outside.ps1").write_text('Write-Output "outside"', encoding="utf-8")
    cases = {}
    entries = [
        (f"case{i:02}", filename, source, filename)
        for i, (filename, source, _) in enumerate(LAUNCH_CASES)
    ]
    entries += [
        (f"focused{i}", "valid.ps1", 'Write-Output "valid"', selected)
        for i, selected in enumerate(["valid.ps1", "broken.ps1", "../outside.ps1"])
    ]
    for name, filename, source, selected in entries:
        case = root / name
        checks = case / "scripts" / "checks"
        checks.mkdir(parents=True)
        shutil.copy2(DEV_SCRIPT.parent / "scripts/checks/check_powershell.ps1", checks)
        shutil.copy2(DEV_SCRIPT.parent / "PSScriptAnalyzerSettings.psd1", case)
        (case / filename).write_text(source, encoding="utf-8")
        if name.startswith("focused"):
            (case / "broken.ps1").write_text("function Broken {", encoding="utf-8")
        cases[name] = {"body": f"& './scripts/checks/check_powershell.ps1' -Paths '{selected}'"}
    results = run_powershell_cases(root, cases)
    return {
        **{
            (filename, source): results[f"case{i:02}"]
            for i, (filename, source, _) in enumerate(LAUNCH_CASES)
        },
        **{
            selected: results[f"focused{i}"]
            for i, selected in enumerate(["valid.ps1", "broken.ps1", "../outside.ps1"])
        },
    }


@pytest.mark.parametrize(("filename", "source", "allowed"), LAUNCH_CASES)
def test_powershell_check_enforces_direct_executable_launches(
    launch_check_results, filename, source, allowed
):
    result = launch_check_results[(filename, source)]
    assert (result.returncode == 0) is allowed, result.stdout + result.stderr
    if not allowed:
        assert "UseShellExecute=false" in result.stdout + result.stderr


PYTHON_PROBE_TEMPLATE = """
$probe = Invoke-PythonProbe -Executable 'PYTHON_PATH' -Code @'
PROBE_CODE
'@
if ($null -eq $probe) { Write-Output "<missing>" } else { Write-Output $probe }
"""


@pytest.fixture(scope="module")
def python_probe_results(tmp_path_factory):
    root = tmp_path_factory.mktemp("python-probes")
    shutil.copy2(DEV_SCRIPT, root / "dev.ps1")
    python = sys.executable.replace("'", "''")
    cases = {
        "version": {"body": f"Get-PythonVersion -Executable '{python}'"},
        "base": {"body": f"Get-PythonBaseExecutable -Executable '{python}'"},
    }
    for index, code in enumerate(
        [
            "print(\"quoted value\"); print('second line')",
            "import sys; sys.stderr.write('error' * 20000); print('ok')",
            "import sys; print('3.10'); sys.exit(1)",
        ]
    ):
        cases[f"probe{index}"] = {
            "body": PYTHON_PROBE_TEMPLATE.replace("PYTHON_PATH", python).replace("PROBE_CODE", code)
        }
    return run_powershell_cases(root, cases, prelude=DEV_PRELUDE)


FAST_CHECK_TEMPLATE = r"""
$script:IsFullSuite = $FULL
$script:SelectedCount = COUNT
$Workers = REQUESTED_WORKERS
function Get-FastCheckPlan {
    $paths = @(for ($i = 0; $i -lt $script:SelectedCount; $i++) { "tests/test_$i.py" })
    return [PSCustomObject]@{ full_suite = $script:IsFullSuite; test_paths = $paths }
}
function Invoke-LintChecks { param($Plan); Write-Host "FAST-LINT" }
function Invoke-TestSuite {
    param([string[]]$Paths, [int]$WorkerCount, [string]$Coverage = "None")
    if ($Coverage -ne "None") { throw "Unexpected coverage" }
    Write-Host "TEST-WORKERS:$WorkerCount PATH-COUNT:$($Paths.Count)"
}
function Invoke-PackageBuild { throw "Unexpected package" }
Invoke-FastCheck
"""


DEV_PRELUDE = '. (Join-Path $PSScriptRoot "dev.ps1") help | Out-Null\n'


@pytest.fixture(scope="module")
def fast_check_results(tmp_path_factory):
    root = tmp_path_factory.mktemp("fast-check")
    shutil.copy2(DEV_SCRIPT, root / "dev.ps1")
    cases = {}
    for count, full, workers, _expected in FAST_CASES:
        body = (
            FAST_CHECK_TEMPLATE.replace("$FULL", "$true" if full else "$false")
            .replace("COUNT", str(count), 1)
            .replace("REQUESTED_WORKERS", str(workers))
        )
        cases[f"{count}-{full}-{workers}"] = {"body": body}
    return run_powershell_cases(root, cases, prelude=DEV_PRELUDE)
