# 000005 - Setup Log Python Installer Fix

Date: 2026-06-06

## Original Prompt

```text
analize the setup_windows.log and make a fix, make sire ut installs python via powershell automaticlly as well 
```

## Setup Log Analysis

The setup log showed the script was run from:

```text
\\192.168.0.30\Tobii\setup_windows.ps1
```

Windows and required project file checks passed.

The failure happened while checking the Python launcher:

```text
[STEP] Finding Python 3.10
[INFO] Checking Python launcher: py -3.10
TerminatingError(py.exe): "The running command stopped because the preference variable "ErrorActionPreference" or common parameter is set to Stop..."
[ERROR] Setup failed
```

Root cause:

- `$ErrorActionPreference = "Stop"` was active.
- `py -3.10` failed because Python 3.10 was not installed.
- PowerShell 5.1 converted that expected native command failure into a terminating error.
- The script stopped before reaching the Python installation path.

## What Was Fixed

Updated `setup_windows.ps1`:

- Added `Invoke-NativeProbe` so detection commands like `py -3.10` can fail without aborting setup.
- Updated `Invoke-NativeCommand` so native command stderr does not unexpectedly terminate the script under PowerShell 5.1.
- Updated Python detection to use `Invoke-NativeProbe` for:
  - `py -3.10`
  - `python3.10`
  - `python`
  - common Python install paths
- Added automatic direct Python.org installation fallback:
  - Downloads the official Python 3.10.11 64-bit Windows installer with PowerShell.
  - Tries download methods in order:
    - `Invoke-WebRequest`
    - `Start-BitsTransfer`
    - `System.Net.WebClient`
  - Enables TLS 1.2 for HTTPS downloads.
  - Runs the Python installer silently as a per-user install.
  - Installs to:

```text
%LocalAppData%\Programs\Python\Python310
```

- `winget` is still tried first when available.
- If `winget` is missing or fails, setup now falls back to the direct PowerShell download/install path.
- Added `-PythonInstallerVersion`, defaulting to `3.10.11`.
- Updated `README.md` to describe the two Python installation methods and the installer version behavior.

## Important Files

- `setup_windows.ps1` - fixed Python detection and automatic installer fallback.
- `README.md` - updated Python install documentation.
- `setup_windows.log` - analyzed failure log from the Windows machine.

## What Is Working

- Python source syntax validation still passes.
- No `__pycache__`, `.pyc`, or `.pyo` files were present after validation.
- The next Windows run should no longer stop at `py -3.10` when Python 3.10 is missing.
- The script now has an automatic PowerShell-only path for downloading and installing Python if `winget` does not solve it.

## What Is Not Confirmed / Needs Real Windows Testing

- PowerShell execution/parsing could not be tested in this Linux workspace because neither `pwsh` nor `powershell` is installed.
- The direct Python.org installer download/install must be tested on the Windows machine.
- If Python installation succeeds but the current PowerShell session still cannot find Python, open a new PowerShell window and rerun setup. The script also checks the direct install target path, so this should usually not be necessary.

## Validation Performed

Python syntax validation:

```text
python - <<'PY'
from pathlib import Path
paths = [Path('run_gaze_mouse.py'), *sorted(Path('gaze_mouse').glob('*.py'))]
for path in paths:
    compile(path.read_text(encoding='utf-8'), str(path), 'exec')
print('python syntax ok')
PY
```

Result:

```text
python syntax ok
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

- Re-run on Windows with:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1
```

- Expected behavior if Python 3.10 is missing:
  - `py -3.10` check logs a normal miss.
  - `winget` is tried if available.
  - If `winget` is unavailable or fails, Python 3.10.11 is downloaded from Python.org and installed silently.
  - Setup proceeds to create `.venv` and install dependencies.

- If the next failure is during `.venv` creation from the UNC path, consider copying the project to a local path like `C:\TobiiGazeMouse` or adding a script-managed local project copy step.
