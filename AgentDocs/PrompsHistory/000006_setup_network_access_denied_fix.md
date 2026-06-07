# 000006 - Setup Network Access Denied Fix

Date: 2026-06-06

## Original Prompt

```text
It failed with access denied, please inspect setpu_windows.log and make fixes. 
make sure everything, every aspect of setup is automated with this setup_windows bash script!
```

## Setup Log Analysis

The latest `setup_windows.log` showed that Python 3.10 installation succeeded:

```text
[OK] Found Python 3.10 through py launcher: C:\Users\Korisnik\AppData\Local\Programs\Python\Python310\python.exe
[OK] Python 3.10 winget installation completed and was verified.
```

The new failure happened while creating the virtual environment directly on the network share:

```text
[STEP] Preparing virtual environment
[INFO] Creating virtual environment at \\192.168.0.30\Tobii\.venv
[INFO] Running: C:\Users\Korisnik\AppData\Local\Programs\Python\Python310\python.exe -m venv \\192.168.0.30\Tobii\.venv
Error: [WinError 5] Access is denied
[ERROR] Setup failed: Creating virtual environment at \\192.168.0.30\Tobii\.venv failed with exit code 1.
```

Root cause:

- Setup was launched from a UNC/network path: `\\192.168.0.30\Tobii`.
- Python `venv` creation attempted to write `.venv` directly under that network share.
- Windows returned `[WinError 5] Access is denied`.
- Python itself was installed correctly by the previous fix; the remaining blocker was the network-share `.venv` location.

## What Was Fixed

Updated `setup_windows.ps1` so setup is fully automated around this failure:

- Added automatic local install bootstrap.
- If setup is launched from a network path like `\\192.168.0.30\Tobii`, it now copies the app to:

```text
%LocalAppData%\TobiiGazeMouse
```

- Setup then switches its working folder to that local install folder.
- `.venv` is created locally, not on the UNC share.
- Python package installation runs from the local install folder.
- `setup_windows.log` is written in the local install folder and copied back to the original source folder at the end when possible.
- Added parameters:
  - `-UseSourceFolder` to force direct setup in the source folder.
  - `-InstallRoot <path>` to choose a custom local install folder.
  - `-NoDesktopShortcut` to skip shortcut creation.
- Added launcher automation:
  - Creates `run_gaze_mouse.bat`.
  - Creates `run_gaze_mouse.ps1`.
  - Creates a desktop shortcut named `Tobii Gaze Mouse`, unless `-NoDesktopShortcut` is used.
- Cache cleanup now checks both:
  - the local install folder
  - the original source folder
- Updated `README.md` to document the local install behavior, launcher scripts, desktop shortcut, and new setup parameters.

## Important Files

- `setup_windows.ps1` - fixed network-share access denied by using a local install folder.
- `README.md` - updated setup documentation.
- `setup_windows.log` - analyzed latest failure.
- `AgentDocs/PrompsHistory/000006_setup_network_access_denied_fix.md` - this handoff file.

## Expected Next Windows Run

Run from the network share as before:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1
```

Expected behavior:

- Script detects source path is a network path.
- Script copies the app to `%LocalAppData%\TobiiGazeMouse`.
- Script creates `.venv` under `%LocalAppData%\TobiiGazeMouse\.venv`.
- Script installs dependencies.
- Script creates launcher scripts and desktop shortcut.
- Script copies the local `setup_windows.log` back to the source share if possible.

## What Is Working

- Python source syntax validation passes.
- No `__pycache__`, `.pyc`, or `.pyo` files were present after validation.
- The script no longer attempts to create `.venv` on the UNC share by default.
- The setup is more automated after success because it creates local launchers and a desktop shortcut.

## What Is Not Confirmed / Needs Real Windows Testing

- PowerShell execution/parsing could not be tested in this Linux workspace because neither `pwsh` nor `powershell` is installed.
- The local install copy and venv creation need to be tested on Windows.
- Package installation still needs to be verified on Windows.
- Tobii device runtime/calibration still must exist on the target machine; the setup script cannot safely calibrate hardware.

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

- If the next Windows failure is from dependency installation, inspect the new `setup_windows.log`.
- If the script cannot copy files to `%LocalAppData%\TobiiGazeMouse`, use:

```powershell
.\setup_windows.ps1 -InstallRoot C:\TobiiGazeMouse
```

- If the user specifically wants to test source-folder setup on a local path, use:

```powershell
.\setup_windows.ps1 -UseSourceFolder
```

- Avoid creating `.venv` on the network share unless the share permissions and Python `venv` behavior have been verified.
