# 000026 - Hotbar Hide Restore Button

Date: 2026-06-07

## Original Prompt

```text
Now in hotbar on top, add action to hide the hotbar. 
When hidden there must be like floating button on right bottom side of the screen to show it again. This hide button must in hotbar must be on the left side of the hotbar

So where you are showing applied actions, dont show applied actions anymore but put in that position the hide button
```

## Changes Made

Updated `gaze_mouse/mouse_controller.py`.

- Added toolbar action constants:
  - `HIDE_HOTBAR = "hide_hotbar"`
  - `SHOW_HOTBAR = "show_hotbar"`
- Added action-overlay labels for these actions:
  - `Hide`
  - `Show`
- This lets the existing gaze dwell engine activate hide/show the same way it activates hotbar buttons.

Updated `gaze_mouse/toolbar.py`.

- Replaced the visible left-side status/action label with a `Hide` `QToolButton`.
- The hotbar no longer displays applied action messages like click coordinates in the UI.
- Runtime status/action information is still logged through `_set_status()`, but it is now stored as tooltip/log information instead of visible left-side hotbar text.
- Added a floating `Show` button:
  - Topmost tool window.
  - Positioned near the bottom right of the primary screen available area.
  - Uses the same gaze feedback pulse styling as other gaze-selectable controls.
  - Works with normal mouse clicks.
  - Works with Tobii gaze dwell selection through the existing hotbar action lookup.
- Added hide/show behavior:
  - `Hide` clears toolbar gaze feedback, unregisters the Windows AppBar reservation, hides the hotbar, and shows the floating restore button.
  - `Show` hides the restore button, shows/repositions the hotbar, re-registers the Windows AppBar reservation, raises the hotbar, and keeps Tobii services running.
- Updated `action_at_global_point()`, `action_center_at_global_point()`, and `contains_global_point()` so the floating restore button participates in gaze hit testing.
- Ensured hidden hotbar geometry does not block desktop-target dwell clicks when the hotbar is hidden.

Updated `README.md`.

- Documents the new left-side `Hide` button.
- Documents the bottom-right floating `Show` button.
- Documents that the visible status/action message area was replaced by the hide button.
- Documents that status and applied-action details are still written to logs instead of shown in the hotbar.

## What Should Work Now

- The left side of the hotbar should show `Hide` instead of status/applied action text.
- Looking at `Hide` for the configured dwell time should hide the hotbar.
- Clicking `Hide` with a normal mouse should also hide the hotbar.
- When hidden, the Windows AppBar reservation should be removed so normal windows can use the top screen area again.
- A floating `Show` button should appear near the bottom right of the screen.
- Looking at `Show` for the configured dwell time should restore the hotbar.
- Clicking `Show` with a normal mouse should restore the hotbar.
- Restoring the hotbar should re-register the AppBar reservation so maximized windows use the area below the hotbar again.
- Tobii gaze tracking, gaze bubble, action overlay, and armed click behavior should continue while the hotbar is hidden.

## What Is Not Confirmed

The Windows AppBar unregister/register behavior and floating button placement could not be visually tested in this Linux workspace because the Windows/PySide runtime is not available here.

The restore button uses `QGuiApplication.primaryScreen().availableGeometry()` so it should avoid the Windows taskbar. If the Windows taskbar is configured unusually, its position should be checked on the Tobii machine.

## Validation Performed

Python syntax validation passed with bytecode disabled:

```text
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

Cache scan was clean:

```text
find . \( -name '__pycache__' -o -name '*.pyc' -o -name '*.pyo' \) -print
```

Result: no output.

Static scan confirmed the expected references:

- `HIDE_HOTBAR`
- `SHOW_HOTBAR`
- `hide_hotbar`
- `show_hotbar`
- `restoreHotbarButton`
- README notes for `Hide` and `Show`

## Next Real-Machine Check

On Windows:

1. Run the app:

```powershell
.\start_gaze_mouse.ps1
```

2. Confirm the left side of the hotbar shows `Hide` and no longer shows applied-action messages.
3. Click `Hide` with the mouse and confirm the hotbar disappears.
4. Confirm maximized windows can use the top area after the hotbar is hidden.
5. Click the bottom-right `Show` button and confirm the hotbar returns.
6. Confirm maximized windows again start below the hotbar after restore.
7. Repeat hide/show using Tobii gaze dwell.
8. Confirm logs still include status/action details in `logs/latest.txt`.
