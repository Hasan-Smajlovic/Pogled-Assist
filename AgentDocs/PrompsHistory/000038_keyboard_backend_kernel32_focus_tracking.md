# 000038 - Keyboard Backend Kernel32 Focus Tracking

## Original Prompt

Keyboard is still not typing on the focused window!!!
It must be able to be used as onscreen gaze keyboard, to type the content in notepad or browser!!
Please look into issue and fix it, IT MUST WORK

## Log Diagnosis

- Inspected `logs/latest.txt` and `start_gaze_mouse.log`.
- The keyboard UI was opening and gaze actions were firing.
- The keyboard backend was not available at all.
- The latest error was:
  - `AttributeError: function 'GetCurrentThreadId' not found`
- This happened during `WindowsInputController()` initialization.
- Root cause: `GetCurrentThreadId` was incorrectly loaded from `user32.dll`.
- Correct Windows DLL: `kernel32.dll`.
- Because this backend failed to initialize, both keyboard input and mouse click input were unavailable.

## What Was Done

- Updated `gaze_mouse/windows_input.py`:
  - Added `self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)`.
  - Moved `GetCurrentThreadId` signature setup from `user32` to `kernel32`.
  - Updated `_force_foreground_window()` to call `self._kernel32.GetCurrentThreadId()`.
- Updated `gaze_mouse/keyboard_window.py`:
  - Added `set_target_window()` so the keyboard can receive a remembered external target window from the hotbar.
- Updated `gaze_mouse/toolbar.py`:
  - Added a foreground window tracker using `WindowsInputController`.
  - It primes the last external foreground window before the hotbar is shown.
  - It refreshes the last external foreground window every 250 ms.
  - It ignores this application's own windows, so browser/Notepad focus is not overwritten by the hotbar/sidebar.
  - It passes the remembered external target into the keyboard sidebar before the sidebar is shown.

## Files Changed

- `gaze_mouse/windows_input.py`
- `gaze_mouse/keyboard_window.py`
- `gaze_mouse/toolbar.py`
- `AgentDocs/PrompsHistory/000038_keyboard_backend_kernel32_focus_tracking.md`

## What Is Working

- The immediate backend initialization failure from the latest logs is fixed.
- The keyboard input backend should initialize instead of reporting:
  - `Keyboard input unavailable: function 'GetCurrentThreadId' not found`
- Mouse click control should also recover because it uses the same `WindowsInputController`.
- The keyboard now has a stronger remembered target-window path for typing into Notepad/browser inputs even when the Tobii UI has recently been clicked.

## What Needs Windows Runtime Confirmation

- This Linux workspace cannot execute Windows `user32`/`kernel32` APIs.
- On Windows, restart the app after copying/installing the updated files.
- The next log should show:
  - `Windows input controller initialized: input_size=40 pointer_size=8.`
- The log should no longer show:
  - `function 'GetCurrentThreadId' not found`
- Then test by focusing a Notepad or browser input and selecting keys from the gaze keyboard.

## Validation

- Python syntax compilation passed with `PYTHONDONTWRITEBYTECODE=1`.
- Checked for generated `__pycache__`, `.pyc`, and `.pyo` files; none were present.

