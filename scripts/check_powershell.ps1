[CmdletBinding()]
param([switch]$RequireAnalyzer)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$searchRoots = @(
    $RepoRoot,
    (Join-Path $RepoRoot "scripts"),
    (Join-Path $RepoRoot "packaging\windows")
)
$files = @(
    foreach ($root in $searchRoots) {
        if (-not (Test-Path -LiteralPath $root)) {
            continue
        }

        if ($root -eq $RepoRoot) {
            Get-ChildItem -LiteralPath $root -File -Filter "*.ps1"
        } else {
            Get-ChildItem -LiteralPath $root -File -Filter "*.ps1" -Recurse
        }
    }
) | Sort-Object -Property FullName -Unique

$parseFailures = @()
foreach ($file in $files) {
    $tokens = $null
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        $file.FullName,
        [ref]$tokens,
        [ref]$parseErrors
    ) | Out-Null

    foreach ($parseError in $parseErrors) {
        $parseFailures += "{0}:{1}:{2}: {3}" -f @(
            $file.FullName,
            $parseError.Extent.StartLineNumber,
            $parseError.Extent.StartColumnNumber,
            $parseError.Message
        )
    }
}

if ($parseFailures.Count -gt 0) {
    $parseFailures | ForEach-Object { Write-Error $_ }
    throw "PowerShell parsing failed for $($parseFailures.Count) error(s)."
}

$analyzerVersion = "1.25.0"
$localAnalyzer = Join-Path $RepoRoot ".dev-tools\PSScriptAnalyzer\$analyzerVersion\PSScriptAnalyzer.psd1"
if (Test-Path -LiteralPath $localAnalyzer -PathType Leaf) {
    Import-Module $localAnalyzer -Force
} elseif (Get-Module -ListAvailable -Name PSScriptAnalyzer) {
    Import-Module PSScriptAnalyzer -Force
}

$analyzerCommand = Get-Command Invoke-ScriptAnalyzer -ErrorAction SilentlyContinue
if ($null -eq $analyzerCommand) {
    if ($RequireAnalyzer) {
        throw "PSScriptAnalyzer $analyzerVersion is required. Run .\dev.ps1 setup."
    }
    Write-Warning "PSScriptAnalyzer is unavailable; only syntax parsing was performed."
} else {
    $settingsPath = Join-Path $RepoRoot "PSScriptAnalyzerSettings.psd1"
    $analysisFailures = @(
        foreach ($file in $files) {
            Invoke-ScriptAnalyzer -Path $file.FullName -Settings $settingsPath
        }
    )
    if ($analysisFailures.Count -gt 0) {
        $analysisFailures | ForEach-Object {
            Write-Error ("{0}:{1}:{2}: [{3}] {4}" -f @(
                $_.ScriptPath,
                $_.Line,
                $_.Column,
                $_.RuleName,
                $_.Message
            ))
        }
        throw "PSScriptAnalyzer failed with $($analysisFailures.Count) finding(s)."
    }
}

Write-Output "PowerShell checks passed for $($files.Count) script(s)."
