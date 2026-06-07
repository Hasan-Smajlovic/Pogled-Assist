# 000021 - Keyboard ShellExecute Fix

Date: 2026-06-07

## Original Prompt

```text
Oke this is right direction, kind of, now there's an issue with keyboard item in hotbar, it's just say Could not open keyaobrd [WinError 740....] then i cant read the rest it's split!

we need to fix that then we will work on optimization to make this work as fast as possible on low end PCs as well.
```

## Log Analysis

Reviewed `logs/latest.txt`.

The latest log confirms the Tobii x86 bridge direction is working:

- Stream Engine gaze samples are arriving.
- `Gaze provider sample ... from stream-engine` lines are present.
- Hotbar dwell actions are firing from gaze.
- Speech-window gaze actions are firing.
- Left click, right click, and double click actions are firing from gaze dwell.

The remaining issue was the Keyboard toolbar action:

```text
Toolbar action requested by gaze: keyboard
Could not open Windows on-screen keyboard.
OSError: [WinError 740] The requested operation requires elevation
Status: Could not open keyboard: [WinError 740] The requested operation requires elevation
```

The code was launching `osk.exe` with:

```python
subprocess.Popen(["osk.exe"], shell=False)
```

That uses Windows `CreateProcess`. `osk.exe` can require ShellExecute handling because of its elevation/uiAccess manifest, so `CreateProcess` returns `WinError 740`.

## Changes Made

Added `gaze_mouse/windows_keyboard.py`.

This module:

- Opens Windows keyboard surfaces with `ShellExecuteW`.
- Tries these targets:
  - `osk.exe`
  - `%WINDIR%\System32\osk.exe`
  - `%WINDIR%\Sysnative\osk.exe`
  - `%ProgramFiles%\Common Files\Microsoft Shared\ink\TabTip.exe`
- Logs each failed candidate.
- Returns the label of the keyboard surface that opened.
- Raises `WindowsKeyboardError` only after all launch targets fail.

Updated `gaze_mouse/toolbar.py`.

- Removed direct `subprocess.Popen(["osk.exe"])`.
- Uses `open_windows_keyboard()`.
- Shows short readable status text:

```text
Keyboard failed. Check logs.
```

- Full detailed errors still go into `logs/latest.txt`.
- `_set_status()` now also sets the status label tooltip to the full status text.

Updated `setup_windows.ps1`.

- Added `gaze_mouse\windows_keyboard.py` to required file checks.

Updated `README.md`.

- Documents that the Keyboard toolbar button opens `osk.exe` through ShellExecute and falls back to the Windows touch keyboard.

## What Should Work Now

When the Keyboard hotbar item is selected by gaze or clicked with mouse:

1. The app should call Windows ShellExecute instead of direct CreateProcess.
2. `WinError 740` should no longer happen for `osk.exe`.
3. If `osk.exe` cannot open, the app tries the touch keyboard fallback.
4. The toolbar should show a short readable failure if all launch attempts fail.
5. Full details should remain available in `logs/latest.txt`.

Expected success log:

```text
Opened Windows on-screen keyboard using ShellExecute target: osk.exe
Status: Windows on-screen keyboard opened.
```

If `osk.exe` fails and the fallback works:

```text
Could not open Windows on-screen keyboard using osk.exe: ...
Opened Windows touch keyboard using ShellExecute target: ...
Status: Windows touch keyboard opened.
```

## What Is Not Confirmed

Actual `osk.exe` launch could not be verified in this Linux workspace.

PowerShell setup and the Windows ShellExecute path need to be confirmed on the Windows Tobii machine.

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

On the Windows Tobii machine:

1. Close the app.
2. Rerun setup so the new `windows_keyboard.py` file is copied to the local install folder:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1
```

3. Start:

```powershell
.\start_gaze_mouse.ps1
```

4. Select `Keyboard` by gaze and by normal mouse click.
5. Check `logs/latest.txt`.

If the keyboard still does not open, the relevant new log lines will show which ShellExecute candidate failed and why.
