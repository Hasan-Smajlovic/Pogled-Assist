"""Speech synthesis through eSpeak NG."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path


logger = logging.getLogger(__name__)

BOSNIAN_LANGUAGE = "bs"


@dataclass
class SpeechSettings:
    language: str = BOSNIAN_LANGUAGE
    speed: int = 155
    pitch: int = 50
    amplitude: int = 120
    letters_per_group: int = 5


class SpeechService:
    """Small Python wrapper around the eSpeak NG command-line tool."""

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._executable = find_espeak_ng()
        self._settings = SpeechSettings()

    @property
    def executable(self) -> Path | None:
        return self._executable

    @property
    def available(self) -> bool:
        return self._executable is not None

    @property
    def settings(self) -> SpeechSettings:
        return replace(self._settings)

    def update_settings(self, settings: SpeechSettings) -> None:
        self._settings = replace(settings)
        logger.info("Speech settings updated: %s", self._settings)

    def refresh(self) -> None:
        self._executable = find_espeak_ng()

    def speak(self, text: str, settings: SpeechSettings | None = None) -> bool:
        settings = replace(settings) if settings is not None else self.settings
        text = text.strip()
        if not text:
            logger.warning("Speech request skipped because text is empty.")
            return False

        if self._executable is None:
            self.refresh()

        if self._executable is None:
            logger.error("Speech request failed because espeak-ng was not found.")
            return False

        self.stop()

        command = [
            str(self._executable),
            "-v",
            settings.language,
            "-s",
            str(settings.speed),
            "-p",
            str(settings.pitch),
            "-a",
            str(settings.amplitude),
            text,
        ]
        logger.info("Starting speech command: %s", command[:-1] + ["<text>"])

        startupinfo = None
        creationflags = 0
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo,
                creationflags=creationflags,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except Exception:
            logger.exception("Failed to start espeak-ng.")
            self._process = None
            return False

        return True

    def stop(self) -> None:
        if self._process is None:
            return

        if self._process.poll() is not None:
            self._log_process_error()
            self._process = None
            return

        logger.info("Stopping active speech process.")
        self._process.terminate()
        try:
            self._process.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            logger.warning("Speech process did not exit after terminate; killing it.")
            self._process.kill()
            self._process.wait(timeout=1.5)
        finally:
            self._log_process_error()
            self._process = None

    def _log_process_error(self) -> None:
        if self._process is None or self._process.stderr is None:
            return

        try:
            stderr = self._process.stderr.read()
        except Exception:
            return

        if stderr.strip():
            logger.warning("espeak-ng stderr: %s", stderr.strip())


def find_espeak_ng() -> Path | None:
    candidates = list(_candidate_paths())
    for candidate in candidates:
        if _is_valid_espeak_ng(candidate):
            logger.info("Found espeak-ng executable: %s", candidate)
            return candidate

    logger.warning("espeak-ng executable was not found.")
    return None


def _candidate_paths() -> list[Path]:
    candidates: list[Path] = []

    env_path = os.environ.get("ESPEAK_NG_EXE", "").strip()
    if env_path:
        candidates.append(Path(env_path))

    path_match = shutil.which("espeak-ng") or shutil.which("espeak-ng.exe")
    if path_match:
        candidates.append(Path(path_match))

    project_root = Path(__file__).resolve().parents[1]
    tools_root = project_root / "tools" / "espeak-ng"
    if tools_root.exists():
        candidates.extend(sorted(tools_root.rglob("espeak-ng.exe")))

    if sys.platform == "win32":
        for env_name in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData"):
            base = os.environ.get(env_name)
            if not base:
                continue

            root = Path(base)
            candidates.extend(
                [
                    root / "eSpeak NG" / "espeak-ng.exe",
                    root / "eSpeak NG" / "command_line" / "espeak-ng.exe",
                    root / "eSpeak NG" / "bin" / "espeak-ng.exe",
                    root / "Programs" / "eSpeak NG" / "espeak-ng.exe",
                    root / "Programs" / "eSpeak NG" / "command_line" / "espeak-ng.exe",
                ]
            )

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).lower()
        if key not in seen:
            seen.add(key)
            deduped.append(candidate)

    return deduped


def _is_valid_espeak_ng(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False

    try:
        result = subprocess.run(
            [str(path), "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
    except Exception:
        logger.exception("Failed while validating espeak-ng candidate: %s", path)
        return False

    if result.returncode != 0:
        return False

    if _has_bosnian_voice(path):
        return True

    logger.warning("espeak-ng candidate does not report Bosnian voice support: %s", path)
    return False


def _has_bosnian_voice(path: Path) -> bool:
    for arguments in ([f"--voices={BOSNIAN_LANGUAGE}"], ["--voices"]):
        try:
            result = subprocess.run(
                [str(path), *arguments],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=5,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except Exception:
            logger.exception("Failed while checking eSpeak NG voices: %s", path)
            return False

        output = "\n".join([result.stdout, result.stderr])
        if result.returncode == 0 and _voice_output_mentions_bosnian(output):
            return True

    return False


def _voice_output_mentions_bosnian(output: str) -> bool:
    return re.search(r"(?im)(^|\s)(bs|bosnian)(\s|$)", output) is not None
