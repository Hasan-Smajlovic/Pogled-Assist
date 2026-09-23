[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ArtifactPath,
    [string]$Repository = $env:GITHUB_REPOSITORY,
    [string]$CommitSha = $env:GITHUB_SHA
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-NativeCommand {
    param(
        [string]$Command,
        [string[]]$Arguments
    )

    # Windows PowerShell turns native stderr into a terminating error while
    # ErrorActionPreference is Stop. gh writes "release not found" there when
    # this version has not been published yet.
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $exitCode = 1
    $output = @()
    try {
        $output = @(& $Command @Arguments 2>&1)
        if (Test-Path -Path "variable:LASTEXITCODE") {
            $exitCode = $LASTEXITCODE
        }
        $output = @($output | ForEach-Object { "$_" })
    } catch {
        $output = @("$_")
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    return [PSCustomObject]@{
        ExitCode = $exitCode
        Output = @($output)
    }
}

function Invoke-CheckedCommand {
    param(
        [string]$Command,
        [string[]]$Arguments
    )

    $result = Invoke-NativeCommand -Command $Command -Arguments $Arguments
    if ($result.ExitCode -ne 0) {
        throw "$Command failed with exit code $($result.ExitCode): $($result.Output -join [Environment]::NewLine)"
    }
    return @($result.Output)
}

if ([string]::IsNullOrWhiteSpace($Repository)) {
    throw "Repository is required. Set GITHUB_REPOSITORY or pass -Repository."
}
if ($CommitSha -notmatch "^[0-9a-fA-F]{40}$") {
    throw "CommitSha must be a full 40-character commit SHA. Found: $CommitSha"
}

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Version = (Get-Content -LiteralPath (Join-Path $RepoRoot "VERSION") -Raw).Trim()
if ($Version -notmatch "^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$") {
    throw "VERSION must contain a stable Semantic Version. Found: $Version"
}

$Tag = "v$Version"
$ResolvedArtifactPath = (Resolve-Path -LiteralPath $ArtifactPath).Path
$Artifact = Get-Item -LiteralPath $ResolvedArtifactPath
$ExpectedArtifactName = "PogledAssist-$Tag-windows-x64.zip"
if ($Artifact.Name -ne $ExpectedArtifactName) {
    throw "Artifact name must be $ExpectedArtifactName. Found: $($Artifact.Name)"
}

$ChecksumPath = "$ResolvedArtifactPath.sha256"
$Hash = (Get-FileHash -LiteralPath $ResolvedArtifactPath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath $ChecksumPath -Value "$Hash  $($Artifact.Name)" -Encoding ascii
$ChecksumName = [IO.Path]::GetFileName($ChecksumPath)

$remoteTag = Invoke-NativeCommand -Command "git" -Arguments @(
    "ls-remote", "--tags", "origin", "refs/tags/$Tag", "refs/tags/$Tag^{}"
)
if ($remoteTag.ExitCode -ne 0) {
    throw "Could not inspect remote tag $Tag`: $($remoteTag.Output -join [Environment]::NewLine)"
}
$remoteTagLines = $remoteTag.Output

$remoteTagSha = $null
foreach ($line in $remoteTagLines) {
    if ($line -match "^([0-9a-fA-F]{40})\s+refs/tags/.+\^\{\}$") {
        $remoteTagSha = $Matches[1]
        break
    }
    if ($line -match "^([0-9a-fA-F]{40})\s+refs/tags/.+$") {
        $remoteTagSha = $Matches[1]
    }
}

if ($null -ne $remoteTagSha -and $remoteTagSha.ToLowerInvariant() -ne $CommitSha.ToLowerInvariant()) {
    throw "Immutable tag $Tag already points to $remoteTagSha instead of $CommitSha. Bump VERSION before releasing another master commit."
}

$releaseView = Invoke-NativeCommand -Command "gh" -Arguments @(
    "release", "view", $Tag,
    "--repo", $Repository,
    "--json", "isDraft,targetCommitish,assets"
)
$releaseExists = $releaseView.ExitCode -eq 0
$release = if ($releaseExists) {
    ($releaseView.Output -join [Environment]::NewLine) | ConvertFrom-Json
} else {
    $null
}

if ($releaseExists -and -not $release.isDraft) {
    if ($null -eq $remoteTagSha) {
        throw "Published release $Tag has no remote tag."
    }
    $assetNames = @($release.assets | ForEach-Object { $_.name })
    foreach ($requiredAsset in @($Artifact.Name, $ChecksumName)) {
        if ($assetNames -notcontains $requiredAsset) {
            throw "Published release $Tag is missing required asset $requiredAsset and will not be mutated."
        }
    }
    Write-Host "Release $Tag already exists for this commit with both assets. Nothing to publish."
    exit 0
}

if (
    $releaseExists -and
    $release.isDraft -and
    $null -eq $remoteTagSha
) {
    $draftTarget = [string]$release.targetCommitish
    if (
        [string]::IsNullOrWhiteSpace($draftTarget) -or
        $draftTarget.ToLowerInvariant() -ne $CommitSha.ToLowerInvariant()
    ) {
        throw "Draft release $Tag targets $draftTarget instead of $CommitSha."
    }
}

if ($releaseExists) {
    Invoke-CheckedCommand -Command "gh" -Arguments @(
        "release", "upload", $Tag,
        $ResolvedArtifactPath, $ChecksumPath,
        "--repo", $Repository,
        "--clobber"
    ) | Out-Null
} else {
    $createArguments = @(
        "release", "create", $Tag,
        $ResolvedArtifactPath, $ChecksumPath,
        "--repo", $Repository,
        "--title", "Pogled Assist $Tag",
        "--generate-notes",
        "--draft"
    )
    if ($null -eq $remoteTagSha) {
        $createArguments += @("--target", $CommitSha)
    } else {
        $createArguments += "--verify-tag"
    }
    Invoke-CheckedCommand -Command "gh" -Arguments $createArguments | Out-Null
}

$readyRelease = (
    Invoke-CheckedCommand -Command "gh" -Arguments @(
        "release", "view", $Tag,
        "--repo", $Repository,
        "--json", "isDraft,assets"
    ) -join [Environment]::NewLine
) | ConvertFrom-Json
$readyAssetNames = @($readyRelease.assets | ForEach-Object { $_.name })
foreach ($requiredAsset in @($Artifact.Name, $ChecksumName)) {
    if ($readyAssetNames -notcontains $requiredAsset) {
        throw "Draft release $Tag is missing required asset $requiredAsset and will not be published."
    }
}

if ($readyRelease.isDraft) {
    Invoke-CheckedCommand -Command "gh" -Arguments @(
        "release", "edit", $Tag,
        "--repo", $Repository,
        "--draft=false"
    ) | Out-Null
}

$verifiedTagLines = Invoke-CheckedCommand -Command "git" -Arguments @(
    "ls-remote", "--tags", "origin", "refs/tags/$Tag", "refs/tags/$Tag^{}"
)
$verifiedTagSha = $null
foreach ($line in $verifiedTagLines) {
    if ($line -match "^([0-9a-fA-F]{40})\s+refs/tags/.+\^\{\}$") {
        $verifiedTagSha = $Matches[1]
        break
    }
    if ($line -match "^([0-9a-fA-F]{40})\s+refs/tags/.+$") {
        $verifiedTagSha = $Matches[1]
    }
}
if ($null -eq $verifiedTagSha -or $verifiedTagSha.ToLowerInvariant() -ne $CommitSha.ToLowerInvariant()) {
    throw "Published tag $Tag does not resolve to the merged commit $CommitSha."
}

$verifiedRelease = (
    Invoke-CheckedCommand -Command "gh" -Arguments @(
        "release", "view", $Tag,
        "--repo", $Repository,
        "--json", "isDraft,assets"
    ) -join [Environment]::NewLine
) | ConvertFrom-Json
if ($verifiedRelease.isDraft) {
    throw "Release $Tag is still a draft after publication."
}
$verifiedAssetNames = @($verifiedRelease.assets | ForEach-Object { $_.name })
foreach ($requiredAsset in @($Artifact.Name, $ChecksumName)) {
    if ($verifiedAssetNames -notcontains $requiredAsset) {
        throw "Published release $Tag is missing required asset $requiredAsset."
    }
}

Write-Host "Published immutable release $Tag for commit $CommitSha."
