[CmdletBinding()]
param(
    [switch]$InstallPython,
    [switch]$SkipPythonInstall,
    [switch]$SkipX86BridgePythonInstall,
    [switch]$Launch,
    [switch]$NoPause,
    [switch]$UseSourceFolder,
    [switch]$NoDesktopShortcut,
    [string]$VenvPath = ".venv",
    [string]$PythonInstallerVersion = "3.10.11",
    [string]$EspeakNgVersion = "1.52.0",
    [string]$InstallRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$script:ExitCode = 0
$script:TranscriptStarted = $false
$script:CacheCleaned = $false
$script:ElevationRequested = $false

$SetupScriptPath = $MyInvocation.MyCommand.Path
$SourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = $SourceRoot

$LogPath = Join-Path $RepoRoot "setup_windows.log"
$SourceLogPath = Join-Path $SourceRoot "setup_windows.log"
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PIP_NO_COMPILE = "1"
$PythonInstallerFileName = "python-$PythonInstallerVersion-amd64.exe"
$PythonInstallerUrl = "https://www.python.org/ftp/python/$PythonInstallerVersion/$PythonInstallerFileName"
$PythonX86InstallerFileName = "python-$PythonInstallerVersion.exe"
$PythonX86InstallerUrl = "https://www.python.org/ftp/python/$PythonInstallerVersion/$PythonX86InstallerFileName"
$EspeakNgPackageId = "eSpeak-NG.eSpeak-NG"
$EspeakNgInstallerFileName = "espeak-ng.msi"
$EspeakNgInstallerUrl = "https://github.com/espeak-ng/espeak-ng/releases/download/$EspeakNgVersion/$EspeakNgInstallerFileName"
$InstallInfoFileName = "install_info.json"
$FixedInstallRoot = "C:\PogledAssist"
$EdgeTtsVoice = "bs-BA-GoranNeural"
$EdgeTtsRate = "-10%"
$EdgeTtsPitch = "-2Hz"
$EdgeTtsTestText = "Dobar dan."

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

function Format-CommandLine {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    $formattedArgs = foreach ($argument in $Arguments) {
        if ($argument -match "\s") {
            '"' + $argument + '"'
        } else {
            $argument
        }
    }

    return "$FilePath $($formattedArgs -join ' ')"
}

function Format-ProcessArguments {
    param([string[]]$Arguments)

    $formattedArgs = foreach ($argument in $Arguments) {
        if ($null -eq $argument) {
            '""'
        } elseif ($argument -match '[\s"]') {
            '"' + $argument.Replace('"', '\"') + '"'
        } else {
            $argument
        }
    }

    return ($formattedArgs -join " ")
}

function Invoke-NativeCommand {
    param(
        [string]$Label,
        [string]$FilePath,
        [string[]]$Arguments
    )

    Write-Info $Label
    Write-Info "Running: $(Format-CommandLine -FilePath $FilePath -Arguments $Arguments)"

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

function Invoke-NativeCommandWithTimeout {
    param(
        [string]$Label,
        [string]$FilePath,
        [string[]]$Arguments,
        [int]$TimeoutSeconds = 30
    )

    Write-Info $Label
    Write-Info "Running: $(Format-CommandLine -FilePath $FilePath -Arguments $Arguments)"

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $FilePath
    $startInfo.Arguments = Format-ProcessArguments -Arguments $Arguments
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo

    try {
        if (-not $process.Start()) {
            throw "$Label failed to start."
        }

        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            try {
                $process.Kill()
            } catch {
                Write-Verbose "Could not stop timed-out process for $Label`: $($_.Exception.Message)"
            }
            throw "$Label timed out after $TimeoutSeconds seconds."
        }

        $stdout = $process.StandardOutput.ReadToEnd()
        $stderr = $process.StandardError.ReadToEnd()

        if (-not [string]::IsNullOrWhiteSpace($stdout)) {
            $stdout -split "(`r`n|`n|`r)" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object {
                Write-Host $_
            }
        }
        if (-not [string]::IsNullOrWhiteSpace($stderr)) {
            $stderr -split "(`r`n|`n|`r)" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object {
                Write-Host $_
            }
        }

        if ($process.ExitCode -ne 0) {
            throw "$Label failed with exit code $($process.ExitCode)."
        }
    } finally {
        $process.Dispose()
    }
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

function Get-SetupPowerShellExecutable {
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

function Format-SetupArgument {
    param([string]$Value)
    return '"' + $Value.Replace('"', '\"') + '"'
}

function Get-ElevatedSetupArguments {
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        (Format-SetupArgument -Value $SetupScriptPath)
    )

    if ($InstallPython) {
        $arguments += "-InstallPython"
    }
    if ($SkipPythonInstall) {
        $arguments += "-SkipPythonInstall"
    }
    if ($SkipX86BridgePythonInstall) {
        $arguments += "-SkipX86BridgePythonInstall"
    }
    if ($Launch) {
        $arguments += "-Launch"
    }
    if ($NoPause) {
        $arguments += "-NoPause"
    }
    if ($UseSourceFolder) {
        $arguments += "-UseSourceFolder"
    }
    if ($NoDesktopShortcut) {
        $arguments += "-NoDesktopShortcut"
    }
    if ($VenvPath -ne ".venv") {
        $arguments += "-VenvPath"
        $arguments += (Format-SetupArgument -Value $VenvPath)
    }
    if ($PythonInstallerVersion -ne "3.10.11") {
        $arguments += "-PythonInstallerVersion"
        $arguments += (Format-SetupArgument -Value $PythonInstallerVersion)
    }
    if ($EspeakNgVersion -ne "1.52.0") {
        $arguments += "-EspeakNgVersion"
        $arguments += (Format-SetupArgument -Value $EspeakNgVersion)
    }
    if (-not [string]::IsNullOrWhiteSpace($InstallRoot)) {
        $arguments += "-InstallRoot"
        $arguments += (Format-SetupArgument -Value $InstallRoot)
    }

    return ($arguments -join " ")
}

function Ensure-SetupAdministrator {
    if (Test-IsAdministrator) {
        Write-Success "Setup is running as Administrator."
        return
    }

    Write-WarningLog "Setup is not elevated. Restarting as Administrator so it can install to $FixedInstallRoot."
    try {
        Start-Process `
            -FilePath (Get-SetupPowerShellExecutable) `
            -ArgumentList (Get-ElevatedSetupArguments) `
            -WorkingDirectory $SourceRoot `
            -Verb "RunAs" | Out-Null
        $script:ElevationRequested = $true
        Write-Info "Elevated setup process requested."
        exit 0
    } catch {
        throw "Could not restart setup as Administrator: $($_.Exception.Message)"
    }
}

function Get-DefaultLocalInstallRoot {
    return $FixedInstallRoot
}

function Test-IsNetworkPath {
    param([string]$Path)

    $cleanPath = Remove-FileSystemProviderPrefix -Path $Path
    if ([string]::IsNullOrWhiteSpace($cleanPath)) {
        return $false
    }

    return $cleanPath.StartsWith("\\")
}

function Remove-FileSystemProviderPrefix {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $Path
    }

    $prefix = "Microsoft.PowerShell.Core\FileSystem::"
    if ($Path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        return $Path.Substring($prefix.Length)
    }

    return $Path
}

function Get-NormalizedFullPath {
    param([string]$Path)

    $cleanPath = Remove-FileSystemProviderPrefix -Path $Path
    try {
        $resolvedPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($cleanPath)
        return (Remove-FileSystemProviderPrefix -Path $resolvedPath).TrimEnd("\")
    } catch {
        return ([IO.Path]::GetFullPath($cleanPath)).TrimEnd("\")
    }
}

function Copy-ProjectToLocalInstallRoot {
    param(
        [string]$SourcePath,
        [string]$TargetPath
    )

    Write-Step "Copying project to local install folder"
    Write-Info "Source: $SourcePath"
    Write-Info "Target: $TargetPath"

    New-Item -Path $TargetPath -ItemType Directory -Force | Out-Null

    $itemsToCopy = @(
        "requirements.txt",
        "run_gaze_mouse.py",
        "README.md",
        "setup_windows.ps1",
        "start_gaze_mouse.ps1",
        "update_windows.ps1",
        "assets",
        "tools",
        "pogled_assist"
    )

    foreach ($relativePath in $itemsToCopy) {
        $sourceItem = Join-Path $SourcePath $relativePath
        if (-not (Test-Path $sourceItem)) {
            Write-Info "Skipping missing optional item: $relativePath"
            continue
        }

        $targetItem = Join-Path $TargetPath $relativePath
        $sourceObject = Get-Item -Path $sourceItem -Force

        if ($sourceObject.PSIsContainer) {
            if (Test-Path $targetItem) {
                Remove-Item -Path $targetItem -Recurse -Force -ErrorAction SilentlyContinue
            }
            Copy-Item -Path $sourceItem -Destination $TargetPath -Recurse -Force
        } else {
            Copy-Item -Path $sourceItem -Destination $targetItem -Force
        }

        Write-Info "Copied $relativePath"
    }

    $legacyPackagePath = Join-Path $TargetPath "gaze_mouse"
    $newPackageMarker = Join-Path $TargetPath "pogled_assist\__init__.py"
    if ((Test-Path -LiteralPath (Join-Path $legacyPackagePath "__init__.py") -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $legacyPackagePath "main.py") -PathType Leaf) -and
        (Test-Path -LiteralPath $newPackageMarker -PathType Leaf)) {
        $targetFullPath = [IO.Path]::GetFullPath($TargetPath).TrimEnd("\")
        $legacyFullPath = [IO.Path]::GetFullPath($legacyPackagePath)
        if (-not $legacyFullPath.StartsWith($targetFullPath + "\", [StringComparison]::OrdinalIgnoreCase)) {
            throw "Legacy package path must stay inside the install folder: $legacyFullPath"
        }

        $legacyPackage = Get-Item -LiteralPath $legacyPackagePath -Force
        $hasUserData = (Test-Path -LiteralPath (Join-Path $legacyPackagePath "data")) -or
            (Test-Path -LiteralPath (Join-Path $legacyPackagePath "logs"))
        if ($hasUserData -or
            ($legacyPackage.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
            @(Get-ChildItem -LiteralPath $legacyPackagePath -Recurse -Force -Attributes ReparsePoint).Count -gt 0) {
            Write-WarningLog "Leaving legacy gaze_mouse folder because it contains user data or links: $legacyPackagePath"
        } else {
            try {
                Remove-Item -LiteralPath $legacyPackagePath -Recurse -Force -ErrorAction Stop
                Write-Info "Removed the old gaze_mouse package from the source installation."
            } catch {
                Write-WarningLog "Could not remove the old gaze_mouse package: $($_.Exception.Message)"
            }
        }
    }

    Write-Success "Project files copied to local install folder."
}

function Initialize-WorkingRoot {
    Write-Step "Preparing setup working folder"

    $sourceFullPath = Get-NormalizedFullPath -Path $SourceRoot
    $targetFullPath = Get-NormalizedFullPath -Path (Get-DefaultLocalInstallRoot)

    if (Test-IsNetworkPath -Path $sourceFullPath) {
        Write-WarningLog "Setup is running from a network path. Python venv creation can fail there with access denied."
    }

    if (-not [string]::IsNullOrWhiteSpace($InstallRoot)) {
        Write-WarningLog "Ignoring -InstallRoot '$InstallRoot'. This setup always installs to $FixedInstallRoot."
    }

    if ($UseSourceFolder) {
        Write-WarningLog "Ignoring -UseSourceFolder. This setup always installs to $FixedInstallRoot."
    }

    if ($sourceFullPath -ieq $targetFullPath) {
        Write-Info "Source and fixed install folder are the same; using $targetFullPath."
        $script:RepoRoot = $targetFullPath
    } else {
        Copy-ProjectToLocalInstallRoot -SourcePath $sourceFullPath -TargetPath $targetFullPath
        $script:RepoRoot = $targetFullPath
    }

    Set-Location $script:RepoRoot
    Write-Success "Setup working folder: $script:RepoRoot"
}

function Write-InstallInfo {
    Write-Step "Writing install metadata"

    $installInfoPath = Join-Path $RepoRoot $InstallInfoFileName
    $sourceFullPath = Get-NormalizedFullPath -Path $SourceRoot
    $repoFullPath = Get-NormalizedFullPath -Path $RepoRoot
    $installInfo = [ordered]@{
        SourceRoot = $repoFullPath
        OriginalSourceRoot = $sourceFullPath
        InstallRoot = $repoFullPath
        BridgePythonX86 = ""
        CreatedAt = (Get-Date).ToString("o")
    }

    $installInfoJson = $installInfo | ConvertTo-Json
    Set-Content -Path $installInfoPath -Value $installInfoJson -Encoding ASCII
    Write-Success "Install metadata written: $installInfoPath"
    Write-Info "Runtime logs will be written to install root when launched through start_gaze_mouse.ps1: $repoFullPath"
}

function Update-InstallInfoBridgePython {
    param([string]$X86Python)

    $installInfoPath = Join-Path $RepoRoot $InstallInfoFileName
    if (-not (Test-Path $installInfoPath)) {
        Write-WarningLog "Install metadata was not found for bridge Python update: $installInfoPath"
        return
    }

    try {
        $installInfo = Get-Content -Path $installInfoPath -Raw | ConvertFrom-Json
        $installInfo | Add-Member -NotePropertyName "BridgePythonX86" -NotePropertyValue $X86Python -Force
        $installInfo | ConvertTo-Json | Set-Content -Path $installInfoPath -Encoding ASCII
        Write-Info "Recorded 32-bit Tobii bridge Python in install metadata: $X86Python"
    } catch {
        Write-WarningLog "Could not update install metadata with bridge Python path: $($_.Exception.Message)"
    }
}

function Sync-SetupLogToSource {
    $logFullPath = Get-NormalizedFullPath -Path $LogPath
    $sourceLogFullPath = Get-NormalizedFullPath -Path $SourceLogPath

    if ($logFullPath -ieq $sourceLogFullPath) {
        return
    }

    if (-not (Test-Path $LogPath)) {
        return
    }

    try {
        Copy-Item -Path $LogPath -Destination $SourceLogPath -Force
        Write-Info "Copied setup log back to source path: $SourceLogPath"
    } catch {
        Write-WarningLog "Could not copy setup log back to source path: $($_.Exception.Message)"
    }
}

function Sync-SetupLogToInstallRoot {
    $logFullPath = Get-NormalizedFullPath -Path $LogPath
    $installLogPath = Join-Path $RepoRoot "setup_windows.log"
    $installLogFullPath = Get-NormalizedFullPath -Path $installLogPath

    if ($logFullPath -ieq $installLogFullPath) {
        return
    }

    if (-not (Test-Path $LogPath)) {
        return
    }

    try {
        Copy-Item -Path $LogPath -Destination $installLogPath -Force
        Write-Info "Copied setup log to install path: $installLogPath"
    } catch {
        Write-WarningLog "Could not copy setup log to install path: $($_.Exception.Message)"
    }
}

function Start-SetupTranscript {
    try {
        Start-Transcript -Path $LogPath -Append | Out-Null
        $script:TranscriptStarted = $true
        Write-Info "Writing detailed setup log to $LogPath"
    } catch {
        Write-WarningLog "Could not start transcript log: $($_.Exception.Message)"
    }
}

function Stop-SetupTranscript {
    if (-not $script:TranscriptStarted) {
        return
    }

    try {
        Stop-Transcript | Out-Null
    } catch {
        Write-WarningLog "Could not stop transcript log cleanly: $($_.Exception.Message)"
    }
}

function Wait-BeforeExit {
    if ($NoPause) {
        return
    }

    Write-Host ""
    Write-Host "Press Enter to close this setup window..." -ForegroundColor Cyan
    Read-Host | Out-Null
}

function Remove-BytecodeCaches {
    Write-Step "Cleaning Python bytecode caches"

    $rootsToClean = @($RepoRoot, $SourceRoot) | Where-Object {
        -not [string]::IsNullOrWhiteSpace($_) -and (Test-Path $_)
    } | ForEach-Object {
        Get-NormalizedFullPath -Path $_
    } | Select-Object -Unique

    $cacheDirCount = 0
    $bytecodeFileCount = 0

    foreach ($rootToClean in $rootsToClean) {
        Write-Info "Cleaning Python bytecode under $rootToClean"

        $cacheDirs = @(
            Get-ChildItem -Path $rootToClean -Directory -Filter "__pycache__" -Recurse -Force -ErrorAction SilentlyContinue
        )
        foreach ($dir in $cacheDirs) {
            Remove-Item -Path $dir.FullName -Recurse -Force -ErrorAction SilentlyContinue
        }

        $bytecodeFiles = @(
            Get-ChildItem -Path $rootToClean -File -Recurse -Force -ErrorAction SilentlyContinue |
                Where-Object { $_.Extension -in @(".pyc", ".pyo") }
        )
        foreach ($file in $bytecodeFiles) {
            Remove-Item -Path $file.FullName -Force -ErrorAction SilentlyContinue
        }

        $cacheDirCount += $cacheDirs.Count
        $bytecodeFileCount += $bytecodeFiles.Count
    }

    Write-Success "Removed $cacheDirCount cache directories and $bytecodeFileCount bytecode files."
    $script:CacheCleaned = $true
}

function Assert-Windows {
    Write-Step "Checking operating system"
    if ($env:OS -ne "Windows_NT") {
        throw "This setup script is intended for Windows. Run it on the Tobii machine."
    }

    Write-Success "Windows detected."
}

function Assert-RepositoryFiles {
    Write-Step "Checking required project files"

    $requiredFiles = @(
        "requirements.txt",
        "run_gaze_mouse.py",
        "start_gaze_mouse.ps1",
        "update_windows.ps1",
        "assets\icon.png",
        "pogled_assist\__init__.py",
        "pogled_assist\app_icon.py",
        "pogled_assist\logging_setup.py",
        "pogled_assist\release_update.py",
        "pogled_assist\settings_store.py",
        "pogled_assist\main.py",
        "pogled_assist\toolbar.py",
        "pogled_assist\assets\checkbox_x.svg",
        "pogled_assist\assets\bosnian-model.json.gz",
        "pogled_assist\assets\bosnian-model.meta.json",
        "pogled_assist\assets\bosnian-islamic-model.json.gz",
        "pogled_assist\assets\bosnian-islamic-model.meta.json",
        "pogled_assist\tracking\__init__.py",
        "pogled_assist\tracking\gaze_provider.py",
        "pogled_assist\tracking\mouse_gaze_provider.py",
        "pogled_assist\tracking\tobii_calibration.py",
        "pogled_assist\tracking\tobii_stream_engine.py",
        "pogled_assist\tracking\tobii_stream_engine_bridge.py",
        "pogled_assist\tracking\tobii_stream_engine_bridge_backend.py",
        "pogled_assist\interaction\__init__.py",
        "pogled_assist\interaction\gaze_selection.py",
        "pogled_assist\interaction\mouse_controller.py",
        "pogled_assist\ui\__init__.py",
        "pogled_assist\ui\controller_window.py",
        "pogled_assist\ui\gaze_bubble.py",
        "pogled_assist\ui\gaze_feedback.py",
        "pogled_assist\ui\interaction_overlay.py",
        "pogled_assist\ui\keyboard_window.py",
        "pogled_assist\ui\quick_action_menu.py",
        "pogled_assist\ui\quick_action_zoom.py",
        "pogled_assist\ui\settings_window.py",
        "pogled_assist\ui\speech_window.py",
        "pogled_assist\speech\__init__.py",
        "pogled_assist\speech\alarm_sound.py",
        "pogled_assist\speech\speech_library.py",
        "pogled_assist\speech\speech_service.py",
        "pogled_assist\suggestions\__init__.py",
        "pogled_assist\suggestions\composition.py",
        "pogled_assist\suggestions\learning.py",
        "pogled_assist\suggestions\model.py",
        "pogled_assist\suggestions\service.py",
        "pogled_assist\suggestions\text.py",
        "pogled_assist\windows\__init__.py",
        "pogled_assist\windows\appbar.py",
        "pogled_assist\windows\dpi.py",
        "pogled_assist\windows\windows_input.py",
        "pogled_assist\windows\windows_keyboard.py",
        "pogled_assist\windows\windows_startup.py",
        "pogled_assist\windows\windows_z_order.py"
    )

    foreach ($relativePath in $requiredFiles) {
        $fullPath = Join-Path $RepoRoot $relativePath
        if (-not (Test-Path $fullPath)) {
            throw "Required file is missing: $relativePath"
        }
        Write-Info "Found $relativePath"
    }

    Write-Success "All required project files are present."
}

function Test-Python310Executable {
    param([string]$PythonPath)

    if ([string]::IsNullOrWhiteSpace($PythonPath) -or -not (Test-Path $PythonPath)) {
        return $null
    }

    $versionProbe = Invoke-NativeProbe `
        -FilePath $PythonPath `
        -Arguments @("-c", "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 10) else 1)")

    if ($versionProbe.ExitCode -ne 0) {
        return $null
    }

    $pathProbe = Invoke-NativeProbe `
        -FilePath $PythonPath `
        -Arguments @("-c", "import sys; print(sys.executable)")

    $resolvedPath = ($pathProbe.Output | Select-Object -First 1)
    if ([string]::IsNullOrWhiteSpace($resolvedPath)) {
        return $PythonPath
    }

    return $resolvedPath.Trim()
}

function Get-Python310 {
    Write-Step "Finding Python 3.10"

    $pyLauncher = Get-Command "py" -ErrorAction SilentlyContinue
    if ($null -ne $pyLauncher) {
        Write-Info "Checking Python launcher: py -3.10"
        $probe = Invoke-NativeProbe `
            -FilePath "py" `
            -Arguments @("-3.10", "-c", "import sys; print(sys.executable)")
        $pythonPath = ($probe.Output | Select-Object -First 1)
        if ($probe.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($pythonPath)) {
            $resolved = Test-Python310Executable -PythonPath $pythonPath.Trim()
            if ($null -ne $resolved) {
                Write-Success "Found Python 3.10 through py launcher: $resolved"
                return $resolved
            }
        } else {
            Write-Info "py launcher did not find Python 3.10."
        }
    }

    foreach ($commandName in @("python3.10", "python")) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($null -eq $command) {
            Write-Info "$commandName was not found in PATH."
            continue
        }

        Write-Info "Checking $($command.Source)"
        $resolved = Test-Python310Executable -PythonPath $command.Source
        if ($null -ne $resolved) {
            Write-Success "Found Python 3.10: $resolved"
            return $resolved
        }
    }

    $commonPaths = @()

    $localAppData = [Environment]::GetFolderPath("LocalApplicationData")
    if (-not [string]::IsNullOrWhiteSpace($localAppData)) {
        $commonPaths += Join-Path $localAppData "Programs\Python\Python310\python.exe"
    }

    $programFiles = [Environment]::GetFolderPath("ProgramFiles")
    if (-not [string]::IsNullOrWhiteSpace($programFiles)) {
        $commonPaths += Join-Path $programFiles "Python310\python.exe"
    }

    $programFilesX86 = ${env:ProgramFiles(x86)}
    if (-not [string]::IsNullOrWhiteSpace($programFilesX86)) {
        $commonPaths += Join-Path $programFilesX86 "Python310\python.exe"
    }

    foreach ($path in $commonPaths) {
        Write-Info "Checking common Python path: $path"
        $resolved = Test-Python310Executable -PythonPath $path
        if ($null -ne $resolved) {
            Write-Success "Found Python 3.10: $resolved"
            return $resolved
        }
    }

    Write-WarningLog "Python 3.10 was not found."
    return $null
}

function Enable-Tls12 {
    try {
        [Net.ServicePointManager]::SecurityProtocol =
            [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        Write-Info "TLS 1.2 enabled for HTTPS downloads."
    } catch {
        Write-WarningLog "Could not explicitly enable TLS 1.2: $($_.Exception.Message)"
    }
}

function Get-PythonInstallTargetDir {
    $localAppData = [Environment]::GetFolderPath("LocalApplicationData")
    if ([string]::IsNullOrWhiteSpace($localAppData)) {
        $localAppData = Join-Path $env:USERPROFILE "AppData\Local"
    }

    return Join-Path $localAppData "Programs\Python\Python310"
}

function Download-FileWithPowerShell {
    param(
        [string]$Url,
        [string]$DestinationPath,
        [string]$Label = "installer"
    )

    Write-Step "Downloading $Label"
    Write-Info "Download URL: $Url"
    Write-Info "Destination: $DestinationPath"

    $destinationDir = Split-Path -Parent $DestinationPath
    New-Item -Path $destinationDir -ItemType Directory -Force | Out-Null
    Remove-Item -Path $DestinationPath -Force -ErrorAction SilentlyContinue

    Enable-Tls12

    $invokeWebRequest = Get-Command "Invoke-WebRequest" -ErrorAction SilentlyContinue
    if ($null -ne $invokeWebRequest) {
        try {
            Write-Info "Trying Invoke-WebRequest."
            Invoke-WebRequest -Uri $Url -OutFile $DestinationPath -UseBasicParsing
            Confirm-DownloadedFile -DestinationPath $DestinationPath
            Write-Success "Downloaded $Label with Invoke-WebRequest."
            return
        } catch {
            Write-WarningLog "Invoke-WebRequest download failed: $($_.Exception.Message)"
            Remove-Item -Path $DestinationPath -Force -ErrorAction SilentlyContinue
        }
    }

    $bitsTransfer = Get-Command "Start-BitsTransfer" -ErrorAction SilentlyContinue
    if ($null -ne $bitsTransfer) {
        try {
            Write-Info "Trying Start-BitsTransfer."
            Start-BitsTransfer -Source $Url -Destination $DestinationPath
            Confirm-DownloadedFile -DestinationPath $DestinationPath
            Write-Success "Downloaded $Label with Start-BitsTransfer."
            return
        } catch {
            Write-WarningLog "Start-BitsTransfer download failed: $($_.Exception.Message)"
            Remove-Item -Path $DestinationPath -Force -ErrorAction SilentlyContinue
        }
    }

    try {
        Write-Info "Trying System.Net.WebClient."
        $webClient = New-Object System.Net.WebClient
        try {
            $webClient.DownloadFile($Url, $DestinationPath)
        } finally {
            $webClient.Dispose()
        }
        Confirm-DownloadedFile -DestinationPath $DestinationPath
        Write-Success "Downloaded $Label with System.Net.WebClient."
        return
    } catch {
        Remove-Item -Path $DestinationPath -Force -ErrorAction SilentlyContinue
        throw "Could not download $Label from $Url. Last error: $($_.Exception.Message)"
    }
}

function Confirm-DownloadedFile {
    param([string]$DestinationPath)

    if (-not (Test-Path $DestinationPath)) {
        throw "Downloaded file was not created: $DestinationPath"
    }

    $downloadedFile = Get-Item -Path $DestinationPath
    if ($downloadedFile.Length -le 0) {
        throw "Downloaded file is empty: $DestinationPath"
    }

    Write-Info "Downloaded file size: $($downloadedFile.Length) bytes."
}

function Install-Python310FromOfficialInstaller {
    Write-Step "Installing Python $PythonInstallerVersion with official Python.org installer"

    $downloadDir = Join-Path ([IO.Path]::GetTempPath()) "PogledAssistSetup"
    $installerPath = Join-Path $downloadDir $PythonInstallerFileName
    Download-FileWithPowerShell `
        -Url $PythonInstallerUrl `
        -DestinationPath $installerPath `
        -Label "Python installer"

    try {
        Unblock-File -Path $installerPath -ErrorAction SilentlyContinue
    } catch {
        Write-WarningLog "Could not unblock installer file: $($_.Exception.Message)"
    }

    $targetDir = Get-PythonInstallTargetDir
    New-Item -Path (Split-Path -Parent $targetDir) -ItemType Directory -Force | Out-Null

    $installerArguments = @(
        "/quiet",
        "InstallAllUsers=0",
        "TargetDir=`"$targetDir`"",
        "PrependPath=1",
        "Include_pip=1",
        "Include_launcher=1",
        "InstallLauncherAllUsers=0",
        "Include_test=0",
        "Include_doc=0",
        "Shortcuts=0",
        "SimpleInstall=1"
    )

    Write-Info "Installer path: $installerPath"
    Write-Info "Install target: $targetDir"
    Write-Info "Running official Python installer silently."

    $process = Start-Process `
        -FilePath $installerPath `
        -ArgumentList $installerArguments `
        -Wait `
        -PassThru

    if ($null -eq $process) {
        throw "Python installer process did not return a process object."
    }

    if ($process.ExitCode -eq 3010) {
        Write-WarningLog "Python installer requested a reboot, but installation may still be usable now."
        return
    }

    if ($process.ExitCode -ne 0) {
        throw "Python installer failed with exit code $($process.ExitCode)."
    }

    Write-Success "Official Python installer completed successfully."
}

function Install-Python310 {
    if ($SkipPythonInstall) {
        throw "Python 3.10 is missing and -SkipPythonInstall was used."
    }

    Write-Step "Installing Python 3.10"

    $winget = Get-Command "winget" -ErrorAction SilentlyContinue
    if ($null -ne $winget) {
        try {
            Invoke-NativeCommand `
                -Label "Installing Python 3.10 with winget" `
                -FilePath "winget" `
                -Arguments @(
                    "install",
                    "--id",
                    "Python.Python.3.10",
                    "--exact",
                    "--source",
                    "winget",
                    "--accept-package-agreements",
                    "--accept-source-agreements"
                )

            $pythonExe = Get-Python310
            if ($null -ne $pythonExe) {
                Write-Success "Python 3.10 winget installation completed and was verified."
                return
            }

            Write-WarningLog "winget finished, but Python 3.10 was not detected in the current session."
        } catch {
            Write-WarningLog "winget Python installation failed: $($_.Exception.Message)"
        }
    } else {
        Write-WarningLog "winget was not found. Falling back to direct Python.org installer download."
    }

    Install-Python310FromOfficialInstaller

    $pythonExe = Get-Python310
    if ($null -eq $pythonExe) {
        throw "Python 3.10 installer completed, but Python 3.10 still was not found."
    }

    Write-Success "Python 3.10 direct installer completed and was verified."
}

function Resolve-OrInstallPython310 {
    $pythonExe = Get-Python310
    if ($null -ne $pythonExe) {
        return $pythonExe
    }

    if ($InstallPython) {
        Write-Info "-InstallPython was supplied. Python install will be attempted."
    } else {
        Write-Info "Python 3.10 is required and was not found. The script will attempt to install it automatically."
    }

    Install-Python310

    $pythonExe = Get-Python310
    if ($null -eq $pythonExe) {
        throw "Python 3.10 installation finished, but Python 3.10 still was not found. Open a new PowerShell window and rerun this script."
    }

    return $pythonExe
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
    Write-Step "Finding 32-bit Python 3.10 for Tobii bridge"

    foreach ($envName in @("POGLED_ASSIST_X86_PYTHON", "TOBII_GAZE_MOUSE_X86_PYTHON")) {
        $configuredPath = [Environment]::GetEnvironmentVariable($envName)
        if (-not [string]::IsNullOrWhiteSpace($configuredPath)) {
            Write-Info "Checking ${envName}: $configuredPath"
            $resolvedEnvPath = Test-Python310X86Executable -PythonPath $configuredPath
            if ($null -ne $resolvedEnvPath) {
                Write-Success "Found 32-bit Python 3.10 from environment: $resolvedEnvPath"
                return $resolvedEnvPath
            }
        }
    }

    $pyLauncher = Get-Command "py" -ErrorAction SilentlyContinue
    if ($null -ne $pyLauncher) {
        Write-Info "Checking Python launcher: py -3.10-32"
        $probe = Invoke-NativeProbe `
            -FilePath "py" `
            -Arguments @("-3.10-32", "-c", "import sys; print(sys.executable)")
        $pythonPath = ($probe.Output | Select-Object -First 1)
        if ($probe.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($pythonPath)) {
            $resolved = Test-Python310X86Executable -PythonPath $pythonPath.Trim()
            if ($null -ne $resolved) {
                Write-Success "Found 32-bit Python 3.10 through py launcher: $resolved"
                return $resolved
            }
        } else {
            Write-Info "py launcher did not find 32-bit Python 3.10."
        }
    }

    $commonPaths = @()

    $localAppData = [Environment]::GetFolderPath("LocalApplicationData")
    if (-not [string]::IsNullOrWhiteSpace($localAppData)) {
        $commonPaths += Join-Path $localAppData "Programs\Python\Python310-32\python.exe"
        $commonPaths += Join-Path $localAppData "Programs\Python\Python310-32bit\python.exe"
    }

    $programFilesX86 = ${env:ProgramFiles(x86)}
    if (-not [string]::IsNullOrWhiteSpace($programFilesX86)) {
        $commonPaths += Join-Path $programFilesX86 "Python310-32\python.exe"
        $commonPaths += Join-Path $programFilesX86 "Python310\python.exe"
    }

    foreach ($path in $commonPaths) {
        Write-Info "Checking common 32-bit Python path: $path"
        $resolved = Test-Python310X86Executable -PythonPath $path
        if ($null -ne $resolved) {
            Write-Success "Found 32-bit Python 3.10: $resolved"
            return $resolved
        }
    }

    Write-WarningLog "32-bit Python 3.10 was not found."
    return $null
}

function Get-PythonX86InstallTargetDir {
    $localAppData = [Environment]::GetFolderPath("LocalApplicationData")
    if ([string]::IsNullOrWhiteSpace($localAppData)) {
        $localAppData = Join-Path $env:USERPROFILE "AppData\Local"
    }

    return Join-Path $localAppData "Programs\Python\Python310-32"
}

function Install-Python310X86FromOfficialInstaller {
    Write-Step "Installing 32-bit Python $PythonInstallerVersion for Tobii bridge"

    $downloadDir = Join-Path ([IO.Path]::GetTempPath()) "PogledAssistSetup"
    $installerPath = Join-Path $downloadDir $PythonX86InstallerFileName
    Download-FileWithPowerShell `
        -Url $PythonX86InstallerUrl `
        -DestinationPath $installerPath `
        -Label "32-bit Python bridge installer"

    try {
        Unblock-File -Path $installerPath -ErrorAction SilentlyContinue
    } catch {
        Write-WarningLog "Could not unblock 32-bit Python installer file: $($_.Exception.Message)"
    }

    $targetDir = Get-PythonX86InstallTargetDir
    New-Item -Path (Split-Path -Parent $targetDir) -ItemType Directory -Force | Out-Null

    $installerArguments = @(
        "/quiet",
        "InstallAllUsers=0",
        "TargetDir=`"$targetDir`"",
        "PrependPath=0",
        "Include_pip=0",
        "Include_launcher=1",
        "InstallLauncherAllUsers=0",
        "Include_test=0",
        "Include_doc=0",
        "Shortcuts=0",
        "SimpleInstall=1"
    )

    Write-Info "Installer path: $installerPath"
    Write-Info "Install target: $targetDir"
    Write-Info "Running official 32-bit Python installer silently."

    $process = Start-Process `
        -FilePath $installerPath `
        -ArgumentList $installerArguments `
        -Wait `
        -PassThru

    if ($null -eq $process) {
        throw "32-bit Python installer process did not return a process object."
    }

    if ($process.ExitCode -eq 3010) {
        Write-WarningLog "32-bit Python installer requested a reboot, but installation may still be usable now."
        return
    }

    if ($process.ExitCode -ne 0) {
        throw "32-bit Python installer failed with exit code $($process.ExitCode)."
    }

    Write-Success "Official 32-bit Python installer completed successfully."
}

function Resolve-OrInstallPython310X86 {
    $pythonExe = Get-Python310X86
    if ($null -ne $pythonExe) {
        return $pythonExe
    }

    if ($SkipX86BridgePythonInstall) {
        Write-WarningLog "32-bit Python bridge runtime is missing and -SkipX86BridgePythonInstall was used."
        return ""
    }

    if ($SkipPythonInstall) {
        throw "32-bit Python 3.10 bridge runtime is missing and -SkipPythonInstall was used."
    }

    Write-Info "32-bit Python 3.10 is required for Tobii Eye Tracking Core Software DLLs. The script will install it automatically."
    Install-Python310X86FromOfficialInstaller

    $pythonExe = Get-Python310X86
    if ($null -eq $pythonExe) {
        throw "32-bit Python 3.10 installation finished, but 32-bit Python 3.10 still was not found."
    }

    return $pythonExe
}

function Test-EspeakNgBosnianVoice {
    param([string]$EspeakExe)

    if ([string]::IsNullOrWhiteSpace($EspeakExe) -or -not (Test-Path $EspeakExe)) {
        return $false
    }

    $versionProbe = Invoke-NativeProbe `
        -FilePath $EspeakExe `
        -Arguments @("--version")
    if ($versionProbe.ExitCode -ne 0) {
        Write-Info "eSpeak NG version probe failed for $EspeakExe."
        return $false
    }

    $versionText = ($versionProbe.Output | Select-Object -First 1)
    if (-not [string]::IsNullOrWhiteSpace($versionText)) {
        Write-Info "eSpeak NG version: $versionText"
    }

    $voiceProbe = Invoke-NativeProbe `
        -FilePath $EspeakExe `
        -Arguments @("--voices=bs")
    $voiceText = ($voiceProbe.Output -join "`n")

    if ($voiceProbe.ExitCode -eq 0 -and $voiceText -match "(?im)(^|\s)(bs|bosnian)(\s|$)") {
        Write-Success "Bosnian eSpeak NG voice was detected."
        return $true
    }

    Write-Info "Direct Bosnian voice probe did not confirm support. Checking full voice list."
    $allVoicesProbe = Invoke-NativeProbe `
        -FilePath $EspeakExe `
        -Arguments @("--voices")
    $allVoiceText = ($allVoicesProbe.Output -join "`n")

    if ($allVoicesProbe.ExitCode -eq 0 -and $allVoiceText -match "(?im)(^|\s)(bs|bosnian)(\s|$)") {
        Write-Success "Bosnian eSpeak NG voice was detected in full voice list."
        return $true
    }

    Write-WarningLog "Bosnian eSpeak NG voice was not detected from $EspeakExe."
    return $false
}

function Get-EspeakNgCandidatePaths {
    $paths = @()

    $configured = $env:ESPEAK_NG_EXE
    if (-not [string]::IsNullOrWhiteSpace($configured)) {
        $paths += $configured
    }

    $command = Get-Command "espeak-ng" -ErrorAction SilentlyContinue
    if ($null -ne $command -and -not [string]::IsNullOrWhiteSpace($command.Source)) {
        $paths += $command.Source
    }

    $programFiles = [Environment]::GetFolderPath("ProgramFiles")
    if (-not [string]::IsNullOrWhiteSpace($programFiles)) {
        $paths += Join-Path $programFiles "eSpeak NG\espeak-ng.exe"
        $paths += Join-Path $programFiles "eSpeak NG\command_line\espeak-ng.exe"
    }

    $programFilesX86 = ${env:ProgramFiles(x86)}
    if (-not [string]::IsNullOrWhiteSpace($programFilesX86)) {
        $paths += Join-Path $programFilesX86 "eSpeak NG\espeak-ng.exe"
        $paths += Join-Path $programFilesX86 "eSpeak NG\command_line\espeak-ng.exe"
    }

    $paths | Where-Object {
        -not [string]::IsNullOrWhiteSpace($_)
    } | Select-Object -Unique
}

function Get-EspeakNgExecutable {
    Write-Step "Finding eSpeak NG with Bosnian voice support"

    foreach ($candidatePath in Get-EspeakNgCandidatePaths) {
        Write-Info "Checking eSpeak NG path: $candidatePath"
        if (-not (Test-Path $candidatePath)) {
            continue
        }

        if (Test-EspeakNgBosnianVoice -EspeakExe $candidatePath) {
            return (Get-NormalizedFullPath -Path $candidatePath)
        }
    }

    Write-WarningLog "eSpeak NG with Bosnian voice support was not found."
    return $null
}

function Install-EspeakNgWithWinget {
    $winget = Get-Command "winget" -ErrorAction SilentlyContinue
    if ($null -eq $winget) {
        Write-WarningLog "winget was not found. Falling back to direct eSpeak NG MSI download."
        return $false
    }

    Write-Step "Installing eSpeak NG with winget"

    $arguments = @(
        "install",
        "--id",
        $EspeakNgPackageId,
        "--exact",
        "--source",
        "winget",
        "--silent",
        "--accept-package-agreements",
        "--accept-source-agreements"
    )

    if (-not [string]::IsNullOrWhiteSpace($EspeakNgVersion)) {
        $arguments += @("--version", $EspeakNgVersion)
    }

    try {
        Invoke-NativeCommand `
            -Label "Installing eSpeak NG package $EspeakNgPackageId with winget" `
            -FilePath "winget" `
            -Arguments $arguments
        return $true
    } catch {
        Write-WarningLog "winget eSpeak NG installation failed: $($_.Exception.Message)"
        return $false
    }
}

function Install-EspeakNgFromMsi {
    Write-Step "Installing eSpeak NG $EspeakNgVersion from MSI"

    $downloadDir = Join-Path ([IO.Path]::GetTempPath()) "PogledAssistSetup"
    $installerPath = Join-Path $downloadDir $EspeakNgInstallerFileName
    Download-FileWithPowerShell `
        -Url $EspeakNgInstallerUrl `
        -DestinationPath $installerPath `
        -Label "eSpeak NG installer"

    try {
        Unblock-File -Path $installerPath -ErrorAction SilentlyContinue
    } catch {
        Write-WarningLog "Could not unblock eSpeak NG installer file: $($_.Exception.Message)"
    }

    $arguments = @(
        "/i",
        "`"$installerPath`"",
        "/quiet",
        "/norestart"
    )

    Write-Info "Installer path: $installerPath"
    Write-Info "Running eSpeak NG MSI installer silently."

    $process = Start-Process `
        -FilePath "msiexec.exe" `
        -ArgumentList $arguments `
        -Wait `
        -PassThru

    if ($null -eq $process) {
        throw "eSpeak NG installer process did not return a process object."
    }

    if ($process.ExitCode -eq 3010) {
        Write-WarningLog "eSpeak NG installer requested a reboot, but installation may still be usable now."
        return
    }

    if ($process.ExitCode -ne 0) {
        throw "eSpeak NG MSI installer failed with exit code $($process.ExitCode)."
    }

    Write-Success "eSpeak NG MSI installer completed successfully."
}

function Install-EspeakNg {
    Write-Step "Installing eSpeak NG"

    $wingetInstalled = Install-EspeakNgWithWinget
    if ($wingetInstalled) {
        $wingetResult = Get-EspeakNgExecutable
        if ($null -ne $wingetResult) {
            Write-Success "eSpeak NG winget installation completed and was verified."
            return $wingetResult
        }

        Write-WarningLog "winget finished, but eSpeak NG with Bosnian support was not detected."
    }

    Install-EspeakNgFromMsi

    $msiResult = Get-EspeakNgExecutable
    if ($null -eq $msiResult) {
        throw "eSpeak NG installation finished, but eSpeak NG with Bosnian voice support still was not found."
    }

    Write-Success "eSpeak NG MSI installation completed and was verified."
    return $msiResult
}

function Resolve-OrInstallEspeakNg {
    $espeakExe = Get-EspeakNgExecutable
    if ($null -ne $espeakExe) {
        return $espeakExe
    }

    Write-Info "eSpeak NG is required for Bosnian speech. The script will attempt to install it automatically."
    return (Install-EspeakNg)
}

function Ensure-VirtualEnvironment {
    param([string]$PythonExe)

    Write-Step "Preparing virtual environment"

    $venvFullPath = Join-Path $RepoRoot $VenvPath
    $venvPython = Join-Path $venvFullPath "Scripts\python.exe"

    if (Test-Path $venvPython) {
        Write-Info "Existing virtual environment found at $venvFullPath"
        $venvProbe = Invoke-NativeProbe `
            -FilePath $venvPython `
            -Arguments @("-c", "import sys; print(sys.version); raise SystemExit(0 if sys.version_info[:2] == (3, 10) else 1)")

        if ($venvProbe.ExitCode -eq 0) {
            $venvVersion = ($venvProbe.Output | Select-Object -First 1)
            Write-Success "Using existing virtual environment at $venvFullPath"
            Write-Info "Virtual environment Python version: $venvVersion"
            return $venvPython
        }

        Write-WarningLog "Existing virtual environment is broken, inaccessible, or not Python 3.10. It will be recreated."
        Remove-Item -Path $venvFullPath -Recurse -Force -ErrorAction SilentlyContinue
    }

    if (-not (Test-Path $venvPython)) {
        Invoke-NativeCommand `
            -Label "Creating virtual environment at $venvFullPath" `
            -FilePath $PythonExe `
            -Arguments @("-m", "venv", $venvFullPath)
    }

    if (-not (Test-Path $venvPython)) {
        throw "Virtual environment Python was not found after creation: $venvPython"
    }

    $createdProbe = Invoke-NativeProbe `
        -FilePath $venvPython `
        -Arguments @("-c", "import sys; print(sys.version); raise SystemExit(0 if sys.version_info[:2] == (3, 10) else 1)")
    if ($createdProbe.ExitCode -ne 0) {
        throw "Virtual environment was created, but its Python executable could not be verified."
    }

    $createdVersion = ($createdProbe.Output | Select-Object -First 1)
    Write-Info "Virtual environment Python version: $createdVersion"

    return $venvPython
}

function Install-PythonPackages {
    param([string]$VenvPython)

    Write-Step "Installing Python package dependencies"

    Invoke-NativeCommand `
        -Label "Ensuring pip is available" `
        -FilePath $VenvPython `
        -Arguments @("-m", "ensurepip", "--upgrade")

    Invoke-NativeCommand `
        -Label "Upgrading pip, setuptools, and wheel" `
        -FilePath $VenvPython `
        -Arguments @("-m", "pip", "install", "--upgrade", "--no-compile", "pip", "setuptools", "wheel")

    $requirementsPath = Join-Path $RepoRoot "requirements.txt"
    Invoke-NativeCommand `
        -Label "Installing requirements from $requirementsPath" `
        -FilePath $VenvPython `
        -Arguments @("-m", "pip", "install", "--no-compile", "--only-binary=:all:", "-r", $requirementsPath)

    Write-Success "Python package installation completed."
}

function Verify-PythonPackages {
    param([string]$VenvPython)

    Write-Step "Verifying installed Python packages"

    $verifyCode = @'
import importlib.util
import sys

from pathlib import Path

required = ["PySide6", "qtawesome", "tobii_research", "edge_tts"]
missing = [name for name in required if importlib.util.find_spec(name) is None]
if missing:
    raise SystemExit("Missing packages: " + ", ".join(missing))

scripts_dir = Path(sys.executable).resolve().parent
edge_names = ["edge-playback.exe", "edge-playback"]
edge_playback = next((scripts_dir / name for name in edge_names if (scripts_dir / name).exists()), None)
if edge_playback is None:
    raise SystemExit("Missing edge-playback CLI in " + str(scripts_dir))

print("Python executable:", sys.executable)
print("edge-playback executable:", edge_playback)
print("Dependency check passed.")
'@

    $verifyScriptPath = Join-Path ([IO.Path]::GetTempPath()) ("tobii_verify_packages_{0}.py" -f [Guid]::NewGuid().ToString("N"))

    Write-Info "Writing dependency verification script: $verifyScriptPath"
    Set-Content -Path $verifyScriptPath -Value $verifyCode -Encoding ASCII

    try {
        Invoke-NativeCommand `
            -Label "Checking required Python modules" `
            -FilePath $VenvPython `
            -Arguments @($verifyScriptPath)
    } finally {
        Remove-Item -Path $verifyScriptPath -Force -ErrorAction SilentlyContinue
    }

    Write-Success "All required Python packages are available."
}

function Get-EdgePlaybackExecutableFromVenv {
    param([string]$VenvPython)

    $scriptsDir = Split-Path -Parent $VenvPython
    $candidates = @(
        (Join-Path $scriptsDir "edge-playback.exe"),
        (Join-Path $scriptsDir "edge-playback")
    )

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    throw "edge-playback CLI was not found in the virtual environment Scripts folder: $scriptsDir"
}

function Get-EdgeTtsExecutableFromVenv {
    param([string]$VenvPython)

    $scriptsDir = Split-Path -Parent $VenvPython
    $candidates = @(
        (Join-Path $scriptsDir "edge-tts.exe"),
        (Join-Path $scriptsDir "edge-tts")
    )

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    throw "edge-tts CLI was not found in the virtual environment Scripts folder: $scriptsDir"
}

function Verify-EdgeTtsVoiceSupport {
    param(
        [string]$VenvPython,
        [string]$EdgeTtsExe,
        [string]$EdgePlaybackExe
    )

    Write-Step "Verifying Edge TTS human-like Bosnian voice"

    $venvScripts = Split-Path -Parent $VenvPython
    $env:PATH = $venvScripts + [IO.Path]::PathSeparator + $env:PATH
    $env:EDGE_PLAYBACK_EXE = $EdgePlaybackExe

    Invoke-NativeCommandWithTimeout `
        -Label "Checking edge-tts command" `
        -FilePath $EdgeTtsExe `
        -Arguments @("--version") `
        -TimeoutSeconds 20

    Invoke-NativeCommandWithTimeout `
        -Label "Checking edge-playback command" `
        -FilePath $EdgePlaybackExe `
        -Arguments @("--help") `
        -TimeoutSeconds 20

    $verifyCode = @'
import asyncio
import sys
import tempfile
from pathlib import Path

import edge_tts


async def main() -> None:
    voice = sys.argv[1]
    rate = sys.argv[2]
    pitch = sys.argv[3]
    text = sys.argv[4]

    print("edge_tts package:", getattr(edge_tts, "__version__", "unknown"))
    voices = await asyncio.wait_for(edge_tts.list_voices(), timeout=35)
    matches = [item for item in voices if item.get("ShortName") == voice]
    if not matches:
        raise SystemExit(f"Voice was not returned by Edge TTS service: {voice}")

    print("Verified Edge TTS voice:", voice)
    media_path = Path(tempfile.gettempdir()) / "tobii_edge_tts_voice_test.mp3"
    if media_path.exists():
        media_path.unlink()

    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await asyncio.wait_for(communicate.save(str(media_path)), timeout=45)

    size = media_path.stat().st_size if media_path.exists() else 0
    if size < 512:
        raise SystemExit(f"Edge TTS generated an invalid media file: {media_path} ({size} bytes)")

    print("Generated Edge TTS voice test media bytes:", size)
    try:
        media_path.unlink()
    except OSError:
        pass


asyncio.run(main())
'@

    $verifyScriptPath = Join-Path ([IO.Path]::GetTempPath()) ("tobii_verify_edge_tts_{0}.py" -f [Guid]::NewGuid().ToString("N"))
    Write-Info "Writing Edge TTS verification script: $verifyScriptPath"
    Set-Content -Path $verifyScriptPath -Value $verifyCode -Encoding ASCII

    try {
        Invoke-NativeCommandWithTimeout `
            -Label "Verifying $EdgeTtsVoice voice can synthesize audio" `
            -FilePath $VenvPython `
            -Arguments @($verifyScriptPath, $EdgeTtsVoice, $EdgeTtsRate, $EdgeTtsPitch, $EdgeTtsTestText) `
            -TimeoutSeconds 90
    } finally {
        Remove-Item -Path $verifyScriptPath -Force -ErrorAction SilentlyContinue
    }

    Invoke-NativeCommandWithTimeout `
        -Label "Running edge-playback smoke test for $EdgeTtsVoice" `
        -FilePath $EdgePlaybackExe `
        -Arguments @("--voice", $EdgeTtsVoice, "--rate=$EdgeTtsRate", "--pitch=$EdgeTtsPitch", "--text", $EdgeTtsTestText) `
        -TimeoutSeconds 90

    Write-Success "Edge playback and $EdgeTtsVoice were verified successfully."
}

function New-LauncherScripts {
    param(
        [string]$VenvPython,
        [string]$EspeakExe,
        [string]$X86Python,
        [string]$EdgePlaybackExe
    )

    Write-Step "Creating launcher scripts"

    $venvScripts = Split-Path -Parent $VenvPython
    $batchPath = Join-Path $RepoRoot "run_gaze_mouse.bat"
    $batchLines = @(
        "@echo off",
        "setlocal",
        "cd /d ""%~dp0""",
        "set ""PATH=$venvScripts;%PATH%""",
        "set ""ESPEAK_NG_EXE=$EspeakExe""",
        "set ""EDGE_PLAYBACK_EXE=$EdgePlaybackExe""",
        "set ""POGLED_ASSIST_X86_PYTHON=$X86Python""",
        """$VenvPython"" ""%~dp0run_gaze_mouse.py""",
        "set EXITCODE=%ERRORLEVEL%",
        "if not ""%EXITCODE%""==""0"" (",
        "  echo.",
        "  echo Pogled Assist exited with code %EXITCODE%.",
        "  echo Check logs\latest.txt for details.",
        "  pause",
        ")",
        "exit /b %EXITCODE%"
    )
    Set-Content -Path $batchPath -Value $batchLines -Encoding ASCII
    Write-Success "Created $batchPath"

    $powerShellLauncherPath = Join-Path $RepoRoot "run_gaze_mouse.ps1"
    $powerShellLines = @(
        '$ErrorActionPreference = "Stop"',
        '$Root = Split-Path -Parent $MyInvocation.MyCommand.Path',
        'Set-Location $Root',
        '$VenvScripts = Join-Path $Root ".venv\Scripts"',
        '$Python = Join-Path $VenvScripts "python.exe"',
        '$App = Join-Path $Root "run_gaze_mouse.py"',
        '$env:PATH = $VenvScripts + [IO.Path]::PathSeparator + $env:PATH',
        '$env:ESPEAK_NG_EXE = "' + $EspeakExe.Replace('"', '""') + '"',
        '$env:EDGE_PLAYBACK_EXE = "' + $EdgePlaybackExe.Replace('"', '""') + '"',
        '$env:POGLED_ASSIST_X86_PYTHON = "' + $X86Python.Replace('"', '""') + '"',
        '& $Python $App',
        'exit $LASTEXITCODE'
    )
    Set-Content -Path $powerShellLauncherPath -Value $powerShellLines -Encoding ASCII
    Write-Success "Created $powerShellLauncherPath"

    if ($NoDesktopShortcut) {
        Write-Info "Desktop shortcut creation skipped because -NoDesktopShortcut was used."
        return
    }

    $startScriptPath = Join-Path $RepoRoot "start_gaze_mouse.ps1"
    if (Test-Path $startScriptPath) {
        New-DesktopShortcut -TargetPath $startScriptPath
    } else {
        Write-WarningLog "start_gaze_mouse.ps1 was not found; desktop shortcut will point to batch launcher."
        New-DesktopShortcut -TargetPath $batchPath
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
    $candidates = @(
        (Join-Path $SourceRoot "data\app_settings.json"),
        (Join-Path $RepoRoot "data\app_settings.json")
    )

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

function Get-PowerShellLaunchArguments {
    param([string]$LauncherPath)

    $arguments = @()
    if (-not (Get-LauncherWindowVisible)) {
        $arguments += "-WindowStyle"
        $arguments += "Hidden"
    }

    $arguments += "-NoProfile"
    $arguments += "-ExecutionPolicy"
    $arguments += "Bypass"
    $arguments += "-File"
    $arguments += (Format-ShortcutArgument -Value $LauncherPath)
    return ($arguments -join " ")
}

function Resolve-ShortcutIconLocation {
    $pngCandidates = @(
        (Join-Path $RepoRoot "assets\icon.png"),
        (Join-Path $SourceRoot "assets\icon.png")
    )

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

function New-DesktopShortcut {
    param([string]$TargetPath)

    Write-Step "Creating desktop shortcut"

    try {
        $desktopPath = [Environment]::GetFolderPath("Desktop")
        if ([string]::IsNullOrWhiteSpace($desktopPath)) {
            throw "Desktop folder path could not be resolved."
        }

        $shortcutPath = Join-Path $desktopPath "Pogled Assist.lnk"
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($shortcutPath)
        if ([IO.Path]::GetExtension($TargetPath) -ieq ".ps1") {
            $shortcut.TargetPath = Get-PowerShellExecutable
            $shortcut.Arguments = Get-PowerShellLaunchArguments -LauncherPath $TargetPath
        } else {
            $shortcut.TargetPath = $TargetPath
            $shortcut.Arguments = ""
        }
        $shortcut.WorkingDirectory = $RepoRoot
        $shortcut.Description = "Launch Pogled Assist"
        $iconLocation = Resolve-ShortcutIconLocation
        if (-not [string]::IsNullOrWhiteSpace($iconLocation)) {
            $shortcut.IconLocation = $iconLocation
        }
        $shortcut.Save()

        Write-Success "Created desktop shortcut: $shortcutPath"
    } catch {
        Write-WarningLog "Could not create desktop shortcut automatically: $($_.Exception.Message)"
    }
}

function Show-ExternalPrerequisiteNotes {
    Write-Step "Checking external Tobii prerequisites"
    Write-WarningLog "This script installs Python and Python packages, but it cannot safely install or calibrate the Tobii device runtime."
    Write-Info "Before running the app, confirm the Tobii Eye Tracker 4C is connected, detected by Tobii software, and calibrated."
}

function Show-FinalInstructions {
    param(
        [string]$VenvPython,
        [string]$EspeakExe,
        [string]$X86Python,
        [string]$EdgePlaybackExe
    )

    Write-Step "Setup complete"
    Write-Success "The program is ready to run."
    Write-Host ""
    Write-Host "Installed folder:" -ForegroundColor Green
    Write-Host "  $RepoRoot" -ForegroundColor White
    Write-Host ""
    Write-Host "Run command:" -ForegroundColor Green
    Write-Host "  .\start_gaze_mouse.ps1" -ForegroundColor White
    Write-Host "  .\run_gaze_mouse.bat" -ForegroundColor White
    Write-Host "  .\$VenvPath\Scripts\python.exe .\run_gaze_mouse.py" -ForegroundColor White
    Write-Host ""
    Write-Host "Notes:" -ForegroundColor Cyan
    Write-Host "  - Make sure the Tobii Eye Tracker 4C is connected and calibrated."
    Write-Host "  - Make sure Tobii software/runtime can see the device."
    Write-Host "  - If tobii-research cannot see the 4C, the app tries the Tobii Stream Engine DLL fallback automatically."
    Write-Host "  - Tobii Core Software 2.x often provides 32-bit DLLs; setup installs 32-bit Python for the x86 bridge."
    Write-Host "  - For Stream Engine fallback, install Tobii Core/Game Hub or place tobii_stream_engine.dll under tools\tobii before rerunning setup."
    Write-Host "  - A desktop shortcut is created unless -NoDesktopShortcut is used."
    Write-Host "  - Setup log: $LogPath"
    Write-Host "  - Runtime log: logs\latest.txt"
    Write-Host "  - Python used by venv: $VenvPython"
    Write-Host "  - 32-bit Python used by Tobii bridge: $X86Python"
    Write-Host "  - eSpeak NG used for Bosnian speech: $EspeakExe"
    Write-Host "  - Edge playback used for human-like Bosnian speech: $EdgePlaybackExe"
    Write-Host "  - Human-like voice verified during setup: $EdgeTtsVoice"
}

try {
    Assert-Windows
    Ensure-SetupAdministrator
    Start-SetupTranscript
    Initialize-WorkingRoot
    Write-InstallInfo
    Write-Step "Starting Pogled Assist setup"
    Write-Info "Source root: $SourceRoot"
    Write-Info "Repository root: $RepoRoot"
    Write-Info "Virtual environment path: $VenvPath"
    Write-Info "Install root override: $InstallRoot"
    Write-Info "Bytecode generation disabled for this setup run."

    Assert-RepositoryFiles
    $pythonExe = Resolve-OrInstallPython310
    Write-Success "Using Python 3.10 executable: $pythonExe"
    $x86PythonExe = Resolve-OrInstallPython310X86
    if (-not [string]::IsNullOrWhiteSpace($x86PythonExe)) {
        $env:POGLED_ASSIST_X86_PYTHON = $x86PythonExe
        Update-InstallInfoBridgePython -X86Python $x86PythonExe
        Write-Success "Using 32-bit Python 3.10 bridge executable: $x86PythonExe"
    } else {
        Write-WarningLog "32-bit Python bridge executable is not configured. Tobii Core 2.x DLLs may not load."
    }
    $espeakExe = Resolve-OrInstallEspeakNg
    $env:ESPEAK_NG_EXE = $espeakExe
    Write-Success "Using eSpeak NG executable: $espeakExe"

    $venvPython = Ensure-VirtualEnvironment -PythonExe $pythonExe
    Install-PythonPackages -VenvPython $venvPython
    Verify-PythonPackages -VenvPython $venvPython
    $edgePlaybackExe = Get-EdgePlaybackExecutableFromVenv -VenvPython $venvPython
    $edgeTtsExe = Get-EdgeTtsExecutableFromVenv -VenvPython $venvPython
    $env:EDGE_PLAYBACK_EXE = $edgePlaybackExe
    Write-Success "Using Edge TTS executable: $edgeTtsExe"
    Write-Success "Using Edge playback executable: $edgePlaybackExe"
    Verify-EdgeTtsVoiceSupport -VenvPython $venvPython -EdgeTtsExe $edgeTtsExe -EdgePlaybackExe $edgePlaybackExe
    New-LauncherScripts -VenvPython $venvPython -EspeakExe $espeakExe -X86Python $x86PythonExe -EdgePlaybackExe $edgePlaybackExe
    Show-ExternalPrerequisiteNotes
    Remove-BytecodeCaches
    Show-FinalInstructions -VenvPython $venvPython -EspeakExe $espeakExe -X86Python $x86PythonExe -EdgePlaybackExe $edgePlaybackExe

    if ($Launch) {
        Write-Step "Launching Pogled Assist"
        Invoke-NativeCommand `
            -Label "Starting application" `
            -FilePath $venvPython `
            -Arguments @((Join-Path $RepoRoot "run_gaze_mouse.py"))
    }
} catch {
    $script:ExitCode = 1
    Write-Host ""
    Write-ErrorLog "Setup failed: $($_.Exception.Message)"
    Write-Info "Review the console output above and setup log if available: $LogPath"
} finally {
    if ($script:ElevationRequested) {
        exit 0
    }

    if (-not $script:CacheCleaned) {
        try {
            Remove-BytecodeCaches
        } catch {
            Write-WarningLog "Cache cleanup failed: $($_.Exception.Message)"
        }
    }

    if ($script:ExitCode -eq 0) {
        Write-Success "Setup script finished successfully."
    } else {
        Write-ErrorLog "Setup script finished with errors."
    }

    Stop-SetupTranscript
    Sync-SetupLogToInstallRoot
    Sync-SetupLogToSource
    Wait-BeforeExit
    exit $script:ExitCode
}
