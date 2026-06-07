# Prompt 000051 - Keyboard Full Height When Hotbar Hidden

## Original Prompt

When Keyboard is active, and hotbar is hidden, make sure that right sidebar takes full height of the screen!

## Changes Made

- Updated `gaze_mouse/keyboard_window.py`.
  - Added `_full_height` state to the right-side keyboard panel.
  - `show_sidebar(...)` now accepts `full_height`.
  - Added `set_full_height(...)` so the existing visible keyboard panel can resize immediately.
  - `_position_on_primary_screen()` now uses:
    - `screen.geometry()` when full-height mode is enabled.
    - `screen.availableGeometry()` when full-height mode is disabled.
  - Full-height mode unregisters the keyboard's right-side AppBar reservation before resizing.
  - Full-height mode skips re-registering the keyboard AppBar, so Windows work-area constraints cannot keep the panel below the former hotbar area.
  - When full-height mode is disabled, the keyboard returns to available-work-area sizing and re-registers the right-side AppBar.

- Updated `gaze_mouse/toolbar.py`.
  - When the hotbar is hidden, an already-visible keyboard panel switches to full-height mode.
  - When the hotbar is shown again, the keyboard panel switches back to available-work-area height below the hotbar.
  - When the keyboard panel is opened, it starts in full-height mode only if the hotbar is currently hidden.

- Updated `README.md`.
  - Documented that the keyboard sidebar expands to full screen height while the hotbar is hidden, skips right AppBar reservation in that mode, and returns to work-area height when the hotbar is shown again.

## What Should Work Now

- If the keyboard panel is open and the hotbar is hidden, the keyboard panel should immediately resize to the full screen height.
- If the hotbar is shown again while the keyboard panel is still open, the panel should resize back below the hotbar.
- If the keyboard panel is opened while the hotbar is hidden, it should open full height from the start.
- In full-height mode, the keyboard should not reserve a right-side Windows work area.

## Important Notes

- Runtime visual behavior was not screenshot-tested from this Linux workspace.
- On Windows, the keyboard panel only registers its right-side AppBar reservation when the hotbar is visible and the keyboard is using available-work-area height.

## Validation Performed

- Syntax-checked `gaze_mouse/toolbar.py` and `gaze_mouse/keyboard_window.py` with `compile(...)` under `PYTHONDONTWRITEBYTECODE=1` and `python -B`.
- Confirmed no `__pycache__`, `.pyc`, or `.pyo` files were created.
- Runtime visual behavior was not screenshot-tested from this Linux workspace.
