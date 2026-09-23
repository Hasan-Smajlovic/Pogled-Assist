[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PackageRoot,
    [Parameter(Mandatory = $true)]
    [string]$ArtifactPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

for ($attempt = 1; $attempt -le 6; $attempt++) {
    if (Test-Path -LiteralPath $ArtifactPath) {
        Remove-Item -LiteralPath $ArtifactPath -Force
    }

    try {
        Compress-Archive `
            -LiteralPath $PackageRoot `
            -DestinationPath $ArtifactPath `
            -CompressionLevel Optimal `
            -ErrorAction Stop
        return
    } catch [System.IO.IOException] {
        if ($attempt -eq 6) {
            throw
        }
        Write-Warning "Package file was busy during archive attempt $attempt; retrying in 2 seconds."
        Start-Sleep -Seconds 2
    }
}
