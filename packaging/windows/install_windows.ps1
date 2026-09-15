[CmdletBinding()]
param(
    [string]$InstallRoot = "C:\TobiiExec",
    [switch]$NoDesktopShortcut,
    [switch]$Launch,
    [switch]$NoElevation
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$SourceRoot = Split-Path -Parent $PSCommandPath
$InstallerPath = $PSCommandPath

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Quote-Argument {
    param([string]$Value)
    return '"' + $Value.Replace('"', '\"') + '"'
}

function Get-PowerShellExecutable {
    return Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
}

if (-not (Test-IsAdministrator) -and -not $NoElevation) {
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", (Quote-Argument $InstallerPath),
        "-InstallRoot", (Quote-Argument $InstallRoot),
        "-NoElevation"
    )
    if ($NoDesktopShortcut) {
        $arguments += "-NoDesktopShortcut"
    }
    if ($Launch) {
        $arguments += "-Launch"
    }

    Start-Process `
        -FilePath (Get-PowerShellExecutable) `
        -ArgumentList ($arguments -join " ") `
        -WorkingDirectory $SourceRoot `
        -Verb RunAs | Out-Null
    exit 0
}

$requiredSourceFiles = @(
    "TobiiGazeMouse.exe",
    "_internal",
    "start_gaze_mouse.ps1",
    "VERSION"
)
foreach ($relativePath in $requiredSourceFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $SourceRoot $relativePath))) {
        throw "The extracted package is incomplete. Missing: $relativePath"
    }
}

$sourceFullPath = [IO.Path]::GetFullPath($SourceRoot).TrimEnd("\")
$installFullPath = [IO.Path]::GetFullPath($InstallRoot).TrimEnd("\")
$installDriveRoot = [IO.Path]::GetPathRoot($installFullPath).TrimEnd("\")
if ($installFullPath -eq $installDriveRoot) {
    throw "InstallRoot cannot be a drive root: $installFullPath"
}
if ($sourceFullPath -ne $installFullPath) {
    $sourcePrefix = $sourceFullPath + "\"
    $installPrefix = $installFullPath + "\"
    if (
        $sourcePrefix.StartsWith($installPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        $installPrefix.StartsWith($sourcePrefix, [StringComparison]::OrdinalIgnoreCase)
    ) {
        throw "InstallRoot and the extracted package cannot contain one another. Source: $sourceFullPath. Target: $installFullPath"
    }
}
if ($sourceFullPath -ne $installFullPath) {
    New-Item -ItemType Directory -Path $installFullPath -Force | Out-Null
    $robocopyArguments = @(
        $sourceFullPath,
        $installFullPath,
        "/MIR",
        "/R:2",
        "/W:2",
        "/NFL",
        "/NDL",
        "/NP",
        "/XD", "data", "logs",
        "/XF", "install_info.json", "*.log"
    )
    & robocopy @robocopyArguments | ForEach-Object { Write-Host $_ }
    $robocopyExitCode = $LASTEXITCODE
    if ($robocopyExitCode -gt 7) {
        throw "Could not copy the package to $installFullPath. Robocopy exit code: $robocopyExitCode"
    }
    # Robocopy uses successful non-zero codes when files were copied or changed.
    $global:LASTEXITCODE = 0
}

$appExecutable = Join-Path $installFullPath "TobiiGazeMouse.exe"
$launcherPath = Join-Path $installFullPath "start_gaze_mouse.ps1"
$smokeProcess = Start-Process `
    -FilePath $appExecutable `
    -ArgumentList "--package-smoke-test" `
    -WorkingDirectory $installFullPath `
    -WindowStyle Hidden `
    -PassThru
if (-not $smokeProcess.WaitForExit(60000)) {
    Stop-Process -Id $smokeProcess.Id -Force -ErrorAction SilentlyContinue
    throw "Installed application verification timed out after 60 seconds."
}
if ($smokeProcess.ExitCode -ne 0) {
    throw "Installed application verification failed with exit code $($smokeProcess.ExitCode)."
}

if (-not $NoDesktopShortcut) {
    $desktopPath = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktopPath "Tobii Gaze Mouse.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = Get-PowerShellExecutable
    $shortcut.Arguments = '-WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File "' + $launcherPath + '" -NoPause'
    $shortcut.WorkingDirectory = $installFullPath
    $shortcut.Description = "Launch Tobii Gaze Mouse"
    $shortcut.IconLocation = "$appExecutable,0"
    $shortcut.Save()
    Write-Host "Created desktop shortcut: $shortcutPath"
}

$version = (Get-Content -LiteralPath (Join-Path $installFullPath "VERSION") -Raw).Trim()
Write-Host "Installed Tobii Gaze Mouse v$version to $installFullPath"
Write-Host "Tobii software, tracker calibration, eSpeak NG, optional edge-playback, and an optional 32-bit bridge runtime are not installed by this package."
Write-Host "See README.md in the installation folder for requirements and manual checks."

if ($Launch) {
    $launchArguments = @(
        "-WindowStyle", "Hidden",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", (Quote-Argument $launcherPath),
        "-NoPause"
    )
    Start-Process `
        -FilePath (Get-PowerShellExecutable) `
        -ArgumentList ($launchArguments -join " ") `
        -WorkingDirectory $installFullPath `
        -WindowStyle Hidden | Out-Null
}
