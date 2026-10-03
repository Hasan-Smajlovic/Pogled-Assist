from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Windows' offscreen Qt plugin does not discover system fonts automatically.
# Use the target platform's installed fonts for shaping and layout assertions.
if sys.platform == "win32":
    font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    if font_directory.is_dir():
        os.environ.setdefault("QT_QPA_FONTDIR", str(font_directory))
sys.dont_write_bytecode = True


@pytest.fixture(autouse=True)
def close_top_level_widgets(qapp) -> Iterator[None]:
    yield
    for widget in qapp.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    qapp.processEvents()
