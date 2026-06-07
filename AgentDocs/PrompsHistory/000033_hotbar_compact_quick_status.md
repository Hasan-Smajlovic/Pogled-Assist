# 000033 - Hotbar Compact Quick Status

## Original Prompt

in the hotbar, make Hide 50% smaller
on the right side where it shojws the bridge with tobii driver, just show red, yellow, and green dot depending on status of connection

Put the Quick actions on the right side, next to the hide button, ubt make some space. When quick actions is active, do not show left click, right click and double click actions

## Files Changed

- `gaze_mouse/toolbar.py`
- `README.md`

## What Was Done

- Removed `Quick actions` from the centered hotbar button group.
- Added a dedicated `Quick actions` button beside `Hide` on the left side of the hotbar.
- Added 26 px of spacing between `Hide` and `Quick actions`.
- Reduced `Hide` from `116x58` to `58x58`.
- Changed `Hide` to icon-over-text so it can fit inside the smaller width.
- Replaced the right-side tracker text label with a small status dot.
- Tracker dot colors:
  - Green: active tracking, based on `Tracking with ...` or a tracker label.
  - Yellow: waiting, starting, trying fallback, or retrying.
  - Red: failed, unavailable, missing, disabled, not found, or error statuses.
- The tracker dot keeps the full status text as a tooltip.
- Added `_set_click_action_buttons_visible()` so explicit click action buttons can be hidden or restored.
- When Quick actions is enabled, the explicit `Left click`, `Right click`, and `Double click` hotbar buttons are hidden.
- When Quick actions is disabled, those explicit click action buttons are shown again.
- Updated `README.md` to document:
  - Compact Hide button.
  - Quick actions beside Hide.
  - Tracker connection dot.
  - Hidden explicit click buttons while Quick actions is active.

## What Should Work Now

- `Hide` takes about half the previous horizontal space.
- `Quick actions` appears immediately to the right of `Hide`, with spacing between them.
- The old text showing tracker/bridge details on the right side is gone.
- The right side shows only the colored tracker dot.
- Hovering the dot should still reveal the detailed tracker/status text as a tooltip.
- Activating Quick actions hides the separate left/right/double-click buttons.
- Disabling Quick actions shows those buttons again.
- Gaze and mouse activation still work for `Hide`, `Quick actions`, and the remaining hotbar buttons.

## Not Fully Verified

- The PySide6 UI could not be visually launched in this Linux workspace.
- Final layout spacing should be checked on the Windows Tobii machine, especially at lower screen widths.

## Validation

Ran syntax validation with bytecode disabled:

```bash
PYTHONDONTWRITEBYTECODE=1 python - <<'PY'
from pathlib import Path
files = sorted(Path('gaze_mouse').glob('*.py')) + [Path('run_gaze_mouse.py')]
for path in files:
    compile(path.read_text(encoding='utf-8'), str(path), 'exec')
print('python syntax ok')
PY
```

Result:

```text
python syntax ok
```

Checked for generated Python cache artifacts:

```bash
find . \( -name '__pycache__' -o -name '*.pyc' -o -name '*.pyo' \) -print
```

Result: no cache files found.

## Notes For Next Agent

- Main file: `gaze_mouse/toolbar.py`.
- Relevant sections:
  - `BUTTONS` and `QUICK_ACTION_BUTTON`.
  - `_build_ui()` for layout and tracker dot creation.
  - `_sync_quick_actions_button()` for hiding explicit click buttons.
  - `_tracker_dot_state()` for color mapping.
- If the user wants the Hide button even smaller vertically, adjust `setFixedSize(58, 58)` in `_build_ui()`.
