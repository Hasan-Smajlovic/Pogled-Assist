# 000041 - Two Eye Tracking Gate

## Original Prompt

for actions to take place both eyes must be open, make sure that if one eye is closed it does not move the cursor, it must stay in it's last postiion, also on the top bar next to the indicator of connection with tobii (with green, yellow and red dot) it must show two white dots which represent eyes, when both eyes are open it must show them both of them, when one is open it must show which one is open and closed one should not be rendered!

## What Was Done

- Added left/right eye-status signaling to `gaze_mouse/gaze_provider.py`.
- The provider now emits gaze samples only when both eyes are valid.
- For the `tobii-research` backend:
  - Left and right gaze-point validity are checked separately.
  - Gaze output is the average of both eyes only when both are valid.
  - If one eye is invalid, no gaze position is emitted.
- For the Tobii Stream Engine backend and the x86 bridge:
  - Added a normalized eye-position subscription.
  - Added a gaze-origin subscription fallback if normalized eye position is unavailable or not supported.
  - Added `TobiiEyePositionNormalized` and `EyePositionReceiver` ctypes bindings.
  - Added `TobiiGazeOrigin` and `GazeOriginReceiver` ctypes bindings.
  - Added left/right validity handling from Stream Engine eye-position samples.
  - Added `eyes` JSON messages from the 32-bit bridge process to the 64-bit GUI process.
  - Main provider now blocks Stream Engine gaze output until eye-status data is known and both eyes are valid.
- Updated `gaze_mouse/mouse_controller.py`:
  - Added `handle_eye_status()`.
  - Cursor movement and gaze dwell handling are ignored unless both eyes are open.
  - If either eye becomes invalid, toolbar dwell, target dwell, quick-action dwell, and quick-action target state are cancelled.
  - Cursor smoothing is reset so the cursor resumes cleanly when both eyes are valid again.
- Updated `gaze_mouse/toolbar.py`:
  - Added two white eye dots next to the Tobii connection dot.
  - Left dot represents left eye, right dot represents right eye.
  - Closed/invalid eyes are rendered transparent, preserving left/right position while visually hiding the closed eye.
  - Active Quick actions zoom/menu overlays close if one eye becomes invalid.
- Updated `gaze_mouse/speech_window.py`, `gaze_mouse/keyboard_window.py`, and `gaze_mouse/settings_window.py`:
  - Added cancel hooks so stale gaze highlights/dwell progress clear when one eye becomes invalid.
- Updated `README.md`:
  - Documented the new two-eye requirement.
  - Documented the two eye dots and behavior when one eye is closed.

## Files Changed

- `gaze_mouse/gaze_provider.py`
- `gaze_mouse/tobii_stream_engine.py`
- `gaze_mouse/tobii_stream_engine_bridge.py`
- `gaze_mouse/tobii_stream_engine_bridge_backend.py`
- `gaze_mouse/mouse_controller.py`
- `gaze_mouse/toolbar.py`
- `gaze_mouse/speech_window.py`
- `gaze_mouse/keyboard_window.py`
- `gaze_mouse/settings_window.py`
- `README.md`
- `AgentDocs/PrompsHistory/000041_two_eye_tracking_gate.md`

## What Is Working

- Gaze movement and gaze-triggered actions are gated behind both eyes being valid.
- If either eye becomes invalid:
  - No new gaze position is emitted to the mouse controller.
  - The real cursor stays at its last position.
  - Active dwell progress is cancelled.
  - Quick actions zoom/menu overlays close.
  - Speech, Keyboard, and Settings gaze highlights are cleared.
- The hotbar now shows eye visibility independently from tracker connection:
  - Both white dots visible means both eyes are valid.
  - Only the left white dot visible means only the left eye is valid.
  - Only the right white dot visible means only the right eye is valid.
  - No white dots visible means neither eye is currently valid or the tracker has not reported eye status yet.

## What Was Not Runtime-Tested

- Actual Tobii 4C hardware behavior was not tested in this Linux workspace.
- Stream Engine eye-position or gaze-origin subscription must be confirmed on the Windows Tobii machine.
- PySide6 runtime UI rendering was not tested here because PySide6 is not installed in this workspace.

## Validation

- Python syntax compilation passed with `PYTHONDONTWRITEBYTECODE=1`.
- Checked for generated `__pycache__`, `.pyc`, and `.pyo` files; none were present.

## Windows Testing Notes

- Start the app on the Tobii machine and confirm that `logs\latest.txt` contains Stream Engine eye samples:

```text
Stream Engine eye-position eye sample #1: left_open=... right_open=...
# or
Stream Engine gaze-origin eye sample #1: left_open=... right_open=...
Eye status from stream-engine changed: left_open=... right_open=...
```

- With both eyes open:
  - Both white dots should be visible.
  - Cursor movement and gaze dwell actions should work.
- Close one eye:
  - The matching eye dot should disappear.
  - The cursor should stop at its last position.
  - Dwell actions should not continue or fire.
- Open both eyes again:
  - Both white dots should appear.
  - Gaze movement and dwell actions should resume.
