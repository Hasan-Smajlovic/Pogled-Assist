# 000023 - Gaze Button Feedback Animation

Date: 2026-06-07

## Original Prompt

```text
Next for buttons in our application, when gaze is happening, add some sort of animation where they change colors so it's noticable that gaze is applied and that it's working. 

Make sure you add that to all buttons in our application
In settings, in tabs as well on speech on hotbar action buttons as well
```

## Changes Made

Added `gaze_mouse/gaze_feedback.py`.

- Provides shared gaze visual feedback for all button-like controls.
- Uses dynamic Qt properties:
  - `gazeTarget`
  - `gazePulse`
- Starts a small `QTimer` on the active widget.
- Alternates `gazePulse` every `180 ms`.
- Refreshes Qt styles after each pulse.
- Stops the timer and clears styles when gaze leaves the widget.

Updated `gaze_mouse/mouse_controller.py`.

- Added `toolbar_gaze_target_changed` signal.
- Tracks the current gaze-targeted toolbar/Speech action separately from dwell timing.
- Emits the current app action immediately after each gaze point is mapped, before dwell and cooldown checks.
- Emits `None` when gaze leaves the toolbar/Speech target.
- This keeps button feedback responsive even during the short cooldown after a gaze action fires.

Updated `gaze_mouse/toolbar.py`.

- Imports and uses `set_gaze_feedback`.
- Hotbar buttons now initialize `gazeTarget` and `gazePulse`.
- Hotbar stylesheet now includes pulsing gaze colors:
  - Yellow pulse state.
  - Green pulse state.
- Hotbar action buttons pulse while gaze is dwelling on them.
- This covers:
  - Left click
  - Right click
  - Double click
  - Speech
  - Keyboard
  - Settings

Updated `gaze_mouse/speech_window.py`.

- Imports and uses `set_gaze_feedback`.
- Tracks the currently gaze-targeted Speech action.
- Clears feedback when gaze leaves a button, when the window closes, and before dynamic keyboard buttons are rebuilt.
- Speech stylesheet now includes pulsing gaze colors for:
  - Letter group buttons
  - Letter buttons
  - Space
  - Backspace
  - Groups
  - Clear
  - Play
  - Close

Updated `gaze_mouse/settings_window.py`.

- Imports and uses `set_gaze_feedback`.
- Settings now uses the shared pulse animation instead of only a static `gazeTarget` style.
- Settings stylesheet now includes pulsing gaze colors for:
  - Exit
  - Gaze settings tab
  - Speech settings tab
  - Less/More controls
  - Move pointer from gaze
  - Start Tobii calibration
  - Test speech

Updated `setup_windows.ps1`.

- Added `gaze_mouse\gaze_feedback.py` to required file checks.

Updated `README.md`.

- Documents that buttons pulse while gaze dwell is active.
- Documents that this applies to hotbar, Speech, and Settings buttons.

## What Should Work Now

When gaze rests on any gaze-selectable button:

- The target button should visibly pulse between highlight colors.
- The user should be able to see that gaze dwell is being applied.
- The animation should stop when gaze leaves the button.
- Mouse clicking still works normally.

Covered UI surfaces:

- Hotbar buttons.
- Speech window buttons.
- Settings buttons.
- Settings tabs.

## What Is Not Confirmed

The Qt UI could not be rendered in this Linux workspace because PySide6 is not installed here.

The actual animation must be visually confirmed on the Windows Tobii machine.

## Validation Performed

Python syntax validation passed with an in-memory compile check:

```text
compiled gaze_mouse modules
```

Cache scan was clean:

```text
find . -name '__pycache__' -o -name '*.pyc' -o -name '*.pyo'
```

Result: no output.

Static scan confirmed all expected references:

- `gaze_feedback.py`
- `set_gaze_feedback`
- `gazePulse`
- `gazeTarget`
- `toolbar_gaze_target_changed`

## Next Real-Machine Check

On Windows:

1. Rerun setup so the local install folder receives `gaze_feedback.py`:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1
```

2. Start the app:

```powershell
.\start_gaze_mouse.ps1
```

3. Look at each hotbar button and confirm it pulses before activation.
4. Open Speech and confirm group, letter, utility, Play, Clear, and Close buttons pulse.
5. Open Settings and confirm Exit, both tabs, and all controls pulse.
