[CmdletBinding()]
param(
    [switch]$NoSetup,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepositoryUrl = "https://github.com/thePi314/TobiiEyeTrackerTool.git"
$ArchiveUrls = @(
    "https://github.com/thePi314/TobiiEyeTrackerTool/archive/refs/heads/main.zip",
    "https://github.com/thePi314/TobiiEyeTrackerTool/archive/refs/heads/master.zip"
)
$InstallRoot = "C:\TobiiExec"
$UpdateScriptPath = $MyInvocation.MyCommand.Path
$script:ExitCode = 0
$script:TranscriptStarted = $false
$script:ElevationRequested = $false
$script:UpdateLogPath = Join-Path $InstallRoot "update_windows.log"

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

function Ensure-Administrator {
    if (Test-IsAdministrator) {
        Write-Success "Updater is running as Administrator."
        return
    }

    Write-WarningLog "Updater is not elevated; restarting as Administrator so it can update $InstallRoot."
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        (Format-ShortcutArgument -Value $UpdateScriptPath)
    )
    if ($NoSetup) {
        $arguments += "-NoSetup"
    }
    if ($NoPause) {
        $arguments += "-NoPause"
    }

    try {
        Start-Process `
            -FilePath (Get-PowerShellExecutable) `
            -ArgumentList ($arguments -join " ") `
            -WorkingDirectory (Split-Path -Parent $UpdateScriptPath) `
            -Verb "RunAs" | Out-Null
        $script:ElevationRequested = $true
        Write-Info "Elevated updater process requested."
        exit 0
    } catch {
        throw "Could not restart updater as Administrator: $($_.Exception.Message)"
    }
}

function Start-UpdateTranscript {
    New-Item -Path $InstallRoot -ItemType Directory -Force | Out-Null
    try {
        Start-Transcript -Path $script:UpdateLogPath -Append | Out-Null
        $script:TranscriptStarted = $true
        Write-Info "Writing update log to $script:UpdateLogPath"
    } catch {
        Write-WarningLog "Could not start update transcript: $($_.Exception.Message)"
    }
}

function Stop-UpdateTranscript {
    if (-not $script:TranscriptStarted) {
        return
    }

    try {
        Stop-Transcript | Out-Null
    } catch {
        Write-WarningLog "Could not stop update transcript cleanly: $($_.Exception.Message)"
    }
}

function Wait-BeforeExit {
    if ($NoPause) {
        return
    }

    Write-Host ""
    Write-Host "Press Enter to close this update window..." -ForegroundColor Cyan
    Read-Host | Out-Null
}

function Invoke-NativeCommand {
    param(
        [string]$Label,
        [string]$FilePath,
        [string[]]$Arguments
    )

    Write-Info $Label
    Write-Info "Running: $FilePath $($Arguments -join ' ')"

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $exitCode = 1
    try {
        & $FilePath @Arguments 2>&1 | ForEach-Object {
            Write-Host $_
        }
        $exitCode = $LASTEXITCODE
    } catch {
        throw "$Label failed to start: $($_.Exception.Message)"
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if ($exitCode -ne 0) {
        throw "$Label failed with exit code $exitCode."
    }
}

function Download-RepositoryWithGit {
    param([string]$DestinationPath)

    $git = Get-Command "git" -ErrorAction SilentlyContinue
    if ($null -eq $git) {
        Write-Info "Git was not found. Falling back to GitHub ZIP download."
        return $false
    }

    Write-Step "Downloading repository with Git"
    try {
        Invoke-NativeCommand `
            -Label "Cloning $RepositoryUrl" `
            -FilePath $git.Source `
            -Arguments @("clone", "--depth", "1", $RepositoryUrl, $DestinationPath)
        return $true
    } catch {
        Write-WarningLog "Git clone failed: $($_.Exception.Message)"
        return $false
    }
}

function Download-RepositoryWithZip {
    param([string]$DownloadRoot)

    Write-Step "Downloading repository ZIP"
    foreach ($url in $ArchiveUrls) {
        $zipPath = Join-Path $DownloadRoot "repository.zip"
        try {
            Write-Info "Downloading: $url"
            Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing
            Expand-Archive -Path $zipPath -DestinationPath $DownloadRoot -Force
            return $true
        } catch {
            Write-WarningLog "ZIP download failed for $url`: $($_.Exception.Message)"
            Remove-Item -Path $zipPath -Force -ErrorAction SilentlyContinue
        }
    }

    return $false
}

function Find-DownloadedRepositoryRoot {
    param([string]$DownloadRoot)

    if (Test-Path (Join-Path $DownloadRoot "setup_windows.ps1")) {
        return $DownloadRoot
    }

    $matches = @(
        Get-ChildItem -Path $DownloadRoot -Directory -Force -ErrorAction SilentlyContinue |
            Where-Object { Test-Path (Join-Path $_.FullName "setup_windows.ps1") }
    )

    if ($matches.Count -lt 1) {
        throw "Downloaded repository content did not contain setup_windows.ps1."
    }

    return $matches[0].FullName
}

function Copy-RepositoryToInstallRoot {
    param([string]$RepositoryRoot)

    Write-Step "Updating installed files"
    New-Item -Path $InstallRoot -ItemType Directory -Force | Out-Null

    $arguments = @(
        $RepositoryRoot,
        $InstallRoot,
        "/MIR",
        "/R:2",
        "/W:2",
        "/NFL",
        "/NDL",
        "/NP",
        "/XD",
        ".git",
        ".github",
        ".venv",
        "data",
        "logs",
        "__pycache__",
        "/XF",
        "install_info.json",
        "setup_windows.log",
        "start_gaze_mouse.log",
        "update_windows.log",
        "run_gaze_mouse.bat",
        "run_gaze_mouse.ps1",
        "icon.ico"
    )

    Write-Info "Running: robocopy $($arguments -join ' ')"
    & robocopy @arguments | ForEach-Object {
        Write-Host $_
    }
    $exitCode = $LASTEXITCODE
    if ($exitCode -gt 7) {
        throw "robocopy failed with exit code $exitCode."
    }

    Write-Success "Repository content copied to $InstallRoot."
}

function Run-SetupAfterUpdate {
    if ($NoSetup) {
        Write-WarningLog "Skipping setup because -NoSetup was used."
        return
    }

    $setupPath = Join-Path $InstallRoot "setup_windows.ps1"
    if (-not (Test-Path $setupPath)) {
        throw "Updated setup script was not found: $setupPath"
    }

    Write-Step "Running setup after update"
    Invoke-NativeCommand `
        -Label "Running setup from $InstallRoot" `
        -FilePath (Get-PowerShellExecutable) `
        -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $setupPath, "-NoPause")
}

function Remove-TemporaryFolder {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path $Path)) {
        return
    }

    try {
        Remove-Item -Path $Path -Recurse -Force -ErrorAction SilentlyContinue
    } catch {
        Write-WarningLog "Could not remove temporary folder $Path`: $($_.Exception.Message)"
    }
}

try {
    Ensure-Administrator
    Start-UpdateTranscript

    Write-Step "Starting manual Tobii Gaze Mouse update"
    Write-Info "Repository: $RepositoryUrl"
    Write-Info "Install folder: $InstallRoot"

    $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("TobiiGazeMouseUpdate_{0}" -f [Guid]::NewGuid().ToString("N"))
    New-Item -Path $tempRoot -ItemType Directory -Force | Out-Null
    $gitRoot = Join-Path $tempRoot "repo"

    $downloaded = Download-RepositoryWithGit -DestinationPath $gitRoot
    if (-not $downloaded) {
        $downloaded = Download-RepositoryWithZip -DownloadRoot $tempRoot
    }
    if (-not $downloaded) {
        throw "Could not download repository from GitHub."
    }

    $repositoryRoot = Find-DownloadedRepositoryRoot -DownloadRoot $tempRoot
    Write-Success "Downloaded repository content: $repositoryRoot"
    Copy-RepositoryToInstallRoot -RepositoryRoot $repositoryRoot
    Run-SetupAfterUpdate

    Write-Success "Manual update completed successfully."
} catch {
    $script:ExitCode = 1
    Write-Host ""
    Write-ErrorLog "Update failed: $($_.Exception.Message)"
    Write-Info "Review update log if available: $script:UpdateLogPath"
} finally {
    if ($script:ElevationRequested) {
        exit 0
    }

    if ($null -ne (Get-Variable -Name tempRoot -Scope Local -ErrorAction SilentlyContinue)) {
        Remove-TemporaryFolder -Path $tempRoot
    }

    Stop-UpdateTranscript
    Wait-BeforeExit
    exit $script:ExitCode
}
