# 000037 - Keyboard SendInput ctypes Fix

## Original Prompt

It's still not able to type in the browser with the keyabord!!!
It must be able to type anywhere! Simulate via python key press based on what is selected on the keyabord!

## Log Diagnosis

- Inspected `logs/latest.txt` and `start_gaze_mouse.log`.
- The keyboard panel was receiving gaze actions correctly.
- The keyboard panel was selecting letter actions correctly.
- The failure happened inside `WindowsInputController.type_text()`.
- Windows returned:
  - `[WinError 87] The parameter is incorrect.`
- The failing API was `SendInput`.
- Root cause: the ctypes `_INPUT` structure only modeled keyboard input in its union. On Windows, `SendInput` expects the full `INPUT` structure size, including the largest union member. With only `_KEYBDINPUT`, the structure size can be too small, causing `SendInput` to reject the call with error 87.

## What Was Done

- Updated `gaze_mouse/windows_input.py` to define the full Windows `INPUT` union:
  - `_MOUSEINPUT`
  - `_KEYBDINPUT`
  - `_HARDWAREINPUT`
  - `_INPUTUNION`
  - `_INPUT`
- Changed `SendInput` signature to use `ctypes.POINTER(_INPUT)` instead of a generic void pointer.
- Changed Unicode typing to pass `wVk=0`, UTF-16 code unit in `wScan`, and `KEYEVENTF_UNICODE`, matching the Windows API requirement.
- Changed Backspace, Enter, and hotkeys to use the same corrected `SendInput` path instead of `keybd_event`.
- Added a keyboard-layout fallback using `VkKeyScanW` for normal characters if Unicode `SendInput` ever fails.
- Added stronger foreground-window restore with `AttachThreadInput`, `BringWindowToTop`, `SetFocus`, and `SetForegroundWindow`.
- Added a runtime log showing the corrected `INPUT` structure size and pointer size when the Windows input controller initializes.

## Files Changed

- `gaze_mouse/windows_input.py`
- `AgentDocs/PrompsHistory/000037_keyboard_sendinput_ctypes_fix.md`

## What Is Working

- The previous `[WinError 87] The parameter is incorrect` failure path has been addressed at the ctypes structure level.
- Text selection from the keyboard now uses corrected Windows `SendInput` keyboard events.
- Backspace, Enter, and calibration hotkeys also use corrected `SendInput` events.
- If the browser or another target app loses foreground focus to the Tobii UI, the app now tries a stronger Windows foreground restore before typing.

## What Needs Windows Runtime Confirmation

- Final typing must be tested on the Windows target machine because this Linux workspace cannot call Windows `user32.SendInput`.
- After restarting the app, the Windows log should include a line similar to:
  - `Windows input controller initialized: input_size=40 pointer_size=8.`
- If the app runs at a lower privilege level than the target application, Windows UIPI can still block injected input. The app and target browser/editor should run at the same privilege level.

## Validation

- Python syntax compilation passed with `PYTHONDONTWRITEBYTECODE=1`.
- Checked for generated `__pycache__`, `.pyc`, and `.pyo` files; none were present.

