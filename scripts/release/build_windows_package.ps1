[CmdletBinding()]
param(
    [string]$PythonPath = "python",
    [string]$OutputDirectory = "dist"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$VersionFile = Join-Path $RepoRoot "VERSION"
$SpecFile = Join-Path $RepoRoot "packaging\windows\PogledAssist.spec"
$PythonExecutable = if (Test-Path -LiteralPath $PythonPath -PathType Leaf) {
    (Resolve-Path -LiteralPath $PythonPath).Path
} else {
    (Get-Command $PythonPath -ErrorAction Stop).Source
}
# Legacy PowerShell drops quotes inside arguments passed to native commands.
$PythonVersion = & $PythonExecutable -c 'import sys; print(str(sys.version_info.major)+chr(46)+str(sys.version_info.minor) if sys.maxsize > 2**32 else 32)'
if ($LASTEXITCODE -ne 0 -or $PythonVersion -ne "3.10") {
    throw "Windows packaging requires 64-bit Python 3.10 because tobii-research 2.1.0 has no Windows wheel for newer Python."
}
$BuildPath = @(
    (Split-Path -Parent $PythonExecutable),
    (Join-Path $env:SystemRoot "System32"),
    $env:SystemRoot
) -join ";"
$PowerShellExecutable = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
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

function Invoke-IsolatedInstaller {
    param(
        [string]$InstallerPath,
        [string]$InstallRoot
    )

    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $InstallerPath,
        "-InstallRoot", $InstallRoot,
        "-NoDesktopShortcut",
        "-NoSetupWindow",
        "-NoElevation"
    )
    $stderrPath = [IO.Path]::GetTempFileName()
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = @(& $PowerShellExecutable @arguments 2> $stderrPath)
        $exitCode = $LASTEXITCODE
        # Keep the child status in the result without leaking it into the build step.
        $global:LASTEXITCODE = 0
        if (Test-Path -LiteralPath $stderrPath -PathType Leaf) {
            $output += Get-Content -LiteralPath $stderrPath
        }
        $output | ForEach-Object { Write-Host $_ }
        return [PSCustomObject]@{
            ExitCode = $exitCode
            Output = $output -join [Environment]::NewLine
        }
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
        Remove-Item -LiteralPath $stderrPath -Force -ErrorAction SilentlyContinue
    }
}

$PackageRoot = Join-Path $OutputRoot "PogledAssist"
$WorkRoot = Join-Path $OutputRoot ".pyinstaller-build"
$ArtifactName = "PogledAssist-v$Version-windows-x64.zip"
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
    (Join-Path $RepoRoot "update_windows.ps1") = "update_windows.ps1"
    (Join-Path $RepoRoot "docs\WINDOWS_RELEASE.md") = "README.md"
    $VersionFile = "VERSION"
}
foreach ($sourcePath in $packageFiles.Keys) {
    Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $PackageRoot $packageFiles[$sourcePath]) -Force
}

$SpeechRoot = Join-Path $PackageRoot "speech"
& $PythonExecutable (Join-Path $PSScriptRoot "prepare_speech_bundle.py") `
    --destination $SpeechRoot `
    --bridge-destination (Join-Path $PackageRoot "runtime\python-x86") `
    --cache (Join-Path $RepoRoot ".dev-tools\speech-cache")
if ($LASTEXITCODE -ne 0) {
    throw "Preparing the bundled speech assets failed."
}
& $PythonExecutable -m PyInstaller --noconfirm --clean `
    --distpath $SpeechRoot `
    --workpath (Join-Path $WorkRoot "speech") `
    (Join-Path $RepoRoot "packaging\windows\SpeechTools.spec")
if ($LASTEXITCODE -ne 0) {
    throw "Building the bundled Edge speech tools failed."
}

$requiredFiles = @(
    "PogledAssist.exe",
    "runtime\python-x86\python.exe",
    "runtime\python-x86\python310.dll",
    "runtime\python-x86\python310.zip",
    "runtime\python-x86\python310._pth",
    "runtime\python-x86\LICENSE.txt",
    "speech\espeak-ng\espeak-ng.exe",
    "speech\espeak-ng\libespeak-ng.dll",
    "speech\espeak-ng\espeak-ng-data\bs_dict",
    "speech\edge\edge-playback.exe",
    "speech\edge\edge-tts.exe",
    "speech\licenses\espeak-ng-LICENSE.txt",
    "speech\licenses\edge-tts-LICENSE.txt",
    "install_windows.ps1",
    "start_gaze_mouse.ps1",
    "update_windows.ps1",
    "README.md",
    "VERSION",
    "_internal\assets\icon.png",
    "_internal\pogled_assist\assets\emergency_alarm.wav",
    "_internal\pogled_assist\assets\bosnian-model.json.gz",
    "_internal\pogled_assist\assets\bosnian-model.meta.json",
    "_internal\pogled_assist\assets\bosnian-islamic-model.json.gz",
    "_internal\pogled_assist\assets\bosnian-islamic-model.meta.json",
    "_internal\pogled_assist\assets\checkbox_x.svg",
    "_internal\pogled_assist\__init__.py",
    "_internal\pogled_assist\tracking\__init__.py",
    "_internal\pogled_assist\tracking\tobii_stream_engine.py",
    "_internal\pogled_assist\tracking\tobii_stream_engine_bridge.py"
)
foreach ($relativePath in $requiredFiles) {
    $fullPath = Join-Path $PackageRoot $relativePath
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        throw "Required package file is missing: $relativePath"
    }
}

$previousQtPlatform = $env:QT_QPA_PLATFORM
$previousSmokeReport = $env:POGLED_ASSIST_PACKAGE_SMOKE_REPORT
$previousPath = $env:PATH
$smokeReportPath = Join-Path $OutputRoot "package-smoke-test.txt"
try {
    $env:QT_QPA_PLATFORM = "offscreen"
    $env:POGLED_ASSIST_PACKAGE_SMOKE_REPORT = $smokeReportPath
    $env:PATH = (Join-Path $env:SystemRoot "System32") + ";" + $env:SystemRoot
    Remove-Item -LiteralPath $smokeReportPath -Force -ErrorAction SilentlyContinue
    $smokeProcess = Start-Process `
        -FilePath (Join-Path $PackageRoot "PogledAssist.exe") `
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
    $env:POGLED_ASSIST_PACKAGE_SMOKE_REPORT = $previousSmokeReport
    $env:PATH = $previousPath
}

Remove-Item -LiteralPath $smokeReportPath -Force -ErrorAction SilentlyContinue

& (Join-Path $PSScriptRoot "compress_package.ps1") -PackageRoot $PackageRoot -ArtifactPath $ArtifactPath

if (-not (Test-Path -LiteralPath $ArtifactPath -PathType Leaf)) {
    throw "Windows package was not created: $ArtifactPath"
}

$InstallerSmokeRoot = Join-Path $OutputRoot (".installer-smoke-{0}" -f [Guid]::NewGuid().ToString("N"))
try {
    $ExtractRoot = Join-Path $InstallerSmokeRoot "extracted"
    $InstallRoot = Join-Path $InstallerSmokeRoot "installed"
    New-Item -ItemType Directory -Path $ExtractRoot -Force | Out-Null
    Expand-Archive -LiteralPath $ArtifactPath -DestinationPath $ExtractRoot

    $InstallerPath = Join-Path $ExtractRoot "PogledAssist\install_windows.ps1"
    $installResult = Invoke-IsolatedInstaller -InstallerPath $InstallerPath -InstallRoot $InstallRoot
    if ($installResult.ExitCode -ne 0) {
        throw "Isolated installer failed with exit code $($installResult.ExitCode)."
    }

    $preservedFiles = @{
        ".venv\Scripts\edge-playback.exe" = "preserved edge playback"
        "tools\tobii\tobii_stream_engine.dll" = "preserved Tobii DLL"
    }
    foreach ($relativePath in $preservedFiles.Keys) {
        $fullPath = Join-Path $InstallRoot $relativePath
        New-Item -ItemType Directory -Path (Split-Path -Parent $fullPath) -Force | Out-Null
        Set-Content -LiteralPath $fullPath -Value $preservedFiles[$relativePath] -Encoding ASCII
    }

    $upgradeResult = Invoke-IsolatedInstaller -InstallerPath $InstallerPath -InstallRoot $InstallRoot
    if ($upgradeResult.ExitCode -ne 0) {
        throw "Isolated installer upgrade failed with exit code $($upgradeResult.ExitCode)."
    }
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
        $runningSourceResult = Invoke-IsolatedInstaller -InstallerPath $InstallerPath -InstallRoot $InstallRoot
        & (Join-Path $PSScriptRoot "check_running_app_rejection.ps1") `
            -ExitCode $runningSourceResult.ExitCode `
            -InstallerOutput $runningSourceResult.Output
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
