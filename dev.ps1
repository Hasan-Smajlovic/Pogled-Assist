[CmdletBinding()]
param(
    [ValidateSet("help", "setup", "run", "ui", "test", "test-ui", "coverage", "lint", "format", "check", "package")]
    [string]$Action = "help",
    [switch]$Open
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = $PSScriptRoot
$VenvRoot = Join-Path $RepoRoot ".venv"
$PythonPath = Join-Path $VenvRoot "Scripts\python.exe"
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
    return $PythonPath
}

function Install-DevEnvironment {
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        $launcher = Get-Command "py.exe" -ErrorAction SilentlyContinue
        if ($null -eq $launcher) {
            throw "Python launcher was not found. Install Python 3.10, then rerun setup."
        }
        Invoke-ExternalCommand -FilePath $launcher.Source -ArgumentList @(
            "-3.10", "-m", "venv", $VenvRoot
        )
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

    & (Join-Path $RepoRoot "scripts\check_github_actions.ps1") -Install

    Write-Output "Development environment is ready. Run .\dev.ps1 check."
}

function Invoke-LintChecks {
    $python = Get-DevPython
    & (Join-Path $RepoRoot "scripts\check_github_actions.ps1")
    Invoke-ExternalCommand -FilePath $python -ArgumentList @("-m", "ruff", "check", ".")
    Invoke-ExternalCommand -FilePath $python -ArgumentList @("-m", "ruff", "format", "--check", ".")
    Invoke-ExternalCommand -FilePath $python -ArgumentList @(
        "-B", "-m", "compileall", "-q", "gaze_mouse", "scripts", "tests", "run_gaze_mouse.py"
    )
    & (Join-Path $RepoRoot "scripts\check_powershell.ps1") -RequireAnalyzer
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
            "--cov=gaze_mouse",
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
    & (Join-Path $RepoRoot "scripts\build_windows_package.ps1") -PythonPath $python
}

function Write-Help {
    Write-Output @"
Tobii Gaze Mouse development commands

  .\dev.ps1 setup       Create .venv and install development/build tools
  .\dev.ps1 run         Start the real application from source
  .\dev.ps1 ui          Render deterministic UI screenshots under dist\ui-preview
  .\dev.ps1 ui -Open    Render UI screenshots and open the HTML gallery
  .\dev.ps1 test        Run the complete hardware-independent test suite
  .\dev.ps1 test-ui     Run only end-to-end UI workflow and rendering tests
  .\dev.ps1 coverage    Run tests with the enforced coverage floor and HTML report
  .\dev.ps1 lint        Run Actions, Ruff, formatting, compile, and PowerShell checks
  .\dev.ps1 format      Apply Ruff import fixes and Python formatting
  .\dev.ps1 check       Run every local check expected before a pull request
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
        "ui" {
            $python = Get-DevPython
            $outputRoot = Join-Path $RepoRoot "dist\ui-preview"
            Invoke-ExternalCommand -FilePath $python -ArgumentList @(
                "-B", "-m", "scripts.capture_ui", "--output", $outputRoot
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
