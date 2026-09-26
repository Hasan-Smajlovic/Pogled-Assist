import sys
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata


repo_root = Path(SPEC).resolve().parents[2]
analysis = Analysis(
    [str(repo_root / "packaging/windows/speech_cli.py")],
    pathex=[str(repo_root)],
    datas=[
        *copy_metadata("edge-tts", recursive=True),
        (str(Path(sys.base_prefix) / "LICENSE.txt"), "licenses/python"),
    ],
    hiddenimports=["edge_playback.win32_playback"],
    excludes=["PySide6", "tobiiresearch"],
)
archive = PYZ(analysis.pure)
executables = [
    EXE(
        archive,
        analysis.scripts,
        [],
        exclude_binaries=True,
        name=name,
        console=True,
    )
    for name in ("edge-playback", "edge-tts")
]
bundle = COLLECT(
    *executables,
    analysis.binaries,
    analysis.datas,
    name="edge",
)
