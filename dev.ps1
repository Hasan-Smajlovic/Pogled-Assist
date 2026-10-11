[CmdletBinding()]
param(
    [ValidateSet("help", "setup", "run", "simulate", "ui", "test", "test-ui", "coverage", "lint", "format", "check-fast", "check", "package")]
    [string]$Action = "help",
    [string]$BasePython,
    [switch]$Open,
    [ValidateSet(0, 1, 2)]
    [int]$Workers = 0,
    [string[]]$TestPaths = @(),
    [string]$BaseRef = "origin/development"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = $PSScriptRoot
$VenvRoot = Join-Path $RepoRoot ".venv"
$PythonPath = Join-Path $VenvRoot "Scripts\python.exe"
$RequiredPythonVersion = "3.10"
$AnalyzerVersion = "1.25.0"
$AnalyzerPath = Join-Path $RepoRoot ".dev-tools\PSScriptAnalyzer\$AnalyzerVersion\PSScriptAnalyzer.psd1"
$StageTimings = [Collections.Generic.List[object]]::new()

if ($TestPaths.Count -gt 0 -and $Action -notin @("test", "test-ui")) {
    throw "-TestPaths is supported only by test and test-ui; coverage and check always run the full suite."
}

function Invoke-CheckStage {
    param([string]$Name, [scriptblock]$Command)

    $timer = [Diagnostics.Stopwatch]::StartNew()
    $status = "FAILED"
    Write-Host "Starting: $Name"
    try {
        & $Command
        $status = "passed"
    } finally {
        $timer.Stop()
        $StageTimings.Add([PSCustomObject]@{
            Name = $Name
            Seconds = $timer.Elapsed.TotalSeconds
            Status = $status
        })
        Write-Host ("Finished: {0} ({1}, {2:N1}s)" -f $Name, $status, $timer.Elapsed.TotalSeconds)
    }
}

function Invoke-ExternalCommand {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath failed with exit code $LASTEXITCODE."
    }
}

function Get-DevPython {
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        throw "Development environment is missing. Run .\dev.ps1 setup first."
    }
    $version = Get-PythonVersion -Executable $PythonPath
    if ($version -ne $RequiredPythonVersion) {
        throw "Development environment is broken or unsupported. Run .\dev.ps1 setup to back it up and recreate it."
    }
    return $PythonPath
}

function Get-PythonVersion {
    param([string]$Executable)

    # Legacy PowerShell drops quotes inside arguments passed to native commands.
    return Invoke-PythonProbe -Executable $Executable -Code 'import sys; print(str(sys.version_info.major)+chr(46)+str(sys.version_info.minor) if sys.maxsize > 2**32 else 32)'
}

function Get-PythonBaseExecutable {
    param([string]$Executable)

    return Invoke-PythonProbe -Executable $Executable -Code 'import sys; print(sys._base_executable)'
}

function Invoke-PythonProbe {
    param([string]$Executable, [string]$Code)

    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        return $null
    }
    try {
        $probe = & $Executable -c $Code 2>$null
        if ($LASTEXITCODE -ne 0) {
            return $null
        }
        return ([string]($probe | Select-Object -First 1)).Trim()
    } catch {
        return $null
    }
}

function Test-SamePythonBase {
    param([string]$ExistingEnvironment, [string]$RequestedInterpreter)

    $existingBase = Get-PythonBaseExecutable -Executable $ExistingEnvironment
    $requestedBase = Get-PythonBaseExecutable -Executable $RequestedInterpreter
    if ([string]::IsNullOrWhiteSpace($existingBase) -or [string]::IsNullOrWhiteSpace($requestedBase)) {
        return $false
    }
    return [IO.Path]::GetFullPath($existingBase).Equals(
        [IO.Path]::GetFullPath($requestedBase),
        [StringComparison]::OrdinalIgnoreCase
    )
}

function Resolve-BasePython {
    if (-not [string]::IsNullOrWhiteSpace($BasePython)) {
        return Get-RequestedPython
    }

    $candidate = Get-LauncherPython
    if ($null -ne $candidate) {
        return $candidate
    }

    $command = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($null -ne $command -and (Get-PythonVersion -Executable $command.Source) -eq $RequiredPythonVersion) {
        return $command.Source
    }
    throw "Python 3.10 x64 was not found. Install it or pass -BasePython <path> to setup."
}

function Get-RequestedPython {
    $command = Get-Command $BasePython -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "Base Python was not found: $BasePython"
    }
    $version = Get-PythonVersion -Executable $command.Source
    if ($version -ne $RequiredPythonVersion) {
        throw "Base Python must be 64-bit Python 3.10. Found: $version"
    }
    return $command.Source
}

function Get-LauncherPython {
    $launcher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($null -eq $launcher) {
        return $null
    }
    try {
        $candidate = & $launcher.Source "-$RequiredPythonVersion" -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -ne 0) {
            return $null
        }
        $candidatePath = ([string]($candidate | Select-Object -First 1)).Trim()
        if ((Get-PythonVersion -Executable $candidatePath) -eq $RequiredPythonVersion) {
            return $candidatePath
        }
    } catch {
        Write-Verbose "Python launcher probe failed: $($_.Exception.Message)"
    }
    return $null
}

function Install-DevEnvironment {
    $currentVersion = Get-PythonVersion -Executable $PythonPath
    $base = $null
    if (-not [string]::IsNullOrWhiteSpace($BasePython)) {
        $base = Resolve-BasePython
    }
    if (-not (Test-DevEnvironmentMatches -Version $currentVersion -Base $base)) {
        if ($null -eq $base) {
            $base = Resolve-BasePython
        }
        Backup-DevEnvironment
        Invoke-ExternalCommand -FilePath $base -ArgumentList @("-m", "venv", $VenvRoot)
        Get-DevPython | Out-Null
    }

    Invoke-ExternalCommand -FilePath $PythonPath -ArgumentList @(
        "-m", "pip", "install", "--no-compile", "--only-binary=:all:",
        "-r", (Join-Path $RepoRoot "requirements-dev.txt"),
        "-r", (Join-Path $RepoRoot "requirements-build.txt")
    )

    if (-not (Test-Path -LiteralPath $AnalyzerPath -PathType Leaf)) {
        $toolRoot = Join-Path $RepoRoot ".dev-tools"
        New-Item -ItemType Directory -Path $toolRoot -Force | Out-Null
        Save-Module `
            -Name "PSScriptAnalyzer" `
            -RequiredVersion $AnalyzerVersion `
            -Path $toolRoot `
            -Repository "PSGallery" `
            -Force
    }

    & (Join-Path $RepoRoot "scripts\checks\check_github_actions.ps1") -Install

    Write-Output "Development environment is ready. Run .\dev.ps1 check."
}

function Test-DevEnvironmentMatches {
    param([string]$Version, $Base)

    if ($Version -ne $RequiredPythonVersion) {
        return $false
    }
    if ($null -eq $Base) {
        return $true
    }
    return Test-SamePythonBase -ExistingEnvironment $PythonPath -RequestedInterpreter $Base
}

function Backup-DevEnvironment {
    if (-not (Test-Path -LiteralPath $VenvRoot)) {
        return
    }
    $backupRoot = Join-Path $RepoRoot ".dev-tools\venv-backups"
    $repoPrefix = [IO.Path]::GetFullPath($RepoRoot).TrimEnd("\") + "\"
    foreach ($path in @($VenvRoot, $backupRoot)) {
        if (-not [IO.Path]::GetFullPath($path).StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Virtual environment path must stay inside the repository: $path"
        }
    }
    New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
    $backupPath = Join-Path $backupRoot ("venv-{0}-{1}" -f (Get-Date -Format "yyyyMMdd-HHmmss"), [Guid]::NewGuid().ToString("N"))
    Move-Item -LiteralPath $VenvRoot -Destination $backupPath
    Write-Output "Saved the old .venv at $backupPath"
}

function Invoke-LintChecks {
    param($Plan = $null)

    $python = Get-DevPython
    if ($null -eq $Plan -or $Plan.actions_check) {
        & (Join-Path $RepoRoot "scripts\checks\check_github_actions.ps1")
    } else {
        Write-Host "Actions check skipped: no workflow or shared-check changes."
    }
    Invoke-ExternalCommand -FilePath $python -ArgumentList @("-m", "ruff", "check", ".")
    Invoke-ExternalCommand -FilePath $python -ArgumentList @("-m", "ruff", "format", "--check", ".")
    Invoke-ExternalCommand -FilePath $python -ArgumentList @(
        "-B", "-m", "compileall", "-q", "pogled_assist", "scripts", "tests", "run_gaze_mouse.py"
    )
    if ($null -eq $Plan -or $Plan.all_powershell) {
        & (Join-Path $RepoRoot "scripts\checks\check_powershell.ps1") -RequireAnalyzer
    } elseif (@($Plan.powershell_paths).Count -gt 0) {
        & (Join-Path $RepoRoot "scripts\checks\check_powershell.ps1") -RequireAnalyzer -Paths $Plan.powershell_paths
    } else {
        Write-Host "PowerShell check skipped: no changed scripts."
    }
}

function Invoke-TestSuite {
    param(
        [switch]$UiOnly,
        [switch]$WithCoverage,
        [string[]]$Paths = @(),
        [int]$WorkerCount = $Workers
    )

    $python = Get-DevPython
    $arguments = @("-B", "-m", "pytest", "-p", "no:cacheprovider")
    if ($WorkerCount -eq 0) {
        $WorkerCount = 2
        if ($WithCoverage) {
            $WorkerCount = 1
        }
    }
    if ($WorkerCount -gt 1) {
        $arguments += @("-n", [string]$WorkerCount, "--dist=loadfile")
    } else {
        $arguments += @("-n", "0")
    }
    Write-Host "Tests: $WorkerCount process(es), grouped by file when parallel."
    if ($UiOnly) {
        $arguments += @("-m", "e2e")
    }
    if ($WithCoverage) {
        $coverageHtml = Join-Path $RepoRoot "dist\coverage-html"
        $arguments += @(
            "--cov=pogled_assist",
            "--cov-report=term-missing:skip-covered",
            "--cov-report=html:$coverageHtml"
        )
    }
    $arguments += $Paths

    $previousQtPlatform = $env:QT_QPA_PLATFORM
    $previousPytestOptions = $env:PYTEST_ADDOPTS
    try {
        $env:QT_QPA_PLATFORM = "offscreen"
        if ($WithCoverage) {
            if (-not [string]::IsNullOrEmpty($previousPytestOptions)) {
                Write-Host "Ignoring PYTEST_ADDOPTS for full-suite coverage verification."
            }
            $env:PYTEST_ADDOPTS = $null
        }
        Invoke-ExternalCommand -FilePath $python -ArgumentList $arguments
    } finally {
        $env:QT_QPA_PLATFORM = $previousQtPlatform
        if ($WithCoverage) {
            $env:PYTEST_ADDOPTS = $previousPytestOptions
        }
    }
}

function Get-FastCheckPlan {
    $python = Get-DevPython
    $planJson = & $python -B -m scripts.checks.select_tests --base-ref $BaseRef
    if ($LASTEXITCODE -ne 0) {
        throw "Test selection failed with exit code $LASTEXITCODE."
    }
    $plan = ($planJson -join "`n") | ConvertFrom-Json
    foreach ($reason in $plan.reasons) {
        Write-Host ("Changed: {0} -> {1}" -f $reason.path, $reason.reason)
    }
    if ($plan.full_suite) {
        Write-Host "Selection: FULL suite (conservative fallback)."
    }
    Write-Host "Selected $(@($plan.test_paths).Count) test file(s):"
    foreach ($path in $plan.test_paths) {
        Write-Host "  $path"
    }
    return $plan
}

function Invoke-FastCheck {
    $plan = Get-FastCheckPlan
    Invoke-CheckStage -Name "Lint" -Command { Invoke-LintChecks -Plan $plan }
    $paths = @($plan.test_paths)
    if ($paths.Count -gt 0 -or $plan.full_suite) {
        $workerCount = $Workers
        if ($workerCount -eq 0) {
            $workerCount = 2
            if (-not $plan.full_suite -and $paths.Count -lt 4) {
                $workerCount = 1
            }
        }
        if ($plan.full_suite) {
            $paths = @()
        }
        Invoke-CheckStage -Name "Tests (without coverage)" -Command {
            Invoke-TestSuite -Paths $paths -WorkerCount $workerCount
        }
    } else {
        Write-Host "No changed paths require tests."
    }
    Write-Host "Coverage and Windows package: skipped by check-fast. Run .\dev.ps1 check before a PR."
}

function Invoke-PackageBuild {
    $python = Get-DevPython
    & (Join-Path $RepoRoot "scripts\release\build_windows_package.ps1") -PythonPath $python
}

function Write-Help {
    Write-Output @"
Pogled Assist development commands

  .\dev.ps1 setup       Create or repair the Python 3.10 .venv and install tools
  .\dev.ps1 setup -BasePython C:\Path\To\python.exe    Select an installed Python
  .\dev.ps1 run         Start the real application from source
  .\dev.ps1 simulate    Start with mouse-driven gaze and no Tobii discovery
  .\dev.ps1 ui          Render deterministic UI screenshots under dist\ui-preview
  .\dev.ps1 ui -Open    Render UI screenshots and open the HTML gallery
  .\dev.ps1 test        Run the complete hardware-independent test suite
  .\dev.ps1 test -TestPaths tests/gaze    Run an explicitly focused selection
  .\dev.ps1 test-ui     Run only end-to-end UI workflow and rendering tests
  .\dev.ps1 coverage    Run tests with the enforced coverage floor and HTML report
  .\dev.ps1 lint        Run Actions, Ruff, formatting, compile, and PowerShell checks
  .\dev.ps1 format      Apply Ruff import fixes and Python formatting
  .\dev.ps1 check-fast  Lint and relevant changed tests, without coverage or package
  .\dev.ps1 check-fast -BaseRef origin/development    Override the comparison ref
  .\dev.ps1 check-fast -Workers 2    Use two workers even for a small selection
  .\dev.ps1 check       Run all local checks, including the Windows package
  .\dev.ps1 test -Workers 1    Run tests sequentially (default without coverage: two)
  .\dev.ps1 coverage -Workers 2    Opt in to parallel coverage (default: one process)
  .\dev.ps1 package     Build and smoke-test the Windows release ZIP

  coverage and check ignore PYTEST_ADDOPTS, then restore it after testing.
"@
}

Push-Location $RepoRoot
$totalTimer = [Diagnostics.Stopwatch]::StartNew()
try {
    switch ($Action) {
        "setup" {
            Install-DevEnvironment
        }
        "run" {
            $python = Get-DevPython
            Invoke-ExternalCommand -FilePath $python -ArgumentList @("-B", "run_gaze_mouse.py")
        }
        "simulate" {
            $python = Get-DevPython
            Invoke-ExternalCommand -FilePath $python -ArgumentList @(
                "-B", "run_gaze_mouse.py", "--simulate-gaze"
            )
        }
        "ui" {
            $python = Get-DevPython
            $outputRoot = Join-Path $RepoRoot "dist\ui-preview"
            Invoke-ExternalCommand -FilePath $python -ArgumentList @(
                "-B", "-m", "scripts.ui.capture_ui", "--output", $outputRoot
            )
            if ($Open) {
                Start-Process -FilePath (Join-Path $outputRoot "index.html")
            }
        }
        "test" {
            Invoke-CheckStage -Name "Tests" -Command { Invoke-TestSuite -Paths $TestPaths }
        }
        "test-ui" {
            Invoke-CheckStage -Name "UI tests" -Command { Invoke-TestSuite -UiOnly -Paths $TestPaths }
        }
        "coverage" {
            Invoke-CheckStage -Name "Tests and coverage" -Command { Invoke-TestSuite -WithCoverage }
        }
        "lint" {
            Invoke-CheckStage -Name "Lint" -Command { Invoke-LintChecks }
        }
        "format" {
            $python = Get-DevPython
            Invoke-ExternalCommand -FilePath $python -ArgumentList @("-m", "ruff", "check", "--fix", ".")
            Invoke-ExternalCommand -FilePath $python -ArgumentList @("-m", "ruff", "format", ".")
        }
        "check" {
            Invoke-CheckStage -Name "Lint" -Command { Invoke-LintChecks }
            Invoke-CheckStage -Name "Tests and coverage" -Command { Invoke-TestSuite -WithCoverage }
            Invoke-CheckStage -Name "Windows package and installer smoke tests" -Command { Invoke-PackageBuild }
        }
        "check-fast" {
            Invoke-FastCheck
        }
        "package" {
            Invoke-CheckStage -Name "Windows package and installer smoke tests" -Command { Invoke-PackageBuild }
        }
        default {
            Write-Help
        }
    }
} finally {
    $totalTimer.Stop()
    if ($StageTimings.Count -gt 0) {
        Write-Host "Verification timings:"
        foreach ($stage in $StageTimings) {
            Write-Host ("  {0}: {1:N1}s ({2})" -f $stage.Name, $stage.Seconds, $stage.Status)
        }
        Write-Host ("Total: {0:N1}s" -f $totalTimer.Elapsed.TotalSeconds)
    }
    Pop-Location
}
