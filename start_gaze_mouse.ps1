[CmdletBinding()]
param(
    [string]$InstallRoot = "",
    [string]$LogRoot = "",
    [switch]$NoShortcut,
    [switch]$NoPause,
    [switch]$PauseOnSuccess
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$script:ExitCode = 0
$script:TranscriptStarted = $false
$script:LauncherLogPath = ""
$script:ShowLauncherWindow = $false
$ScriptPath = $MyInvocation.MyCommand.Path
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Log {
    param(
        [string]$Level,
        [string]$Message,
        [ConsoleColor]$Color = [ConsoleColor]::White
    )

    $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    Write-Host "[$timestamp] [$Level] $Message" -ForegroundColor $Color
}

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Log -Level "STEP" -Message $Message -Color Cyan
}

function Write-Info {
    param([string]$Message)
    Write-Log -Level "INFO" -Message $Message -Color Gray
}

function Write-Success {
    param([string]$Message)
    Write-Log -Level "OK" -Message $Message -Color Green
}

function Write-WarningLog {
    param([string]$Message)
    Write-Log -Level "WARN" -Message $Message -Color Yellow
}

function Write-ErrorLog {
    param([string]$Message)
    Write-Log -Level "ERROR" -Message $Message -Color Red
}

function Get-DefaultInstallRoot {
    return "C:\PogledAssist"
}

function Test-AppRoot {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path $Path)) {
        return $false
    }

    $appPath = Join-Path $Path "run_gaze_mouse.py"
    $pythonPath = Join-Path $Path ".venv\Scripts\python.exe"
    return (Test-Path $appPath) -and (Test-Path $pythonPath)
}

function Resolve-AppRoot {
    Write-Step "Finding installed Pogled Assist"

    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($InstallRoot)) {
        $candidates += $InstallRoot
    }
    $candidates += Get-DefaultInstallRoot
    $candidates += $ScriptRoot

    foreach ($candidate in ($candidates | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)) {
        Write-Info "Checking install folder: $candidate"
        if (Test-AppRoot -Path $candidate) {
            $resolved = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($candidate)
            Write-Success "Using install folder: $resolved"
            return $resolved
        }
    }

    throw "Installed app was not found. Run setup_windows.ps1 first, then run this launcher again."
}

function Get-NormalizedPath {
    param([string]$Path)

    try {
        return $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path)
    } catch {
        return $Path
    }
}

function Resolve-LogRoot {
    param([string]$AppRoot)

    Write-Step "Resolving log location"

    if (-not [string]::IsNullOrWhiteSpace($LogRoot)) {
        $resolvedOverride = Get-NormalizedPath -Path $LogRoot
        New-Item -Path $resolvedOverride -ItemType Directory -Force | Out-Null
        Write-Success "Using log root from -LogRoot: $resolvedOverride"
        return $resolvedOverride
    }

    $installInfoPath = Join-Path $AppRoot "install_info.json"
    if (Test-Path $installInfoPath) {
        try {
            $installInfo = Get-Content -Path $installInfoPath -Raw | ConvertFrom-Json
            $sourceRoot = [string]$installInfo.SourceRoot
            if (-not [string]::IsNullOrWhiteSpace($sourceRoot) -and (Test-Path $sourceRoot)) {
                $resolvedSourceRoot = Get-NormalizedPath -Path $sourceRoot
                Write-Success "Using install metadata log folder: $resolvedSourceRoot"
                return $resolvedSourceRoot
            }

            Write-WarningLog "Install metadata log folder is not available: $sourceRoot"
        } catch {
            Write-WarningLog "Could not read install metadata at $installInfoPath`: $($_.Exception.Message)"
        }
    } else {
        Write-WarningLog "Install metadata was not found at $installInfoPath"
    }

    Write-WarningLog "Falling back to installed app folder for logs: $AppRoot"
    return $AppRoot
}

function Start-LauncherTranscript {
    param([string]$ResolvedLogRoot)

    $script:LauncherLogPath = Join-Path $ResolvedLogRoot "start_gaze_mouse.log"
    try {
        Start-Transcript -Path $script:LauncherLogPath -Append | Out-Null
        $script:TranscriptStarted = $true
        Write-Info "Writing launcher log to $script:LauncherLogPath"
    } catch {
        Write-WarningLog "Could not start launcher transcript at $script:LauncherLogPath`: $($_.Exception.Message)"
    }
}

function Stop-LauncherTranscript {
    if (-not $script:TranscriptStarted) {
        return
    }

    try {
        Stop-Transcript | Out-Null
    } catch {
        Write-WarningLog "Could not stop launcher transcript cleanly: $($_.Exception.Message)"
    }
}

function Get-PowerShellExecutable {
    $command = Get-Command "powershell.exe" -ErrorAction SilentlyContinue
    if ($null -ne $command -and -not [string]::IsNullOrWhiteSpace($command.Source)) {
        return $command.Source
    }

    $windowsPowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    if (Test-Path $windowsPowerShell) {
        return $windowsPowerShell
    }

    return "powershell.exe"
}

function Format-ShortcutArgument {
    param([string]$Value)
    return '"' + $Value.Replace('"', '\"') + '"'
}

function Get-LauncherWindowVisible {
    param([string]$AppRoot = "")

    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($env:POGLED_ASSIST_LOG_ROOT)) {
        $candidates += Join-Path $env:POGLED_ASSIST_LOG_ROOT "data\app_settings.json"
    }
    if (-not [string]::IsNullOrWhiteSpace($AppRoot)) {
        $sourceRoot = Get-InstallSourceRoot -AppRoot $AppRoot
        if (-not [string]::IsNullOrWhiteSpace($sourceRoot)) {
            $candidates += Join-Path $sourceRoot "data\app_settings.json"
        }
        $candidates += Join-Path $AppRoot "data\app_settings.json"
    }
    if (-not [string]::IsNullOrWhiteSpace($InstallRoot)) {
        $installSourceRoot = Get-InstallSourceRoot -AppRoot $InstallRoot
        if (-not [string]::IsNullOrWhiteSpace($installSourceRoot)) {
            $candidates += Join-Path $installSourceRoot "data\app_settings.json"
        }
        $candidates += Join-Path $InstallRoot "data\app_settings.json"
    }
    $defaultInstallRoot = Get-DefaultInstallRoot
    $defaultSourceRoot = Get-InstallSourceRoot -AppRoot $defaultInstallRoot
    if (-not [string]::IsNullOrWhiteSpace($defaultSourceRoot)) {
        $candidates += Join-Path $defaultSourceRoot "data\app_settings.json"
    }
    $candidates += Join-Path $defaultInstallRoot "data\app_settings.json"
    $scriptSourceRoot = Get-InstallSourceRoot -AppRoot $ScriptRoot
    if (-not [string]::IsNullOrWhiteSpace($scriptSourceRoot)) {
        $candidates += Join-Path $scriptSourceRoot "data\app_settings.json"
    }
    $candidates += Join-Path $ScriptRoot "data\app_settings.json"

    foreach ($candidate in ($candidates | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)) {
        if (-not (Test-Path $candidate)) {
            continue
        }

        try {
            $settings = Get-Content -Path $candidate -Raw | ConvertFrom-Json
            $gazeProperty = $settings.PSObject.Properties["gaze"]
            if ($null -eq $gazeProperty) {
                continue
            }

            $launcherProperty = $gazeProperty.Value.PSObject.Properties["show_launcher_window"]
            if ($null -eq $launcherProperty) {
                continue
            }

            return [System.Convert]::ToBoolean($launcherProperty.Value)
        } catch {
            continue
        }
    }

    return $false
}

function Get-InstallSourceRoot {
    param([string]$AppRoot)

    if ([string]::IsNullOrWhiteSpace($AppRoot)) {
        return ""
    }

    $installInfoPath = Join-Path $AppRoot "install_info.json"
    if (-not (Test-Path $installInfoPath)) {
        return ""
    }

    try {
        $installInfo = Get-Content -Path $installInfoPath -Raw | ConvertFrom-Json
        $sourceProperty = $installInfo.PSObject.Properties["SourceRoot"]
        if ($null -eq $sourceProperty) {
            return ""
        }

        $sourceRoot = [string]$sourceProperty.Value
        if ([string]::IsNullOrWhiteSpace($sourceRoot) -or -not (Test-Path $sourceRoot)) {
            return ""
        }

        return $sourceRoot
    } catch {
        return ""
    }
}

function Get-ShowLauncherWindow {
    return [bool]$script:ShowLauncherWindow
}

function Sync-ConsoleWindowVisibility {
    try {
        if ($null -eq ("PogledAssistConsoleWindow" -as [type])) {
            Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class PogledAssistConsoleWindow
{
    [DllImport("kernel32.dll")]
    public static extern IntPtr GetConsoleWindow();

    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@
        }

        $hwnd = [PogledAssistConsoleWindow]::GetConsoleWindow()
        if ($hwnd -ne [IntPtr]::Zero) {
            $showWindowCommand = 0
            if (Get-ShowLauncherWindow) {
                $showWindowCommand = 5
            }

            [PogledAssistConsoleWindow]::ShowWindow($hwnd, $showWindowCommand) | Out-Null
        }
    } catch {
        Write-Verbose "Could not update the launcher window state: $($_.Exception.Message)"
    }
}

function Get-PowerShellLaunchArguments {
    param(
        [string]$LauncherPath,
        [bool]$ShowWindow,
        [switch]$NoPauseArgument
    )

    $arguments = @()
    if (-not $ShowWindow) {
        $arguments += "-WindowStyle"
        $arguments += "Hidden"
    }

    $arguments += "-NoProfile"
    $arguments += "-ExecutionPolicy"
    $arguments += "Bypass"
    $arguments += "-File"
    $arguments += (Format-ShortcutArgument -Value $LauncherPath)
    if ($NoPauseArgument) {
        $arguments += "-NoPause"
    }

    return ($arguments -join " ")
}

function Resolve-ShortcutIconLocation {
    param([string]$AppRoot)

    $pngCandidates = @()
    if (-not [string]::IsNullOrWhiteSpace($AppRoot)) {
        $pngCandidates += Join-Path $AppRoot "assets\icon.png"
        $sourceRoot = Get-InstallSourceRoot -AppRoot $AppRoot
        if (-not [string]::IsNullOrWhiteSpace($sourceRoot)) {
            $pngCandidates += Join-Path $sourceRoot "assets\icon.png"
        }
    }
    $scriptSourceRoot = Get-InstallSourceRoot -AppRoot $ScriptRoot
    if (-not [string]::IsNullOrWhiteSpace($scriptSourceRoot)) {
        $pngCandidates += Join-Path $scriptSourceRoot "assets\icon.png"
    }
    $pngCandidates += Join-Path $ScriptRoot "assets\icon.png"

    foreach ($pngPath in ($pngCandidates | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)) {
        if (-not (Test-Path $pngPath)) {
            continue
        }

        $icoPath = [IO.Path]::ChangeExtension($pngPath, ".ico")
        $resolvedIcon = Convert-PngToShortcutIcon -PngPath $pngPath -IconPath $icoPath
        if (-not [string]::IsNullOrWhiteSpace($resolvedIcon) -and (Test-Path $resolvedIcon)) {
            return $resolvedIcon
        }
    }

    return ""
}

function Convert-PngToShortcutIcon {
    param(
        [string]$PngPath,
        [string]$IconPath
    )

    if ([string]::IsNullOrWhiteSpace($PngPath) -or -not (Test-Path $PngPath)) {
        return ""
    }

    if ((Test-Path $IconPath) -and ((Get-Item $IconPath).LastWriteTimeUtc -ge (Get-Item $PngPath).LastWriteTimeUtc)) {
        return $IconPath
    }

    $bitmap = $null
    $resized = $null
    $graphics = $null
    $icon = $null
    $stream = $null
    $hIcon = [IntPtr]::Zero

    try {
        Add-Type -AssemblyName System.Drawing
        if ($null -eq ("PogledAssistIconInterop" -as [type])) {
            Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class PogledAssistIconInterop
{
    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool DestroyIcon(IntPtr hIcon);
}
"@
        }

        $iconDirectory = Split-Path -Parent $IconPath
        if (-not [string]::IsNullOrWhiteSpace($iconDirectory)) {
            New-Item -Path $iconDirectory -ItemType Directory -Force | Out-Null
        }

        $bitmap = [System.Drawing.Bitmap]::FromFile($PngPath)
        $resized = New-Object System.Drawing.Bitmap -ArgumentList 256, 256
        $graphics = [System.Drawing.Graphics]::FromImage($resized)
        $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
        $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $graphics.Clear([System.Drawing.Color]::Transparent)
        $graphics.DrawImage($bitmap, 0, 0, 256, 256)

        $hIcon = $resized.GetHicon()
        $icon = [System.Drawing.Icon]::FromHandle($hIcon)
        $stream = [System.IO.File]::Open($IconPath, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write)
        $icon.Save($stream)
        return $IconPath
    } catch {
        Write-WarningLog "Could not create shortcut icon from $PngPath`: $($_.Exception.Message)"
        return ""
    } finally {
        if ($null -ne $stream) {
            $stream.Dispose()
        }
        if ($null -ne $icon) {
            $icon.Dispose()
        }
        if ($hIcon -ne [IntPtr]::Zero -and $null -ne ("PogledAssistIconInterop" -as [type])) {
            [PogledAssistIconInterop]::DestroyIcon($hIcon) | Out-Null
        }
        if ($null -ne $graphics) {
            $graphics.Dispose()
        }
        if ($null -ne $resized) {
            $resized.Dispose()
        }
        if ($null -ne $bitmap) {
            $bitmap.Dispose()
        }
    }
}

function Test-IsAdministrator {
    try {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($identity)
        return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch {
        Write-WarningLog "Could not determine administrator status: $($_.Exception.Message)"
        return $false
    }
}

function Get-ElevatedLauncherArguments {
    $arguments = @()
    if (-not (Get-ShowLauncherWindow)) {
        $arguments += "-WindowStyle"
        $arguments += "Hidden"
    }

    $arguments += "-NoProfile"
    $arguments += "-ExecutionPolicy"
    $arguments += "Bypass"
    $arguments += "-File"
    $arguments += (Format-ShortcutArgument -Value $ScriptPath)

    if (-not [string]::IsNullOrWhiteSpace($InstallRoot)) {
        $arguments += "-InstallRoot"
        $arguments += (Format-ShortcutArgument -Value $InstallRoot)
    }
    if (-not [string]::IsNullOrWhiteSpace($LogRoot)) {
        $arguments += "-LogRoot"
        $arguments += (Format-ShortcutArgument -Value $LogRoot)
    }
    if ($NoShortcut) {
        $arguments += "-NoShortcut"
    }
    if ($NoPause) {
        $arguments += "-NoPause"
    }
    if ($PauseOnSuccess) {
        $arguments += "-PauseOnSuccess"
    }

    return ($arguments -join " ")
}

function Ensure-Administrator {
    if (Test-IsAdministrator) {
        Write-Success "Launcher is running as Administrator."
        return
    }

    Write-WarningLog "Launcher is not elevated; restarting as Administrator."
    $powerShell = Get-PowerShellExecutable
    $argumentLine = Get-ElevatedLauncherArguments
    try {
        $startParams = @{
            FilePath = $powerShell
            ArgumentList = $argumentLine
            WorkingDirectory = $ScriptRoot
            Verb = "RunAs"
        }
        if (-not (Get-ShowLauncherWindow)) {
            $startParams.WindowStyle = "Hidden"
        }

        Start-Process @startParams | Out-Null
        Write-Info "Elevated launcher process requested."
        exit 0
    } catch {
        throw "Could not restart launcher as Administrator: $($_.Exception.Message)"
    }
}

function New-DesktopShortcut {
    param([string]$AppRoot)

    if ($NoShortcut) {
        Write-Info "Desktop shortcut creation skipped because -NoShortcut was used."
        return
    }

    Write-Step "Ensuring desktop shortcut"

    $desktopPath = [Environment]::GetFolderPath("Desktop")
    if ([string]::IsNullOrWhiteSpace($desktopPath)) {
        throw "Desktop folder path could not be resolved."
    }

    $launcherPath = Join-Path $AppRoot "start_gaze_mouse.ps1"
    if (-not (Test-Path $launcherPath)) {
        Write-WarningLog "Installed start_gaze_mouse.ps1 was not found. Using current script path."
        $launcherPath = $ScriptPath
    }

    if ([string]::IsNullOrWhiteSpace($launcherPath) -or -not (Test-Path $launcherPath)) {
        throw "PowerShell launcher script was not found for shortcut creation."
    }

    $shortcutPath = Join-Path $desktopPath "Pogled Assist.lnk"
    $showLauncherWindow = Get-LauncherWindowVisible -AppRoot $AppRoot
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = Get-PowerShellExecutable
    $shortcut.Arguments = Get-PowerShellLaunchArguments `
        -LauncherPath $launcherPath `
        -ShowWindow $showLauncherWindow
    $shortcut.WorkingDirectory = $AppRoot
    $shortcut.Description = "Launch Pogled Assist"
    $iconLocation = Resolve-ShortcutIconLocation -AppRoot $AppRoot
    if (-not [string]::IsNullOrWhiteSpace($iconLocation)) {
        $shortcut.IconLocation = $iconLocation
    } else {
        $shortcut.IconLocation = "$($shortcut.TargetPath),0"
    }
    $shortcut.Save()

    Write-Success "Desktop shortcut ready: $shortcutPath"
}

function Get-EspeakNgExecutable {
    param([string]$AppRoot)

    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($env:ESPEAK_NG_EXE)) {
        $candidates += $env:ESPEAK_NG_EXE
    }

    $programFiles = [Environment]::GetFolderPath("ProgramFiles")
    if (-not [string]::IsNullOrWhiteSpace($programFiles)) {
        $candidates += Join-Path $programFiles "eSpeak NG\espeak-ng.exe"
        $candidates += Join-Path $programFiles "eSpeak NG\command_line\espeak-ng.exe"
    }

    $programFilesX86 = ${env:ProgramFiles(x86)}
    if (-not [string]::IsNullOrWhiteSpace($programFilesX86)) {
        $candidates += Join-Path $programFilesX86 "eSpeak NG\espeak-ng.exe"
        $candidates += Join-Path $programFilesX86 "eSpeak NG\command_line\espeak-ng.exe"
    }

    $toolsRoot = Join-Path $AppRoot "tools\espeak-ng"
    if (Test-Path $toolsRoot) {
        $localMatches = @(Get-ChildItem -Path $toolsRoot -Filter "espeak-ng.exe" -File -Recurse -ErrorAction SilentlyContinue)
        foreach ($match in $localMatches) {
            $candidates += $match.FullName
        }
    }

    foreach ($candidate in ($candidates | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    return $null
}

function Get-EdgePlaybackExecutable {
    param([string]$AppRoot)

    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($env:EDGE_PLAYBACK_EXE)) {
        $candidates += $env:EDGE_PLAYBACK_EXE
    }

    $venvScripts = Join-Path $AppRoot ".venv\Scripts"
    $candidates += Join-Path $venvScripts "edge-playback.exe"
    $candidates += Join-Path $venvScripts "edge-playback"

    $command = Get-Command "edge-playback" -ErrorAction SilentlyContinue
    if ($null -ne $command -and -not [string]::IsNullOrWhiteSpace($command.Source)) {
        $candidates += $command.Source
    }

    foreach ($candidate in ($candidates | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    return $null
}

function Invoke-NativeProbe {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $exitCode = 1
    try {
        $output = @(& $FilePath @Arguments 2>$null)
        $exitCode = $LASTEXITCODE
    } catch {
        $output = @()
        $exitCode = 1
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    return [PSCustomObject]@{
        ExitCode = $exitCode
        Output = $output
    }
}

function Test-Python310X86Executable {
    param([string]$PythonPath)

    if ([string]::IsNullOrWhiteSpace($PythonPath) -or -not (Test-Path $PythonPath)) {
        return $null
    }

    $probe = Invoke-NativeProbe `
        -FilePath $PythonPath `
        -Arguments @(
            "-c",
            "import ctypes, sys; print(sys.executable); raise SystemExit(0 if sys.version_info[:2] == (3, 10) and ctypes.sizeof(ctypes.c_void_p) == 4 else 1)"
        )

    if ($probe.ExitCode -ne 0) {
        return $null
    }

    $resolvedPath = ($probe.Output | Select-Object -First 1)
    if ([string]::IsNullOrWhiteSpace($resolvedPath)) {
        return $PythonPath
    }

    return $resolvedPath.Trim()
}

function Get-Python310X86 {
    param([string]$AppRoot)

    Write-Step "Finding 32-bit Python for Tobii bridge"

    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($env:POGLED_ASSIST_X86_PYTHON)) {
        $candidates += $env:POGLED_ASSIST_X86_PYTHON
    }

    $installInfoPath = Join-Path $AppRoot "install_info.json"
    if (Test-Path $installInfoPath) {
        try {
            $installInfo = Get-Content -Path $installInfoPath -Raw | ConvertFrom-Json
            $bridgePython = [string]$installInfo.BridgePythonX86
            if (-not [string]::IsNullOrWhiteSpace($bridgePython)) {
                $candidates += $bridgePython
            }
        } catch {
            Write-WarningLog "Could not read bridge Python from install metadata: $($_.Exception.Message)"
        }
    }

    $pyLauncher = Get-Command "py" -ErrorAction SilentlyContinue
    if ($null -ne $pyLauncher) {
        $probe = Invoke-NativeProbe `
            -FilePath "py" `
            -Arguments @("-3.10-32", "-c", "import sys; print(sys.executable)")
        $launcherPath = ($probe.Output | Select-Object -First 1)
        if ($probe.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($launcherPath)) {
            $candidates += $launcherPath.Trim()
        }
    }

    $localAppData = [Environment]::GetFolderPath("LocalApplicationData")
    if (-not [string]::IsNullOrWhiteSpace($localAppData)) {
        $candidates += Join-Path $localAppData "Programs\Python\Python310-32\python.exe"
        $candidates += Join-Path $localAppData "Programs\Python\Python310-32bit\python.exe"
    }

    $programFilesX86 = ${env:ProgramFiles(x86)}
    if (-not [string]::IsNullOrWhiteSpace($programFilesX86)) {
        $candidates += Join-Path $programFilesX86 "Python310-32\python.exe"
        $candidates += Join-Path $programFilesX86 "Python310\python.exe"
    }

    foreach ($candidate in ($candidates | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)) {
        Write-Info "Checking 32-bit Python candidate: $candidate"
        $resolved = Test-Python310X86Executable -PythonPath $candidate
        if ($null -ne $resolved) {
            Write-Success "Using 32-bit Python for Tobii bridge: $resolved"
            return $resolved
        }
    }

    Write-WarningLog "32-bit Python 3.10 was not found. Tobii Core Software 2.x may need rerunning setup_windows.ps1."
    return $null
}

function Start-GazeMouse {
    param(
        [string]$AppRoot,
        [string]$ResolvedLogRoot
    )

    Write-Step "Starting Pogled Assist"

    $pythonPath = Join-Path $AppRoot ".venv\Scripts\python.exe"
    $appPath = Join-Path $AppRoot "run_gaze_mouse.py"

    if (-not (Test-Path $pythonPath)) {
        throw "Python virtual environment was not found: $pythonPath"
    }
    if (-not (Test-Path $appPath)) {
        throw "Application entry point was not found: $appPath"
    }

    $venvScripts = Split-Path -Parent $pythonPath
    $env:PATH = $venvScripts + [IO.Path]::PathSeparator + $env:PATH
    Write-Info "Virtual environment Scripts path added to PATH: $venvScripts"

    $espeakExe = Get-EspeakNgExecutable -AppRoot $AppRoot
    if ($null -ne $espeakExe) {
        $env:ESPEAK_NG_EXE = $espeakExe
        Write-Info "Using eSpeak NG executable: $espeakExe"
    } else {
        Write-WarningLog "eSpeak NG executable was not found. Speech may not work until setup installs it."
    }

    $edgePlaybackExe = Get-EdgePlaybackExecutable -AppRoot $AppRoot
    if ($null -ne $edgePlaybackExe) {
        $env:EDGE_PLAYBACK_EXE = $edgePlaybackExe
        Write-Info "Using Edge playback executable: $edgePlaybackExe"
    } else {
        Write-WarningLog "edge-playback was not found. The Human like voice will not work until setup installs edge-tts."
    }

    $x86Python = Get-Python310X86 -AppRoot $AppRoot
    if ($null -ne $x86Python) {
        $env:POGLED_ASSIST_X86_PYTHON = $x86Python
    }

    Write-Info "Python: $pythonPath"
    Write-Info "Tobii bridge 32-bit Python: $env:POGLED_ASSIST_X86_PYTHON"
    Write-Info "App: $appPath"
    $env:POGLED_ASSIST_LOG_ROOT = $ResolvedLogRoot
    $runtimeLogPath = Join-Path (Join-Path $ResolvedLogRoot "logs") "latest.txt"
    Write-Info "Runtime latest log: $runtimeLogPath"
    Set-Location $AppRoot

    & $pythonPath $appPath
    $exitCode = $LASTEXITCODE
    if ($null -eq $exitCode) {
        $exitCode = 0
    }

    if ($exitCode -ne 0) {
        throw "Pogled Assist exited with code $exitCode. Check $runtimeLogPath for details."
    }

    Write-Success "Pogled Assist exited normally."
}

function Wait-BeforeExit {
    if ($NoPause -or -not (Get-ShowLauncherWindow)) {
        return
    }

    if ($script:ExitCode -ne 0 -or $PauseOnSuccess) {
        Write-Host ""
        Write-Host "Press Enter to close this launcher window..." -ForegroundColor Cyan
        Read-Host | Out-Null
    }
}

try {
    $script:ShowLauncherWindow = Get-LauncherWindowVisible
    Sync-ConsoleWindowVisibility
    Write-Step "Pogled Assist launcher"
    Write-Info "Launcher script: $ScriptPath"
    Ensure-Administrator

    $appRoot = Resolve-AppRoot
    $resolvedLogRoot = Resolve-LogRoot -AppRoot $appRoot
    Start-LauncherTranscript -ResolvedLogRoot $resolvedLogRoot
    Write-Step "Pogled Assist launcher"
    Write-Info "Launcher script: $ScriptPath"
    Write-Info "Install folder: $appRoot"
    Write-Info "Log root: $resolvedLogRoot"
    New-DesktopShortcut -AppRoot $appRoot
    Start-GazeMouse -AppRoot $appRoot -ResolvedLogRoot $resolvedLogRoot
} catch {
    $script:ExitCode = 1
    Write-Host ""
    Write-ErrorLog $_.Exception.Message
} finally {
    Stop-LauncherTranscript
    Wait-BeforeExit
    exit $script:ExitCode
}
