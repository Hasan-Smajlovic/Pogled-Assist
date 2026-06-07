# 000028 - Quick Actions Radial Menu

Date: 2026-06-07

## Original Prompt

```text
Let's add easier way of interactions. In the Toolbar add one button which will be kind of toggle on off button. 

Call it quick actions. When it's enabled, if gaze is applied at one position it should pop up like circlar menu in that position. In circlirat menu it must have Left click, Right click, and double click and cancle. Show only icons for those.
For all of the actions dedicate equal angle of the circle, if gaze happenis in that area of circle no matter where on the screen it should applie that action on that position, or if it's cancel it should just cancel the action
```

## Changes Made

Added `gaze_mouse/quick_action_menu.py`.

- Adds `QuickActionRadialMenu`, a fullscreen transparent overlay that draws an icon-only radial menu around the original gaze target point.
- The menu has four equal 90-degree sectors:
  - Top: left click.
  - Right: right click.
  - Bottom: double left click.
  - Left: cancel.
- The sectors show icons only, with no visible text labels.
- Gaze selection is based on the angle from the original target point to the current gaze point.
- This means gaze can be anywhere on the screen as long as it is in the correct sector direction.
- Mouse selection is also supported by clicking a sector.
- `Esc` selects cancel when the radial menu has keyboard focus.

Updated `gaze_mouse/mouse_controller.py`.

- Added `QUICK_ACTIONS = "quick_actions"`.
- Added `quick_actions_enabled` state.
- Added signals:
  - `quick_actions_mode_changed(bool)`
  - `quick_action_menu_requested(QPoint)`
- Added `set_quick_actions_enabled()`.
- Added `execute_quick_action()`.
- Added `cancel_quick_action_menu()`.
- When Quick actions is enabled:
  - The controller waits for stable gaze on a desktop/app target.
  - It emits normal action-overlay progress with the label `Quick`.
  - After the configured dwell time, it stores both logical and physical coordinates for the original target.
  - It requests the radial menu at the logical target point.
  - The later radial-menu sector gaze does not change the stored click target.
- When a sector action is selected:
  - Left click, right click, or double click is fired at the stored physical Windows coordinate.
  - Cancel clears the stored target and does not click.
- Selecting one of the old explicit click modes disables Quick actions to avoid conflicting target dwell behavior.

Updated `gaze_mouse/toolbar.py`.

- Added `Quick actions` as a checkable toolbar button using a bolt icon.
- Wires the toolbar button to `GazeMouseController.set_quick_actions_enabled()`.
- Keeps the Quick actions button checked while the mode is enabled.
- Opens `QuickActionRadialMenu` when the controller requests it.
- Sends radial menu selections back to the controller.
- Closes and cancels any open radial menu when hiding the hotbar, showing the hotbar, quitting, or closing.
- Connects the existing gaze stream to the radial menu; no second Tobii subscription is created.
- Ensures old click-mode buttons are still independent and continue to work.

Updated `setup_windows.ps1`.

- Added `gaze_mouse\quick_action_menu.py` to required project-file checks.

Updated `README.md`.

- Documents the new `Quick actions` toggle.
- Documents the radial menu sector layout.
- Documents that the selected click is applied to the original target point, not the later sector gaze point.
- Documents that mouse clicks can also select sectors.

## What Should Work Now

- The top hotbar should include a checkable `Quick actions` button.
- Clicking `Quick actions` with a normal mouse should toggle quick mode on/off.
- Looking at `Quick actions` with Tobii gaze dwell should toggle quick mode on/off.
- When Quick actions is enabled, looking steadily at a desktop/app target should open the circular radial menu at that target.
- The radial menu should show only icons:
  - Top icon for left click.
  - Right icon for right click.
  - Bottom icon for double click.
  - Left icon for cancel.
- Looking anywhere in a sector direction from the menu center should select that action after a short selection dwell.
- Clicking a sector with the normal mouse should select it immediately.
- Left/right/double click actions should apply at the original target point.
- Cancel should close the radial menu without clicking.
- Existing explicit Left click, Right click, and Double click toolbar modes should still work.

## What Is Not Confirmed

The actual fullscreen transparent radial menu rendering could not be visually tested in this Linux workspace because PySide6 and the Windows Tobii runtime are not available here.

The menu selection uses a short dwell delay instead of firing on the first single gaze sample. This is intentional to reduce accidental clicks from tracker jitter. The selection delay is currently derived from the configured dwell time and clamped between `120 ms` and `420 ms`.

The radial menu is fullscreen while open so mouse sector clicks can work. During that menu state, it intentionally blocks normal clicks to underlying apps until a sector or cancel is selected.

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

- `Quick actions`
- `QUICK_ACTIONS`
- `QuickActionRadialMenu`
- `CANCEL_QUICK_ACTION`
- `quick_action_menu_requested`
- `quick_actions_mode_changed`
- `gaze_mouse\quick_action_menu.py` in `setup_windows.ps1`

## Next Real-Machine Check

On Windows:

1. Rerun setup so the local install folder receives `quick_action_menu.py`:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1
```

2. Start the app:

```powershell
.\start_gaze_mouse.ps1
```

3. Toggle `Quick actions` on with the mouse.
4. Look steadily at a desktop icon and confirm the radial menu opens at that point.
5. Look to the top sector and confirm left click fires at the original point.
6. Repeat for right sector/right click and bottom sector/double click.
7. Confirm left sector/cancel closes the menu without clicking.
8. Repeat toggling and sector selection using Tobii gaze dwell on the `Quick actions` button.
9. Confirm the old explicit Left click, Right click, and Double click toolbar buttons still behave as before.
