# 000040 - Quick Actions Zoom Precision

## Original Prompt

We have to improve quick actions
When something is selected with quick actions it has to create a zoom in rectangle with image of what's the selected, it has to be in square shape of selected item. 
this will give ultra focuse to what is selected and will allow us to have better precission. when zoom in square opens, then gaze should be active again to select position in that zoom in square, then gaze position must be applied correcly on real screen from that zoom in position
after gaze selection happened in that zoom in then it has to show those actions around the position (left click, right click, double left click and cancel)

## What Was Done

- Added `gaze_mouse/quick_action_zoom.py`.
- Added a fullscreen transparent zoom overlay for Quick actions.
- The first Quick actions dwell no longer opens the radial menu immediately.
- The new flow is:
  - User enables `Quick actions`.
  - User gazes steadily at the desktop/app target.
  - App captures a square screenshot around that target.
  - App opens a centered magnified square zoom view.
  - User gazes steadily inside the zoom square to pick the exact refined point.
  - The selected zoom-square point is mapped back to the real screen coordinate.
  - App opens the radial menu around the refined coordinate.
  - User selects left click, right click, double left click, or cancel by gaze dwell.
- Added normal mouse support for the zoom square:
  - Clicking inside the zoom square selects the refined point immediately.
  - Clicking outside the zoom square cancels the quick action.
  - Escape cancels the zoom window.
- Updated `gaze_mouse/mouse_controller.py`:
  - Added `quick_action_zoom_requested(QPoint)`.
  - Added `set_quick_target_from_logical()` so a refined logical point is converted to the same physical click coordinate mapping used by normal gaze samples.
  - Initial Quick actions dwell now requests the zoom overlay instead of directly requesting the radial menu.
- Updated `gaze_mouse/toolbar.py`:
  - Creates and manages `QuickActionZoomWindow`.
  - Routes gaze samples to the zoom overlay while it is open.
  - Shows the radial menu only after the zoom overlay emits the refined target.
  - Closes/cancels the zoom overlay when Quick actions are disabled, the hotbar is hidden/shown, settings opens, or the app quits.
- Updated `setup_windows.ps1`:
  - Added `gaze_mouse\quick_action_zoom.py` to required project file checks so Windows setup installs/copies the new module.
- Updated `README.md`:
  - Documented the new Quick actions precision zoom step and how the refined point maps back to real-screen clicks.

## Files Changed

- `gaze_mouse/quick_action_zoom.py`
- `gaze_mouse/mouse_controller.py`
- `gaze_mouse/toolbar.py`
- `setup_windows.ps1`
- `README.md`
- `AgentDocs/PrompsHistory/000040_quick_actions_zoom_precision.md`

## What Is Working

- Quick actions now have a two-step precision target flow before action selection.
- The zoom overlay displays a magnified square screenshot around the original gaze target.
- Gaze dwell inside the zoom square selects a refined point.
- The refined point is mapped back to the actual screen coordinate before the radial action menu opens.
- The radial menu opens around the refined point and still supports left click, right click, double left click, and cancel.
- The real mouse pointer is still not moved while the zoom square or radial menu is open, because the controller treats Quick actions selection as an active quick-action overlay.
- Normal mouse clicks still work for the zoom square and radial menu.

## What Was Not Runtime-Tested

- Full Windows runtime behavior was not tested in this Linux workspace.
- Tobii hardware gaze input, screenshot scaling on the Windows target, and physical click accuracy must be confirmed on the Tobii machine.
- PySide6 is not installed in this workspace, so validation was limited to Python syntax compilation.

## Validation

- Python syntax compilation passed with `PYTHONDONTWRITEBYTECODE=1`.
- Checked for generated `__pycache__`, `.pyc`, and `.pyo` files; none were present.

## Windows Testing Notes

- Rerun `setup_windows.ps1` on the Windows target so `gaze_mouse\quick_action_zoom.py` is copied into the installed app folder.
- Start the app, enable `Quick actions`, and gaze at a target.
- Expected behavior:
  - A centered square zoom view opens after the first dwell.
  - Looking inside the zoom square shows dwell progress and selects a refined point.
  - The radial menu opens around that refined point.
  - Selecting a sector applies the click at the refined point, not at the later sector gaze point.
- If click placement is still inaccurate on Windows, inspect `logs\latest.txt` for:
  - `Quick action zoom opened`
  - `Quick action zoom selected`
  - `Quick action refined target set`
  - `Firing click action`
  These log lines include the logical and physical coordinates needed to compare the zoom mapping against the actual click.
