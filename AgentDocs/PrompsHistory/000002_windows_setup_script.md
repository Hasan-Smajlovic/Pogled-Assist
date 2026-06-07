# 000002 - Windows Setup Script

Date: 2026-06-06

## Original Prompt

```text
generate a powershell script which will setup everything for program to be runnable on the windows
```

## What Was Done

- Added `setup_windows.ps1` in the repository root.
- Updated `README.md` with Windows setup commands that use `setup_windows.ps1`.
- The setup script:
  - Verifies it is running on Windows.
  - Finds Python 3.10 through the `py` launcher, `python3.10`, or `python`.
  - Optionally installs Python 3.10 with `winget` when run with `-InstallPython`.
  - Creates `.venv` if it does not already exist.
  - Upgrades `pip`.
  - Installs `requirements.txt` with `--no-compile`.
  - Sets `PYTHONDONTWRITEBYTECODE=1` and `PIP_NO_COMPILE=1`.
  - Verifies that `PySide6`, `pyautogui`, `qtawesome`, and `tobii_research` are discoverable.
  - Removes `__pycache__`, `.pyc`, and `.pyo` files under the repo after setup and also on failure.
  - Prints the command to run the application.
  - Can launch the app immediately with `-Launch`.

## Important Files

- `setup_windows.ps1` - Windows setup automation script.
- `README.md` - updated setup usage documentation.
- `requirements.txt` - dependencies installed by the setup script.
- `run_gaze_mouse.py` - app launch target used by the setup script.

## How To Use On Windows

Normal setup:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1
```

Install Python 3.10 with `winget` if Python 3.10 is missing:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1 -InstallPython
```

Setup and launch immediately:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1 -Launch
```

Run after setup:

```powershell
.\.venv\Scripts\python.exe .\run_gaze_mouse.py
```

## What Is Working

- Python source syntax validation still passes for all app `.py` files.
- No `__pycache__`, `.pyc`, or `.pyo` files were present after validation.
- The setup script is written to avoid Python bytecode generation where possible and cleans caches afterward.
- The setup script supports both existing Python 3.10 installs and optional `winget` installation.

## What Is Not Confirmed / Needs Real Windows Testing

- `setup_windows.ps1` was not executed in this Linux workspace because PowerShell (`pwsh`/`powershell`) is not installed.
- Dependency installation was not run here because the target Tobii SDK package is Windows/Python 3.10 oriented and this workspace is Linux with Python 3.12.
- Real Tobii Eye Tracker 4C discovery still needs testing on the target Windows machine.
- The Windows AppBar desktop work-area reservation still needs testing on the target Windows machine.

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

Result: no output, so PowerShell script execution/parsing could not be performed here.

## Notes For Next Agent

- First run should happen on the Tobii Windows machine:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1 -InstallPython
```

- If installation fails at `tobii-research`, confirm Python is exactly 3.10 64-bit.
- If the app opens but no tracker is found, verify Tobii software can see and calibrate the Eye Tracker 4C before debugging Python code.
- If the toolbar opens but does not push maximized windows down, inspect the AppBar registration status in `gaze_mouse/appbar.py`.
