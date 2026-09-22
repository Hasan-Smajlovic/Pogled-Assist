"""Application icon helpers."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon

from .logging_setup import get_project_root

APP_ICON_RELATIVE_PATH = Path("assets") / "icon.png"


def app_icon_path() -> Path | None:
    """Return the first available application icon path."""

    candidates = [
        get_project_root() / APP_ICON_RELATIVE_PATH,
        Path(__file__).resolve().parents[1] / APP_ICON_RELATIVE_PATH,
    ]

    if getattr(sys, "frozen", False):
        candidates.insert(0, Path(sys.executable).resolve().parent / APP_ICON_RELATIVE_PATH)
        bundle_root = getattr(sys, "_MEIPASS", "")
        if bundle_root:
            candidates.insert(0, Path(bundle_root) / APP_ICON_RELATIVE_PATH)

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return None


def load_app_icon() -> QIcon:
    """Load the application icon, returning an empty icon if the asset is missing."""

    path = app_icon_path()
    if path is None:
        return QIcon()
    return QIcon(str(path))
