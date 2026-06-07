# 000056 Start Menu Overlay Topmost

## Original prompt

Zoom in window, and gaze cursor are stil lnot rendered on top of the start menu!!!!!

It's critical for it to be rendered on top of it!

## What changed

- Updated `gaze_mouse/windows_z_order.py`.
  - Added an aggressive topmost mode to `force_window_topmost()`.
  - Aggressive mode:
    - Detaches the Win32 owner from Qt-owned tool windows with `GWLP_HWNDPARENT`.
    - Applies overlay extended styles:
      - `WS_EX_TOPMOST`
      - `WS_EX_TOOLWINDOW`
      - `WS_EX_NOACTIVATE`
    - Calls `SetWindowPos(HWND_TOPMOST, ...)` without preserving owner z-order.
    - Uses `SWP_ASYNCWINDOWPOS` to help when the shell/start menu is owned by another thread.
  - Added 32-bit and 64-bit compatible `GetWindowLong` / `SetWindowLong` handling.

- Updated `gaze_mouse/gaze_bubble.py`.
  - Gaze cursor/bubble now uses aggressive topmost mode.
  - Topmost refresh interval changed from 100 ms to 33 ms while visible.

- Updated `gaze_mouse/quick_action_zoom.py`.
  - Zoom-in precision window now uses aggressive topmost mode.
  - Topmost refresh interval changed from 100 ms to 33 ms while visible.

- Updated `gaze_mouse/quick_action_menu.py`.
  - Quick action radial menu now uses aggressive topmost mode.
  - Topmost refresh interval changed from 100 ms to 33 ms while visible.

- Updated `gaze_mouse/interaction_overlay.py`.
  - Action/progress overlay now uses aggressive topmost mode.
  - Topmost refresh interval changed from 100 ms to 33 ms while visible.

## What is expected to work

- Gaze bubble should be reinserted into the Win32 topmost band repeatedly while visible.
- Quick action zoom square should be reinserted into the Win32 topmost band repeatedly while visible.
- Quick action radial menu should be reinserted into the Win32 topmost band repeatedly while visible.
- Gaze interaction progress/fired overlay should be reinserted into the Win32 topmost band repeatedly while visible.
- Detaching the Win32 owner should avoid the overlay being kept behind the hotbar/main Qt owner window.

## Important limitation

Windows Start menu and some shell surfaces can be displayed in a protected shell/immersive Z-band above normal topmost windows. This change uses the strongest normal Win32 topmost path available to an unsigned Python process. If Windows still keeps the Start menu above these overlays on the target machine, the next step is a packaged/signed executable with `uiAccess=true` installed in a trusted location, which is how assistive technology apps are allowed to draw above more shell UI.

## Validation

- Parsed changed Python files with `ast.parse`:
  - `gaze_mouse/windows_z_order.py`
  - `gaze_mouse/gaze_bubble.py`
  - `gaze_mouse/quick_action_zoom.py`
  - `gaze_mouse/quick_action_menu.py`
  - `gaze_mouse/interaction_overlay.py`
- Verified no `__pycache__`, `.pyc`, or `.pyo` files remain in the workspace.

## Notes

- Windows GUI / Start menu Z-order behavior could not be executed in this Linux workspace. This must be validated on the Windows test machine.
