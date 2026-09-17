[CmdletBinding()]
param(
    [string]$InstallRoot = "C:\PogledAssist",
    [switch]$Launch,
    [switch]$NoDesktopShortcut,
    [switch]$NoPause,
    [switch]$NoElevation,
    [string]$ReleaseApiUrl = "https://api.github.com/repos/Hasan-Smajlovic/TobiiEyeTrackerTool/releases/latest"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$OfficialReleaseApiUrl = "https://api.github.com/repos/Hasan-Smajlovic/TobiiEyeTrackerTool/releases/latest"
$OfficialReleaseAssetRoot = "https://github.com/Hasan-Smajlovic/TobiiEyeTrackerTool/releases/download"
$UpdaterPath = $PSCommandPath
$script:ExitCode = 0
$script:ElevationRequested = $false
$script:TranscriptStarted = $false
$script:UpdateLogPath = $null
$script:OperationRoot = $null
$script:UpdateMutex = $null
$script:UpdateMutexAcquired = $false

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
        return $false
    }
}

function Get-PowerShellExecutable {
    $command = Get-Command "powershell.exe" -ErrorAction SilentlyContinue
    if ($null -ne $command -and -not [string]::IsNullOrWhiteSpace($command.Source)) {
        return $command.Source
    }

    $windowsPowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    if (Test-Path -LiteralPath $windowsPowerShell -PathType Leaf) {
        return $windowsPowerShell
    }

    return "powershell.exe"
}

function Quote-Argument {
    param([string]$Value)
    return '"' + $Value.Replace('"', '\"') + '"'
}

function Assert-DedicatedInstallRoot {
    $requestedRoot = [IO.Path]::GetFullPath($InstallRoot).TrimEnd("\")
    $legacyRoot = [IO.Path]::GetFullPath("C:\TobiiExec").TrimEnd("\")
    if ($requestedRoot.Equals($legacyRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "C:\TobiiExec belongs to the previous application and will not be changed. Install Pogled Assist to C:\PogledAssist or another separate folder."
    }
}

function Ensure-Administrator {
    if ($NoElevation -or (Test-IsAdministrator)) {
        return
    }

    Write-Info "Requesting Administrator access to update $InstallRoot."
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", (Quote-Argument -Value $UpdaterPath),
        "-InstallRoot", (Quote-Argument -Value $InstallRoot)
    )
    if ($Launch) {
        $arguments += "-Launch"
    }
    if ($NoDesktopShortcut) {
        $arguments += "-NoDesktopShortcut"
    }
    if ($NoPause) {
        $arguments += "-NoPause"
    }

    Start-Process `
        -FilePath (Get-PowerShellExecutable) `
        -ArgumentList ($arguments -join " ") `
        -WorkingDirectory (Split-Path -Parent $UpdaterPath) `
        -Verb RunAs | Out-Null
    $script:ElevationRequested = $true
    exit 0
}

function Enter-UpdateLock {
    $mutexName = "Global\PogledAssist.Update"
    try {
        $createdNew = $false
        $script:UpdateMutex = New-Object System.Threading.Mutex($false, $mutexName, [ref]$createdNew)
    } catch [System.UnauthorizedAccessException] {
        $mutexName = "Local\PogledAssist.Update"
        $createdNew = $false
        $script:UpdateMutex = New-Object System.Threading.Mutex($false, $mutexName, [ref]$createdNew)
    }

    try {
        $script:UpdateMutexAcquired = $script:UpdateMutex.WaitOne(0, $false)
    } catch [System.Threading.AbandonedMutexException] {
        $script:UpdateMutexAcquired = $true
    }

    if (-not $script:UpdateMutexAcquired) {
        $script:UpdateMutex.Dispose()
        $script:UpdateMutex = $null
        throw "Another Pogled Assist update is already in progress. Wait for it to finish before trying again."
    }
}

function Exit-UpdateLock {
    if ($null -eq $script:UpdateMutex) {
        return
    }

    if ($script:UpdateMutexAcquired) {
        try {
            $script:UpdateMutex.ReleaseMutex()
        } catch {
            Write-WarningLog "Could not release the updater lock cleanly: $($_.Exception.Message)"
        }
    }
    $script:UpdateMutex.Dispose()
    $script:UpdateMutex = $null
    $script:UpdateMutexAcquired = $false
}

function Start-UpdateTranscript {
    $script:OperationRoot = Join-Path `
        ([IO.Path]::GetTempPath()) `
        ("PogledAssistUpdate_{0}" -f [Guid]::NewGuid().ToString("N"))
    [IO.Directory]::CreateDirectory($script:OperationRoot) | Out-Null
    $script:UpdateLogPath = Join-Path $script:OperationRoot "update_windows.log"

    try {
        Start-Transcript -LiteralPath $script:UpdateLogPath | Out-Null
        $script:TranscriptStarted = $true
    } catch {
        Write-WarningLog "Could not start the update log: $($_.Exception.Message)"
    }
}

function Stop-UpdateTranscript {
    if (-not $script:TranscriptStarted) {
        return
    }

    try {
        Stop-Transcript | Out-Null
    } catch {
        Write-WarningLog "Could not stop the update log cleanly: $($_.Exception.Message)"
    }
    $script:TranscriptStarted = $false
}

function Save-UpdateLog {
    if (
        [string]::IsNullOrWhiteSpace($script:UpdateLogPath) -or
        -not (Test-Path -LiteralPath $script:UpdateLogPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $InstallRoot -PathType Container)
    ) {
        return
    }

    $destination = Join-Path $InstallRoot "update_windows.log"
    try {
        if (Test-Path -LiteralPath $destination -PathType Leaf) {
            Add-Content -LiteralPath $destination -Value "" -Encoding UTF8
            Get-Content -LiteralPath $script:UpdateLogPath | Add-Content -LiteralPath $destination -Encoding UTF8
        } else {
            Copy-Item -LiteralPath $script:UpdateLogPath -Destination $destination -Force
        }
    } catch {
        Write-WarningLog "Could not save the update log to $destination`: $($_.Exception.Message)"
    }
}

function Remove-OperationRoot {
    if (
        -not [string]::IsNullOrWhiteSpace($script:OperationRoot) -and
        (Test-Path -LiteralPath $script:OperationRoot)
    ) {
        try {
            Remove-Item -LiteralPath $script:OperationRoot -Recurse -Force
        } catch {
            Write-WarningLog "Could not remove temporary update files: $($_.Exception.Message)"
        }
    }
}

function Wait-BeforeExit {
    if ($NoPause) {
        return
    }

    Write-Host ""
    Read-Host "Press Enter to close this update window" | Out-Null
}

function ConvertTo-StableVersion {
    param(
        [string]$Value,
        [string]$Label
    )

    if ($Value -notmatch "^(?:v)?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$") {
        throw "$Label must be a stable Semantic Version such as 0.2.0. Found: $Value"
    }
    return [version]::new(
        [int]$Matches[1],
        [int]$Matches[2],
        [int]$Matches[3]
    )
}

function Get-InstalledRelease {
    if (-not (Test-Path -LiteralPath $InstallRoot -PathType Container)) {
        throw "No Pogled Assist installation was found at $InstallRoot. Install a release before using the updater."
    }

    $sourceMarkers = @(
        (Join-Path $InstallRoot "setup_windows.ps1"),
        (Join-Path $InstallRoot "run_gaze_mouse.py"),
        (Join-Path $InstallRoot "gaze_mouse")
    )
    $isSourceInstallation = @(
        $sourceMarkers | Where-Object { Test-Path -LiteralPath $_ }
    ).Count -eq $sourceMarkers.Count

    $versionPath = Join-Path $InstallRoot "VERSION"
    if (-not (Test-Path -LiteralPath $versionPath -PathType Leaf)) {
        if ($isSourceInstallation) {
            return [PSCustomObject]@{
                Version = $null
                DisplayVersion = "legacy source installation"
                IsSourceInstallation = $true
            }
        }
        throw "The installed VERSION file is missing. The installation is unsupported and was not changed."
    }

    $versionText = (Get-Content -LiteralPath $versionPath -Raw).Trim()
    $version = ConvertTo-StableVersion -Value $versionText -Label "Installed VERSION"
    return [PSCustomObject]@{
        Version = $version
        DisplayVersion = $version.ToString(3)
        IsSourceInstallation = $isSourceInstallation
    }
}

function Assert-AppNotRunning {
    $runningApps = @(Get-Process -Name "PogledAssist" -ErrorAction SilentlyContinue)
    if ($runningApps.Count -gt 0) {
        $processIds = ($runningApps | ForEach-Object { $_.Id }) -join ", "
        throw "Close Pogled Assist before updating. Running process IDs: $processIds"
    }

    try {
        $installPrefix = [IO.Path]::GetFullPath($InstallRoot).TrimEnd("\") + "\"
        $sourceProcesses = @(
            Get-CimInstance Win32_Process -ErrorAction Stop |
                Where-Object {
                    $_.Name -in @("python.exe", "pythonw.exe") -and
                    (
                        (-not [string]::IsNullOrWhiteSpace($_.ExecutablePath) -and
                            $_.ExecutablePath.StartsWith($installPrefix, [StringComparison]::OrdinalIgnoreCase)) -or
                        (-not [string]::IsNullOrWhiteSpace($_.CommandLine) -and
                            $_.CommandLine.IndexOf($installPrefix, [StringComparison]::OrdinalIgnoreCase) -ge 0)
                    )
                }
        )
        if ($sourceProcesses.Count -gt 0) {
            $processIds = ($sourceProcesses | ForEach-Object { $_.ProcessId }) -join ", "
            throw "Close the source-installed Pogled Assist before updating. Running process IDs: $processIds"
        }
    } catch {
        if ($_.Exception.Message -like "Close the source-installed*") {
            throw
        }
        Write-Info "Source-process detection was unavailable. The package installer will perform the final running-app check."
    }
}

function Get-LatestStableRelease {
    if (
        $ReleaseApiUrl -ne $OfficialReleaseApiUrl -and
        $env:POGLED_ASSIST_TESTING -ne "1"
    ) {
        throw "A custom release source is allowed only by the automated test suite."
    }

    [Net.ServicePointManager]::SecurityProtocol = (
        [Net.ServicePointManager]::SecurityProtocol -bor
        [Net.SecurityProtocolType]::Tls12
    )
    Write-Step "Checking the latest stable release"
    try {
        $response = Invoke-WebRequest `
            -Uri $ReleaseApiUrl `
            -Headers @{
                "Accept" = "application/vnd.github+json"
                "User-Agent" = "PogledAssistUpdater"
            } `
            -UseBasicParsing
        $metadata = $response.Content | ConvertFrom-Json
    } catch {
        throw "Could not query the latest stable release: $($_.Exception.Message)"
    }

    $requiredProperties = @("tag_name", "draft", "prerelease", "assets")
    foreach ($property in $requiredProperties) {
        if ($metadata.PSObject.Properties.Name -notcontains $property) {
            throw "Latest release metadata is missing '$property'. The installation was not changed."
        }
    }
    if ([bool]$metadata.draft -or [bool]$metadata.prerelease) {
        throw "GitHub returned a draft or prerelease instead of a stable release. The installation was not changed."
    }

    $tag = [string]$metadata.tag_name
    $version = ConvertTo-StableVersion -Value $tag -Label "Latest release tag"
    $normalizedTag = "v$($version.ToString(3))"
    if ($tag -ne $normalizedTag) {
        throw "Latest release tag must be exactly $normalizedTag. Found: $tag"
    }

    $artifactName = "PogledAssist-$normalizedTag-windows-x64.zip"
    $checksumName = "$artifactName.sha256"
    $artifactMatches = @($metadata.assets | Where-Object { $_.name -eq $artifactName })
    $checksumMatches = @($metadata.assets | Where-Object { $_.name -eq $checksumName })
    if ($artifactMatches.Count -ne 1 -or $checksumMatches.Count -ne 1) {
        throw "Stable release $normalizedTag must contain exactly one $artifactName and one $checksumName asset."
    }

    foreach ($asset in @($artifactMatches[0], $checksumMatches[0])) {
        if (
            $asset.PSObject.Properties.Name -notcontains "browser_download_url" -or
            [string]::IsNullOrWhiteSpace([string]$asset.browser_download_url)
        ) {
            throw "Stable release $normalizedTag contains an asset without a download URL."
        }
    }
    $artifactUrl = [string]$artifactMatches[0].browser_download_url
    $checksumUrl = [string]$checksumMatches[0].browser_download_url
    if ($ReleaseApiUrl -eq $OfficialReleaseApiUrl) {
        $expectedArtifactUrl = "$OfficialReleaseAssetRoot/$normalizedTag/$artifactName"
        $expectedChecksumUrl = "$OfficialReleaseAssetRoot/$normalizedTag/$checksumName"
        if ($artifactUrl -ne $expectedArtifactUrl -or $checksumUrl -ne $expectedChecksumUrl) {
            throw "Stable release assets did not point to the official Hasan-Smajlovic/TobiiEyeTrackerTool release."
        }
    }

    return [PSCustomObject]@{
        Version = $version
        Tag = $normalizedTag
        ArtifactName = $artifactName
        ArtifactUrl = $artifactUrl
        ChecksumName = $checksumName
        ChecksumUrl = $checksumUrl
    }
}

function Save-ReleaseAsset {
    param(
        [string]$Label,
        [string]$Url,
        [string]$Destination
    )

    try {
        Invoke-WebRequest `
            -Uri $Url `
            -OutFile $Destination `
            -Headers @{ "User-Agent" = "PogledAssistUpdater" } `
            -UseBasicParsing
    } catch {
        throw "Could not download $Label from $Url`: $($_.Exception.Message)"
    }
}

function Assert-ReleaseChecksum {
    param(
        [string]$ArtifactPath,
        [string]$ChecksumPath,
        [string]$ArtifactName
    )

    $checksumText = (Get-Content -LiteralPath $ChecksumPath -Raw).Trim()
    $escapedName = [regex]::Escape($ArtifactName)
    if ($checksumText -notmatch "^(?<Hash>[0-9a-fA-F]{64})\s{2}$escapedName$") {
        throw "The checksum file for $ArtifactName has an invalid format or filename."
    }

    $expectedHash = $Matches["Hash"].ToLowerInvariant()
    $actualHash = (Get-FileHash -LiteralPath $ArtifactPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedHash) {
        throw "Checksum mismatch for $ArtifactName. Expected $expectedHash but downloaded $actualHash. No application files were changed."
    }
}

function Expand-VerifiedRelease {
    param(
        [string]$ArtifactPath,
        [version]$ExpectedVersion
    )

    $extractRoot = Join-Path $script:OperationRoot "extracted"
    try {
        Expand-Archive -LiteralPath $ArtifactPath -DestinationPath $extractRoot
    } catch {
        throw "The verified release archive could not be extracted: $($_.Exception.Message)"
    }

    $packageRoot = Join-Path $extractRoot "PogledAssist"
    $requiredPaths = @(
        "PogledAssist.exe",
        "_internal",
        "install_windows.ps1",
        "start_gaze_mouse.ps1",
        "update_windows.ps1",
        "README.md",
        "VERSION"
    )
    foreach ($relativePath in $requiredPaths) {
        if (-not (Test-Path -LiteralPath (Join-Path $packageRoot $relativePath))) {
            throw "The verified release archive is incomplete. Missing: $relativePath"
        }
    }

    $packageVersionText = (Get-Content -LiteralPath (Join-Path $packageRoot "VERSION") -Raw).Trim()
    $packageVersion = ConvertTo-StableVersion -Value $packageVersionText -Label "Downloaded package VERSION"
    if ($packageVersion -ne $ExpectedVersion) {
        throw "Downloaded package VERSION $packageVersion does not match release $ExpectedVersion."
    }

    return $packageRoot
}

function Invoke-ReleaseInstaller {
    param(
        [string]$PackageRoot,
        [version]$ExpectedVersion
    )

    $installerPath = Join-Path $PackageRoot "install_windows.ps1"
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $installerPath,
        "-InstallRoot", $InstallRoot,
        "-ExpectedVersion", $ExpectedVersion.ToString(3),
        "-NoElevation"
    )
    if ($NoDesktopShortcut) {
        $arguments += "-NoDesktopShortcut"
    }
    if ($Launch) {
        $arguments += "-Launch"
    }

    Write-Step "Installing verified release v$($ExpectedVersion.ToString(3))"
    Push-Location $script:OperationRoot
    try {
        & (Get-PowerShellExecutable) @arguments
        if ($LASTEXITCODE -ne 0) {
            throw "The release installer failed with exit code $LASTEXITCODE."
        }
    } finally {
        Pop-Location
    }
}

function Invoke-ReleaseUpdate {
    Assert-AppNotRunning
    $installed = Get-InstalledRelease
    Write-Info "Installed version: $($installed.DisplayVersion)"

    $release = Get-LatestStableRelease
    Write-Info "Latest stable release: $($release.Tag)"

    if (
        -not $installed.IsSourceInstallation -and
        $null -ne $installed.Version -and
        $installed.Version -eq $release.Version
    ) {
        Write-Success "Pogled Assist v$($installed.Version.ToString(3)) is already up to date."
        return
    }
    if (
        $null -ne $installed.Version -and
        $installed.Version -gt $release.Version
    ) {
        throw "Installed VERSION $($installed.Version.ToString(3)) is newer than latest stable release $($release.Version.ToString(3)). Automatic downgrade is not supported."
    }
    if ($installed.IsSourceInstallation) {
        Write-Info "Migrating the existing source installation to the stable release channel."
    }

    Write-Step "Downloading release assets"
    $artifactPath = Join-Path $script:OperationRoot $release.ArtifactName
    $checksumPath = Join-Path $script:OperationRoot $release.ChecksumName
    Save-ReleaseAsset -Label $release.ArtifactName -Url $release.ArtifactUrl -Destination $artifactPath
    Save-ReleaseAsset -Label $release.ChecksumName -Url $release.ChecksumUrl -Destination $checksumPath

    Write-Step "Verifying release checksum"
    Assert-ReleaseChecksum `
        -ArtifactPath $artifactPath `
        -ChecksumPath $checksumPath `
        -ArtifactName $release.ArtifactName
    Write-Success "Release checksum is valid."

    Write-Step "Inspecting verified release"
    $packageRoot = Expand-VerifiedRelease `
        -ArtifactPath $artifactPath `
        -ExpectedVersion $release.Version
    Invoke-ReleaseInstaller -PackageRoot $packageRoot -ExpectedVersion $release.Version

    $installedVersionText = (Get-Content -LiteralPath (Join-Path $InstallRoot "VERSION") -Raw).Trim()
    $installedVersion = ConvertTo-StableVersion -Value $installedVersionText -Label "Updated VERSION"
    if ($installedVersion -ne $release.Version) {
        throw "Update verification failed. Installed VERSION $installedVersion does not match $($release.Version)."
    }

    Write-Success "Pogled Assist was updated to v$($release.Version.ToString(3))."
}

try {
    if ($env:OS -ne "Windows_NT") {
        throw "The Pogled Assist updater can run only on Windows."
    }

    Assert-DedicatedInstallRoot
    Ensure-Administrator
    Enter-UpdateLock
    Start-UpdateTranscript
    Write-Step "Starting Pogled Assist release update"
    Write-Info "Install folder: $InstallRoot"
    Invoke-ReleaseUpdate
} catch {
    $script:ExitCode = 1
    Write-Host ""
    Write-ErrorLog "Update failed: $($_.Exception.Message)"
} finally {
    if ($script:ElevationRequested) {
        exit 0
    }

    Stop-UpdateTranscript
    Save-UpdateLog
    Remove-OperationRoot
    Exit-UpdateLock
    Wait-BeforeExit
    exit $script:ExitCode
}
