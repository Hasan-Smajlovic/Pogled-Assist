[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [int]$ExitCode,
    [Parameter(Mandatory = $true)]
    [string]$InstallerOutput
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($ExitCode -eq 0) {
    throw "Installer did not reject a running source application."
}

if (($InstallerOutput -replace "\s", "") -notlike "*ClosePogledAssistbeforeinstalling*") {
    throw "Installer failed for an unexpected reason while the source application was running."
}
