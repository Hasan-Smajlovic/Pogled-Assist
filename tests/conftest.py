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
def isolate_elevenlabs_credentials_and_cache(monkeypatch, tmp_path):
    from _speech_fakes import FakeCredentials

    from pogled_assist.speech.elevenlabs import ENV_OVERRIDES

    monkeypatch.setattr(
        "pogled_assist.speech.eleven_account.WindowsCredentialStore", FakeCredentials
    )
    monkeypatch.setattr(
        "pogled_assist.speech.speech_service.cache_root", lambda: tmp_path / "speech-audio"
    )
    for name in ENV_OVERRIDES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def close_top_level_widgets(qapp) -> Iterator[None]:
    from PySide6.QtCore import QEvent

    yield
    for widget in qapp.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()
