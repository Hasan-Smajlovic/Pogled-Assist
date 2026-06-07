# 000019 - Tobii 4C Stream Engine Fallback

Date: 2026-06-07

## Original Prompt

```text
there's an issue with bridging tobii eye tracker 4c with the application, tracking does not work, gaze and staring do not work!
They must work. You have logs in logs folder. analize them and make corrections
```

## Log Analysis

Reviewed `logs/latest.txt`.

The runtime log showed the application starting correctly on Windows:

- The hotbar was created.
- The Windows AppBar reservation succeeded.
- The mouse controller started with the Windows `user32` input backend.
- Toolbar, Speech, Settings, and mouse-click UI actions were working with normal mouse clicks.

The gaze failure was here:

```text
Starting Tobii gaze provider.
Scanning for Tobii eye trackers.
No Tobii eye trackers were found.
Status: No Tobii eye tracker found.
```

There were no later gaze sample logs, so the dwell/stare system never received gaze positions. The code was only using the `tobii-research` backend. Tobii Eye Tracker 4C is a consumer tracker and is commonly available through Tobii Stream Engine/runtime even when the Pro SDK path does not enumerate it.

The log also showed an unrelated Windows keyboard launch problem:

```text
OSError: [WinError 740] The requested operation requires elevation
```

That keyboard issue was not changed in this prompt because the requested failure was Tobii gaze tracking.

## Changes Made

Added `gaze_mouse/tobii_stream_engine.py`.

This new module is a `ctypes` wrapper for Tobii Stream Engine:

- Searches for `tobii_stream_engine.dll` and `StreamEngineClient.dll`.
- Supports explicit `TOBII_STREAM_ENGINE_DLL`.
- Supports `TOBII_STREAM_ENGINE_DLL` pointing to a DLL file or a folder.
- Searches the app root and these bundled locations:
  - `tools`
  - `tools\tobii`
  - `tools\tobii-stream-engine`
- Searches common Tobii runtime roots:
  - `%ProgramFiles%\Tobii`
  - `%ProgramFiles(x86)%\Tobii`
  - `%LocalAppData%\Tobii`
  - `%ProgramData%\Tobii`
- Recursively scans Tobii folders for the DLL.
- Adds the DLL folder to the Windows DLL search path before loading, so sibling dependency DLLs can load.
- Creates the Stream Engine API and device.
- Enumerates local device URLs.
- Subscribes to gaze point samples.
- Runs a callback pump thread.
- Emits normalized gaze coordinates back to the app.
- Logs the first gaze sample and every 300th sample.

Updated `gaze_mouse/gaze_provider.py`.

The gaze provider now:

- Tries `tobii-research` first.
- If `tobii-research` finds no tracker, tries the Stream Engine fallback.
- If neither backend finds a tracker, retries automatically every 3 seconds.
- Logs backend startup status.
- Logs first and periodic gaze-provider samples.
- Normalizes Stream Engine coordinates.
- Caches primary-screen geometry on the Qt main thread before using it for any fallback normalization.

Updated `setup_windows.ps1`.

- Copies optional `tools` folder into the local install folder when setup runs from a network share.
- Requires `gaze_mouse\tobii_stream_engine.py` during repository file checks.
- Adds final setup notes about the Stream Engine fallback and runtime log.

Updated `README.md`.

- Documents that the app tries `tobii-research` first and then Tobii Stream Engine.
- Documents how to confirm tracking in logs.
- Documents that `tobii_stream_engine.dll` can be placed under `tools\tobii`.
- Documents `TOBII_STREAM_ENGINE_DLL` for explicit DLL selection.

## What Should Work Now

On the Tobii Windows machine, startup should now do this:

1. Try the existing `tobii-research` backend.
2. If no tracker is found, try the Tobii Stream Engine fallback.
3. If a Stream Engine compatible 4C is found, begin emitting gaze samples.
4. Those samples feed the existing mouse controller.
5. Gaze movement, hotbar dwell actions, Speech-window gaze selection, Settings-window gaze selection, and armed target clicks should start working.

Expected successful runtime log lines include:

```text
Trying Tobii Stream Engine fallback.
Tobii Stream Engine backend started with ...
Stream Engine gaze sample #1: ...
Gaze provider sample #1 from stream-engine: ...
Tracking with ...
```

If the DLL is not found, expected log lines include:

```text
Tobii Stream Engine DLL load attempts failed: ...
Stream Engine unavailable: tobii_stream_engine.dll was not found. Install Tobii Core/Game Hub or set TOBII_STREAM_ENGINE_DLL to the DLL path.
No Tobii eye tracker found. Retrying.
```

In that case, install Tobii Core/Game Hub on the Tobii machine or copy `tobii_stream_engine.dll` into:

```text
tools\tobii\tobii_stream_engine.dll
```

Then rerun setup or launch from the install folder again.

## What Is Not Confirmed

Actual Tobii hardware streaming could not be confirmed in this Linux workspace.

The real confirmation must be done on the Windows machine with the Tobii Eye Tracker 4C connected, Tobii runtime installed, and the tracker calibrated.

PowerShell setup/launcher execution was also not run locally because this workspace is Linux and does not have Windows PowerShell or the Tobii runtime.

## Validation Performed

Python syntax validation passed:

```text
python syntax ok
```

Bytecode/cache scan was clean:

```text
find . -name '__pycache__' -o -name '*.pyc' -o -name '*.pyo'
```

Result: no output.

Static code scan confirmed the new Stream Engine log paths and setup copy behavior are present.

## Next Real-Machine Check

On the Windows Tobii machine:

1. Rerun setup from the project/network folder:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1
```

2. Start the app:

```powershell
.\start_gaze_mouse.ps1
```

3. Open `logs\latest.txt` in the project root.
4. Confirm one of these paths:
   - `Tracking with ...` from `tobii-research`.
   - `Tobii Stream Engine backend started ...` and `Gaze provider sample #1 from stream-engine`.
5. If Stream Engine DLL is not found, install Tobii Core/Game Hub or place the DLL under `tools\tobii`, rerun setup, and start again.
