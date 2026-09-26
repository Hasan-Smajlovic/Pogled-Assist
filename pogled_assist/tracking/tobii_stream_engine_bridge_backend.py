"""Parent-process bridge for 32-bit Tobii Stream Engine access."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .tobii_stream_engine import APP_ROOT_ENV

logger = logging.getLogger(__name__)

X86_PYTHON_ENV = "POGLED_ASSIST_X86_PYTHON"
LEGACY_X86_PYTHON_ENV = "TOBII_GAZE_MOUSE_X86_PYTHON"
START_TIMEOUT_SECONDS = 12.0

GazeCallback = Callable[[float, float, int], None]
EyeStatusCallback = Callable[[bool, bool, int], None]


def bridge_script_path() -> Path:
    """Return the bridge source used by the external 32-bit Python runtime."""

    return Path(__file__).with_name("tobii_stream_engine_bridge.py")


class TobiiStreamEngineBridgeError(RuntimeError):
    """Raised when the 32-bit Tobii bridge cannot be started."""


class TobiiStreamEngineBridgeBackend:
    """Run the 32-bit Stream Engine reader and forward its gaze samples."""

    def __init__(
        self,
        gaze_callback: GazeCallback,
        eye_status_callback: EyeStatusCallback,
    ) -> None:
        self._gaze_callback = gaze_callback
        self._eye_status_callback = eye_status_callback
        self._process: subprocess.Popen[str] | None = None
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._started_event = threading.Event()
        self._error_event = threading.Event()
        self._stop_event = threading.Event()
        self._start_error = ""
        self._label = "Tobii Stream Engine x86 bridge"
        self._python_path = ""

    @property
    def label(self) -> str:
        return self._label

    @property
    def python_path(self) -> str:
        return self._python_path

    def start(self) -> None:
        self._python_path = _find_x86_python()
        script_path = bridge_script_path()
        app_root = Path(__file__).resolve().parents[2]
        command = [
            self._python_path,
            "-B",
            "-u",
            str(script_path),
        ]

        logger.info("Starting Tobii Stream Engine x86 bridge: %s", command)
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = _prepend_pythonpath(str(app_root), env.get("PYTHONPATH", ""))

        try:
            self._process = subprocess.Popen(
                command,
                cwd=str(app_root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            raise TobiiStreamEngineBridgeError(
                f"Could not start 32-bit Tobii bridge with {self._python_path}: {exc}"
            ) from exc

        self._stdout_thread = threading.Thread(
            target=self._read_stdout,
            name="TobiiStreamEngineBridgeStdout",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._read_stderr,
            name="TobiiStreamEngineBridgeStderr",
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()
        self._wait_for_start()

    def stop(self) -> None:
        self._stop_event.set()
        process = self._process
        if process is None:
            self._join_reader_threads()
            return

        if process.poll() is None:
            logger.info("Stopping Tobii Stream Engine x86 bridge.")
            process.terminate()
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                logger.warning("Tobii Stream Engine x86 bridge did not stop; killing it.")
                process.kill()
                process.wait(timeout=3.0)

        self._join_reader_threads()
        self._process = None
        logger.info("Tobii Stream Engine x86 bridge stopped.")

    def _wait_for_start(self) -> None:
        deadline = time.monotonic() + START_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            process = self._process
            if process is not None and process.poll() is not None:
                self._join_reader_threads()
                self._process = None
                raise TobiiStreamEngineBridgeError(
                    f"32-bit Tobii bridge exited before startup with code {process.returncode}."
                )

            if self._started_event.is_set():
                logger.info(
                    "Tobii Stream Engine x86 bridge started with %s via %s.",
                    self._label,
                    self._python_path,
                )
                return

            if self._error_event.is_set():
                message = self._start_error or "Bridge startup failed."
                self.stop()
                raise TobiiStreamEngineBridgeError(message)

            time.sleep(0.05)

        self.stop()
        raise TobiiStreamEngineBridgeError(
            f"32-bit Tobii bridge did not report ready within {START_TIMEOUT_SECONDS:.0f} seconds."
        )

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return

        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Tobii x86 bridge stdout was not JSON: %s", line)
                continue
            self._handle_message(message)

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return

        for raw_line in process.stderr:
            line = raw_line.strip()
            if line:
                logger.info("Tobii x86 bridge: %s", line)

    def _join_reader_threads(self) -> None:
        current_thread = threading.current_thread()
        for thread in (self._stdout_thread, self._stderr_thread):
            if thread is None or thread is current_thread or not thread.is_alive():
                continue

            thread.join(timeout=0.75)
            if thread.is_alive():
                logger.warning("%s did not stop cleanly.", thread.name)

        self._stdout_thread = None
        self._stderr_thread = None

    def _handle_message(self, message: dict[str, object]) -> None:
        message_type = message.get("type")
        if message_type == "started":
            label = str(message.get("label") or self._label)
            dll_path = str(message.get("dll_path") or "")
            self._label = f"{label} (x86 bridge)"
            logger.info("Tobii x86 bridge loaded DLL: %s", dll_path)
            self._started_event.set()
            return

        if message_type == "gaze":
            try:
                x = float(message["x"])
                y = float(message["y"])
                timestamp = int(message.get("timestamp") or 0)
            except (KeyError, TypeError, ValueError):
                logger.warning("Tobii x86 bridge gaze payload was invalid: %s", message)
                return
            self._gaze_callback(x, y, timestamp)
            return

        if message_type == "eyes":
            try:
                left_open = bool(message["left_open"])
                right_open = bool(message["right_open"])
                timestamp = int(message.get("timestamp") or 0)
            except (KeyError, TypeError, ValueError):
                logger.warning("Tobii x86 bridge eye-status payload was invalid: %s", message)
                return
            self._eye_status_callback(left_open, right_open, timestamp)
            return

        if message_type == "error":
            self._start_error = str(message.get("message") or "Bridge reported an error.")
            logger.warning("Tobii x86 bridge error: %s", self._start_error)
            self._error_event.set()
            return

        if message_type == "stopped":
            logger.info("Tobii x86 bridge reported stopped.")
            return

        logger.info("Tobii x86 bridge message: %s", message)


def _find_x86_python() -> str:
    candidates: list[str] = []
    for name in (X86_PYTHON_ENV, LEGACY_X86_PYTHON_ENV):
        configured = os.environ.get(name, "").strip()
        if configured:
            candidates.append(configured)

    candidates.append(str(bundled_x86_python()))
    candidates.extend(_py_launcher_candidates())
    candidates.extend(_common_python_candidates())

    for candidate in candidates:
        if _is_x86_python(candidate):
            logger.info("Found 32-bit Python for Tobii bridge: %s", candidate)
            return candidate

    raise TobiiStreamEngineBridgeError(
        "32-bit Python 3.10 was not found. Reinstall the release to restore its bundled "
        "Tobii bridge runtime, or rerun setup_windows.ps1 for a source installation."
    )


def bundled_x86_python() -> Path:
    configured = os.environ.get(APP_ROOT_ENV, "").strip()
    if configured:
        root = Path(configured)
    elif getattr(sys, "frozen", False):
        root = Path(sys.executable).resolve().parent
    else:
        root = Path(__file__).resolve().parents[2]
    return root / "runtime" / "python-x86" / "python.exe"


def verify_bundled_bridge(root: Path) -> None:
    subprocess.run(
        [
            str(root / "runtime/python-x86/python.exe"),
            "-I",
            "-B",
            str(root / "_internal/pogled_assist/tracking/tobii_stream_engine_bridge.py"),
            "--check",
        ],
        check=True,
        capture_output=True,
        timeout=10,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _py_launcher_candidates() -> list[str]:
    if sys.platform != "win32":
        return []

    try:
        completed = subprocess.run(
            ["py", "-3.10-32", "-c", "import sys; print(sys.executable)"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []

    candidate = completed.stdout.strip().splitlines()
    if completed.returncode == 0 and candidate:
        return [candidate[0].strip()]

    return []


def _common_python_candidates() -> list[str]:
    candidates: list[str] = []
    home = Path.home()

    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        candidates.extend(
            [
                str(Path(local_app_data) / "Programs" / "Python" / "Python310-32" / "python.exe"),
                str(
                    Path(local_app_data) / "Programs" / "Python" / "Python310-32bit" / "python.exe"
                ),
            ]
        )

    candidates.append(
        str(home / "AppData" / "Local" / "Programs" / "Python" / "Python310-32" / "python.exe")
    )

    program_files_x86 = os.environ.get("PROGRAMFILES(X86)", "").strip()
    if program_files_x86:
        candidates.extend(
            [
                str(Path(program_files_x86) / "Python310-32" / "python.exe"),
                str(Path(program_files_x86) / "Python310" / "python.exe"),
            ]
        )

    return candidates


def _is_x86_python(candidate: str) -> bool:
    if not candidate:
        return False

    path = Path(candidate)
    if path.name.lower() == "python.exe" and not path.exists():
        return False

    try:
        completed = subprocess.run(
            [
                candidate,
                "-B",
                "-c",
                (
                    "import ctypes, sys; "
                    "raise SystemExit(0 if sys.version_info[:2] == (3, 10) "
                    "and ctypes.sizeof(ctypes.c_void_p) == 4 else 1)"
                ),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False

    return completed.returncode == 0


def _prepend_pythonpath(path: str, existing: str) -> str:
    if not existing:
        return path
    return path + os.pathsep + existing
