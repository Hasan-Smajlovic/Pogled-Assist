# Prompt 000046 - Start Menu Topmost Overlays

## Original Prompt

Make sure that mouse hover overlay and this action indicator get's rendered on top of the Start menu as well
Currently it's being rendered behind it.

Our application must be rendering on top of everything!

## Changes Made

- Added `gaze_mouse/windows_z_order.py`.
  - Provides `force_window_topmost(...)`.
  - Uses Win32 `SetWindowPos(HWND_TOPMOST, ...)` with `SWP_NOACTIVATE`, `SWP_NOOWNERZORDER`, `SWP_NOMOVE`, and `SWP_NOSIZE`.
  - This reasserts topmost z-order at the Windows API level instead of relying only on Qt's `WindowStaysOnTopHint`.

- Updated `gaze_mouse/gaze_bubble.py`.
  - Gaze bubble now calls `force_window_topmost(...)` after it is shown.
  - Added a 100 ms refresh timer while the bubble is visible, so it can reclaim topmost z-order if the Start menu opens after the bubble.

- Updated `gaze_mouse/interaction_overlay.py`.
  - Action indicator/progress overlay now calls `force_window_topmost(...)` when shown.
  - Its existing animation timer now reasserts Win32 topmost z-order every 100 ms while visible.

- Updated quick-action overlays for consistency.
  - `gaze_mouse/quick_action_menu.py` now reasserts topmost z-order when shown and every 100 ms while visible.
  - `gaze_mouse/quick_action_zoom.py` now reasserts topmost z-order when shown and every 100 ms while visible.

- Updated setup validation.
  - `setup_windows.ps1` now includes `gaze_mouse/windows_z_order.py` in required project files.

## What Should Work Now

- The transparent gaze bubble should stay above the Windows Start menu.
- The animated action indicator should stay above the Windows Start menu.
- Quick-action radial and zoom overlays should also stay above Start menu and similar shell UI while visible.

## Important Notes

- This uses normal Win32 topmost z-order. It cannot draw over Windows secure desktop surfaces such as UAC consent prompts, lock screen, or Ctrl+Alt+Del security UI.
- Runtime behavior over the actual Windows Start menu was not testable from this Linux workspace.

## Validation Performed

- Syntax-checked changed Python files with `compile(...)` under `PYTHONDONTWRITEBYTECODE=1` and `python -B`.
- Imported `gaze_mouse.windows_z_order` under `python -B`.
- Confirmed no `__pycache__`, `.pyc`, or `.pyo` files were created.

