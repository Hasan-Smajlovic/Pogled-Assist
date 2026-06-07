# 000057 Independent Start Menu Overlays

## Original prompt

Gaze cursor and gaze interaction indicator and focus window are still being render behind start menu!!!

Please look into this, its crucial they start rendering on top of it!
Thi sis the start menu  on the left side

## What changed

- Updated `gaze_mouse/toolbar.py`.
  - Gaze overlay windows are no longer created as children/owned tool windows of the hotbar.
  - These are now independent top-level windows:
    - `GazeBubbleWindow`
    - `InteractionOverlayWindow`
    - `QuickActionZoomWindow`
    - `QuickActionRadialMenu`
  - The hotbar still explicitly closes these windows during shutdown.

- Updated `gaze_mouse/gaze_bubble.py`.
  - Changed the gaze cursor from a parented `Qt.Tool` style overlay to an independent `Qt.Window` overlay.
  - Keeps no-focus and transparent-input flags.
  - Continues to use aggressive Win32 topmost reinforcement.

- Updated `gaze_mouse/interaction_overlay.py`.
  - Changed the gaze interaction indicator from a parented `Qt.Tool` style overlay to an independent `Qt.Window` overlay.
  - Keeps no-focus and transparent-input flags.
  - Continues to use aggressive Win32 topmost reinforcement.

- Updated `gaze_mouse/quick_action_zoom.py`.
  - Changed the focus/zoom window from `Qt.Tool` to independent `Qt.Window`.
  - Added `WA_ShowWithoutActivating`.
  - Removed `activateWindow()` and focus forcing on open so it does not fight the Start menu focus state.
  - Continues to use aggressive Win32 topmost reinforcement.

- Updated `gaze_mouse/quick_action_menu.py`.
  - Changed the quick action radial menu from `Qt.Tool` to independent `Qt.Window`.
  - Added `WA_ShowWithoutActivating`.
  - Removed `activateWindow()` and focus forcing on open so it does not fight the Start menu focus state.
  - Continues to use aggressive Win32 topmost reinforcement.

- Updated `gaze_mouse/windows_z_order.py`.
  - Aggressive topmost mode now includes `SWP_FRAMECHANGED` after applying extended styles.

## Why this matters

The previous topmost pass still used Qt-owned `Tool` windows created with the hotbar as parent. Windows can keep owned tool windows below shell UI surfaces even when `SetWindowPos(HWND_TOPMOST)` is called repeatedly. This change makes the affected overlays independent top-level no-activate windows before applying the Win32 topmost reinforcement.

## What is expected to work

- Gaze cursor should no longer be constrained by the hotbar's owner z-order.
- Gaze interaction indicator should no longer be constrained by the hotbar's owner z-order.
- Quick action zoom/focus window should no longer be constrained by the hotbar's owner z-order.
- Quick action radial menu should no longer be constrained by the hotbar's owner z-order.
- The overlays should continue to refresh their Win32 topmost state every 33 ms while visible.

## Remaining Windows limitation

If the Windows Start menu is still drawn above these independent top-level topmost windows, then that specific shell surface is in a higher protected/immersive Z-band than normal desktop topmost windows. The next implementation step would be packaging the app as an assistive-technology executable with `uiAccess=true`, signing it, and installing it in a trusted location such as `Program Files`.

## Validation

- Parsed changed Python files with `ast.parse`:
  - `gaze_mouse/toolbar.py`
  - `gaze_mouse/windows_z_order.py`
  - `gaze_mouse/gaze_bubble.py`
  - `gaze_mouse/interaction_overlay.py`
  - `gaze_mouse/quick_action_zoom.py`
  - `gaze_mouse/quick_action_menu.py`
- Verified no `__pycache__`, `.pyc`, or `.pyo` files remain in the workspace.

## Notes

- Windows GUI / Start menu Z-order behavior could not be executed in this Linux workspace. This must be validated on the Windows test machine.
