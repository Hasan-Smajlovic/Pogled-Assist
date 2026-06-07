# 000013 - Setup Install Dependency Fix

Date: 2026-06-06

## Original Prompt

```text
Please inspect file setup_windows.log, there is still seems to be some issues with installation! 
find the issues, and fix thme pretty please
```

## Setup Log Analysis

The current `setup_windows.log` contains multiple setup attempts.

Older failed attempts:

- The script originally ran directly from `\\192.168.0.30\Tobii`.
- Python 3.10 was installed successfully.
- Virtual environment creation failed on the network share with `Access is denied`.
- A later attempt also failed trying to run `.venv\Scripts\python.exe` from the network share.

Latest attempt:

- The script correctly detected the network path.
- It copied the project to `C:\Users\Korisnik\AppData\Local\TobiiGazeMouse`.
- Python 3.10 was found.
- eSpeak NG 1.52.0 was installed and Bosnian voice support was verified.
- The virtual environment was created locally.
- The latest log does not show a final PowerShell error. It stops during `pip install` while resolving/building `pyautogui` dependency packages, specifically after starting build dependencies for `pyrect`.

The likely remaining setup problem was the required `pyautogui` dependency chain pulling several source distributions on Windows:

- `pymsgbox`
- `pytweening`
- `pyscreeze`
- `pygetwindow`
- `mouseinfo`
- `pyrect`

This made setup slower and more fragile than necessary.

## Changes Made

Removed `pyautogui` from the required install path.

Added `gaze_mouse/windows_input.py`:

- Uses Windows `user32` APIs directly.
- Moves the mouse pointer with `SetCursorPos`.
- Fires left/right/double-click actions with `mouse_event`.
- Sends hotkeys with `keybd_event`.

Updated `gaze_mouse/mouse_controller.py`:

- Replaced `pyautogui` mouse movement and click calls with `WindowsInputController`.
- Keeps existing gaze smoothing, dwell timing, cooldowns, and action reset behavior.

Updated `gaze_mouse/tobii_calibration.py`:

- Replaced the old `pyautogui.hotkey(...)` path with direct `user32` hotkey sending.
- The Tobii calibration shortcut remains `Ctrl+Shift+F10`.

Updated `requirements.txt`:

- Removed `pyautogui>=0.9.54`.
- Remaining required packages are `PySide6`, `qtawesome`, and `tobii-research`.

Updated `setup_windows.ps1`:

- Package verification no longer requires `pyautogui`.
- Requirements installation now uses `--only-binary=:all:` so pip installs wheel packages and fails clearly instead of spending time building source packages.

Updated `README.md`:

- Documents Windows `user32` input instead of `pyautogui`.
- Documents wheel-only dependency installation.

## What Should Work Now

- Setup should no longer stop or appear stuck while building `pyautogui` dependency packages.
- Mouse movement and click simulation should still work on Windows through native `user32`.
- Tobii calibration launch should still send `Ctrl+Shift+F10`.
- The setup script should still:
  - Copy from the network share to local app data.
  - Install/find Python 3.10.
  - Install/find eSpeak NG with Bosnian support.
  - Create `.venv`.
  - Install dependencies.
  - Create launchers and desktop shortcut.

## What Is Not Confirmed

Real Windows runtime behavior was not executed from this Linux workspace:

- PowerShell is not available in this environment, so `setup_windows.ps1` could not be run here.
- The Tobii device is not available here.
- PySide6 is not installed in the local Linux Python environment.

## Validation Performed

Python syntax validation passed for all project Python files:

```text
python syntax ok
```

Direct imports passed for modules that do not require Qt:

```text
windows_input import ok
calibration import ok
```

Active setup/runtime files no longer reference `pyautogui`.

Cache scan was clean:

```text
find . -name '__pycache__' -o -name '*.pyc' -o -name '*.pyo'
```

Result: no output.

## Next Real-Machine Check

On the Windows Tobii machine, rerun:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1
```

Then confirm:

- The setup log reaches `Setup complete`.
- `run_gaze_mouse.bat` is created in `%LocalAppData%\TobiiGazeMouse`.
- The toolbar starts.
- Gaze moves the pointer.
- Left click, right click, and double left click still fire correctly.
- Settings calibration still triggers the Tobii calibration shortcut.
