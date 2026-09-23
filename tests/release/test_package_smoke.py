from __future__ import annotations

from pathlib import Path

import pogled_assist.main as main_module


def test_package_smoke_loads_the_bundled_suggestion_model(monkeypatch, tmp_path):
    report = tmp_path / "smoke.txt"
    monkeypatch.setenv(main_module.PACKAGE_SMOKE_REPORT_ENV, str(report))

    assert main_module.package_smoke_test() == 0
    contents = report.read_text(encoding="utf-8")
    assert "suggestions_loaded=True" in contents
    assert "bosnian-model.json.gz exists=True" in contents
    assert "bosnian-model.meta.json exists=True" in contents
    assert "bosnian-islamic-model.json.gz exists=True" in contents
    assert "bosnian-islamic-model.meta.json exists=True" in contents


def test_windows_package_declares_the_bundled_suggestion_files():
    root = Path(__file__).resolve().parents[2]
    spec = (root / "packaging" / "windows" / "PogledAssist.spec").read_text(encoding="utf-8")
    build = (root / "scripts" / "release" / "build_windows_package.ps1").read_text(encoding="utf-8")

    for name in (
        "bosnian-model.json.gz",
        "bosnian-model.meta.json",
        "bosnian-islamic-model.json.gz",
        "bosnian-islamic-model.meta.json",
    ):
        assert name in spec
        assert name in build


def test_source_tree_passes_package_smoke_test():
    assert main_module.package_smoke_test() == 0
