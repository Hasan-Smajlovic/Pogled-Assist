# Prompt 000050 - Hotbar Button Spacing Order

## Original Prompt

1) In the hot bar, put settings button to be between Hide and Quick Actions Button, make some space between them
2) Move Left click, Right clik and Double click closer to the Quick Actions
3) Make a bit of space between Left Click, Right Click, Double Click and Speech and Keyboard buttons

## Changes Made

- Updated `gaze_mouse/toolbar.py`.
  - Split the hotbar button definitions into click buttons, secondary buttons, a dedicated Settings button, and the Quick actions button.
  - Moved `Settings` out of the old centered button group.
  - Rebuilt the hotbar layout as one left-side cluster:
    - `Hide`
    - `Settings`
    - `Quick actions`
    - `Left click`
    - `Right click`
    - `Double click`
    - gap
    - `Speech`
    - `Keyboard`
  - Left/right/double click buttons are now directly beside Quick actions instead of being centered farther away.
  - Added a larger spacer before Speech and Keyboard so those controls visually separate from the click-action group.
  - Kept the tracker/eye indicators on the right side of the hotbar.

- Updated `README.md`.
  - Documented the new hotbar order.
  - Updated Quick actions wording to account for the precision zoom toggle.

## What Should Work Now

- Settings should appear between Hide and Quick actions in the hotbar.
- Left click, right click, and double click should sit close to Quick actions.
- Speech and Keyboard should remain to the right of the click actions with a visible gap between groups.
- Existing gaze and mouse behavior should continue because every moved button is still registered in the same `_buttons` action map.

## Important Notes

- Runtime visual spacing was not screenshot-tested from this Linux workspace.
- If the Windows test machine has a very narrow primary display, the left cluster may become dense because all main controls now occupy one row.

## Validation Performed

- Syntax-checked `gaze_mouse/toolbar.py` with `compile(...)` under `PYTHONDONTWRITEBYTECODE=1` and `python -B`.
- Confirmed no `__pycache__`, `.pyc`, or `.pyo` files were created.
- Runtime visual spacing was not screenshot-tested from this Linux workspace.
