"""Cancellable speech through local and online voices."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import Event, Lock, Thread

from PySide6.QtCore import QObject, Qt, Signal, Slot

from ..keyboard_layouts import ARABIC_SCRIPT, LATIN_SCRIPT
from ..settings_limits import ELEVENLABS_SIMILARITY_DEFAULT, ELEVENLABS_STABILITY_DEFAULT
from ..tracking.tobii_stream_engine import APP_ROOT_ENV
from ..windows.speech_process import start_speech_process
from .audio_cache import AudioCache, cache_root
from .audio_playback import AudioPlayback, PlaybackResult
from .eleven_account import ElevenAccount
from .elevenlabs import DEFAULT_MODEL, ElevenConfig, configuration
from .voice_router import Playback, VoiceRouter
from .voice_state import (ACTIVE_PLAYBACK_STATES, EFENDIJA, NATURAL, STANDARD, NATURAL_VOICE, NATURAL_RATE, NATURAL_PITCH, REASONS, VOICE_TEST_TEXT, SpeechCancelled, VoiceError, VoiceState)

logger = logging.getLogger(__name__)

BOSNIAN_LANGUAGE = "bs"
VOICE_PRESET_DEFAULT = STANDARD
VOICE_PRESET_HUMAN_LIKE = NATURAL
VOICE_PRESET_EFENDIJA = EFENDIJA
VOICE_PRESETS: tuple[tuple[str, str], ...] = (
    (VOICE_PRESET_DEFAULT, "Standardni"),
    (VOICE_PRESET_HUMAN_LIKE, "Prirodni"),
    (VOICE_PRESET_EFENDIJA, "Efendija"),
)
VOICE_PRESET_LABELS = dict(VOICE_PRESETS)
EDGE_PLAYBACK_VOICE = NATURAL_VOICE
ARABIC_EDGE_PLAYBACK_VOICE = "ar-SA-HamedNeural"
EDGE_PLAYBACK_RATE = NATURAL_RATE
EDGE_PLAYBACK_PITCH = NATURAL_PITCH


@dataclass
class SpeechSettings:
    language: str = BOSNIAN_LANGUAGE
    speed: int = 155
    pitch: int = 50
    amplitude: int = 120
    letters_per_group: int = 5
    voice_preset: str = VOICE_PRESET_DEFAULT
    keyboard_script: str = LATIN_SCRIPT
    elevenlabs_voice_id: str = field(default="", repr=False)
    elevenlabs_model_id: str = field(default=DEFAULT_MODEL, repr=False)
    elevenlabs_stability: int = ELEVENLABS_STABILITY_DEFAULT
    elevenlabs_similarity: int = ELEVENLABS_SIMILARITY_DEFAULT

    @property
    def uses_efendija(self) -> bool:
        return self.voice_preset == EFENDIJA and self.keyboard_script != ARABIC_SCRIPT


@dataclass(frozen=True)
class EfendijaRequest:
    request_id: int
    cancel: Event
    text: str = field(repr=False)
    settings: SpeechSettings
    config: ElevenConfig
    test: bool = False


def _voice_identity(settings: SpeechSettings) -> tuple:
    identity = (settings.voice_preset, settings.keyboard_script)
    if settings.uses_efendija:
        identity += (settings.elevenlabs_voice_id, settings.elevenlabs_model_id, settings.elevenlabs_stability, settings.elevenlabs_similarity)
    return identity


def _test_message(state, reason="") -> str:
    if reason:
        return "Proba Efendije nije uspjela. " + REASONS[reason]
    return "Proba Efendije je završena." if state == "finished" else "Izgovor Efendije nije završen. Pokušajte ponovo."


class SpeechService(QObject):
    """Own playback, provider state and cancellation across voice changes."""

    playback_changed = Signal(int, str)
    voice_changed = Signal(int, object)
    test_finished = Signal(int, str)
    _worker_state = Signal(int, str)
    _worker_voice = Signal(int, object)
    _worker_test = Signal(int, str)
    _audio_requested = Signal(int, object, object, object)

    def __init__(self, *, credentials=None, client=None, cache: AudioCache | None = None) -> None:
        super().__init__()
        self.request_id = 0
        self.playback_state = "stopped"
        self._cancel: Event | None = None
        self._efendija_request: int | None = None
        self._efendija_started = False
        self._process_lock = Lock()
        self._worker_state.connect(self._deliver_state, Qt.QueuedConnection)
        self._executable = find_espeak_ng()
        self._edge_playback_executable = find_edge_playback()
        self._settings = SpeechSettings()
        self.account = ElevenAccount(self, store=credentials, client=client)
        self.account.configure(self.settings)
        self.audio_cache = cache if cache is not None else AudioCache(cache_root())
        self._router = VoiceRouter(self.audio_cache, client)
        self._audio = AudioPlayback(self)
        self._audio.started.connect(self._audio_started)
        self._audio_voice = VoiceState()
        self.voice_state = VoiceState()
        self._saved_texts: set[str] | None = None
        self._worker_voice.connect(self._deliver_voice, Qt.QueuedConnection)
        self._worker_test.connect(self._deliver_test, Qt.QueuedConnection)
        self._audio_requested.connect(self._play_audio, Qt.QueuedConnection)
        self.account.credentials_changed.connect(self._credentials_changed)
        self.account.checked.connect(self._router.gate.checked)
        self._router.gate.configure(self.account.config.fingerprint)

    @property
    def executable(self) -> Path | None:
        return self._executable

    @property
    def available(self) -> bool:
        return self._executable is not None or self._edge_playback_executable is not None

    @property
    def is_busy(self) -> bool:
        return self.playback_state in ACTIVE_PLAYBACK_STATES

    @property
    def settings(self) -> SpeechSettings:
        return replace(self._settings)

    def update_settings(self, settings: SpeechSettings) -> None:
        previous = self._settings
        self._settings = replace(settings)
        self.account.configure(self.settings)
        if _voice_identity(previous) != _voice_identity(settings):
            self.stop()
            self.voice_state = VoiceState()
            self.voice_changed.emit(self.request_id, self.voice_state)
        self._configure_audio()
        logger.info("Speech settings updated: %s", self._settings)

    def set_saved_texts(self, texts: set[str] | None) -> None:
        self._saved_texts = set(texts) if texts is not None else None
        self._configure_audio()

    def _configure_audio(self) -> None:
        config = self.account.config
        self._router.gate.configure(config.fingerprint)
        self.audio_cache.configure(config.audio_identity, self._saved_texts)

    def _credentials_changed(self) -> None:
        self.stop()
        self._configure_audio()

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
        if settings.voice_preset == VOICE_PRESET_EFENDIJA:
            return self._speak_efendija(text, settings)
        if settings.voice_preset == VOICE_PRESET_HUMAN_LIKE:
            return self._speak_edge_playback(text)

        return self._speak_espeak(text, settings)

    def test_efendija(self) -> bool:
        return self._speak_efendija(VOICE_TEST_TEXT, self.settings, test=True)

    def _speak_efendija(self, text: str, settings: SpeechSettings, *, test=False) -> bool:
        self.stop()
        self.request_id += 1
        request_id, cancel = self.request_id, Event()
        self._efendija_request = request_id
        self._efendija_started = False
        self._cancel = cancel
        self.playback_state = "preparing"
        config = configuration(settings, self.account.config.key)
        self._configure_audio()
        request = EfendijaRequest(request_id, cancel, text, settings, config, test)
        try:
            Thread(
                target=self._run_efendija,
                args=(request,),
                daemon=True,
                name="efendija-speech",
            ).start()
        except RuntimeError:
            self._cancel = None
            self.playback_state = "failed"
            return False
        return True

    def _request_audio(self, request, data, voice):
        result = PlaybackResult()
        if request.cancel.is_set():
            result.outcome = "stopped"
            return result
        self._audio_requested.emit(request.request_id, data, result, voice)
        while not result.done.wait(0.02):
            if request.cancel.is_set():
                result.outcome = "stopped"
                return result
        return result

    def _run_efendija(self, request: EfendijaRequest) -> None:
        with self._process_lock:
            if request.cancel.is_set():
                return
            self._worker_state.emit(request.request_id, "preparing")
            state = self._route_efendija(request)
        if request.cancel.is_set():
            return
        if state == "standard":
            command, environment = self._espeak_command(request.text, request.settings)
            self._run_process(request.request_id, request.cancel, command, "espeak-ng", environment)
        else:
            self._worker_state.emit(request.request_id, state)

    def _route_efendija(self, request):
        def publish(state):
            if not request.cancel.is_set():
                self._worker_voice.emit(request.request_id, state)

        reason = ""
        try:
            state = self._router.run(request.text, request.config, Playback(request.cancel, lambda data, voice: self._request_audio(request, data, voice), publish), test=request.test)
        except SpeechCancelled:
            return "stopped"
        except VoiceError as error:
            state, reason = "failed", error.reason
        except Exception as error:
            logger.error("Speech preparation failed: %s.", type(error).__name__)
            state, reason = "failed", "offline"
        if request.test:
            self._worker_test.emit(request.request_id, _test_message(state, reason))
        return state

    def _is_current(self, request_id) -> bool:
        return request_id == self.request_id and self._cancel is not None and not self._cancel.is_set()

    @Slot(int, object, object, object)
    def _play_audio(self, request_id, data, result, voice) -> None:
        if not self._is_current(request_id):
            result.outcome = "stopped"
            result.done.set()
            return
        self._audio_voice = voice
        self._audio.play(request_id, data, result)

    @Slot(int)
    def _audio_started(self, request_id: int) -> None:
        if not self._is_current(request_id):
            return
        self._efendija_started = True
        self._deliver_voice(request_id, self._audio_voice)
        self._deliver_state(request_id, "speaking")

    @Slot(int, object)
    def _deliver_voice(self, request_id: int, state: VoiceState) -> None:
        if request_id == self.request_id:
            self.voice_state = replace(state, recovered=False)
            self.voice_changed.emit(request_id, state)

    @Slot(int, str)
    def _deliver_test(self, request_id: int, message: str) -> None:
        if request_id == self.request_id:
            self.test_finished.emit(request_id, message)

    def _speak_espeak(self, text: str, settings: SpeechSettings) -> bool:
        command, environment = self._espeak_command(text, settings)
        if environment is not None:
            return self._start_process(command, "espeak-ng", environment=environment)
        return self._start_process(command, "espeak-ng")

    def _espeak_command(self, text: str, settings: SpeechSettings):
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
        return command, environment

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
        self.playback_state = "preparing"
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
            self.playback_state = "failed"
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
                environment = self._resolve_command(command, engine_name, environment)
                if cancel.is_set():
                    return
                if not command[0]:
                    self._worker_state.emit(request_id, "failed")
                    return
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

    def _resolve_command(self, command, engine_name, environment):
        if command[0]:
            return environment
        attribute, find, environment_for = {
            "espeak-ng": ("_executable", find_espeak_ng, _espeak_environment),
            "edge-playback": ("_edge_playback_executable", find_edge_playback, _environment_with_executable_directory),
        }[engine_name]
        executable = find()
        setattr(self, attribute, executable)
        environment = environment_for(executable) if executable else None
        if executable is not None:
            command[0] = str(executable)
        else:
            logger.error("Speech engine was not found: %s.", engine_name)
        return environment

    def _finish_efendija(self, request_id, state):
        if request_id != self._efendija_request:
            return
        if state == "failed" and self._efendija_started:
            self._deliver_voice(request_id, replace(self.voice_state, partial=True))
        if state in ("finished", "failed"):
            self.account.refresh_subscription()

    @Slot(int, str)
    def _deliver_state(self, request_id: int, state: str) -> None:
        if request_id == self.request_id and self._cancel is not None:
            self.playback_state = state
            self._finish_efendija(request_id, state)
            if state in ("finished", "failed"):
                self._cancel = None
            self.playback_changed.emit(request_id, state)

    def stop(self) -> None:
        request_id = self.request_id
        cancel = self._cancel
        if self._cancel is not None:
            self._cancel.set()
            self._cancel = None
        # Invalidate already queued worker notifications without waiting on Qt.
        self.request_id += 1
        self._audio.stop()
        if cancel is not None:
            self.playback_state = "stopped"
            self.playback_changed.emit(request_id, "stopped")


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
