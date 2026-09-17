[CmdletBinding()]
param(
    [string]$PythonPath = "python",
    [string]$OutputDirectory = "dist"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$VersionFile = Join-Path $RepoRoot "VERSION"
$SpecFile = Join-Path $RepoRoot "packaging\windows\TobiiGazeMouse.spec"
$PythonExecutable = if (Test-Path -LiteralPath $PythonPath -PathType Leaf) {
    (Resolve-Path -LiteralPath $PythonPath).Path
} else {
    (Get-Command $PythonPath -ErrorAction Stop).Source
}
$BuildPath = @(
    (Split-Path -Parent $PythonExecutable),
    (Join-Path $env:SystemRoot "System32"),
    $env:SystemRoot
) -join ";"
$OutputRoot = if ([IO.Path]::IsPathRooted($OutputDirectory)) {
    [IO.Path]::GetFullPath($OutputDirectory)
} else {
    [IO.Path]::GetFullPath((Join-Path $RepoRoot $OutputDirectory))
}
$RepoPrefix = [IO.Path]::GetFullPath($RepoRoot).TrimEnd("\") + "\"

if (-not ($OutputRoot + "\").StartsWith($RepoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDirectory must be inside the repository: $OutputRoot"
}

$Version = (Get-Content -LiteralPath $VersionFile -Raw).Trim()
if ($Version -notmatch "^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$") {
    throw "VERSION must contain a stable Semantic Version such as 0.1.0. Found: $Version"
}

$PackageRoot = Join-Path $OutputRoot "TobiiGazeMouse"
$WorkRoot = Join-Path $OutputRoot ".pyinstaller-build"
$ArtifactName = "TobiiGazeMouse-v$Version-windows-x64.zip"
$ArtifactPath = Join-Path $OutputRoot $ArtifactName

New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
foreach ($path in @($PackageRoot, $WorkRoot, $ArtifactPath)) {
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}

Push-Location $RepoRoot
$previousPath = $env:PATH
try {
    $env:PATH = $BuildPath
    & $PythonExecutable -m PyInstaller `
        --noconfirm `
        --clean `
        --distpath $OutputRoot `
        --workpath $WorkRoot `
        $SpecFile
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }
} finally {
    $env:PATH = $previousPath
    Pop-Location
}

$packageFiles = @{
    (Join-Path $RepoRoot "packaging\windows\install_windows.ps1") = "install_windows.ps1"
    (Join-Path $RepoRoot "packaging\windows\start_gaze_mouse.ps1") = "start_gaze_mouse.ps1"
    (Join-Path $RepoRoot "docs\WINDOWS_RELEASE.md") = "README.md"
    $VersionFile = "VERSION"
}
foreach ($sourcePath in $packageFiles.Keys) {
    Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $PackageRoot $packageFiles[$sourcePath]) -Force
}

$requiredFiles = @(
    "TobiiGazeMouse.exe",
    "install_windows.ps1",
    "start_gaze_mouse.ps1",
    "README.md",
    "VERSION",
    "_internal\assets\icon.png",
    "_internal\gaze_mouse\assets\checkbox_x.svg",
    "_internal\gaze_mouse\__init__.py",
    "_internal\gaze_mouse\tobii_stream_engine.py",
    "_internal\gaze_mouse\tobii_stream_engine_bridge.py"
)
foreach ($relativePath in $requiredFiles) {
    $fullPath = Join-Path $PackageRoot $relativePath
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        throw "Required package file is missing: $relativePath"
    }
}

$previousQtPlatform = $env:QT_QPA_PLATFORM
$previousSmokeReport = $env:TOBII_GAZE_MOUSE_PACKAGE_SMOKE_REPORT
$previousPath = $env:PATH
$smokeReportPath = Join-Path $OutputRoot "package-smoke-test.txt"
try {
    $env:QT_QPA_PLATFORM = "offscreen"
    $env:TOBII_GAZE_MOUSE_PACKAGE_SMOKE_REPORT = $smokeReportPath
    $env:PATH = (Join-Path $env:SystemRoot "System32") + ";" + $env:SystemRoot
    Remove-Item -LiteralPath $smokeReportPath -Force -ErrorAction SilentlyContinue
    $smokeProcess = Start-Process `
        -FilePath (Join-Path $PackageRoot "TobiiGazeMouse.exe") `
        -ArgumentList "--package-smoke-test" `
        -WorkingDirectory $PackageRoot `
        -WindowStyle Hidden `
        -PassThru
    if (-not $smokeProcess.WaitForExit(60000)) {
        Stop-Process -Id $smokeProcess.Id -Force -ErrorAction SilentlyContinue
        throw "Packaged application smoke test timed out after 60 seconds."
    }
    if ($smokeProcess.ExitCode -ne 0) {
        $smokeReport = if (Test-Path -LiteralPath $smokeReportPath) {
            (Get-Content -LiteralPath $smokeReportPath -Raw).Trim()
        } else {
            "No smoke-test report was written."
        }
        throw "Packaged application smoke test failed with exit code $($smokeProcess.ExitCode). $smokeReport"
    }
} finally {
    $env:QT_QPA_PLATFORM = $previousQtPlatform
    $env:TOBII_GAZE_MOUSE_PACKAGE_SMOKE_REPORT = $previousSmokeReport
    $env:PATH = $previousPath
}

Remove-Item -LiteralPath $smokeReportPath -Force -ErrorAction SilentlyContinue

Compress-Archive -LiteralPath $PackageRoot -DestinationPath $ArtifactPath -CompressionLevel Optimal

if (-not (Test-Path -LiteralPath $ArtifactPath -PathType Leaf)) {
    throw "Windows package was not created: $ArtifactPath"
}

$InstallerSmokeRoot = Join-Path $OutputRoot (".installer-smoke-{0}" -f [Guid]::NewGuid().ToString("N"))
try {
    $ExtractRoot = Join-Path $InstallerSmokeRoot "extracted"
    $InstallRoot = Join-Path $InstallerSmokeRoot "installed"
    New-Item -ItemType Directory -Path $ExtractRoot -Force | Out-Null
    Expand-Archive -LiteralPath $ArtifactPath -DestinationPath $ExtractRoot

    $InstallerPath = Join-Path $ExtractRoot "TobiiGazeMouse\install_windows.ps1"
    & $InstallerPath `
        -InstallRoot $InstallRoot `
        -NoDesktopShortcut `
        -NoElevation

    $preservedFiles = @{
        ".venv\Scripts\edge-playback.exe" = "preserved edge playback"
        "tools\tobii\tobii_stream_engine.dll" = "preserved Tobii DLL"
    }
    foreach ($relativePath in $preservedFiles.Keys) {
        $fullPath = Join-Path $InstallRoot $relativePath
        New-Item -ItemType Directory -Path (Split-Path -Parent $fullPath) -Force | Out-Null
        Set-Content -LiteralPath $fullPath -Value $preservedFiles[$relativePath] -Encoding ASCII
    }

    & $InstallerPath `
        -InstallRoot $InstallRoot `
        -NoDesktopShortcut `
        -NoElevation
    foreach ($relativePath in $preservedFiles.Keys) {
        $fullPath = Join-Path $InstallRoot $relativePath
        $actual = (Get-Content -LiteralPath $fullPath -Raw).Trim()
        if ($actual -ne $preservedFiles[$relativePath]) {
            throw "Installer did not preserve external component: $relativePath"
        }
    }

    $sourceScript = Join-Path $InstallRoot "run_gaze_mouse.py"
    Set-Content `
        -LiteralPath $sourceScript `
        -Value "import time; time.sleep(60)" `
        -Encoding ASCII
    $sourceProcess = Start-Process `
        -FilePath $PythonExecutable `
        -ArgumentList @("-B", ('"' + $sourceScript + '"')) `
        -WorkingDirectory $InstallRoot `
        -PassThru
    try {
        Start-Sleep -Milliseconds 500
        $runningSourceWasBlocked = $false
        try {
            & $InstallerPath `
                -InstallRoot $InstallRoot `
                -NoDesktopShortcut `
                -NoElevation
        } catch {
            if ($_.Exception.Message -like "Close Tobii Gaze Mouse before installing*") {
                $runningSourceWasBlocked = $true
            } else {
                throw
            }
        }
        if (-not $runningSourceWasBlocked) {
            throw "Installer did not reject a running source application."
        }
    } finally {
        if (-not $sourceProcess.HasExited) {
            Stop-Process -Id $sourceProcess.Id -Force -ErrorAction SilentlyContinue
        }
        $sourceProcess.Dispose()
    }

    Write-Host "Isolated install, upgrade preservation, and running-app checks passed."
} finally {
    if (Test-Path -LiteralPath $InstallerSmokeRoot) {
        Remove-Item -LiteralPath $InstallerSmokeRoot -Recurse -Force
    }
}

if (-not [string]::IsNullOrWhiteSpace($env:GITHUB_OUTPUT)) {
    Add-Content -LiteralPath $env:GITHUB_OUTPUT -Value "version=$Version"
    Add-Content -LiteralPath $env:GITHUB_OUTPUT -Value "artifact_name=$ArtifactName"
    Add-Content -LiteralPath $env:GITHUB_OUTPUT -Value "artifact_path=$ArtifactPath"
}

Write-Host "Created Windows package: $ArtifactPath"
