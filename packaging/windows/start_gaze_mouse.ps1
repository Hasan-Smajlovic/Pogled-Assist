[CmdletBinding()]
param(
    [switch]$NoPause,
    [switch]$NoElevation
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$AppRoot = Split-Path -Parent $PSCommandPath
$LauncherPath = $PSCommandPath
$AppExecutable = Join-Path $AppRoot "TobiiGazeMouse.exe"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-PowerShellExecutable {
    return Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
}

function Quote-Argument {
    param([string]$Value)
    return '"' + $Value.Replace('"', '\"') + '"'
}

function Find-FirstFile {
    param([string[]]$Candidates)

    foreach ($candidate in $Candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return $candidate
        }
    }
    return $null
}

if (-not (Test-Path -LiteralPath $AppExecutable -PathType Leaf)) {
    throw "Application executable was not found: $AppExecutable"
}

if (-not (Test-IsAdministrator) -and -not $NoElevation) {
    $arguments = @(
        "-WindowStyle", "Hidden",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", (Quote-Argument $LauncherPath),
        "-NoElevation"
    )
    if ($NoPause) {
        $arguments += "-NoPause"
    }

    Start-Process `
        -FilePath (Get-PowerShellExecutable) `
        -ArgumentList ($arguments -join " ") `
        -WorkingDirectory $AppRoot `
        -Verb RunAs `
        -WindowStyle Hidden | Out-Null
    exit 0
}

$env:TOBII_GAZE_MOUSE_LOG_ROOT = $AppRoot

if ([string]::IsNullOrWhiteSpace($env:ESPEAK_NG_EXE) -or -not (Test-Path -LiteralPath $env:ESPEAK_NG_EXE)) {
    $env:ESPEAK_NG_EXE = Find-FirstFile -Candidates @(
        (Join-Path $env:ProgramFiles "eSpeak NG\espeak-ng.exe"),
        (Join-Path $env:ProgramFiles "eSpeak NG\command_line\espeak-ng.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "eSpeak NG\espeak-ng.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "eSpeak NG\command_line\espeak-ng.exe")
    )
}

if ([string]::IsNullOrWhiteSpace($env:TOBII_GAZE_MOUSE_X86_PYTHON) -or -not (Test-Path -LiteralPath $env:TOBII_GAZE_MOUSE_X86_PYTHON)) {
    $env:TOBII_GAZE_MOUSE_X86_PYTHON = Find-FirstFile -Candidates @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python310-32\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python310-32bit\python.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Python310-32\python.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Python310\python.exe")
    )
}

if ([string]::IsNullOrWhiteSpace($env:EDGE_PLAYBACK_EXE) -or -not (Test-Path -LiteralPath $env:EDGE_PLAYBACK_EXE)) {
    $edgePlayback = Get-Command "edge-playback.exe" -ErrorAction SilentlyContinue
    if ($null -ne $edgePlayback) {
        $env:EDGE_PLAYBACK_EXE = $edgePlayback.Source
    }
}

try {
    Start-Process -FilePath $AppExecutable -WorkingDirectory $AppRoot | Out-Null
} catch {
    Write-Error "Could not launch Tobii Gaze Mouse: $($_.Exception.Message)"
    if (-not $NoPause) {
        Read-Host "Press Enter to close"
    }
    exit 1
}
