[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$version = "1.25.0"
$expectedHash = "14e634c828eb98efb9f40b2918ba90f139ed5eccdf663a2a747736d996995d60"
$toolRoot = Join-Path $repoRoot ".dev-tools\PSScriptAnalyzer"
$moduleRoot = Join-Path $toolRoot $version

function Test-AnalyzerModule {
    param([string]$Path)

    $manifest = Join-Path $Path "PSScriptAnalyzer.psd1"
    if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) {
        return $false
    }
    try {
        $module = Test-ModuleManifest -Path $manifest -ErrorAction Stop
        return $module.Version -eq [version]$version
    } catch {
        Write-Verbose "Analyzer cache is incomplete: $($_.Exception.Message)"
        return $false
    }
}

if (Test-AnalyzerModule -Path $moduleRoot) {
    return
}

New-Item -ItemType Directory -Path $toolRoot -Force | Out-Null
$staging = Join-Path $toolRoot (".download-{0}" -f [Guid]::NewGuid().ToString("N"))
try {
    New-Item -ItemType Directory -Path $staging | Out-Null
    $archive = Join-Path $staging "analyzer.zip"
    $uri = "https://github.com/PowerShell/PSScriptAnalyzer/releases/download/$version/PSScriptAnalyzer.$version.nupkg"
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Invoke-WebRequest -Uri $uri -OutFile $archive -UseBasicParsing -TimeoutSec 30
            break
        } catch {
            if ($attempt -eq 3) {
                throw "Could not download PSScriptAnalyzer $version after 3 attempts: $($_.Exception.Message)"
            }
            Write-Warning "Analyzer download attempt $attempt failed; retrying."
            Start-Sleep -Seconds ([Math]::Pow(2, $attempt))
        }
    }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expectedHash) {
        throw "PSScriptAnalyzer $version archive checksum does not match."
    }
    $expanded = Join-Path $staging "module"
    Expand-Archive -LiteralPath $archive -DestinationPath $expanded
    if (-not (Test-AnalyzerModule -Path $expanded)) {
        throw "PSScriptAnalyzer $version archive does not contain a valid module."
    }
    if (Test-Path -LiteralPath $moduleRoot) {
        Remove-Item -LiteralPath $moduleRoot -Recurse -Force
    }
    Move-Item -LiteralPath $expanded -Destination $moduleRoot
} finally {
    Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
}
