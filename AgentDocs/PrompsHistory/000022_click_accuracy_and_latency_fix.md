# 000022 - Click Accuracy And Latency Fix

Date: 2026-06-07

## Original Prompt

```text
Oke, now let's fix some issues with using left click, right click and double left click actions. they are not beng applied on the screen correcly... they are way off and offten not working at all. 
Please look into that, make sure it's accurate as much as possible.
Make sure it's gathering current gaze position as fast as possible
Make sure there is no delays at all!
```

## Log Analysis

Reviewed `logs/latest.txt`.

The logs showed the Tobii x86 bridge is working and gaze samples are arriving:

```text
Stream Engine gaze sample #...
Gaze provider sample #... from stream-engine
Toolbar dwell action fired: ...
Firing click action ...
```

Two click-accuracy issues were visible.

First, Stream Engine sometimes reports normalized display-area values slightly outside `0..1`, for example:

```text
Stream Engine gaze sample #23100: x=0.4751 y=1.0067
Gaze provider sample #23100 from stream-engine: x=0.0004 y=0.0012
```

That conversion was wrong. The raw value was still a normalized gaze value that only needed clamping to the screen edge. Instead, the app treated it as a pixel coordinate and divided it by screen size, causing huge jumps toward the top-left.

Second, the logs showed a DPI/scaling mismatch:

```text
Positioning hotbar on primary screen: left=0 top=0 width=1216 height=811.
Windows AppBar positioned: left=0 top=0 right=2736 bottom=171 dpi=216.
```

Qt was using logical coordinates, while Windows cursor APIs need physical coordinates. The old controller used the same `QPoint` for both Qt hit testing and Windows `SetCursorPos`, which can make clicks land far away on scaled displays.

## Changes Made

Updated `gaze_mouse/gaze_provider.py`.

- Added a normalized-coordinate margin.
- Stream Engine values in the range `-0.5..1.5` are now treated as normalized display-area coordinates and clamped.
- Values are only treated as pixel coordinates when they clearly look like pixel coordinates.
- This fixes cases like `x=0.4751 y=1.0067` being converted to `x=0.0004 y=0.0012`.

Updated `gaze_mouse/windows_input.py`.

- Added `ScreenRect`.
- Added `primary_screen_rect()`.
- Reads the primary monitor physical rectangle using Windows monitor APIs.
- Falls back to `GetSystemMetrics` if monitor info is unavailable.
- Reduced click press duration from `20 ms` to `5 ms`.
- Reduced default double-click interval to `40 ms`.

Updated `gaze_mouse/mouse_controller.py`.

- Added `GazeScreenPoint` containing:
  - `logical`: Qt logical coordinates for toolbar, Speech, and Settings hit testing.
  - `physical`: Windows physical coordinates for cursor movement and actual clicks.
- Gaze hit testing now uses logical coordinates.
- Actual left click, right click, and double left click now use physical coordinates.
- Click firing uses the latest raw gaze point instead of the smoothed cursor point.
- Pointer smoothing now affects only cursor movement, not the actual click target.
- Default gaze settings are more responsive:

```text
smoothing = 1.0
dwell_ms = 500
dwell_radius_px = 48
click_cooldown_ms = 350
```

- Added a startup log line showing logical and physical screen mapping:

```text
Gaze screen mapping: logical=... physical=...
```

Updated `gaze_mouse/settings_window.py`.

- Lowered the minimum stare time from `250 ms` to `150 ms`.
- Lowered the minimum repeat delay from `250 ms` to `100 ms`.

Updated `gaze_mouse/tobii_stream_engine.py`.

- Increased Stream Engine callback polling from 120 Hz to 240 Hz.
- This reduces app-side waiting for freshly available Tobii samples without changing Tobii hardware sample rate.

Updated `README.md`.

- Documents that gaze selection uses Qt logical coordinates while real cursor/click actions use Windows physical coordinates.
- Documents that lower stare time and repeat delay make clicks fire faster.

## What Should Work Now

Left click, right click, and double left click should:

- Use current gaze coordinates more directly.
- Avoid the top-left jump when Stream Engine returns values slightly outside the display bounds.
- Click the Windows physical screen position that corresponds to the gaze target on high-DPI/scaled displays.
- Fire faster after dwell because click press duration and double-click interval were reduced.
- Keep hotbar/Speech/Settings gaze selection accurate because those surfaces still use Qt logical coordinates.

Expected new log lines on Windows:

```text
Gaze screen mapping: logical=0,0 1216x811 physical=0,0 2736x...
Firing click action left_click at physical=... logical=...
```

When Stream Engine reports a value such as:

```text
x=0.4751 y=1.0067
```

The provider should now log approximately:

```text
x=0.4751 y=1.0000
```

instead of:

```text
x=0.0004 y=0.0012
```

## What Is Not Confirmed

The Qt app and Windows cursor behavior could not be executed in this Linux workspace because PySide6 and Windows APIs are not available here.

The real confirmation must be done on the Windows Tobii machine.

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

Also checked that `ctypes.wintypes` provides `HMONITOR` and `POINT` in this Python environment.

## Next Real-Machine Check

On the Windows Tobii machine:

1. Close the app.
2. Rerun setup so the local install folder receives the updated files:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1
```

3. Start the app:

```powershell
.\start_gaze_mouse.ps1
```

4. Check `logs/latest.txt` for:

```text
Gaze screen mapping: logical=... physical=...
```

5. Test left click, right click, and double left click on known large targets.
6. If clicks are still offset, compare the physical screen size in the mapping log with Windows Display Settings resolution and scaling.
7. If clicks are accurate but too sensitive, increase stare time or repeat delay in Settings.
