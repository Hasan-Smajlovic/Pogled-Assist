"""Speech synthesis through configured command-line speech engines."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event, Lock, Thread

from PySide6.QtCore import QObject, Qt, Signal, Slot

from ..keyboard_layouts import ARABIC_SCRIPT, LATIN_SCRIPT
from ..tracking.tobii_stream_engine import APP_ROOT_ENV
from ..windows.speech_process import start_speech_process

logger = logging.getLogger(__name__)

BOSNIAN_LANGUAGE = "bs"
VOICE_PRESET_DEFAULT = "default"
VOICE_PRESET_HUMAN_LIKE = "human_like"
VOICE_PRESETS: tuple[tuple[str, str], ...] = (
    (VOICE_PRESET_DEFAULT, "Standardni"),
    (VOICE_PRESET_HUMAN_LIKE, "Prirodni"),
)
VOICE_PRESET_LABELS = dict(VOICE_PRESETS)
EDGE_PLAYBACK_VOICE = "bs-BA-GoranNeural"
ARABIC_EDGE_PLAYBACK_VOICE = "ar-SA-HamedNeural"
EDGE_PLAYBACK_RATE = "-10%"
EDGE_PLAYBACK_PITCH = "-2Hz"


@dataclass
class SpeechSettings:
    language: str = BOSNIAN_LANGUAGE
    speed: int = 155
    pitch: int = 50
    amplitude: int = 120
    letters_per_group: int = 5
    voice_preset: str = VOICE_PRESET_DEFAULT
    keyboard_script: str = LATIN_SCRIPT


class SpeechService(QObject):
    """Small Python wrapper around the configured speech command-line tools."""

    playback_changed = Signal(int, str)
    _worker_state = Signal(int, str)

    def __init__(self) -> None:
        super().__init__()
        self.request_id = 0
        self._cancel: Event | None = None
        self._process_lock = Lock()
        self._worker_state.connect(self._deliver_state, Qt.QueuedConnection)
        self._executable = find_espeak_ng()
        self._edge_playback_executable = find_edge_playback()
        self._settings = SpeechSettings()

    @property
    def executable(self) -> Path | None:
        return self._executable

    @property
    def edge_playback_executable(self) -> Path | None:
        return self._edge_playback_executable

    @property
    def available(self) -> bool:
        return self._executable is not None or self._edge_playback_executable is not None

    @property
    def settings(self) -> SpeechSettings:
        return replace(self._settings)

    def update_settings(self, settings: SpeechSettings) -> None:
        self._settings = replace(settings)
        logger.info("Speech settings updated: %s", self._settings)

    def refresh(self) -> None:
        self._executable = find_espeak_ng()
        self._edge_playback_executable = find_edge_playback()

    def speak(self, text: str, settings: SpeechSettings | None = None) -> bool:
        settings = replace(settings) if settings is not None else self.settings
        text = text.strip()
        if not text:
            logger.warning("Speech request skipped because text is empty.")
            return False

        if settings.keyboard_script == ARABIC_SCRIPT:
            return self._speak_edge_playback(text, voice=ARABIC_EDGE_PLAYBACK_VOICE)
        if settings.voice_preset == VOICE_PRESET_HUMAN_LIKE:
            return self._speak_edge_playback(text)

        return self._speak_espeak(text, settings)

    def _speak_espeak(self, text: str, settings: SpeechSettings) -> bool:
        command = [
            str(self._executable) if self._executable is not None else "",
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
        environment = (
            _espeak_environment(self._executable) if self._executable is not None else None
        )
        if environment is not None:
            return self._start_process(command, "espeak-ng", environment=environment)
        return self._start_process(command, "espeak-ng")

    def _speak_edge_playback(self, text: str, *, voice: str = EDGE_PLAYBACK_VOICE) -> bool:
        command = [
            str(self._edge_playback_executable)
            if self._edge_playback_executable is not None
            else "",
            "--voice",
            voice,
            f"--rate={EDGE_PLAYBACK_RATE}",
            f"--pitch={EDGE_PLAYBACK_PITCH}",
            "--text",
            text,
        ]
        environment = (
            _environment_with_executable_directory(self._edge_playback_executable)
            if self._edge_playback_executable is not None
            else None
        )
        return self._start_process(command, "edge-playback", environment=environment)

    def _start_process(
        self,
        command: list[str],
        engine_name: str,
        *,
        environment: dict[str, str] | None = None,
    ) -> bool:
        logger.info("Starting speech command (%s): %s", engine_name, [*command[:-1], "<text>"])

        self.stop()
        self.request_id += 1
        request_id = self.request_id
        cancel = Event()
        self._cancel = cancel
        worker = Thread(
            target=self._run_process,
            args=(request_id, cancel, command, engine_name, environment),
            name="speech-playback",
            daemon=True,
        )
        try:
            worker.start()
        except RuntimeError:
            self._cancel = None
            logger.error("Could not start speech worker.")
            return False
        return True

    def _run_process(
        self,
        request_id: int,
        cancel: Event,
        command: list[str],
        engine_name: str,
        environment: dict[str, str] | None,
    ) -> None:
        # Serialize replacement: the previous process tree is closed before a
        # new voice can start. Queued requests cancelled meanwhile never launch.
        with self._process_lock:
            if cancel.is_set():
                return
            process = None
            state = "failed"
            try:
                if not command[0]:
                    if engine_name == "espeak-ng":
                        self._executable = executable = find_espeak_ng()
                        environment = _espeak_environment(executable) if executable else None
                    else:
                        self._edge_playback_executable = executable = find_edge_playback()
                        environment = (
                            _environment_with_executable_directory(executable)
                            if executable
                            else None
                        )
                    if cancel.is_set():
                        return
                    if executable is None:
                        logger.error("Speech engine was not found: %s.", engine_name)
                        self._worker_state.emit(request_id, "failed")
                        return
                    command[0] = str(executable)
                process = start_speech_process(command, environment)
                if not cancel.is_set():
                    self._worker_state.emit(request_id, "speaking")
                while not cancel.is_set():
                    exit_code = process.poll()
                    if exit_code is not None:
                        state = "finished" if exit_code == 0 else "failed"
                        if exit_code:
                            logger.error("%s exited with code %s.", engine_name, exit_code)
                        break
                    cancel.wait(0.05)
            except Exception as error:
                # Exceptions and engine stderr may echo the private command.
                logger.error("Speech process failed (%s): %s.", engine_name, type(error).__name__)
            finally:
                if process is not None:
                    try:
                        process.close()
                    except Exception as error:
                        logger.error("Speech cleanup failed: %s.", type(error).__name__)
                        state = "failed"
            if not cancel.is_set():
                self._worker_state.emit(request_id, state)

    @Slot(int, str)
    def _deliver_state(self, request_id: int, state: str) -> None:
        if request_id == self.request_id and self._cancel is not None:
            if state in ("finished", "failed"):
                self._cancel = None
            self.playback_changed.emit(request_id, state)

    def stop(self) -> None:
        if self._cancel is not None:
            self._cancel.set()
            self._cancel = None
            self.playback_changed.emit(self.request_id, "stopped")
        # Invalidate already queued worker notifications without waiting on Qt.
        self.request_id += 1


def _environment_with_executable_directory(executable: Path) -> dict[str, str]:
    environment = os.environ.copy()
    path_key = next((key for key in environment if key.casefold() == "path"), "PATH")
    current_path = environment.get(path_key, "")
    environment[path_key] = os.pathsep.join(
        part for part in (str(executable.parent), current_path) if part
    )
    return environment


def _espeak_environment(executable: Path) -> dict[str, str] | None:
    if not (executable.parent / "espeak-ng-data").is_dir():
        return None
    environment = _environment_with_executable_directory(executable)
    # The Windows engine otherwise consults the MSI registry path, which is
    # absent in portable/clean installs (including its --version command).
    environment["ESPEAK_DATA_PATH"] = str(executable.parent)
    return environment


def find_espeak_ng() -> Path | None:
    candidates = list(_candidate_paths())
    for candidate in candidates:
        if _is_valid_espeak_ng(candidate):
            logger.info("Found espeak-ng executable: %s", candidate)
            return candidate

    logger.warning("espeak-ng executable was not found.")
    return None


def find_edge_playback() -> Path | None:
    candidates = list(_edge_playback_candidate_paths())
    for candidate in candidates:
        if _is_valid_edge_playback(candidate):
            logger.info("Found edge-playback executable: %s", candidate)
            return candidate

    logger.warning("edge-playback executable was not found.")
    return None


def _candidate_paths() -> list[Path]:
    candidates = _environment_candidates("ESPEAK_NG_EXE")
    candidates.append(_application_root() / "speech" / "espeak-ng" / "espeak-ng.exe")

    path_match = shutil.which("espeak-ng") or shutil.which("espeak-ng.exe")
    if path_match:
        candidates.append(Path(path_match))

    app_root = _application_root()
    tools_root = app_root / "tools" / "espeak-ng"
    if tools_root.exists():
        candidates.extend(sorted(tools_root.rglob("espeak-ng.exe")))

    candidates.extend(_espeak_system_paths())
    return _unique_paths(candidates)


def _edge_playback_candidate_paths() -> list[Path]:
    candidates = _environment_candidates("EDGE_PLAYBACK_EXE")
    candidates.append(_application_root() / "speech" / "edge" / "edge-playback.exe")

    for name in ("edge-playback", "edge-playback.exe"):
        path_match = shutil.which(name)
        if path_match:
            candidates.append(Path(path_match))

    executable_dir = Path(sys.executable).resolve().parent
    candidates.extend(
        [
            executable_dir / "edge-playback.exe",
            executable_dir / "edge-playback",
            executable_dir / "edge-playback-script.py",
        ]
    )

    app_root = _application_root()
    candidates.extend(
        [
            app_root / ".venv" / "Scripts" / "edge-playback.exe",
            app_root / ".venv" / "Scripts" / "edge-playback",
            app_root / ".venv" / "bin" / "edge-playback",
        ]
    )

    return _unique_paths(candidates)


def _environment_candidates(name: str) -> list[Path]:
    value = os.environ.get(name, "").strip()
    return [Path(value)] if value else []


def _espeak_system_paths() -> list[Path]:
    if sys.platform != "win32":
        return []
    paths: list[Path] = []
    for name in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData"):
        base = os.environ.get(name)
        if base:
            paths.extend(_espeak_paths_under(Path(base)))
    return paths


def _espeak_paths_under(root: Path) -> list[Path]:
    return [
        root / "eSpeak NG" / "espeak-ng.exe",
        root / "eSpeak NG" / "command_line" / "espeak-ng.exe",
        root / "eSpeak NG" / "bin" / "espeak-ng.exe",
        root / "Programs" / "eSpeak NG" / "espeak-ng.exe",
        root / "Programs" / "eSpeak NG" / "command_line" / "espeak-ng.exe",
    ]


def _unique_paths(candidates: list[Path]) -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).lower()
        if key not in seen:
            seen.add(key)
            paths.append(candidate)
    return paths


def _application_root() -> Path:
    configured = os.environ.get(APP_ROOT_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _is_valid_espeak_ng(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False

    try:
        result = subprocess.run(
            [str(path), "--version"],
            env=_espeak_environment(path),
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


def _is_valid_edge_playback(path: Path) -> bool:
    return path.exists() and path.is_file()


def _has_bosnian_voice(path: Path) -> bool:
    for arguments in ([f"--voices={BOSNIAN_LANGUAGE}"], ["--voices"]):
        try:
            result = subprocess.run(
                [str(path), *arguments],
                env=_espeak_environment(path),
                stdin=subprocess.DEVNULL,
                capture_output=True,
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
