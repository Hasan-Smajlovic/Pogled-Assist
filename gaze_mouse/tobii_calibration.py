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

from .windows_input import WindowsInputController

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


def launch_tobii_guest_calibration() -> str:
    """Open Tobii Core/Experience calibration through the installed Tobii UI."""

    if sys.platform != "win32":
        raise RuntimeError("Tobii calibration launch is only available on Windows.")

    launched_methods: list[str] = []
    errors: list[str] = []

    configured = os.environ.get(CALIBRATION_COMMAND_ENV, "").strip()
    if configured and _launch_configured_command(configured, errors):
        launched_methods.append(f"{CALIBRATION_COMMAND_ENV}")

    if not launched_methods:
        target = _best_tobii_launch_target()
        if target is not None and _shell_execute(str(target), errors):
            launched_methods.append(_short_display_path(target))
            time.sleep(1.25)

    if not launched_methods:
        uri = _first_working_protocol(errors)
        if uri:
            launched_methods.append(uri)
            time.sleep(1.0)

    shortcut_sent = _send_calibration_shortcut(errors)
    if shortcut_sent:
        launched_methods.append("Ctrl+Shift+F10")

    if launched_methods:
        logger.info("Tobii calibration launch requested through: %s", launched_methods)
        return "Tobii calibration launch requested."

    raise RuntimeError(
        "Could not launch Tobii calibration. Tried Tobii UI shortcuts/executables, "
        f"protocols, and Ctrl+Shift+F10. Details: {'; '.join(errors) or 'no launch target found'}"
    )


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


def _best_tobii_launch_target() -> Path | None:
    candidates = _start_menu_shortcuts() + _installed_tobii_executables()
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
    roots = []
    for base in ("ProgramData", "AppData"):
        value = os.environ.get(base, "").strip()
        if value:
            roots.append(Path(value) / "Microsoft" / "Windows" / "Start Menu" / "Programs")

    shortcuts: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        try:
            shortcuts.extend(path for path in root.rglob("*.lnk") if "tobii" in str(path).lower())
        except OSError:
            logger.exception("Could not scan Start Menu shortcuts under %s.", root)

    return shortcuts


def _installed_tobii_executables() -> list[Path]:
    roots = _tobii_search_roots()
    direct_candidates: list[Path] = []
    for root in roots:
        for exe_name in _KNOWN_CONFIG_EXES:
            direct_candidates.extend(root.glob(f"**/{exe_name}"))

    discovered: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        try:
            discovered.extend(path for path in root.rglob("*.exe") if "tobii" in str(path).lower())
        except OSError:
            logger.exception("Could not scan Tobii executable folder: %s.", root)

    return _unique_paths(direct_candidates + discovered)


def _tobii_search_roots() -> list[Path]:
    roots: list[Path] = []
    for env_name in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData", "ProgramData"):
        value = os.environ.get(env_name, "").strip()
        if value:
            roots.append(Path(value) / "Tobii")

    return [root for root in roots if root.exists()]


def _target_score(path: Path) -> int:
    text = str(path).lower()
    name = path.name.lower()
    parent = path.parent.name.lower()
    score = 0

    if path.suffix.lower() == ".lnk":
        score += 40
    if name in (item.lower() for item in _KNOWN_CONFIG_EXES):
        score += 120
    if "tobii eyex config" in text:
        score += 80
    if "tobii eye tracking" in text:
        score += 45
    if "calibr" in text:
        score += 100
    if "config" in text or "setting" in text:
        score += 70
    if "profile" in text:
        score += 55
    if "testeyetracking" in text:
        score += 35
    if "experience" in text:
        score += 30

    if any(keyword in text for keyword in _UI_KEYWORDS):
        score += 15
    if parent == "troubleshooter":
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
