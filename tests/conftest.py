from __future__ import annotations

import os
import sys
from collections.abc import Iterator

import pytest

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.dont_write_bytecode = True


@pytest.fixture(autouse=True)
def close_top_level_widgets(qapp) -> Iterator[None]:
    yield
    for widget in qapp.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    qapp.processEvents()
