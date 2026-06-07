# 000036 - Keyboard Typing Grouping Hotbar Hide

## Original Prompt

1) Keyboard must type it in the focused input (notepad, browser, anywhere) what is selected. currently it's not typing anything....
2) Please apply grouping rules for the Numpad and Symbols as well
3) When Keyabord is opened and Hotbar is hidden, do not hide keyboard, keyboard must stay visable

## What Was Done

- Updated `gaze_mouse/windows_input.py` with foreground window helpers:
  - Get the current Windows foreground window.
  - Check if a stored window handle is still valid.
  - Restore a stored foreground window.
  - Detect if the current foreground window belongs to this application process.
- Updated `gaze_mouse/keyboard_window.py` so the sidebar keyboard:
  - Remembers the last external foreground window before opening.
  - Restores that external target before sending text or key presses.
  - Uses `SendInput` text/key delivery after the target window is restored.
  - Keeps the currently focused outside input as the typing target when the hotbar/sidebar do not take focus.
- Updated `gaze_mouse/toolbar.py` so the hotbar and restore button use no-focus tool-window flags.
- Removed the automatic keyboard close from hotbar hide behavior.
- Removed the explicit hotbar activation call when showing the hotbar again.
- Added grouped first-level screens for Numpad and Symbols using the same configured `letters_per_group` value as the letter keyboard.
- Added group drill-down behavior for:
  - Numpad groups
  - Symbol groups
- Kept the existing bottom utility buttons:
  - Groups
  - Space
  - Backspace

## Files Changed

- `gaze_mouse/windows_input.py`
- `gaze_mouse/keyboard_window.py`
- `gaze_mouse/toolbar.py`
- `AgentDocs/PrompsHistory/000036_keyboard_typing_grouping_hotbar_hide.md`

## What Is Working

- The hotbar no longer intentionally steals foreground focus from Notepad/browser/other apps.
- The keyboard sidebar no longer intentionally steals foreground focus.
- The keyboard tries to restore the remembered external target window before typing each selected character/key.
- Numpad and Symbols now open as grouped pages first.
- The configured speech/keyboard letter group size now controls Numpad and Symbol grouping too.
- Hiding the hotbar while the keyboard sidebar is open leaves the keyboard visible.
- Gaze and mouse selection still use the same registered keyboard action path.

## What Needs Windows Runtime Confirmation

- Final typing behavior must be verified on the Windows test machine because this Linux workspace cannot execute Windows `user32` APIs or PySide UI behavior against real Windows foreground windows.
- If Windows blocks `SetForegroundWindow` for a specific elevated application, the app may need to run at the same privilege level as the target app.

## Validation

- Python syntax compilation passed with `PYTHONDONTWRITEBYTECODE=1`.
- Checked for generated `__pycache__`, `.pyc`, and `.pyo` files; none were present.

