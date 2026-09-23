[CmdletBinding()]
param(
    [ValidateSet("help", "setup", "run", "simulate", "ui", "test", "test-ui", "coverage", "lint", "format", "check", "package")]
    [string]$Action = "help",
    [string]$BasePython,
    [switch]$Open
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = $PSScriptRoot
$VenvRoot = Join-Path $RepoRoot ".venv"
$PythonPath = Join-Path $VenvRoot "Scripts\python.exe"
$RequiredPythonVersion = "3.10"
$AnalyzerVersion = "1.25.0"
$AnalyzerPath = Join-Path $RepoRoot ".dev-tools\PSScriptAnalyzer\$AnalyzerVersion\PSScriptAnalyzer.psd1"

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

    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        return $null
    }
    try {
        # Legacy PowerShell drops quotes inside arguments passed to native commands.
        $probe = & $Executable -c 'import sys; print(str(sys.version_info.major)+chr(46)+str(sys.version_info.minor) if sys.maxsize > 2**32 else 32)' 2>$null
        if ($LASTEXITCODE -ne 0) {
            return $null
        }
        return ([string]($probe | Select-Object -First 1)).Trim()
    } catch {
        return $null
    }
}

function Get-PythonBaseExecutable {
    param([string]$Executable)

    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        return $null
    }
    try {
        $probe = & $Executable -c 'import sys; print(sys._base_executable)' 2>$null
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

    $launcher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($null -ne $launcher) {
        try {
            $candidate = & $launcher.Source "-$RequiredPythonVersion" -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0) {
                $candidatePath = ([string]($candidate | Select-Object -First 1)).Trim()
                if ((Get-PythonVersion -Executable $candidatePath) -eq $RequiredPythonVersion) {
                    return $candidatePath
                }
            }
        } catch {
            Write-Verbose "Python launcher probe failed: $($_.Exception.Message)"
        }
    }

    $command = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($null -ne $command -and (Get-PythonVersion -Executable $command.Source) -eq $RequiredPythonVersion) {
        return $command.Source
    }
    throw "Python 3.10 x64 was not found. Install it or pass -BasePython <path> to setup."
}

function Install-DevEnvironment {
    $currentVersion = Get-PythonVersion -Executable $PythonPath
    $base = $null
    if (-not [string]::IsNullOrWhiteSpace($BasePython)) {
        $base = Resolve-BasePython
    }
    if ($currentVersion -ne $RequiredPythonVersion -or
        ($null -ne $base -and -not (Test-SamePythonBase -ExistingEnvironment $PythonPath -RequestedInterpreter $base))) {
        if ($null -eq $base) {
            $base = Resolve-BasePython
        }
        if (Test-Path -LiteralPath $VenvRoot) {
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

function Invoke-LintChecks {
    $python = Get-DevPython
    & (Join-Path $RepoRoot "scripts\checks\check_github_actions.ps1")
    Invoke-ExternalCommand -FilePath $python -ArgumentList @("-m", "ruff", "check", ".")
    Invoke-ExternalCommand -FilePath $python -ArgumentList @("-m", "ruff", "format", "--check", ".")
    Invoke-ExternalCommand -FilePath $python -ArgumentList @(
        "-B", "-m", "compileall", "-q", "pogled_assist", "scripts", "tests", "run_gaze_mouse.py"
    )
    & (Join-Path $RepoRoot "scripts\checks\check_powershell.ps1") -RequireAnalyzer
}

function Invoke-TestSuite {
    param(
        [switch]$UiOnly,
        [switch]$WithCoverage
    )

    $python = Get-DevPython
    $arguments = @("-B", "-m", "pytest", "-p", "no:cacheprovider")
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

    $previousQtPlatform = $env:QT_QPA_PLATFORM
    try {
        $env:QT_QPA_PLATFORM = "offscreen"
        Invoke-ExternalCommand -FilePath $python -ArgumentList $arguments
    } finally {
        $env:QT_QPA_PLATFORM = $previousQtPlatform
    }
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
  .\dev.ps1 test-ui     Run only end-to-end UI workflow and rendering tests
  .\dev.ps1 coverage    Run tests with the enforced coverage floor and HTML report
  .\dev.ps1 lint        Run Actions, Ruff, formatting, compile, and PowerShell checks
  .\dev.ps1 format      Apply Ruff import fixes and Python formatting
  .\dev.ps1 check       Run all local checks, including the Windows package
  .\dev.ps1 package     Build and smoke-test the Windows release ZIP
"@
}

Push-Location $RepoRoot
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
            Invoke-TestSuite
        }
        "test-ui" {
            Invoke-TestSuite -UiOnly
        }
        "coverage" {
            Invoke-TestSuite -WithCoverage
        }
        "lint" {
            Invoke-LintChecks
        }
        "format" {
            $python = Get-DevPython
            Invoke-ExternalCommand -FilePath $python -ArgumentList @("-m", "ruff", "check", "--fix", ".")
            Invoke-ExternalCommand -FilePath $python -ArgumentList @("-m", "ruff", "format", ".")
        }
        "check" {
            Invoke-LintChecks
            Invoke-TestSuite -WithCoverage
            Invoke-PackageBuild
        }
        "package" {
            Invoke-PackageBuild
        }
        default {
            Write-Help
        }
    }
} finally {
    Pop-Location
}
