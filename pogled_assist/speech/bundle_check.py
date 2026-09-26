"""Offline verification of speech tools shipped in the Windows release."""

from __future__ import annotations

import os
import subprocess
import tempfile
import wave
from pathlib import Path


def verify_bundled_speech(root: Path) -> None:
    """Check the actual bundle, ignoring external installations and PATH tools."""
    speech = root / "speech"
    espeak = speech / "espeak-ng" / "espeak-ng.exe"
    edge = speech / "edge"
    environment = os.environ.copy()
    for key in list(environment):
        if key.casefold() == "path" or key.upper() == "ESPEAK_DATA_PATH":
            del environment[key]
    windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    environment["PATH"] = os.pathsep.join(map(str, (edge, windows / "System32", windows)))

    def run(executable: Path, *arguments: str) -> None:
        subprocess.run(
            [str(executable), *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=15,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    # Produce a WAV without playing it, checking both synthesis and the bs voice data.
    with tempfile.TemporaryDirectory(prefix="pogled-speech-check-") as temporary:
        wav = Path(temporary) / "bosnian.wav"
        run(espeak, "-v", "bs", "-w", str(wav), "Dobar dan.")
        with wave.open(str(wav), "rb") as audio:
            if audio.getnframes() == 0:
                raise ValueError("Bundled eSpeak NG produced an empty WAV")
    for name in ("edge-tts.exe", "edge-playback.exe"):
        run(edge / name, "--help")
