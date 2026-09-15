"""Windows startup task management."""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

TASK_NAME = "Tobii Gaze Mouse"
LAUNCHER_SCRIPT_NAME = "start_gaze_mouse.ps1"


@dataclass(frozen=True)
class StartupTaskResult:
    """Result of enabling or disabling Windows startup."""

    enabled: bool
    success: bool
    message: str


def is_windows_startup_enabled() -> bool:
    """Return whether the scheduled startup task exists and is enabled."""

    if sys.platform != "win32":
        return False

    try:
        completed = _run_powershell(_query_script())
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Could not query Windows startup task: %s", exc)
        return False

    if completed.returncode != 0:
        logger.warning(
            "Could not query Windows startup task: %s",
            _completed_output(completed),
        )
        return False

    return completed.stdout.strip().lower().splitlines()[-1:] == ["true"]


def set_windows_startup_enabled(
    enabled: bool,
    *,
    show_launcher_window: bool = False,
) -> StartupTaskResult:
    """Enable or disable the elevated Windows logon scheduled task."""

    if sys.platform != "win32":
        return StartupTaskResult(
            enabled=False,
            success=False,
            message="Windows startup can only be changed on Windows.",
        )

    script = (
        _enable_script(_launcher_script_path(), show_launcher_window=show_launcher_window)
        if enabled
        else _disable_script()
    )
    try:
        completed = _run_powershell(script)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Could not update Windows startup task: %s", exc)
        return StartupTaskResult(
            enabled=is_windows_startup_enabled(),
            success=False,
            message=f"Windows startup update failed: {exc}",
        )

    actual_enabled = is_windows_startup_enabled()

    if completed.returncode == 0:
        if enabled:
            message = "Windows startup enabled. The app will run as Administrator after logon."
        else:
            message = "Windows startup disabled. Start the app manually when needed."
        logger.info(message)
        return StartupTaskResult(enabled=actual_enabled, success=True, message=message)

    message = _completed_output(completed) or "Scheduled task command failed."
    logger.warning("Could not update Windows startup task: %s", message)
    return StartupTaskResult(
        enabled=actual_enabled,
        success=False,
        message=f"Windows startup update failed: {message}",
    )


def _launcher_script_path() -> Path:
    return launcher_script_path()


def launcher_script_path() -> Path:
    """Return the launcher beside the source tree or frozen executable."""

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / LAUNCHER_SCRIPT_NAME
    return Path(__file__).resolve().parents[1] / LAUNCHER_SCRIPT_NAME


def _run_powershell(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )


def _query_script() -> str:
    task_name = _ps_quote(TASK_NAME)
    return f"""
$ErrorActionPreference = 'Stop'
$task = Get-ScheduledTask -TaskName {task_name} -ErrorAction SilentlyContinue
if ($null -eq $task) {{
    Write-Output 'false'
    exit 0
}}
if ($task.State -eq 'Disabled') {{
    Write-Output 'false'
}} else {{
    Write-Output 'true'
}}
"""


def _enable_script(launcher_path: Path, *, show_launcher_window: bool) -> str:
    task_name = _ps_quote(TASK_NAME)
    launcher = _ps_quote(str(launcher_path))
    window_style = "" if show_launcher_window else "-WindowStyle Hidden "
    description = _ps_quote(
        "Starts Tobii Gaze Mouse at Windows logon with highest available privileges."
    )
    return f"""
$ErrorActionPreference = 'Stop'
$taskName = {task_name}
$launcher = {launcher}
if (-not (Test-Path -LiteralPath $launcher)) {{
    throw "Launcher script was not found: $launcher"
}}
$powerShell = Join-Path $env:SystemRoot 'System32\\WindowsPowerShell\\v1.0\\powershell.exe'
$arguments = '{window_style}-NoProfile -ExecutionPolicy Bypass -File "' + $launcher + '" -NoPause'
$workingDirectory = Split-Path -Parent $launcher
$action = New-ScheduledTaskAction -Execute $powerShell -Argument $arguments -WorkingDirectory $workingDirectory
$trigger = New-ScheduledTaskTrigger -AtLogOn
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description {description} `
    -Force | Out-Null
Write-Output 'enabled'
"""


def _disable_script() -> str:
    task_name = _ps_quote(TASK_NAME)
    return f"""
$ErrorActionPreference = 'Stop'
$task = Get-ScheduledTask -TaskName {task_name} -ErrorAction SilentlyContinue
if ($null -ne $task) {{
    Unregister-ScheduledTask -TaskName {task_name} -Confirm:$false
}}
Write-Output 'disabled'
"""


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _completed_output(completed: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join(
        part.strip() for part in (completed.stdout, completed.stderr) if part and part.strip()
    )
    return output.strip()
