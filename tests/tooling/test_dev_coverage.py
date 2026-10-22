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
Invoke-TestSuite -Coverage Collect -Paths @($partial) -WorkerCount 1
if (Test-Path -LiteralPath $html) { throw "Partial HTML was generated" }
$floorFailed = $false
try {
    Invoke-TestSuite -Coverage Append -Paths @($partial) -WorkerCount 1
} catch {
    if ($LASTEXITCODE -ne 1) { throw }
    $floorFailed = $true
}
if (-not $floorFailed) { throw "Combined coverage floor was bypassed" }
if (-not (Test-Path -LiteralPath $html)) { throw "Failed coverage report missing" }
Invoke-TestSuite -Coverage Append -Paths @($remaining) -WorkerCount 1
if (-not (Test-Path -LiteralPath $html)) { throw "Combined HTML was not generated" }
""".replace("PYTHON_PATH", powershell_literal(sys.executable)),
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "100%" in result.stdout
