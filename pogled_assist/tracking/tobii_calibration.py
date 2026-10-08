"""Helpers for launching Tobii calibration."""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

from ..windows.windows_input import WindowsInputController

logger = logging.getLogger(__name__)

SW_SHOWNORMAL = 1
SHELLEXECUTE_SUCCESS_MIN = 32
CALIBRATION_COMMAND_ENV = "TOBII_CALIBRATION_COMMAND"

_TOBII_PROTOCOLS = (
    "tobii://calibration",
    "tobii://settings/calibration",
    "tobii://profiles",
    "tobii://",
)

_KNOWN_CONFIG_EXES = (
    "Tobii.EyeX.Config.exe",
    "Tobii.EyeX.Configuration.exe",
    "Tobii.EyeX.Settings.exe",
    "Tobii.EyeX.TestEyeTracking.exe",
    "Tobii.EyeTracking.Config.exe",
    "Tobii.EyeTracking.Settings.exe",
    "TobiiEyeTracking.exe",
    "TobiiExperience.exe",
)
_KNOWN_CONFIG_NAMES = frozenset(name.lower() for name in _KNOWN_CONFIG_EXES)

_EXCLUDED_EXE_KEYWORDS = (
    "unins",
    "uninstall",
    "updater",
    "update",
    "service",
    "engine",
    "stream",
    "crash",
    "diagnostic",
)

_UI_KEYWORDS = (
    "calibr",
    "config",
    "setting",
    "profile",
    "experience",
    "testeyetracking",
    "eyetracking",
    "eyex",
)

_PATH_KEYWORD_SCORES = (
    (("tobii eyex config",), 80),
    (("tobii eye tracking",), 45),
    (("calibr",), 100),
    (("config", "setting"), 70),
    (("profile",), 55),
    (("testeyetracking",), 35),
    (("experience",), 30),
    (_UI_KEYWORDS, 15),
)


def launch_tobii_guest_calibration() -> str:
    """Open Tobii Core/Experience calibration through the installed Tobii UI."""

    if sys.platform != "win32":
        raise RuntimeError("Tobii kalibracija se može pokrenuti samo na Windowsu.")

    errors: list[str] = []
    opened = _open_calibration_ui(errors)
    launched_methods = [opened] if opened else []
    if _send_calibration_shortcut(errors):
        launched_methods.append("Ctrl+Shift+F10")

    if launched_methods:
        logger.info("Tobii calibration launch requested through: %s", launched_methods)
        return "Pokretanje Tobii kalibracije je zatraženo."

    raise RuntimeError(
        "Tobii kalibracija se nije mogla pokrenuti. Pokušani su Tobii programi, veze i "
        "prečica Ctrl+Shift+F10."
    )


def launch_tobii_settings() -> str:
    """Open the installed settings UI without sending the Guest shortcut."""
    if sys.platform != "win32":
        raise RuntimeError("Tobii postavke se mogu otvoriti samo na Windowsu.")
    errors: list[str] = []
    target = _best_tobii_launch_target(settings_only=True)
    if target is not None and _shell_execute(str(target), errors):
        logger.info("Tobii settings launch requested: %s", _short_display_path(target))
        return "Otvaranje Tobii postavki je zatraženo."
    raise RuntimeError("Tobii postavke se nisu mogle otvoriti. Otvorite Tobii ikonu pored sata.")


def _open_calibration_ui(errors: list[str]) -> str | None:
    configured = os.environ.get(CALIBRATION_COMMAND_ENV, "").strip()
    if configured and _launch_configured_command(configured, errors):
        return CALIBRATION_COMMAND_ENV

    target = _best_tobii_launch_target()
    if target is not None and _shell_execute(str(target), errors):
        time.sleep(1.25)
        return _short_display_path(target)

    uri = _first_working_protocol(errors)
    if uri:
        time.sleep(1.0)
    return uri


def _launch_configured_command(command: str, errors: list[str]) -> bool:
    try:
        subprocess.Popen(command, shell=True)
    except OSError as exc:
        message = f"{CALIBRATION_COMMAND_ENV} failed: {exc}"
        logger.warning(message)
        errors.append(message)
        return False

    logger.info("Started Tobii calibration command from %s: %s", CALIBRATION_COMMAND_ENV, command)
    time.sleep(1.25)
    return True


def _best_tobii_launch_target(*, settings_only: bool = False) -> Path | None:
    candidates = _start_menu_shortcuts() + _installed_tobii_executables()
    if settings_only:
        candidates = [
            candidate
            for candidate in candidates
            if not any(word in candidate.stem.lower() for word in ("calibr", "guest", "test"))
        ]
    ranked = sorted(
        ((candidate, _target_score(candidate)) for candidate in candidates),
        key=lambda item: item[1],
        reverse=True,
    )
    ranked = [(candidate, score) for candidate, score in ranked if score > 0]
    if not ranked:
        logger.warning("No Tobii calibration/configuration launch target was found.")
        return None

    logger.info(
        "Best Tobii launch candidates: %s",
        [f"{_short_display_path(path)} score={score}" for path, score in ranked[:8]],
    )
    return ranked[0][0]


def _start_menu_shortcuts() -> list[Path]:
    return [
        shortcut
        for base in _environment_dirs("ProgramData", "AppData")
        for shortcut in _tobii_files(
            base / "Microsoft" / "Windows" / "Start Menu" / "Programs", "*.lnk"
        )
    ]


def _installed_tobii_executables() -> list[Path]:
    roots = _tobii_search_roots()
    direct_candidates = [
        path for root in roots for name in _KNOWN_CONFIG_EXES for path in root.glob(f"**/{name}")
    ]
    discovered = [path for root in roots for path in _tobii_files(root, "*.exe")]
    return _unique_paths(direct_candidates + discovered)


def _tobii_search_roots() -> list[Path]:
    bases = _environment_dirs("ProgramFiles", "ProgramFiles(x86)", "LocalAppData", "ProgramData")
    roots = (base / "Tobii" for base in bases)
    return [root for root in roots if root.exists()]


def _environment_dirs(*names: str) -> list[Path]:
    values = (os.environ.get(name, "").strip() for name in names)
    return [Path(value) for value in values if value]


def _tobii_files(root: Path, pattern: str) -> list[Path]:
    found: list[Path] = []
    if not root.exists():
        return found
    try:
        found.extend(path for path in root.rglob(pattern) if "tobii" in str(path).lower())
    except OSError:
        logger.exception("Could not scan %s for Tobii launch targets.", root)
    return found


def _target_score(path: Path) -> int:
    text = str(path).lower()
    name = path.name.lower()
    score = sum(
        weight
        for keywords, weight in _PATH_KEYWORD_SCORES
        if any(keyword in text for keyword in keywords)
    )
    if path.suffix.lower() == ".lnk":
        score += 40
    if name in _KNOWN_CONFIG_NAMES:
        score += 120
    if path.parent.name.lower() == "troubleshooter":
        score -= 20
    if any(keyword in name for keyword in _EXCLUDED_EXE_KEYWORDS):
        score -= 140
    return score


def _first_working_protocol(errors: list[str]) -> str | None:
    for uri in _TOBII_PROTOCOLS:
        if _shell_execute(uri, errors):
            logger.info("Started Tobii calibration/settings protocol: %s", uri)
            return uri

    return None


def _shell_execute(target: str, errors: list[str]) -> bool:
    shell32 = ctypes.windll.shell32
    shell32.ShellExecuteW.argtypes = [
        wintypes.HWND,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.c_int,
    ]
    shell32.ShellExecuteW.restype = wintypes.HINSTANCE

    working_dir = None
    if not _looks_like_uri(target):
        working_dir = str(Path(target).parent)

    raw_result = shell32.ShellExecuteW(
        None,
        "open",
        target,
        None,
        working_dir,
        SW_SHOWNORMAL,
    )
    if isinstance(raw_result, int):
        result = raw_result
    else:
        result = int(getattr(raw_result, "value", None) or 0)
    if result > SHELLEXECUTE_SUCCESS_MIN:
        logger.info("ShellExecute started Tobii launch target: %s", target)
        return True

    message = f"ShellExecute failed for {target!r} with code {result}"
    logger.warning(message)
    errors.append(message)
    return False


def _send_calibration_shortcut(errors: list[str]) -> bool:
    try:
        controller = WindowsInputController()
        for index in range(3):
            if index:
                time.sleep(0.45)
            controller.hotkey("ctrl", "shift", "f10")
        logger.info("Sent Tobii calibration shortcut Ctrl+Shift+F10 through user32.")
        return True
    except Exception as exc:
        message = f"Ctrl+Shift+F10 failed: {exc}"
        logger.warning(message)
        errors.append(message)
        return False


def _looks_like_uri(value: str) -> bool:
    normalized = value.strip().lower()
    return "://" in normalized or normalized.startswith(("ms-", "tobii:"))


def _short_display_path(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _unique_paths(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique
