"""Batch independent PowerShell probes while retaining named pytest cases."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def powershell_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def run_powershell_cases(root: Path, cases: dict, *, prelude: str = "", timeout: int = 120):
    """Run bodies that throw on failure (never exit), in separate child scopes.

    Each case supplies body, optional environment overrides and cwd. Callers still
    assert production environment recovery inside the body, before driver cleanup.
    Real process/timeouts must retain their own cleanup assertions and deadlines.
    """
    manifest = []
    for name, case in cases.items():
        directory = Path(case.get("cwd", root / name))
        directory.mkdir(parents=True, exist_ok=True)
        body = root / f"{name}.ps1"
        body.write_text(case["body"], encoding="utf-8-sig")
        manifest.append(
            {"name": name, "body": str(body), "cwd": str(directory), "env": case.get("env", {})}
        )
    (root / "cases.json").write_text(json.dumps(manifest), encoding="utf-8")
    driver = root / "run-cases.ps1"
    driver.write_text(
        '$ErrorActionPreference = "Stop"\n'
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)\n"
        + prelude
        + r"""
$cases = Get-Content -LiteralPath (Join-Path $PSScriptRoot "cases.json") -Raw | ConvertFrom-Json
$results = foreach ($case in $cases) {
    $before = @{}
    Get-ChildItem Env: | ForEach-Object { $before[$_.Name] = $_.Value }
    $location = Get-Location
    $output = [System.Collections.Generic.List[string]]::new()
    $failure = ""
    try {
        Set-Location -LiteralPath $case.cwd
        foreach ($entry in $case.env.PSObject.Properties) {
            [Environment]::SetEnvironmentVariable($entry.Name, $entry.Value, "Process")
        }
        & $case.body *>&1 | ForEach-Object { $output.Add("$_") }
    } catch {
        $failure = "$_"
    } finally {
        Set-Location -LiteralPath $location.Path
        Get-ChildItem Env: | Where-Object { -not $before.ContainsKey($_.Name) } |
            ForEach-Object { [Environment]::SetEnvironmentVariable($_.Name, $null, "Process") }
        foreach ($name in $before.Keys) {
            [Environment]::SetEnvironmentVariable($name, $before[$name], "Process")
        }
    }
    [pscustomobject]@{ name = $case.name; output = $output -join "`n"; error = $failure }
}
ConvertTo-Json -InputObject @($results) -Depth 5 -Compress
""",
        encoding="utf-8-sig",
    )
    process = _run_powershell(root, driver, timeout)
    stdout, stderr = process.stdout, process.stderr
    assert process.returncode == 0, stdout + stderr
    results = json.loads(stdout.strip().splitlines()[-1])
    assert [item["name"] for item in results] == list(cases), stdout + stderr
    return {
        item["name"]: subprocess.CompletedProcess(
            process.args, int(bool(item["error"])), item["output"], item["error"]
        )
        for item in results
    }


def run_dev_driver(root: Path, body: str, *, timeout: int = 20):
    script = Path(__file__).resolve().parents[1] / "dev.ps1"
    shutil.copy2(script, root / "dev.ps1")
    driver = root / "driver.ps1"
    driver.write_text(
        '. (Join-Path $PSScriptRoot "dev.ps1") help | Out-Null\n' + body, encoding="utf-8"
    )
    return _run_powershell(root, driver, timeout)


def _run_powershell(root: Path, driver: Path, timeout: int):
    command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(driver)]
    environment = os.environ.copy()
    environment.pop("PSMODULEPATH", None)
    process = subprocess.Popen(
        command,
        cwd=root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        subprocess.run(
            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            timeout=10,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        process.communicate(timeout=5)
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def function_definitions(script: Path) -> str:
    """Load top-level functions without executing a bootstrap's entry point."""
    return r"""
Set-StrictMode -Version Latest
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    SCRIPT_PATH, [ref]$tokens, [ref]$errors
)
if ($errors.Count) { throw "Script could not be parsed" }
foreach ($statement in $ast.EndBlock.Statements) {
    if ($statement -is [System.Management.Automation.Language.FunctionDefinitionAst]) {
        . ([scriptblock]::Create($statement.Extent.Text))
    }
}
""".replace("SCRIPT_PATH", powershell_literal(script))
