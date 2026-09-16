[CmdletBinding()]
param([switch]$Install)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Version = "1.7.12"
$ToolRoot = Join-Path $RepoRoot ".dev-tools\actionlint\$Version"
$ToolPath = Join-Path $ToolRoot "actionlint.exe"

function Install-Actionlint {
    $assetName = "actionlint_${Version}_windows_amd64.zip"
    $checksumName = "actionlint_${Version}_checksums.txt"
    $releaseRoot = "https://github.com/rhysd/actionlint/releases/download/v$Version"
    $tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd("\")
    $tempRoot = Join-Path $tempBase ("TobiiGazeMouseActionlint_{0}" -f [Guid]::NewGuid().ToString("N"))

    try {
        New-Item -ItemType Directory -Path $tempRoot | Out-Null
        $archivePath = Join-Path $tempRoot $assetName
        $checksumPath = Join-Path $tempRoot $checksumName
        Invoke-WebRequest -Uri "$releaseRoot/$assetName" -OutFile $archivePath -UseBasicParsing
        Invoke-WebRequest -Uri "$releaseRoot/$checksumName" -OutFile $checksumPath -UseBasicParsing

        $escapedAssetName = [Regex]::Escape($assetName)
        $checksumLine = Get-Content -LiteralPath $checksumPath |
            Where-Object { $_ -match "^[0-9a-fA-F]{64}\s+$escapedAssetName$" } |
            Select-Object -First 1
        if ([string]::IsNullOrWhiteSpace($checksumLine)) {
            throw "The actionlint checksum file does not contain $assetName."
        }

        $expectedHash = ($checksumLine -split "\s+", 2)[0]
        $actualHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash
        if ($actualHash -ne $expectedHash) {
            throw "The actionlint archive checksum does not match."
        }

        New-Item -ItemType Directory -Path $ToolRoot -Force | Out-Null
        Expand-Archive -LiteralPath $archivePath -DestinationPath $ToolRoot -Force
    } finally {
        $resolvedTempRoot = [IO.Path]::GetFullPath($tempRoot)
        if ($resolvedTempRoot.StartsWith($tempBase + "\", [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $resolvedTempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

if (-not (Test-Path -LiteralPath $ToolPath -PathType Leaf)) {
    if (-not $Install) {
        throw "actionlint $Version is required. Run .\dev.ps1 setup."
    }
    Install-Actionlint
}

& $ToolPath -color `
    (Join-Path $RepoRoot ".github\workflows\ci.yml") `
    (Join-Path $RepoRoot ".github\workflows\release.yml")
if ($LASTEXITCODE -ne 0) {
    throw "actionlint failed with exit code $LASTEXITCODE."
}

Write-Output "GitHub Actions checks passed."
