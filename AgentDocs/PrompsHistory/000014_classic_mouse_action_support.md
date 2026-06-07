# 000014 - Classic Mouse Action Support

Date: 2026-06-06

## Original Prompt

```text
Make sure all of the actions on the hotbar and gaze work with classic mouse as well
```

## What Was Checked

Inspected the active UI code for hotbar, speech window, and settings window:

- `gaze_mouse/toolbar.py`
- `gaze_mouse/speech_window.py`
- `gaze_mouse/settings_window.py`

The speech window already registered every gaze-selectable button with a normal Qt `clicked` handler:

- Close
- Clear
- Play
- Letter groups
- Letters
- Space
- Backspace
- Period
- Groups/back navigation

The settings window already registered every gaze-selectable settings control with a normal Qt `clicked` handler:

- Exit
- Gaze settings tab
- Speech settings tab
- Less/More buttons for all settings
- Move pointer from gaze
- Start Tobii calibration
- Test speech

The hotbar already had normal mouse click handlers for:

- Left click
- Right click
- Double click
- Speech
- Keyboard
- Settings

## Changes Made

Updated `gaze_mouse/toolbar.py`:

- Hotbar buttons now show a pointing-hand cursor for classic mouse use.
- Hotbar action handling now distinguishes between `mouse` and `gaze` sources.
- Classic mouse clicks now respect the checked state of click-mode buttons.
- Clicking `Left click`, `Right click`, or `Double click` with a mouse arms that mode.
- Clicking the same armed click-mode button again with a mouse now unarms it.
- Gaze dwell still arms click modes reliably and does not accidentally toggle them off through the normal mouse checked-state path.

Updated `gaze_mouse/settings_window.py`:

- Settings buttons now show a pointing-hand cursor for classic mouse use.

Updated `README.md`:

- Documents that every gaze-selectable toolbar, speech, and settings button is also a normal clickable Qt button.
- Documents that clicking the same hotbar click mode again unarms it.

## Current Behavior

Classic mouse support:

- Hotbar buttons can be clicked normally.
- Speech window buttons can be clicked normally.
- Settings window buttons can be clicked normally.
- Hotbar click modes can be armed/unarmed with normal mouse clicks.

Gaze support:

- Hotbar buttons can still be activated by gaze dwell.
- Speech window buttons can still be activated by gaze dwell.
- Settings window buttons can still be activated by gaze dwell.
- Armed click modes still fire by gaze dwell on the target point.

## What Is Not Confirmed

This workspace cannot run the full Qt/Tobii application because:

- PySide6 is not installed in the local Linux Python environment.
- The Tobii Eye Tracker 4C is not available here.
- Windows-only mouse input and AppBar APIs cannot be exercised from this environment.

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

1. Launch `run_gaze_mouse.bat`.
2. Click each hotbar button with a normal mouse.
3. Confirm `Left click`, `Right click`, and `Double click` arm and unarm from mouse clicks.
4. Open Speech and confirm all speech buttons work with mouse clicks and gaze dwell.
5. Open Settings and confirm tabs, Exit, Less/More, calibration, and speech test work with mouse clicks and gaze dwell.
