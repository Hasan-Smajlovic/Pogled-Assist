[CmdletBinding()]
param(
    [switch]$NoPause,
    [switch]$NoElevation
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$AppRoot = Split-Path -Parent $PSCommandPath
$LauncherPath = $PSCommandPath
$AppExecutable = Join-Path $AppRoot "PogledAssist.exe"

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

function Find-FirstRecursiveFile {
    param(
        [string]$Root,
        [string]$Name
    )

    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        return $null
    }

    return Get-ChildItem `
        -LiteralPath $Root `
        -Filter $Name `
        -File `
        -Recurse `
        -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
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

$env:POGLED_ASSIST_LOG_ROOT = $AppRoot
$env:POGLED_ASSIST_APP_ROOT = $AppRoot

if ([string]::IsNullOrWhiteSpace($env:ESPEAK_NG_EXE) -or -not (Test-Path -LiteralPath $env:ESPEAK_NG_EXE)) {
    $env:ESPEAK_NG_EXE = Find-FirstFile -Candidates @(
        (Join-Path $AppRoot "speech\espeak-ng\espeak-ng.exe"),
        (Find-FirstRecursiveFile -Root (Join-Path $AppRoot "tools\espeak-ng") -Name "espeak-ng.exe"),
        (Join-Path $env:ProgramFiles "eSpeak NG\espeak-ng.exe"),
        (Join-Path $env:ProgramFiles "eSpeak NG\command_line\espeak-ng.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "eSpeak NG\espeak-ng.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "eSpeak NG\command_line\espeak-ng.exe")
    )
}

if ([string]::IsNullOrWhiteSpace($env:POGLED_ASSIST_X86_PYTHON) -or -not (Test-Path -LiteralPath $env:POGLED_ASSIST_X86_PYTHON)) {
    $env:POGLED_ASSIST_X86_PYTHON = Find-FirstFile -Candidates @(
        $env:TOBII_GAZE_MOUSE_X86_PYTHON,
        (Join-Path $AppRoot "runtime\python-x86\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python310-32\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python310-32bit\python.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Python310-32\python.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Python310\python.exe")
    )
}

if ([string]::IsNullOrWhiteSpace($env:EDGE_PLAYBACK_EXE) -or -not (Test-Path -LiteralPath $env:EDGE_PLAYBACK_EXE)) {
    $edgePlayback = Get-Command "edge-playback.exe" -ErrorAction SilentlyContinue
    $edgePlaybackFromPath = if ($null -ne $edgePlayback) { $edgePlayback.Source } else { $null }
    $env:EDGE_PLAYBACK_EXE = Find-FirstFile -Candidates @(
        (Join-Path $AppRoot "speech\edge\edge-playback.exe"),
        (Join-Path $AppRoot ".venv\Scripts\edge-playback.exe"),
        $edgePlaybackFromPath
    )
}

try {
    Start-Process -FilePath $AppExecutable -WorkingDirectory $AppRoot | Out-Null
} catch {
    Write-Error "Could not launch Pogled Assist: $($_.Exception.Message)"
    if (-not $NoPause) {
        Read-Host "Press Enter to close"
    }
    exit 1
}
