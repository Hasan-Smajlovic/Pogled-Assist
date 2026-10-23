from __future__ import annotations

import sys

import pytest
from _powershell import powershell_literal, run_dev_driver

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="dev.ps1 uses Windows PowerShell")


def test_deferred_coverage_enforces_floor_on_combined_data(tmp_path):
    package = tmp_path / "pogled_assist"
    package.mkdir()
    package.joinpath("__init__.py").write_text(
        "def small():\n    return 1\n\ndef large():\n"
        + "".join(f"    value = {index}\n" for index in range(20))
        + "    return value\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        "[tool.coverage.report]\nfail_under = 60\n", encoding="utf-8"
    )
    (tmp_path / "test_partial.py").write_text(
        "from pogled_assist import small\ndef test_small():\n    assert small() == 1\n",
        encoding="utf-8",
    )
    (tmp_path / "test_remaining.py").write_text(
        "from pogled_assist import large\ndef test_large():\n    assert large() == 19\n",
        encoding="utf-8",
    )
    result = run_dev_driver(
        tmp_path,
        r"""
function Get-DevPython { return PYTHON_PATH }
$env:PYTEST_ADDOPTS = "--cov-fail-under=0"
$partial = Join-Path $PSScriptRoot "test_partial.py"
$remaining = Join-Path $PSScriptRoot "test_remaining.py"
$html = Join-Path $PSScriptRoot "dist\coverage-html\index.html"
$application = Join-Path $PSScriptRoot "application.coverage"
$infrastructure = Join-Path $PSScriptRoot "infrastructure.coverage"
$installer = Join-Path $PSScriptRoot "installer.coverage"
$combined = Join-Path $PSScriptRoot ".coverage"
$env:COVERAGE_FILE = $application
Invoke-TestSuite -Coverage Collect -Paths @($partial) -WorkerCount 1
$env:COVERAGE_FILE = $infrastructure
Invoke-TestSuite -Coverage Collect -Paths @($partial) -WorkerCount 1
if (Test-Path -LiteralPath $html) { throw "Partial HTML was generated" }
# Seed unrelated data that would incorrectly lift the floor if combine appended.
$env:COVERAGE_FILE = $combined
Invoke-TestSuite -Coverage Collect -Paths @($remaining) -WorkerCount 1
Copy-Item -LiteralPath $combined -Destination "$combined.stale"
$floorFailed = $false
try {
    Merge-CheckCoverage -Files @($application, $infrastructure)
} catch {
    if ($LASTEXITCODE -ne 2) { throw }
    $floorFailed = $true
}
if (-not $floorFailed) { throw "Combined coverage floor was bypassed" }
if (-not (Test-Path -LiteralPath $html)) { throw "Failed coverage report missing" }
$env:COVERAGE_FILE = $installer
Invoke-TestSuite -Coverage Collect -Paths @($remaining) -WorkerCount 1
$env:COVERAGE_FILE = $combined
try {
    Merge-CheckCoverage -Files @($application, (Join-Path $PSScriptRoot "missing.coverage"))
    throw "Missing group was accepted"
} catch {
    if ($_ -notlike "*Missing coverage data:*") { throw }
}
Merge-CheckCoverage -Files @($application, $infrastructure, $installer)
if (-not (Test-Path -LiteralPath $html)) { throw "Combined HTML was not generated" }
if (-not (Test-Path -LiteralPath "$combined.stale")) { throw "Stale shard was consumed" }
if ((Get-FileHash -LiteralPath $combined).Hash -ne
    (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot "combined.coverage")).Hash) {
    throw "Combined data was not published to the requested destination"
}
foreach ($file in @($application, $infrastructure, $installer)) {
    if (-not (Test-Path -LiteralPath $file)) { throw "Group data was not retained" }
}
""".replace("PYTHON_PATH", powershell_literal(sys.executable)),
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "100%" in result.stdout
