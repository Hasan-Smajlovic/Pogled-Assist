# Prompt 000049 - Precision Zoom For Click Modes

## Original Prompt

In settings in Gaze tab add checkbox for toggling this zoom in which we are using in quick actions
If it's on it should be used not just for quick actions, but for left click, right click, double click outside of the quick actions as well

## Changes Made

- Added a new persisted gaze setting: `use_precision_zoom`.
  - Default is `true` to preserve the existing quick-action zoom behavior.
  - Loaded and saved through `data/app_settings.json` with the other gaze settings.

- Updated the fullscreen Settings window.
  - Added `Use precision zoom` checkbox in the `Gaze settings` tab.
  - The checkbox is gaze-selectable and mouse-clickable through the existing settings gaze interaction system.
  - The checkbox state is refreshed from saved settings and saved immediately when changed.

- Updated quick actions.
  - When `Use precision zoom` is enabled, quick actions keep the existing flow:
    1. Dwell on screen target.
    2. Open zoom square.
    3. Select refined target inside zoom.
    4. Open radial menu for left click, right click, double click, or cancel.
  - When `Use precision zoom` is disabled, quick actions skip zoom and open the radial menu directly at the dwell target.

- Updated normal armed click modes.
  - `Left click`, `Right click`, and `Double click` now use the zoom square when `Use precision zoom` is enabled.
  - Flow:
    1. Select `Left click`, `Right click`, or `Double click` from the hotbar.
    2. Dwell on the rough screen target.
    3. Zoom square opens around that target.
    4. Dwell/click inside the zoom square to select the precise point.
    5. The chosen click action fires at the mapped real screen coordinate.
  - When `Use precision zoom` is disabled, those click modes keep the previous direct dwell-to-click behavior.

- Updated hotbar zoom routing.
  - The same `QuickActionZoomWindow` is reused for both quick-action targeting and normal click targeting.
  - The hotbar tracks whether the active zoom belongs to quick actions or a normal click.
  - Quick-action zoom selection opens the radial menu.
  - Normal click zoom selection fires the pending click action.
  - Cancel/stale zoom paths now clear both possible zoom states safely.

- Updated README.
  - Documented the new `Use precision zoom` Gaze setting and its behavior for quick actions and normal click modes.

## What Should Work Now

- `Settings -> Gaze settings -> Use precision zoom` should toggle the zoom behavior.
- With the checkbox on:
  - Quick actions should use zoom before the radial menu.
  - Normal `Left click`, `Right click`, and `Double click` modes should use zoom before clicking.
- With the checkbox off:
  - Quick actions should open the radial menu directly.
  - Normal click modes should fire directly after dwell, as before.

## Important Notes

- The zoom square still uses the same dwell time and stable target radius settings as other gaze selections.
- Runtime behavior with a real Tobii device was not testable from this Linux workspace.

## Validation Performed

- Syntax-checked `gaze_mouse/mouse_controller.py`, `gaze_mouse/settings_store.py`, `gaze_mouse/settings_window.py`, and `gaze_mouse/toolbar.py` with `compile(...)` under `PYTHONDONTWRITEBYTECODE=1` and `python -B`.
- Confirmed no `__pycache__`, `.pyc`, or `.pyo` files were created.
- Runtime behavior with a real Tobii device was not testable from this Linux workspace.
