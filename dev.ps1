[CmdletBinding()]
param(
    [ValidateSet("help", "setup", "run", "simulate", "ui", "test", "test-ui", "coverage", "lint", "format", "check-fast", "check", "package")]
    [string]$Action = "help",
    [string]$BasePython,
    [switch]$Open,
    [ValidateSet("core", "full")]
    [string]$UiProfile = "core",
    [ValidateSet("speech", "keyboards", "settings", "tracking", "gaze-check", "voice")]
    [string[]]$UiGroup = @(),
    [ValidateSet(0, 1, 2)]
    [int]$Workers = 0,
    [switch]$Parallel,
    [Parameter(DontShow)]
    [switch]$ParallelCoverageSubset,
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
if (($UiProfile -ne "core" -or $UiGroup.Count -gt 0) -and $Action -ne "ui") {
    throw "-UiProfile and -UiGroup are supported only by ui."
}
if ($Parallel -and $Action -ne "check") {
    throw "-Parallel is supported only by check."
}
if ($ParallelCoverageSubset -and $Action -ne "coverage") {
    throw "-ParallelCoverageSubset is supported only by the internal coverage check."
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

    return Invoke-PythonProbe -Executable $Executable -Code 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}" if sys.maxsize > 2**32 else 32)'
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
    $process = [Diagnostics.Process]::new()
    try {
        $process.StartInfo.FileName = $Executable
        # Passing code through stdin avoids legacy PowerShell argument quoting.
        $process.StartInfo.Arguments = "-"
        # The Windows shell can prompt before rejecting a broken executable.
        $process.StartInfo.UseShellExecute = $false
        $process.StartInfo.CreateNoWindow = $true
        $process.StartInfo.RedirectStandardInput = $true
        $process.StartInfo.RedirectStandardOutput = $true
        $process.StartInfo.RedirectStandardError = $true
        $process.Start() | Out-Null
        $output = $process.StandardOutput.ReadToEndAsync()
        $errors = $process.StandardError.ReadToEndAsync()
        $process.StandardInput.WriteLine($Code)
        $process.StandardInput.Close()
        $process.WaitForExit()
        $probe = $output.GetAwaiter().GetResult()
        $errors.GetAwaiter().GetResult() | Out-Null
        if ($process.ExitCode -ne 0) {
            return $null
        }
        return ($probe -split "`n")[0].Trim()
    } catch {
        return $null
    } finally {
        $process.Dispose()
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

    Write-Output "Development environment is ready. Run .\dev.ps1 check -Parallel."
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

function Resolve-TestWorkerCount {
    param([int]$WorkerCount, [switch]$WithCoverage)

    if ($WorkerCount -eq 0) {
        $WorkerCount = 2
        if ($WithCoverage) {
            $WorkerCount = 1
        }
    }
    return $WorkerCount
}

function Invoke-TestSuite {
    param(
        [switch]$UiOnly,
        [ValidateSet("None", "Full", "Collect", "Append")]
        [string]$Coverage = "None",
        [string[]]$Paths = @(),
        [string[]]$IgnorePaths = @(),
        [int]$WorkerCount = $Workers
    )

    $python = Get-DevPython
    $withCoverage = $Coverage -ne "None"
    $arguments = @("-B", "-m", "pytest", "-p", "no:cacheprovider")
    $WorkerCount = Resolve-TestWorkerCount -WorkerCount $WorkerCount -WithCoverage:$WithCoverage
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
        $arguments += Get-CoverageArguments -Mode $Coverage
    }
    $arguments += @($IgnorePaths | ForEach-Object { "--ignore=$_" })
    $arguments += $Paths

    Invoke-Pytest -Python $python -Arguments $arguments -WithCoverage:$WithCoverage
}

function Get-CoverageArguments {
    param([ValidateSet("Full", "Collect", "Append")][string]$Mode)

    $arguments = @("--cov=pogled_assist")
    if ($Mode -eq "Collect") {
        # Enforce the floor on the combined data after the installer phase.
        $arguments += @("--cov-report=", "--cov-fail-under=0")
    } else {
        $coverageHtml = Join-Path $RepoRoot "dist\coverage-html"
        $arguments += @(
            "--cov-report=term-missing:skip-covered",
            "--cov-report=html:$coverageHtml"
        )
    }
    if ($Mode -eq "Append") {
        $arguments += "--cov-append"
    }
    return $arguments
}

function Invoke-Pytest {
    param([string]$Python, [string[]]$Arguments, [switch]$WithCoverage)

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
    Write-Host "Coverage and Windows package: skipped by check-fast. Run .\dev.ps1 check -Parallel before a PR."
}

function Invoke-PackageBuild {
    $python = Get-DevPython
    & (Join-Path $RepoRoot "scripts\release\build_windows_package.ps1") -PythonPath $python
}

function New-CheckStage {
    param($Definition, [string]$LogRoot)

    $process = [Diagnostics.Process]::new()
    $stage = [PSCustomObject]@{
        Name = $definition.Name
        Process = $process
        Timer = [Diagnostics.Stopwatch]::new()
        Started = $false
        Finished = $false
        OutputFile = $null
        ErrorFile = $null
        OutputTask = $null
        ErrorTask = $null
        Log = Join-Path $logRoot ($definition.Action + ".log")
        ErrorLog = Join-Path $logRoot ($definition.Action + ".stderr.log")
    }
    return $stage
}

function Start-CheckStage {
    param($Stage, $Definition, [string]$ScriptPath)

    $process = $Stage.Process
    $shellName = if ($PSEdition -eq "Desktop") { "powershell.exe" } else { "pwsh.exe" }
    $stage.OutputFile = [IO.File]::Create($stage.Log)
    $stage.ErrorFile = [IO.File]::Create($stage.ErrorLog)
    $stageArguments = "{0} -Workers {1}" -f $definition.Action, $Workers
    if ($definition.ParallelCoverageSubset) {
        $stageArguments += " -ParallelCoverageSubset"
    }
    $command = "try {{ & '{0}' {1}; exit 0 }} catch {{ Write-Error `$_ -ErrorAction Continue; exit 1 }}" -f @(
        $ScriptPath.Replace("'", "''"), $stageArguments
    )
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
    $process.StartInfo.FileName = Join-Path $PSHOME $shellName
    $process.StartInfo.Arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -OutputFormat Text -EncodedCommand $encoded"
    $process.StartInfo.WorkingDirectory = $RepoRoot
    $process.StartInfo.UseShellExecute = $false
    $process.StartInfo.CreateNoWindow = $true
    $process.StartInfo.RedirectStandardOutput = $true
    $process.StartInfo.RedirectStandardError = $true
    Write-Host "Starting: $($stage.Name); logs: $($stage.Log), $($stage.ErrorLog)"
    $stage.Timer.Start()
    if (-not $process.Start()) { throw "Could not start $($stage.Name)." }
    $stage.Started = $true
    $stage.OutputTask = $process.StandardOutput.BaseStream.CopyToAsync($stage.OutputFile)
    $stage.ErrorTask = $process.StandardError.BaseStream.CopyToAsync($stage.ErrorFile)
}

function Complete-CheckStage {
    param($Stage, $Failed)

    $stage.Timer.Stop()
    $status = "passed"
    try {
        foreach ($task in @($stage.OutputTask, $stage.ErrorTask)) {
            if (-not $task.Wait(10000)) { throw "Timed out draining check output." }
        }
        if ($stage.Process.ExitCode -ne 0) { $status = "FAILED" }
    } catch {
        $status = "FAILED"
        Write-Warning "$($stage.Name): $_"
    }
    $stage.Finished = $true
    $StageTimings.Add([PSCustomObject]@{
        Name = $stage.Name
        Seconds = $stage.Timer.Elapsed.TotalSeconds
        Status = $status
    })
    if ($status -ne "passed") { $failed.Add($stage.Name) }
    Write-Host ("Finished: {0} ({1}, {2:N1}s); logs: {3}, {4}" -f @(
        $stage.Name, $status, $stage.Timer.Elapsed.TotalSeconds, $stage.Log, $stage.ErrorLog
    ))
}

function Write-CheckProgress {
    param($Stages, $Timer, [double]$NextStatus, [int]$Interval)

    $active = @($Stages | Where-Object { -not $_.Finished })
    if ($active.Count -eq 0 -or $Timer.Elapsed.TotalMilliseconds -lt $NextStatus) {
        return $NextStatus
    }
    $details = foreach ($stage in $active) {
        "{0} ({1:mm\:ss} elapsed)" -f $stage.Name, $stage.Timer.Elapsed
    }
    # Plain lines remain visible in captured output as well as terminals.
    Write-Host ("Running: {0} | {1}/{2} finished" -f @(
        ($details -join "; "), ($Stages.Count - $active.Count), $Stages.Count
    ))
    return $Timer.Elapsed.TotalMilliseconds + $Interval
}

function Wait-CheckStages {
    param($Stages, $Failed, [int]$StatusIntervalMilliseconds)

    $statusTimer = [Diagnostics.Stopwatch]::StartNew()
    $nextStatusMilliseconds = 0
    while (@($stages | Where-Object { -not $_.Finished }).Count -gt 0) {
        foreach ($stage in $stages) {
            if ($stage.Finished -or -not $stage.Process.HasExited) { continue }
            Complete-CheckStage -Stage $stage -Failed $failed
        }
        $nextStatusMilliseconds = Write-CheckProgress `
            -Stages $stages -Timer $statusTimer -NextStatus $nextStatusMilliseconds `
            -Interval $StatusIntervalMilliseconds
        if (@($stages | Where-Object { -not $_.Finished }).Count -gt 0) {
            Start-Sleep -Milliseconds 200
        }
    }
}

function Close-CheckStages {
    param($Stages)

    foreach ($stage in $stages) {
        if ($stage.Started -and -not $stage.Process.HasExited) {
            & (Join-Path $env:SystemRoot "System32\taskkill.exe") /PID $stage.Process.Id /T /F | Out-Null
            $null = $stage.Process.WaitForExit(5000)
        }
        foreach ($stream in @($stage.OutputFile, $stage.ErrorFile)) {
            if ($null -ne $stream) { $stream.Dispose() }
        }
        $stage.Process.Dispose()
    }
}

function Invoke-ParallelCheck {
    param(
        [string]$ScriptPath = (Join-Path $RepoRoot "dev.ps1"),
        [ValidateRange(100, 60000)]
        [int]$StatusIntervalMilliseconds = 5000
    )

    $logRoot = Join-Path $RepoRoot ("dist\check-{0}" -f [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
    $stages = [Collections.Generic.List[object]]::new()
    $failed = [Collections.Generic.List[string]]::new()
    try {
        foreach ($definition in @(
            @{
                Action = "coverage"
                Name = "Tests and coverage"
                ParallelCoverageSubset = $true
            },
            @{
                Action = "package"
                Name = "Windows package and installer smoke tests"
                ParallelCoverageSubset = $false
            }
        )) {
            $stage = New-CheckStage -Definition $definition -LogRoot $logRoot
            $stages.Add($stage)
            Start-CheckStage -Stage $stage -Definition $definition -ScriptPath $ScriptPath
        }
        Wait-CheckStages -Stages $stages -Failed $failed -StatusIntervalMilliseconds $StatusIntervalMilliseconds
        try {
            Invoke-CheckStage -Name "Installer integration tests and coverage" -Command {
                Invoke-TestSuite `
                    -Coverage Append `
                    -Paths @("tests/release/test_windows_installer.py")
            }
        } catch {
            $failed.Add("Installer integration tests and coverage")
        }
        if ($failed.Count -gt 0) { throw "Failed checks: $($failed -join ', '). See logs in $logRoot" }
    } finally {
        Close-CheckStages -Stages $stages
    }
}

function Write-Help {
    Write-Output @"
Pogled Assist development commands

  .\dev.ps1 setup       Create or repair the Python 3.10 .venv and install tools
  .\dev.ps1 setup -BasePython C:\Path\To\python.exe    Select an installed Python
  .\dev.ps1 run         Start the real application from source
  .\dev.ps1 simulate    Start with mouse-driven gaze and no Tobii discovery
  .\dev.ps1 ui          Render representative UI screenshots under dist\ui-preview
  .\dev.ps1 ui -Open    Render UI screenshots and open the HTML gallery
  .\dev.ps1 ui -UiProfile full    Render all screenshot variants
  .\dev.ps1 ui -UiProfile full -UiGroup voice    Render only the extended voice group
  .\dev.ps1 test        Run the complete hardware-independent test suite
  .\dev.ps1 test -TestPaths tests/gaze    Run an explicitly focused selection
  .\dev.ps1 test-ui     Run only end-to-end UI workflow and rendering tests
  .\dev.ps1 coverage    Run tests with the enforced coverage floor and HTML report
  .\dev.ps1 lint        Run Actions, Ruff, formatting, compile, and PowerShell checks
  .\dev.ps1 format      Apply Ruff import fixes and Python formatting
  .\dev.ps1 check-fast  Lint and relevant changed tests, without coverage or package
  .\dev.ps1 check-fast -BaseRef origin/development    Override the comparison ref
  .\dev.ps1 check-fast -Workers 2    Use two workers even for a small selection
  .\dev.ps1 check       Run all local checks sequentially, including the Windows package
  .\dev.ps1 check -Parallel    After lint, run coverage and packaging with status every 5 seconds
  .\dev.ps1 test -Workers 1    Run tests sequentially (default without coverage: two)
  .\dev.ps1 coverage -Workers 2    Opt in to parallel coverage (default: one process)
  .\dev.ps1 package     Build and smoke-test the Windows release ZIP

  coverage and check ignore PYTEST_ADDOPTS, then restore it after testing.
  check -Parallel writes combined coverage reports once, after installer tests.
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
            $uiArguments = @(
                "-B", "-m", "scripts.ui.capture_ui", "--output", $outputRoot,
                "--profile", $UiProfile
            )
            foreach ($group in $UiGroup) {
                $uiArguments += @("--group", $group)
            }
            Invoke-ExternalCommand -FilePath $python -ArgumentList $uiArguments
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
            if ($ParallelCoverageSubset) {
                Invoke-CheckStage -Name "Tests and coverage" -Command {
                    Invoke-TestSuite `
                        -Coverage Collect `
                        -IgnorePaths @("tests/release/test_windows_installer.py")
                }
            } else {
                Invoke-CheckStage -Name "Tests and coverage" -Command { Invoke-TestSuite -Coverage Full }
            }
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
            if ($Parallel) {
                Invoke-ParallelCheck
            } else {
                Invoke-CheckStage -Name "Tests and coverage" -Command { Invoke-TestSuite -Coverage Full }
                Invoke-CheckStage -Name "Windows package and installer smoke tests" -Command { Invoke-PackageBuild }
            }
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
