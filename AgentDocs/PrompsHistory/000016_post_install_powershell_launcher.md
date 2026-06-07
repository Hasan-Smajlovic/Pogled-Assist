# 000016 - Post Install PowerShell Launcher

Date: 2026-06-06

## Original Prompt

```text
now create a windows power shell script which will start the program after installation, make sure it create shortcut on desktop
```

## Changes Made

Added `start_gaze_mouse.ps1`.

The script is intended to be run after setup has completed. It:

- Finds the installed app folder.
- Prefers `%LocalAppData%\TobiiGazeMouse`.
- Supports a custom install folder through `-InstallRoot`.
- Verifies `run_gaze_mouse.py` and `.venv\Scripts\python.exe` exist.
- Ensures the `Tobii Gaze Mouse` desktop shortcut exists.
- Points the desktop shortcut at `powershell.exe -NoProfile -ExecutionPolicy Bypass -File start_gaze_mouse.ps1`.
- Detects eSpeak NG in common install locations and sets `ESPEAK_NG_EXE` when found.
- Starts the program through the installed `.venv`.
- Keeps the launcher window open on failures unless `-NoPause` is used.
- Can also pause on normal app exit with `-PauseOnSuccess`.

Updated `setup_windows.ps1`:

- Copies `start_gaze_mouse.ps1` into the local install folder.
- Treats `start_gaze_mouse.ps1` as a required project file.
- Creates the desktop shortcut pointing to `start_gaze_mouse.ps1` instead of the batch file when the script is present.
- Final setup instructions now show `.\start_gaze_mouse.ps1` as the primary run command.

Updated `README.md`:

- Documents `start_gaze_mouse.ps1`.
- Documents it as the normal post-install launcher.

## Files Changed

- `start_gaze_mouse.ps1`
- `setup_windows.ps1`
- `README.md`

## Expected Windows Behavior

After successful setup, the installed folder should contain:

```text
%LocalAppData%\TobiiGazeMouse\start_gaze_mouse.ps1
```

The desktop should contain:

```text
Tobii Gaze Mouse.lnk
```

The shortcut should run the PowerShell launcher, which starts:

```text
%LocalAppData%\TobiiGazeMouse\.venv\Scripts\python.exe
%LocalAppData%\TobiiGazeMouse\run_gaze_mouse.py
```

## What Is Not Confirmed

PowerShell is not installed in this Linux workspace, so the launcher could not be executed here.

The full app still requires a Windows machine with:

- PySide6 installed in the setup-created venv.
- Tobii Eye Tracker 4C available.
- Tobii runtime/software available.

## Validation Performed

Python syntax validation passed:

```text
python syntax ok
```

Cache scan was clean:

```text
find . -name '__pycache__' -o -name '*.pyc' -o -name '*.pyo'
```

Result: no output.

## Next Real-Machine Check

On Windows:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1
```

Then test:

```powershell
.\start_gaze_mouse.ps1
```

Also double-click the desktop shortcut:

```text
Tobii Gaze Mouse
```
