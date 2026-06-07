# 000024 - Gaze Bubble Overlay Toggle

Date: 2026-06-07

## Original Prompt

```text
now we need to have a boubble which will follow follow the eye movement on the screen so we always know where it is. 
Make sure it's kind of transparent.

Also add ability to turn it on and off in the settings
```

## Changes Made

Added `gaze_mouse/gaze_bubble.py`.

- Adds `GazeBubbleWindow`, a small transparent top-level overlay that follows the latest gaze point.
- The bubble is drawn with translucent rings and a small center dot.
- The bubble uses Qt transparent-window attributes and `WindowTransparentForInput` when available.
- On Windows, the bubble also applies native extended window styles:
  - `WS_EX_LAYERED`
  - `WS_EX_TRANSPARENT`
  - `WS_EX_NOACTIVATE`
- This is intended to keep the bubble visual-only so it does not steal mouse clicks from the desktop or app controls underneath it.
- The bubble raises itself lightly every `250 ms` while gaze is active so it should remain visible above Speech and Settings fullscreen windows without doing extra work on every gaze sample.

Updated `gaze_mouse/mouse_controller.py`.

- Added `show_gaze_bubble: bool = True` to `GazeSettings`.
- The existing `gaze_position_changed` signal remains the source for overlay movement.
- The bubble receives logical Qt screen coordinates, matching the same coordinate system used for app hit testing.

Updated `gaze_mouse/toolbar.py`.

- Creates one `GazeBubbleWindow` owned by the hotbar.
- Connects `GazeMouseController.gaze_position_changed` to `GazeBubbleWindow.handle_gaze`.
- Adds `_update_gaze_settings()` so gaze settings updates now apply both to the mouse controller and the bubble visibility setting.
- Disables and closes the bubble when the hotbar exits.

Updated `gaze_mouse/settings_window.py`.

- Added a gaze-selectable and mouse-clickable `Show gaze bubble` button in `Gaze settings`.
- The button is checkable and reflects `GazeSettings.show_gaze_bubble`.
- Gaze dwell selection and classic mouse clicks both toggle the setting.
- Changed the gaze action button area to a compact grid so `Move pointer from gaze`, `Show gaze bubble`, and `Start Tobii calibration` do not crowd one row on smaller screens.

Updated `setup_windows.ps1`.

- Added `gaze_mouse\gaze_bubble.py` to required project-file checks.

Updated `README.md`.

- Documents that the app shows a transparent gaze bubble over the latest gaze point.
- Documents that the bubble can be toggled from `Gaze settings`.

## What Should Work Now

- When Tobii gaze samples arrive, a semi-transparent bubble should follow the gaze point on screen.
- The bubble should appear over the hotbar, Speech window, Settings window, and normal desktop/apps.
- The bubble should not block normal mouse clicks because it is configured as click-through.
- `Settings` -> `Gaze settings` -> `Show gaze bubble` should turn the bubble on and off.
- The `Show gaze bubble` setting should work with Tobii gaze dwell selection and with normal mouse clicks.
- The bubble follows the raw logical gaze point emitted by the controller, so it is not delayed by pointer smoothing.

## What Is Not Confirmed

The actual transparent overlay could not be visually tested in this Linux workspace because PySide6 and the Windows Tobii runtime are not available here.

The Windows native click-through style path could not be runtime-tested here. It should be verified on the Tobii machine by moving the gaze bubble over a button or desktop item and confirming normal mouse clicks still reach the item underneath.

Runtime settings are still not persisted across app restarts. `show_gaze_bubble` defaults to `True` each time the program starts, matching the current non-persistent settings behavior.

## Validation Performed

Python syntax validation passed with bytecode disabled:

```text
PYTHONDONTWRITEBYTECODE=1 python - <<'PY'
from pathlib import Path
files = sorted(Path('gaze_mouse').glob('*.py')) + [Path('run_gaze_mouse.py')]
for path in files:
    compile(path.read_text(encoding='utf-8'), str(path), 'exec')
print('python syntax ok')
PY
```

Result:

```text
python syntax ok
```

Cache scan was clean:

```text
find . \( -name '__pycache__' -o -name '*.pyc' -o -name '*.pyo' \) -print
```

Result: no output.

Static scan confirmed the expected references:

- `gaze_mouse/gaze_bubble.py`
- `GazeBubbleWindow`
- `show_gaze_bubble`
- `Show gaze bubble`
- `gaze_position_changed.connect(self._gaze_bubble.handle_gaze)`
- `gaze_mouse\gaze_bubble.py` in `setup_windows.ps1`

## Next Real-Machine Check

On Windows:

1. Rerun setup so the local install folder receives `gaze_bubble.py`:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1
```

2. Start the app:

```powershell
.\start_gaze_mouse.ps1
```

3. Confirm the bubble appears and follows gaze as soon as tracking starts.
4. Open Settings and toggle `Show gaze bubble` off and on with gaze.
5. Toggle it again using the mouse.
6. Confirm mouse clicks still pass through the bubble to whatever is underneath it.
7. If the bubble appears behind Speech or Settings, inspect `logs\latest.txt` for overlay or Qt window warnings.
