# 000015 - Setup Verification Quoting Fix

Date: 2026-06-06

## Original Prompt

```text
again, there an issue with the insallation script setup_windows.log
That must work perfectly....

Analize the log and fix the issue pretty fucking please
```

## Setup Log Analysis

The latest run in `setup_windows.log` started at `2026-06-06 21:52:19`.

This run successfully completed the major install steps:

- Detected the network path.
- Copied the project to `C:\Users\Korisnik\AppData\Local\TobiiGazeMouse`.
- Found Python 3.10.
- Found eSpeak NG 1.52.0 with Bosnian voice support.
- Reused the local `.venv`.
- Installed Python requirements with `--only-binary=:all:`.

The actual failure happened during package verification:

```text
File "<string>", line 7
    raise SystemExit(Missing
                    ^
SyntaxError: '(' was never closed
```

Root cause:

- `setup_windows.ps1` passed a multi-line Python program through `python -c`.
- Windows PowerShell 5.1/native-command argument handling stripped the embedded double quotes inside the Python code.
- Python received `raise SystemExit(Missing packages: ...` instead of `raise SystemExit("Missing packages: ...")`, so verification failed even though dependencies were already installed.

## Changes Made

Updated `setup_windows.ps1` in `Verify-PythonPackages`:

- No longer passes the verification program through `python -c`.
- Writes the verification program to a temporary `.py` file under `%TEMP%`.
- Runs the venv Python executable against that temporary file.
- Deletes the temporary verification file in a `finally` block.

This avoids PowerShell 5.1 quote stripping entirely.

## Expected Result

On the next Windows run, the script should continue past:

```text
Verifying installed Python packages
```

and then proceed to:

- Create `run_gaze_mouse.bat`.
- Create `run_gaze_mouse.ps1`.
- Create the desktop shortcut unless disabled.
- Print final setup instructions.
- Finish with success.

## What Is Not Confirmed

PowerShell is not installed in this Linux workspace, so `setup_windows.ps1` could not be executed locally.

The fix is based on the exact error in the Windows transcript and avoids the failing command-line quoting path.

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

On the Windows Tobii machine, rerun:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1
```

Then verify the log reaches:

```text
Setup script finished successfully.
```
