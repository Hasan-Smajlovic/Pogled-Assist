[CmdletBinding()]
param(
    [string]$InstallRoot = "C:\PogledAssist",
    [string]$ExpectedVersion = "",
    [switch]$NoDesktopShortcut,
    [switch]$Launch,
    [switch]$NoElevation
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$SourceRoot = Split-Path -Parent $PSCommandPath
$InstallerPath = $PSCommandPath
$script:InstallMutex = $null
$script:InstallMutexAcquired = $false

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

function Assert-DedicatedInstallRoot {
    $requestedRoot = [IO.Path]::GetFullPath($InstallRoot).TrimEnd("\")
    $legacyRoot = [IO.Path]::GetFullPath("C:\TobiiExec").TrimEnd("\")
    if ($requestedRoot.Equals($legacyRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "C:\TobiiExec belongs to the previous application and will not be changed. Install Pogled Assist to C:\PogledAssist or another separate folder."
    }
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
        Get-Process -Name "PogledAssist" -ErrorAction SilentlyContinue |
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
        throw "Close Pogled Assist before installing or rolling back. Running process IDs: $processIdList"
    }
}

function Enter-InstallLock {
    $mutexName = "Global\PogledAssist.Install"
    try {
        $createdNew = $false
        $script:InstallMutex = New-Object System.Threading.Mutex($false, $mutexName, [ref]$createdNew)
    } catch [System.UnauthorizedAccessException] {
        $mutexName = "Local\PogledAssist.Install"
        $createdNew = $false
        $script:InstallMutex = New-Object System.Threading.Mutex($false, $mutexName, [ref]$createdNew)
    }

    try {
        $script:InstallMutexAcquired = $script:InstallMutex.WaitOne(0, $false)
    } catch [System.Threading.AbandonedMutexException] {
        $script:InstallMutexAcquired = $true
    }

    if (-not $script:InstallMutexAcquired) {
        $script:InstallMutex.Dispose()
        $script:InstallMutex = $null
        throw "Another Pogled Assist install or update is already in progress."
    }
}

function Exit-InstallLock {
    if ($null -eq $script:InstallMutex) {
        return
    }

    if ($script:InstallMutexAcquired) {
        try {
            $script:InstallMutex.ReleaseMutex()
        } catch {
            Write-Warning "Could not release the installer lock cleanly: $($_.Exception.Message)"
        }
    }
    $script:InstallMutex.Dispose()
    $script:InstallMutex = $null
    $script:InstallMutexAcquired = $false
}

function ConvertTo-StableVersion {
    param(
        [string]$Value,
        [string]$Label
    )

    if ($Value -notmatch "^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$") {
        throw "$Label must contain a stable Semantic Version such as 0.2.0. Found: $Value"
    }
    return [version]::new(
        [int]$Matches[1],
        [int]$Matches[2],
        [int]$Matches[3]
    )
}

function Assert-PackageLayout {
    $requiredSourcePaths = @(
        "PogledAssist.exe",
        "_internal",
        "install_windows.ps1",
        "start_gaze_mouse.ps1",
        "update_windows.ps1",
        "README.md",
        "VERSION"
    )
    foreach ($relativePath in $requiredSourcePaths) {
        if (-not (Test-Path -LiteralPath (Join-Path $SourceRoot $relativePath))) {
            throw "The extracted package is incomplete. Missing: $relativePath"
        }
    }

    $versionText = (Get-Content -LiteralPath (Join-Path $SourceRoot "VERSION") -Raw).Trim()
    $packageVersion = ConvertTo-StableVersion -Value $versionText -Label "Package VERSION"
    if (-not [string]::IsNullOrWhiteSpace($ExpectedVersion)) {
        $requiredVersion = ConvertTo-StableVersion -Value $ExpectedVersion -Label "ExpectedVersion"
        if ($packageVersion -ne $requiredVersion) {
            throw "Package VERSION $packageVersion does not match expected release $requiredVersion."
        }
    }
    return $packageVersion
}

function Get-InstallPaths {
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

    return [PSCustomObject]@{
        Source = $sourceFullPath
        Install = $installFullPath
        Parent = Split-Path -Parent $installFullPath
        Name = Split-Path -Leaf $installFullPath
    }
}

function Invoke-RobocopyMirror {
    param(
        [string]$Source,
        [string]$Destination
    )

    [IO.Directory]::CreateDirectory($Destination) | Out-Null
    $arguments = @(
        $Source,
        $Destination,
        "/MIR",
        "/R:2",
        "/W:2",
        "/NFL",
        "/NDL",
        "/NP",
        "/XD", (Join-Path $Source "data"), (Join-Path $Source "logs"),
        "/XF", "install_info.json", "*.log"
    )
    & robocopy @arguments | ForEach-Object { Write-Host $_ }
    $exitCode = $LASTEXITCODE
    if ($exitCode -gt 7) {
        throw "Could not mirror $Source to $Destination. Robocopy exit code: $exitCode"
    }

    $global:LASTEXITCODE = 0
}

function Copy-PersistentContent {
    param(
        [string]$ExistingRoot,
        [string]$StagingRoot
    )

    foreach ($directoryName in @("data", "logs")) {
        $sourceDirectory = Join-Path $ExistingRoot $directoryName
        if (Test-Path -LiteralPath $sourceDirectory -PathType Container) {
            Copy-Item -LiteralPath $sourceDirectory -Destination $StagingRoot -Recurse -Force
        }
    }

    $metadataPath = Join-Path $ExistingRoot "install_info.json"
    if (Test-Path -LiteralPath $metadataPath -PathType Leaf) {
        Copy-Item -LiteralPath $metadataPath -Destination $StagingRoot -Force
    }

    Get-ChildItem -LiteralPath $ExistingRoot -File -Filter "*.log" -ErrorAction SilentlyContinue |
        ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $StagingRoot -Force
        }
}

function Get-ExternalComponentPaths {
    return @(
        ".venv",
        "tools",
        "edge-playback",
        "edge-playback.exe",
        "edge-playback-script.py",
        "espeak-ng.exe",
        "tobii_stream_engine.dll",
        "StreamEngineClient.dll"
    )
}

function Copy-ExternalComponents {
    param(
        [string]$ExistingRoot,
        [string]$StagingRoot,
        [string[]]$RelativePaths
    )

    foreach ($relativePath in $RelativePaths) {
        $sourcePath = Join-Path $ExistingRoot $relativePath
        if (Test-Path -LiteralPath $sourcePath) {
            Copy-Item -LiteralPath $sourcePath -Destination $StagingRoot -Recurse -Force
        }
    }
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

    $appExecutable = Join-Path $Root "PogledAssist.exe"
    if (-not (Test-Path -LiteralPath $appExecutable -PathType Leaf)) {
        throw "$Label could not start because PogledAssist.exe is missing."
    }

    $reportPath = Join-Path `
        ([IO.Path]::GetTempPath()) `
        ("PogledAssistSmoke_{0}.txt" -f [Guid]::NewGuid().ToString("N"))
    $previousReportPath = $env:POGLED_ASSIST_PACKAGE_SMOKE_REPORT
    try {
        $env:POGLED_ASSIST_PACKAGE_SMOKE_REPORT = $reportPath
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
        $env:POGLED_ASSIST_PACKAGE_SMOKE_REPORT = $previousReportPath
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

function Write-InstallTransaction {
    param(
        [string]$TransactionPath,
        [string]$InstallPath,
        [string]$StagingPath,
        [string]$BackupPath
    )

    $temporaryPath = "$TransactionPath.$([Guid]::NewGuid().ToString("N")).tmp"
    try {
        [PSCustomObject]@{
            InstallRoot = $InstallPath
            StagingRoot = $StagingPath
            BackupRoot = $BackupPath
        } | ConvertTo-Json | Set-Content -LiteralPath $temporaryPath -Encoding UTF8
        [IO.File]::Move($temporaryPath, $TransactionPath)
    } finally {
        Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
    }
}

function Assert-TransactionOperationPath {
    param(
        [string]$Candidate,
        [string]$ExpectedParent,
        [string]$ExpectedPrefix,
        [string]$Label
    )

    $fullPath = [IO.Path]::GetFullPath($Candidate).TrimEnd("\")
    $parent = Split-Path -Parent $fullPath
    $name = Split-Path -Leaf $fullPath
    if (
        -not $parent.Equals($ExpectedParent, [StringComparison]::OrdinalIgnoreCase) -or
        -not $name.StartsWith($ExpectedPrefix, [StringComparison]::OrdinalIgnoreCase)
    ) {
        throw "Interrupted-install recovery rejected an unsafe $Label path: $Candidate"
    }
    return $fullPath
}

function Restore-PreviousInstallation {
    param(
        [string]$InstallPath,
        [string]$BackupPath,
        [string]$InstallName
    )

    if (-not (Test-Path -LiteralPath $BackupPath -PathType Container)) {
        throw "The previous installation backup is missing: $BackupPath"
    }

    $failedPath = Join-Path `
        (Split-Path -Parent $InstallPath) `
        (".$InstallName.failed-{0}" -f [Guid]::NewGuid().ToString("N"))
    $movedFailedInstall = $false
    if (Test-Path -LiteralPath $InstallPath) {
        Move-Item -LiteralPath $InstallPath -Destination $failedPath
        $movedFailedInstall = $true
    }

    try {
        Move-Item -LiteralPath $BackupPath -Destination $InstallPath
    } catch {
        if ($movedFailedInstall -and -not (Test-Path -LiteralPath $InstallPath)) {
            Move-Item -LiteralPath $failedPath -Destination $InstallPath -ErrorAction SilentlyContinue
        }
        throw
    }

    Remove-OperationDirectory -Path $failedPath
}

function Recover-InterruptedInstallation {
    param(
        [string]$TransactionPath,
        [string]$InstallPath,
        [string]$InstallParent,
        [string]$InstallName
    )

    if (-not (Test-Path -LiteralPath $TransactionPath -PathType Leaf)) {
        return
    }

    Write-Warning "An interrupted installation was found. Recovering it before continuing."
    try {
        $transaction = Get-Content -LiteralPath $TransactionPath -Raw | ConvertFrom-Json
    } catch {
        throw "Could not read interrupted-install recovery data at $TransactionPath`: $($_.Exception.Message)"
    }

    $recordedInstall = [IO.Path]::GetFullPath([string]$transaction.InstallRoot).TrimEnd("\")
    if (-not $recordedInstall.Equals($InstallPath, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Interrupted-install recovery data targets another installation: $recordedInstall"
    }
    $stagingPath = Assert-TransactionOperationPath `
        -Candidate ([string]$transaction.StagingRoot) `
        -ExpectedParent $InstallParent `
        -ExpectedPrefix ".$InstallName.install-" `
        -Label "staging"
    $backupPath = Assert-TransactionOperationPath `
        -Candidate ([string]$transaction.BackupRoot) `
        -ExpectedParent $InstallParent `
        -ExpectedPrefix ".$InstallName.backup-" `
        -Label "backup"

    $installExists = Test-Path -LiteralPath $InstallPath -PathType Container
    $backupExists = Test-Path -LiteralPath $backupPath -PathType Container
    if ($installExists -and $backupExists) {
        try {
            Invoke-PackageSmokeTest -Root $InstallPath -Label "Interrupted update verification"
            Write-Host "Recovered a completed installation after an interrupted cleanup."
        } catch {
            Restore-PreviousInstallation `
                -InstallPath $InstallPath `
                -BackupPath $backupPath `
                -InstallName $InstallName
            Write-Host "Restored the previous installation after an interrupted update."
        }
    } elseif (-not $installExists -and $backupExists) {
        Move-Item -LiteralPath $backupPath -Destination $InstallPath
        Write-Host "Restored the previous installation after an interrupted directory swap."
    } elseif (-not $installExists) {
        Remove-OperationDirectory -Path $stagingPath
        Remove-Item -LiteralPath $TransactionPath -Force
        throw "An interrupted first installation had no previous version to restore. Run the installer again."
    }

    Remove-OperationDirectory -Path $stagingPath
    Remove-OperationDirectory -Path $backupPath
    Remove-Item -LiteralPath $TransactionPath -Force
}

function Invoke-TransactionalInstall {
    param(
        [PSCustomObject]$Paths,
        [version]$PackageVersion
    )

    if ($Paths.Source -eq $Paths.Install) {
        Invoke-PackageSmokeTest -Root $Paths.Install -Label "Installed application verification"
        return
    }

    [IO.Directory]::CreateDirectory($Paths.Parent) | Out-Null
    $transactionPath = Join-Path $Paths.Parent ".$($Paths.Name).install-transaction.json"
    Recover-InterruptedInstallation `
        -TransactionPath $transactionPath `
        -InstallPath $Paths.Install `
        -InstallParent $Paths.Parent `
        -InstallName $Paths.Name

    $operationId = [Guid]::NewGuid().ToString("N")
    $stagingRoot = Join-Path $Paths.Parent ".$($Paths.Name).install-$operationId"
    $backupRoot = Join-Path $Paths.Parent ".$($Paths.Name).backup-$operationId"
    $hadExistingInstallation = Test-Path -LiteralPath $Paths.Install -PathType Container
    $preservedExternalPaths = @()
    $swapStarted = $false
    $keepRecoveryFiles = $false

    try {
        Invoke-RobocopyMirror -Source $Paths.Source -Destination $stagingRoot
        if ($hadExistingInstallation) {
            Copy-PersistentContent -ExistingRoot $Paths.Install -StagingRoot $stagingRoot
            $preservedExternalPaths = @(
                Get-ExternalComponentPaths | Where-Object {
                    Test-Path -LiteralPath (Join-Path $Paths.Install $_)
                }
            )
            Copy-ExternalComponents -ExistingRoot $Paths.Install -StagingRoot $stagingRoot -RelativePaths $preservedExternalPaths
        }
        Invoke-PackageSmokeTest -Root $stagingRoot -Label "Staged application verification"

        Write-InstallTransaction `
            -TransactionPath $transactionPath `
            -InstallPath $Paths.Install `
            -StagingPath $stagingRoot `
            -BackupPath $backupRoot

        Assert-AppNotRunning -InstallRoot $Paths.Install
        $swapStarted = $true
        if ($hadExistingInstallation) {
            Move-Item -LiteralPath $Paths.Install -Destination $backupRoot
        }
        Move-Item -LiteralPath $stagingRoot -Destination $Paths.Install

        Assert-PreservedPaths -Root $Paths.Install -RelativePaths $preservedExternalPaths
        Invoke-PackageSmokeTest -Root $Paths.Install -Label "Installed application verification"
        $installedVersionText = (Get-Content -LiteralPath (Join-Path $Paths.Install "VERSION") -Raw).Trim()
        $installedVersion = ConvertTo-StableVersion `
            -Value $installedVersionText `
            -Label "Installed VERSION"
        if ($installedVersion -ne $PackageVersion) {
            throw "Installed VERSION $installedVersion does not match package VERSION $PackageVersion."
        }

        Remove-OperationDirectory -Path $backupRoot
        Remove-Item -LiteralPath $transactionPath -Force -ErrorAction SilentlyContinue
    } catch {
        $installError = $_
        if ($swapStarted) {
            try {
                if ($hadExistingInstallation -and (Test-Path -LiteralPath $backupRoot)) {
                    Restore-PreviousInstallation `
                        -InstallPath $Paths.Install `
                        -BackupPath $backupRoot `
                        -InstallName $Paths.Name
                } elseif (-not $hadExistingInstallation) {
                    Remove-OperationDirectory -Path $Paths.Install
                }
            } catch {
                $keepRecoveryFiles = $true
                throw "Installation failed: $($installError.Exception.Message) Automatic rollback also failed: $($_.Exception.Message) Recovery data remains at $transactionPath."
            }
        }
        throw $installError
    } finally {
        if (-not $keepRecoveryFiles) {
            Remove-OperationDirectory -Path $stagingRoot
            Remove-OperationDirectory -Path $backupRoot
            Remove-Item -LiteralPath $transactionPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function New-DesktopShortcut {
    param([string]$InstalledRoot)

    $appExecutable = Join-Path $InstalledRoot "PogledAssist.exe"
    $launcherPath = Join-Path $InstalledRoot "start_gaze_mouse.ps1"
    try {
        $desktopPath = [Environment]::GetFolderPath("Desktop")
        $shortcutPath = Join-Path $desktopPath "Pogled Assist.lnk"
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = Get-PowerShellExecutable
        $shortcut.Arguments = '-WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File "' + $launcherPath + '" -NoPause'
        $shortcut.WorkingDirectory = $InstalledRoot
        $shortcut.Description = "Launch Pogled Assist"
        $shortcut.IconLocation = "$appExecutable,0"
        $shortcut.Save()
        Write-Host "Created desktop shortcut: $shortcutPath"
    } catch {
        Write-Warning "The application was installed, but the desktop shortcut could not be updated: $($_.Exception.Message)"
    }
}

function Start-InstalledApplication {
    param([string]$InstalledRoot)

    $launcherPath = Join-Path $InstalledRoot "start_gaze_mouse.ps1"
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
        -WorkingDirectory $InstalledRoot `
        -WindowStyle Hidden | Out-Null
}

if (-not (Test-IsAdministrator) -and -not $NoElevation) {
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", (Quote-Argument $InstallerPath),
        "-InstallRoot", (Quote-Argument $InstallRoot),
        "-NoElevation"
    )
    if (-not [string]::IsNullOrWhiteSpace($ExpectedVersion)) {
        $arguments += @("-ExpectedVersion", (Quote-Argument $ExpectedVersion))
    }
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

$installerExitCode = 0
try {
    Assert-DedicatedInstallRoot
    $packageVersion = Assert-PackageLayout
    $paths = Get-InstallPaths
    Assert-AppNotRunning -InstallRoot $paths.Install
    Enter-InstallLock
    Assert-AppNotRunning -InstallRoot $paths.Install
    Invoke-TransactionalInstall -Paths $paths -PackageVersion $packageVersion

    if (-not $NoDesktopShortcut) {
        New-DesktopShortcut -InstalledRoot $paths.Install
    }

    Write-Host "Installed Pogled Assist v$($packageVersion.ToString(3)) to $($paths.Install)"
    Write-Host "Tobii software, tracker calibration, eSpeak NG, optional edge-playback, and an optional 32-bit bridge runtime are not installed by this package."
    Write-Host "See README.md in the installation folder for requirements and manual checks."

    if ($Launch) {
        Start-InstalledApplication -InstalledRoot $paths.Install
    }
} catch {
    $installerExitCode = 1
    Write-Error "Installation failed: $($_.Exception.Message)"
} finally {
    Exit-InstallLock
}

exit $installerExitCode
