# 000020 - Tobii Core X86 Bridge Fix

Date: 2026-06-07

## Original Prompt

```text
no, tobii still not working with this....

On the windows machine there is installed tobii eyetracking 
Tobii Eye Tracking Core Software v2.16.8

"https://gaming.tobii.com/getstarted/?srsltid=AfmBOopFlx6Nv-OFcUls1ImYTbkpWSHzd0INB6_ni3tA1sg5ED1uBuXm"

And it there, it does not have a gaze mechanizam, but eye tracking works perfecly


For some reason this does not work correcty with this program, it's not applying gaze or maybe not recognizin that it's working and that it's there!

There are logsi n /logs folder, please inspect what is happening, find the issue and fix it
```

## Log Analysis

Reviewed `logs/latest.txt`, `logs/20260607_002430_814792.txt`, and `start_gaze_mouse.log`.

The latest runtime log showed:

- App launched correctly from the local install folder.
- Runtime logs were written back to the network project root.
- The hotbar and AppBar started.
- The Windows mouse controller started.
- `tobii-research` found no tracker.
- Stream Engine fallback found Tobii DLLs under `C:\Program Files (x86)\Tobii\...`.
- Every direct DLL load failed with:

```text
[WinError 193] %1 is not a valid Win32 application
```

That error means the Tobii DLLs found on the Windows machine are 32-bit DLLs, while the app is running inside 64-bit Python:

```text
Python executable: C:\Users\Korisnik\AppData\Local\TobiiGazeMouse\.venv\Scripts\python.exe
Python version: 3.10.11 ... 64 bit (AMD64)
```

The app was not failing because the Tobii software was missing. It was failing because the Tobii Eye Tracking Core Software v2.16.8 installation exposes 32-bit Stream Engine DLLs, and those cannot be loaded inside the 64-bit GUI process.

## Changes Made

Added `gaze_mouse/tobii_stream_engine_bridge.py`.

- Runs as a separate subprocess.
- Must run under 32-bit Python.
- Loads Tobii Stream Engine through the existing `TobiiStreamEngineBackend`.
- Emits JSON lines to stdout:
  - `started`
  - `gaze`
  - `error`
  - `stopped`
- Keeps all detailed bridge logs on stderr so the parent app can record them.

Added `gaze_mouse/tobii_stream_engine_bridge_backend.py`.

- Runs in the main 64-bit GUI process.
- Finds 32-bit Python from:
  - `TOBII_GAZE_MOUSE_X86_PYTHON`
  - `py -3.10-32`
  - common per-user install paths such as `%LocalAppData%\Programs\Python\Python310-32\python.exe`
  - common `%ProgramFiles(x86)%` Python paths
- Starts the bridge subprocess with `-B -u`.
- Reads bridge stdout JSON messages.
- Forwards `gaze` messages to the existing gaze callback.
- Logs bridge stderr into `logs/latest.txt`.
- Waits up to 12 seconds for bridge startup.
- Stops the bridge subprocess when the app exits.

Updated `gaze_mouse/gaze_provider.py`.

Startup order is now:

1. Try `tobii-research`.
2. Try direct Stream Engine in the 64-bit process.
3. If direct Stream Engine fails, try the 32-bit Stream Engine bridge.
4. If all fail, retry every 3 seconds.

Updated `gaze_mouse/tobii_stream_engine.py`.

- The DLL load error now explains that `WinError 193` means the x86 bridge is required.
- `tobii_device_create` now supports both known Stream Engine signatures:
  - `tobii_device_create(api, url, field_of_use, device)`
  - `tobii_device_create(api, url, device)`
- The wrapper tries the 4-argument form first, then the 3-argument form.
- `TOBII_STREAM_ENGINE_DEVICE_CREATE_ARGS=3` or `4` can force a specific mode if needed.

Updated `setup_windows.ps1`.

- Adds new switch: `-SkipX86BridgePythonInstall`.
- Automatically installs 32-bit Python 3.10 from the official Python.org installer when missing.
- Uses installer file `python-3.10.11.exe`.
- Installs to:

```text
%LocalAppData%\Programs\Python\Python310-32
```

- Verifies that the bridge Python is Python 3.10 and 32-bit.
- Records the bridge Python path in `install_info.json` as `BridgePythonX86`.
- Exports `TOBII_GAZE_MOUSE_X86_PYTHON` in generated launch scripts.
- Requires the new bridge files in the setup file check.
- Final setup output now lists the 32-bit Python used by the Tobii bridge.

Updated `start_gaze_mouse.ps1`.

- Resolves 32-bit Python before starting the app.
- Reads `BridgePythonX86` from `install_info.json`.
- Falls back to `py -3.10-32` and common install paths.
- Exports `TOBII_GAZE_MOUSE_X86_PYTHON` for the Python app.
- Logs the bridge Python path in `start_gaze_mouse.log`.

Updated `README.md`.

- Documents the 32-bit bridge requirement for Tobii Eye Tracking Core Software 2.x.
- Documents that `[WinError 193]` means setup should be rerun to install the x86 bridge runtime.
- Documents the new expected success log:

```text
Tobii Stream Engine x86 bridge started ...
```

## What Should Work Now

On the Windows Tobii machine with Tobii Eye Tracking Core Software v2.16.8:

1. `setup_windows.ps1` should install or find 64-bit Python 3.10 for the GUI.
2. `setup_windows.ps1` should install or find 32-bit Python 3.10 for the Tobii bridge.
3. `start_gaze_mouse.ps1` should set `TOBII_GAZE_MOUSE_X86_PYTHON`.
4. The app should try direct Stream Engine, see that the installed DLL cannot be loaded in 64-bit Python, then start the x86 bridge.
5. The x86 bridge should load `C:\Program Files (x86)\Tobii\...\tobii_stream_engine.dll`.
6. Gaze samples should flow back into the existing gaze provider.
7. Mouse movement, hotbar dwell, Speech-window gaze selection, Settings-window gaze selection, and stare-click actions should receive gaze data.

Expected runtime log lines after rerunning setup:

```text
Trying Tobii Stream Engine x86 bridge after direct backend failure...
Starting Tobii Stream Engine x86 bridge...
Found 32-bit Python for Tobii bridge...
Tobii x86 bridge loaded DLL: ...
Tobii Stream Engine x86 bridge started with ...
Gaze provider sample #1 from stream-engine: ...
Tracking with ... (x86 bridge).
```

## What Is Not Confirmed

Actual hardware streaming could not be confirmed in this Linux workspace.

PowerShell scripts could not be executed locally because Windows PowerShell is not installed in this environment.

The real confirmation must be done on the Windows machine with the Tobii Eye Tracker 4C connected, Tobii Eye Tracking Core Software running, and setup rerun after these changes.

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

Static scans confirmed:

- New bridge files are referenced by setup.
- `TOBII_GAZE_MOUSE_X86_PYTHON` is set by generated launchers.
- `start_gaze_mouse.ps1` can discover the 32-bit bridge Python.
- README documents the `[WinError 193]` fix.

## Next Real-Machine Check

On Windows:

1. Close the app if it is running.
2. Rerun setup from the project/network folder:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1
```

3. Confirm setup logs a line like:

```text
Using 32-bit Python 3.10 bridge executable: C:\Users\Korisnik\AppData\Local\Programs\Python\Python310-32\python.exe
```

4. Start the app:

```powershell
.\start_gaze_mouse.ps1
```

5. Check:

```text
start_gaze_mouse.log
logs\latest.txt
```

6. Confirm `logs\latest.txt` contains:

```text
Tobii Stream Engine x86 bridge started
Gaze provider sample #1
```

If the bridge starts but there are no gaze samples, the next likely issue is Stream Engine device enumeration or Tobii Core state, and the bridge stderr lines in `logs/latest.txt` should show the exact failing API call.
