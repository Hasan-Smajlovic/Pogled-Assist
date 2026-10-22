[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$version = "1.25.0"
$toolRoot = Join-Path $repoRoot ".dev-tools"
$manifest = Join-Path $toolRoot "PSScriptAnalyzer\$version\PSScriptAnalyzer.psd1"
if (Test-Path -LiteralPath $manifest -PathType Leaf) {
    return
}

if ($null -eq (Get-PSRepository -Name PSGallery -ErrorAction SilentlyContinue)) {
    Register-PSRepository -Default -ErrorAction Stop
}

New-Item -ItemType Directory -Path $toolRoot -Force | Out-Null
Save-Module `
    -Name PSScriptAnalyzer `
    -RequiredVersion $version `
    -Path $toolRoot `
    -Repository PSGallery `
    -Force `
    -ErrorAction Stop
