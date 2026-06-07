# 000055 Controller Keyboard Sidebar Layout

## Original prompt

1) In Controler sidebar, make sure when keyboard is opened trough it it usese the same space, same right sidebar,
    Make sure those Genral Keybaord Speech and Settings tabs are still visable!

2) When Any right sidebar is open, and hotbar is closed, and hotbar is open again it should squize the right sidebar,
    to make space for hotbar, as righ tnot hotbar get's rendered behind right sidebar and is not accessable!

3) Move the Show Hotbar float button on the top left position of the screen!

4) In Settings windwos move Quit App on the right side of the screen! It should be in same row, just on the right side
    Where it currently is "Genral settings" label

5) In Controler sidebar on Left Click, Right Click, Double Left Click, ENTER, Scroll Up and Scroll Down buttons please add Icons!

## What changed

- Updated `gaze_mouse/controller_window.py`.
  - Controler `Keyboard` tab no longer opens the separate standalone Keyboard sidebar.
  - Controler now renders its own embedded keyboard content inside the same right sidebar.
  - The main Controler tabs remain visible while using the embedded keyboard:
    - General
    - Keyboard
    - Speech
    - Settings
  - Embedded keyboard supports:
    - Letters
    - Numpad
    - Symbols
    - Groups
    - Space
    - Backspace
  - Embedded keyboard uses the same Bosnian alphabet and same `letters_per_group` speech setting as the standalone Keyboard panel.
  - Embedded keyboard uses the same Windows input backend and restores the last external target window before typing.
  - Added icons to Controler General buttons:
    - Left Click
    - Right Click
    - Double Left Click
    - ENTER
    - Scroll Up
    - Scroll Down
  - Added `set_reserved_top_height()` so Controler can reserve space under the hotbar when the hotbar is visible again.

- Updated `gaze_mouse/keyboard_window.py`.
  - Added `set_reserved_top_height()` to the standalone Keyboard sidebar.
  - When not full-height, the standalone Keyboard sidebar now honors an explicit top reservation so it starts below the hotbar even if Windows `availableGeometry()` is slow to update.
  - Increased grid row stretch cleanup range to handle very small letter group sizes without stale row stretch.

- Updated `gaze_mouse/toolbar.py`.
  - When hiding the hotbar, visible right sidebars switch to full-height mode and clear the reserved top height.
  - When showing the hotbar, visible right sidebars are given the hotbar height reservation before switching back out of full-height mode.
  - Hotbar is raised after sidebars resize so it remains accessible.
  - The floating `Show` button now appears near the top-left of the primary screen.
  - Controler is now created with both gaze settings and speech settings.
  - Speech setting updates are forwarded to Controler so the embedded keyboard grouping stays in sync.
  - Removed the stale Controler-to-standalone-keyboard signal path.

- Updated `gaze_mouse/settings_window.py`.
  - Moved `Quit app` from beside the top-left `Exit` button into the General settings header row.
  - The button is aligned on the right side of that header row.

- Updated `README.md`.
  - Documented embedded Controler keyboard behavior.
  - Documented top-left floating `Show` button.
  - Documented new `Quit app` position.
  - Documented Controler General button icons.

## What is expected to work

- Opening Controler and selecting the `Keyboard` tab keeps the same Controler sidebar open.
- The Controler main tabs remain visible above embedded keyboard controls.
- Embedded keyboard selections work with gaze dwell and mouse clicks.
- Embedded keyboard types into the last focused external app/window using the Windows input backend.
- The standalone hotbar `Keyboard` button still opens the standalone Keyboard sidebar and still closes Controler first.
- If any right sidebar is full height while the hotbar is hidden, pressing `Show` should resize it below the hotbar before the hotbar is raised.
- Floating `Show` appears at the top-left of the primary screen.
- Settings `Quit app` appears on the right side of the `General settings` header row.
- Controler General buttons show icons.

## Validation

- Parsed changed Python files with `ast.parse`:
  - `gaze_mouse/controller_window.py`
  - `gaze_mouse/keyboard_window.py`
  - `gaze_mouse/toolbar.py`
  - `gaze_mouse/settings_window.py`
- Verified no stale `keyboard_requested` references remain in source/README files.
- Verified no `__pycache__`, `.pyc`, or `.pyo` files remain in the workspace.

## Notes

- The Windows GUI/Tobii hardware behavior was not executed in this Linux workspace. The next validation should be done on the Windows test machine.
