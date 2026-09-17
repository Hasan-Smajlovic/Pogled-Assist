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

function Test-IsSourceAppProcess {
    param(
        [object]$Process,
        [string]$InstallRoot
    )

    $commandLine = [string]$Process.CommandLine
    if ([string]::IsNullOrWhiteSpace($commandLine)) {
        return $false
    }

    $targetScript = Join-Path $InstallRoot "run_gaze_mouse.py"
    if ($commandLine.IndexOf($targetScript, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
        return $true
    }

    $executablePath = [string]$Process.ExecutablePath
    $targetPythonPaths = @(
        (Join-Path $InstallRoot ".venv\Scripts\python.exe"),
        (Join-Path $InstallRoot ".venv\Scripts\pythonw.exe")
    )
    $usesTargetPython = $targetPythonPaths | Where-Object {
        $executablePath.Equals($_, [StringComparison]::OrdinalIgnoreCase)
    }
    if ($null -eq $usesTargetPython) {
        return $false
    }

    return [Regex]::IsMatch(
        $commandLine,
        '(^|[\\/"\s])run_gaze_mouse\.py(?=["\s]|$)',
        [Text.RegularExpressions.RegexOptions]::IgnoreCase
    )
}

function Assert-AppNotRunning {
    param([string]$InstallRoot)

    $processIds = @(
        Get-Process -Name "TobiiGazeMouse" -ErrorAction SilentlyContinue |
            ForEach-Object { $_.Id }
    )
    try {
        $sourceProcesses = Get-CimInstance `
            -ClassName Win32_Process `
            -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" `
            -ErrorAction Stop
        $processIds += @(
            $sourceProcesses |
                Where-Object { Test-IsSourceAppProcess -Process $_ -InstallRoot $InstallRoot } |
                ForEach-Object { $_.ProcessId }
        )
    } catch {
        throw "Could not check whether the source application is running: $($_.Exception.Message)"
    }

    $processIds = @($processIds | Sort-Object -Unique)
    if ($processIds.Count -gt 0) {
        $processIdList = $processIds -join ", "
        throw "Close Tobii Gaze Mouse before installing or rolling back. Running process IDs: $processIdList"
    }
}

function Invoke-RobocopyMirror {
    param(
        [string]$Source,
        [string]$Destination,
        [switch]$PreserveExternalComponents
    )

    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $excludedDirectories = @("data", "logs")
    $excludedFiles = @("install_info.json", "*.log")
    if ($PreserveExternalComponents) {
        $excludedDirectories += @(".venv", "tools")
        $excludedFiles += @(
            "edge-playback",
            "edge-playback.exe",
            "edge-playback-script.py",
            "espeak-ng.exe",
            "tobii_stream_engine.dll",
            "StreamEngineClient.dll"
        )
    }
    $arguments = @(
        $Source,
        $Destination,
        "/MIR",
        "/R:2",
        "/W:2",
        "/NFL",
        "/NDL",
        "/NP",
        "/XD"
    ) + $excludedDirectories + @("/XF") + $excludedFiles
    & robocopy @arguments | ForEach-Object { Write-Host $_ }
    $exitCode = $LASTEXITCODE
    if ($exitCode -gt 7) {
        throw "Could not mirror $Source to $Destination. Robocopy exit code: $exitCode"
    }

    # Robocopy uses successful non-zero codes when files were copied or changed.
    $global:LASTEXITCODE = 0
}

function Assert-PreservedPaths {
    param(
        [string]$Root,
        [string[]]$RelativePaths
    )

    $missing = @(
        $RelativePaths | Where-Object {
            -not (Test-Path -LiteralPath (Join-Path $Root $_))
        }
    )
    if ($missing.Count -gt 0) {
        throw "Installation removed external components that must be preserved: $($missing -join ', ')"
    }
}

function Invoke-PackageSmokeTest {
    param(
        [string]$Root,
        [string]$Label
    )

    $appExecutable = Join-Path $Root "TobiiGazeMouse.exe"
    $tempRoot = [IO.Path]::GetTempPath()
    $reportName = "TobiiGazeMouseSmoke_{0}.txt" -f [Guid]::NewGuid().ToString("N")
    $reportPath = Join-Path $tempRoot $reportName
    $previousReportPath = $env:TOBII_GAZE_MOUSE_PACKAGE_SMOKE_REPORT
    try {
        $env:TOBII_GAZE_MOUSE_PACKAGE_SMOKE_REPORT = $reportPath
        $smokeProcess = Start-Process `
            -FilePath $appExecutable `
            -ArgumentList "--package-smoke-test" `
            -WorkingDirectory $Root `
            -WindowStyle Hidden `
            -PassThru
        if (-not $smokeProcess.WaitForExit(60000)) {
            Stop-Process -Id $smokeProcess.Id -Force -ErrorAction SilentlyContinue
            throw "$Label timed out after 60 seconds."
        }
        if ($smokeProcess.ExitCode -ne 0) {
            $report = if (Test-Path -LiteralPath $reportPath -PathType Leaf) {
                (Get-Content -LiteralPath $reportPath -Raw).Trim()
            } else {
                "No smoke-test report was written."
            }
            throw "$Label failed with exit code $($smokeProcess.ExitCode). $report"
        }
    } finally {
        $env:TOBII_GAZE_MOUSE_PACKAGE_SMOKE_REPORT = $previousReportPath
        Remove-Item -LiteralPath $reportPath -Force -ErrorAction SilentlyContinue
    }
}

function Remove-OperationDirectory {
    param([string]$Path)

    if (-not [string]::IsNullOrWhiteSpace($Path) -and (Test-Path -LiteralPath $Path)) {
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force
        } catch {
            Write-Warning "Could not remove temporary installer directory $Path`: $($_.Exception.Message)"
        }
    }
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
    "README.md",
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

Assert-AppNotRunning -InstallRoot $installFullPath
if ($sourceFullPath -ne $installFullPath) {
    $installParent = Split-Path -Parent $installFullPath
    $installName = Split-Path -Leaf $installFullPath
    $operationId = [Guid]::NewGuid().ToString("N")
    $stagingRoot = Join-Path $installParent ".$installName.install-$operationId"
    $backupRoot = Join-Path $installParent ".$installName.backup-$operationId"
    $installChanged = $false
    $keepBackup = $false
    $hadExistingInstallation = Test-Path -LiteralPath $installFullPath
    $externalRelativePaths = @(
        ".venv",
        "tools",
        "edge-playback",
        "edge-playback.exe",
        "edge-playback-script.py",
        "espeak-ng.exe",
        "tobii_stream_engine.dll",
        "StreamEngineClient.dll"
    )
    $preservedExternalPaths = @(
        $externalRelativePaths | Where-Object {
            Test-Path -LiteralPath (Join-Path $installFullPath $_)
        }
    )

    New-Item -ItemType Directory -Path $installParent -Force | Out-Null
    try {
        Invoke-RobocopyMirror -Source $sourceFullPath -Destination $stagingRoot
        Invoke-PackageSmokeTest -Root $stagingRoot -Label "Staged application verification"

        New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
        if ($hadExistingInstallation) {
            Invoke-RobocopyMirror -Source $installFullPath -Destination $backupRoot
        }

        Assert-AppNotRunning -InstallRoot $installFullPath
        $installChanged = $true
        Invoke-RobocopyMirror `
            -Source $stagingRoot `
            -Destination $installFullPath `
            -PreserveExternalComponents
        Assert-PreservedPaths `
            -Root $installFullPath `
            -RelativePaths $preservedExternalPaths
        Invoke-PackageSmokeTest -Root $installFullPath -Label "Installed application verification"
    } catch {
        $installError = $_
        if ($installChanged) {
            try {
                Invoke-RobocopyMirror -Source $backupRoot -Destination $installFullPath
            } catch {
                $keepBackup = $true
                throw "Installation failed: $($installError.Exception.Message) Restoring the previous files also failed: $($_.Exception.Message) Backup files remain at $backupRoot."
            }
        }
        throw $installError
    } finally {
        Remove-OperationDirectory -Path $stagingRoot
        if (-not $keepBackup) {
            Remove-OperationDirectory -Path $backupRoot
        }
    }
} else {
    Invoke-PackageSmokeTest -Root $installFullPath -Label "Installed application verification"
}

$appExecutable = Join-Path $installFullPath "TobiiGazeMouse.exe"
$launcherPath = Join-Path $installFullPath "start_gaze_mouse.ps1"

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
