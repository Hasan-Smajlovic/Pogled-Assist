from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import pogled_assist.main as main_module


def test_packaged_bridge_imports_using_only_declared_source_files(tmp_path):
    root = Path(__file__).resolve().parents[2]
    spec = root / "packaging/windows/PogledAssist.spec"
    tree = ast.parse(spec.read_text(encoding="utf-8"))
    declaration = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "datas" for target in node.targets)
    )
    sources = eval(compile(ast.Expression(declaration), str(spec), "eval"), {"repo_root": root})
    internal = tmp_path / "release with spaces/_internal"
    for source, destination in sources:
        if Path(source).suffix == ".py":
            folder = internal / destination
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, folder)
    # No repository or site-packages on sys.path: the x86 process cannot import
    # Python modules from the main executable's PyInstaller archive.
    script = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from pogled_assist.tracking import tobii_stream_engine_bridge as bridge; "
        "bridge._pointer_size = lambda: 4; "
        "sys.argv = [bridge.__file__, '--check']; raise SystemExit(bridge.main())"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", script, str(internal)],
        capture_output=True,
        text=True,
        timeout=10,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"type": "checked", "python_bits": 32}


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

    monkeypatch.delenv(main_module.PACKAGE_SMOKE_REPORT_ENV)

    def unexpected_write(*_args, **_kwargs):
        pytest.fail("Smoke diagnostics must not write a report without a requested path")

    monkeypatch.setattr(Path, "write_text", unexpected_write)
    main_module._write_package_smoke_report(["synthetic smoke result"])


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


@pytest.mark.parametrize("supported", [False, True])
def test_audio_decoder_check_requires_mp3_without_opening_a_device(monkeypatch, supported):
    from types import SimpleNamespace

    from PySide6 import QtMultimedia

    from pogled_assist.speech.bundle_check import verify_audio_decoder

    class Formats:
        Decode = "decode"
        AudioCodec = SimpleNamespace(MP3="mp3")

        def supportedAudioCodecs(self, mode):
            assert mode == "decode"
            return ["mp3"] if supported else []

    monkeypatch.setattr(QtMultimedia, "QMediaFormat", Formats)
    if supported:
        verify_audio_decoder()
    else:
        with pytest.raises(RuntimeError, match="MP3 decoder"):
            verify_audio_decoder()
