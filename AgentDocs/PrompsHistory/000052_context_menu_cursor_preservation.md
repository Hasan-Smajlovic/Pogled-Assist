# Prompt 000052 - Context Menu Cursor Preservation

## Original Prompt

There's a small issue with simulating clicks, for example when right click is applied on desktop
and this toolbar appears then when you try to click it closes it! It msut not do that, it msut work properpy
so everything can be done on PC with just gaze controle

## Changes Made

- Updated `gaze_mouse/mouse_controller.py`.
  - Changed the gaze handling order so toolbar/application UI detection happens before moving the real Windows cursor.
  - The real cursor now only moves when gaze is outside this app's own UI surfaces.
  - Gaze over toolbar buttons, the restore button, speech window, keyboard sidebar, settings window, quick-action menu, or zoom overlay can still select those controls, but it no longer drags the Windows cursor onto the application UI.
  - Added a native-menu follow-up state after right clicks.
  - After any right click, the controller automatically arms `Left click` for menu selection.
  - The one follow-up left click bypasses precision zoom so a fullscreen zoom overlay does not close the native context menu before the menu item can be clicked.

- Updated `README.md`.
  - Documented that gaze-selecting controls inside this application does not move the real Windows cursor.
  - Documented why this matters for desktop context menus and similar popups.
  - Documented the automatic direct left-click follow-up after right clicks.

## Why This Fix Matters

Previously, after a right click opened a desktop context menu, looking back at the hotbar could move the real cursor to the hotbar before the hotbar dwell action fired. Some Windows menus/popups close when the pointer leaves or when focus/hover changes in that way. That made it difficult to perform right-click workflows using gaze only.

The new behavior keeps the real cursor at the context menu or desktop target while the user looks at the hotbar to arm the next action. The hotbar still receives gaze dwell events because app UI selection uses Qt coordinates and does not require physically moving the Windows cursor.

The controller also treats a right click as the start of a native menu workflow. It automatically arms a direct left click after the right click. That avoids a second trip to the toolbar and avoids precision zoom opening a fullscreen overlay that could close the native context menu.

## What Should Work Now

- Right-clicking the desktop with gaze should open the desktop context menu.
- Looking back at the hotbar to choose `Left click`, `Right click`, `Double click`, `Quick actions`, Settings, Speech, or Keyboard should not move the real cursor away from the context menu.
- After the right click, `Left click` should be armed automatically for choosing a menu item.
- Looking at a menu item should move/click on the menu item directly without opening precision zoom.
- Other gaze-selectable application windows should also be selectable without moving the real Windows cursor onto them.

## Important Notes

- Runtime behavior with actual Windows context menus was not testable from this Linux workspace.
- This change intentionally separates "gaze selection of app UI" from "real cursor movement on external Windows UI".

## Validation Performed

- Syntax-checked `gaze_mouse/mouse_controller.py` with `compile(...)` under `PYTHONDONTWRITEBYTECODE=1` and `python -B`.
- Confirmed no `__pycache__`, `.pyc`, or `.pyo` files were created.
- Runtime behavior with actual Windows context menus was not testable from this Linux workspace.
