# 000017 - Network Source Launcher Logs

Date: 2026-06-06

## Original Prompt

```text
oke, now make sure that when start_gaze_mouse.ps1 is running it's storing log at the same location from which it is installed. As I am using the network to acces project root on this device and teting on another, i need those logs to be in the same folder
```

## Changes Made

Updated `setup_windows.ps1`:

- Writes `install_info.json` into the active install folder after the working root is resolved.
- Stores:
  - `SourceRoot`
  - `InstallRoot`
  - `CreatedAt`
- When setup is launched from a network share and copies the app to `%LocalAppData%\TobiiGazeMouse`, `SourceRoot` remains the original network/project folder.

Updated `start_gaze_mouse.ps1`:

- Reads `install_info.json` from the installed app folder.
- Uses `SourceRoot` as the log root when it is available.
- Adds a `-LogRoot` override for manual log-root selection.
- Starts a PowerShell transcript at:

```text
<SourceRoot>\start_gaze_mouse.log
```

- Sets this environment variable before starting Python:

```text
TOBII_GAZE_MOUSE_LOG_ROOT=<SourceRoot>
```

- Logs the exact runtime latest log path before starting the app.

Updated `gaze_mouse/logging_setup.py`:

- Runtime logs now honor `TOBII_GAZE_MOUSE_LOG_ROOT`.
- When that environment variable is set, app logs are written under:

```text
<TOBII_GAZE_MOUSE_LOG_ROOT>\logs\latest.txt
```

Updated `README.md`:

- Documents `start_gaze_mouse.log`.
- Documents that network-share installs write runtime logs back to the original source/network project folder.

## Expected Behavior

Network workflow:

1. Run setup from a share such as:

```text
\\192.168.0.30\Tobii\setup_windows.ps1
```

2. Setup copies the app locally to:

```text
%LocalAppData%\TobiiGazeMouse
```

3. Setup writes:

```text
%LocalAppData%\TobiiGazeMouse\install_info.json
```

4. Running `start_gaze_mouse.ps1` writes launcher logs to:

```text
\\192.168.0.30\Tobii\start_gaze_mouse.log
```

5. The Python app writes runtime logs to:

```text
\\192.168.0.30\Tobii\logs\latest.txt
```

## What Is Not Confirmed

PowerShell is not installed in this Linux workspace, so `setup_windows.ps1` and `start_gaze_mouse.ps1` could not be executed locally.

The behavior should be verified on the Windows Tobii machine after rerunning setup so the new `install_info.json` is created.

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

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1
.\start_gaze_mouse.ps1
```

Then verify these files appear in the network project folder:

```text
start_gaze_mouse.log
logs\latest.txt
```
