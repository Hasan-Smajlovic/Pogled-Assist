[CmdletBinding()]
param([switch]$RequireAnalyzer, [string[]]$Paths = @())

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$searchRoots = @(
    $RepoRoot,
    (Join-Path $RepoRoot "scripts"),
    (Join-Path $RepoRoot "packaging\windows")
)
$files = @(
    if ($Paths.Count -gt 0) {
        $repoPrefix = [IO.Path]::GetFullPath($RepoRoot).TrimEnd("\") + "\"
        foreach ($path in $Paths) {
            $file = Get-Item -LiteralPath (Join-Path $RepoRoot $path)
            if ($file.PSIsContainer -or $file.Extension -ne ".ps1" -or
                -not $file.FullName.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
                throw "PowerShell check path must be a script inside the repository: $path"
            }
            $file
        }
    } else {
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
    }
) | Sort-Object -Property FullName -Unique
$files = @($files)

$parseFailures = @()
$processFailures = @()
foreach ($file in $files) {
    $tokens = $null
    $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
        $file.FullName,
        [ref]$tokens,
        [ref]$parseErrors
    )

    foreach ($parseError in $parseErrors) {
        $parseFailures += "{0}:{1}:{2}: {3}" -f @(
            $file.FullName,
            $parseError.Extent.StartLineNumber,
            $parseError.Extent.StartColumnNumber,
            $parseError.Message
        )
    }

    # Start-Process defaults to ShellExecute on Windows PowerShell 5.1. Keep
    # shell semantics only for explicit UAC and the one HTML preview opener.
    $commands = $ast.FindAll({ param($node)
        $node -is [System.Management.Automation.Language.CommandAst]
    }, $true)
    foreach ($command in $commands) {
        $name = $command.GetCommandName()
        if ($null -eq $name -or ($name -split '\\')[-1] -notin @("Start-Process", "start", "saps")) {
            continue
        }
        $elements = $command.CommandElements
        $isElevation = $false
        for ($index = 1; $index -lt $elements.Count; $index++) {
            $element = $elements[$index]
            if ($element -is [System.Management.Automation.Language.CommandParameterAst] -and
                $element.ParameterName -eq "Verb") {
                $value = if ($null -ne $element.Argument) { $element.Argument } elseif ($index + 1 -lt $elements.Count) { $elements[$index + 1] }
                $isElevation = $value -is [System.Management.Automation.Language.StringConstantExpressionAst] -and $value.Value -eq "RunAs"
            }
        }
        $isGallery = $file.FullName -eq (Join-Path $RepoRoot "dev.ps1") -and
            $command.Extent.Text -ceq 'Start-Process -FilePath (Join-Path $outputRoot "index.html")'
        if (-not $isElevation -and -not $isGallery) {
            $processFailures += "{0}:{1}: Start-Process requires a reviewed shell purpose. Use ProcessStartInfo with UseShellExecute=false for executable launches." -f $file.FullName, $command.Extent.StartLineNumber
        }
    }
}

if ($parseFailures.Count -gt 0) {
    $parseFailures | ForEach-Object { Write-Error $_ }
    throw "PowerShell parsing failed for $($parseFailures.Count) error(s)."
}

if ($processFailures.Count -gt 0) {
    $processFailures | ForEach-Object { Write-Error $_ -ErrorAction Continue }
    throw "PowerShell process launch check failed with $($processFailures.Count) finding(s)."
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
