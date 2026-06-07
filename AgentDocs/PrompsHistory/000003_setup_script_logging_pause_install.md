# 000003 - Setup Script Logging Pause Install

Date: 2026-06-06

## Original Prompt

```text
Make sure that powershell script install everything it needs!
Make sure it does not close immidietly if something fails, or if it's finished
Make sure it has console logs for all steps
```

## What Was Done

- Reworked `setup_windows.ps1` into a more complete Windows setup script.
- Added structured timestamped console logs:
  - `STEP`
  - `INFO`
  - `OK`
  - `WARN`
  - `ERROR`
- Added transcript logging to `setup_windows.log` when PowerShell supports `Start-Transcript`.
- Added a final pause by default on both success and failure:
  - The script prints `Press Enter to close this setup window...`.
  - Added `-NoPause` for users running inside an existing terminal or automation.
- Changed Python setup behavior:
  - Python 3.10 is now auto-installed with `winget` if missing.
  - Existing `-InstallPython` is still accepted for compatibility.
  - Added `-SkipPythonInstall` to fail instead of auto-installing Python.
- Improved installation steps:
  - Verifies required project files exist.
  - Finds Python 3.10 through `py -3.10`, `python3.10`, `python`, and common install paths.
  - Creates `.venv` if missing.
  - Runs `ensurepip`.
  - Upgrades `pip`, `setuptools`, and `wheel`.
  - Installs `requirements.txt` with `--no-compile`.
  - Verifies `PySide6`, `pyautogui`, `qtawesome`, and `tobii_research` are available.
  - Cleans `__pycache__`, `.pyc`, and `.pyo` files.
- Added explicit logging that the script installs Python/Python packages, but cannot safely install or calibrate Tobii vendor runtime/device software.
- Updated `README.md` to document:
  - Default setup.
  - Default pause behavior.
  - `-NoPause`.
  - `-Launch`.
  - `-SkipPythonInstall`.
  - Tobii runtime/calibration note.

## Important Files

- `setup_windows.ps1` - updated installer-style setup script.
- `README.md` - updated setup usage docs.
- `AgentDocs/PrompsHistory/000003_setup_script_logging_pause_install.md` - this handoff file.

## What Is Working

- Python source syntax validation still passes.
- No `__pycache__`, `.pyc`, or `.pyo` files were present after validation.
- The script is designed to keep the console window open after both success and failure unless `-NoPause` is used.
- The script logs every major setup action and native command invocation.
- The script attempts to install missing Python 3.10 automatically with `winget`.
- The script installs the app's Python dependencies from `requirements.txt`.

## What Is Not Confirmed / Needs Real Windows Testing

- PowerShell execution/parsing could not be tested in this Linux workspace because neither `pwsh` nor `powershell` is installed.
- Python 3.10 installation through `winget` must be tested on Windows.
- `.venv` creation and dependency installation must be tested on Windows.
- Tobii hardware/runtime discovery still must be tested on the Tobii Windows machine.

## Validation Performed

Python syntax validation:

```text
python - <<'PY'
from pathlib import Path
paths = [Path('run_gaze_mouse.py'), *sorted(Path('gaze_mouse').glob('*.py'))]
for path in paths:
    compile(path.read_text(encoding='utf-8'), str(path), 'exec')
    print(f'OK {path}')
PY
```

Result:

```text
OK run_gaze_mouse.py
OK gaze_mouse/__init__.py
OK gaze_mouse/appbar.py
OK gaze_mouse/dpi.py
OK gaze_mouse/gaze_provider.py
OK gaze_mouse/main.py
OK gaze_mouse/mouse_controller.py
OK gaze_mouse/toolbar.py
```

Cache check:

```text
find . -name '__pycache__' -o -name '*.pyc' -o -name '*.pyo'
```

Result: no output.

PowerShell availability check:

```text
command -v pwsh || command -v powershell || true
```

Result: no output.

## Notes For Next Agent

- First Windows test command:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1
```

- The setup window should remain open until Enter is pressed.
- If testing from an already-open terminal and pause is annoying:

```powershell
.\setup_windows.ps1 -NoPause
```

- If Python 3.10 install completes but Python is still not found, open a new PowerShell window and rerun the script. This can happen after a fresh `winget` install if PATH changes are not available in the current process.
- If dependency installation fails at `tobii-research`, confirm Python is exactly 3.10 64-bit.
