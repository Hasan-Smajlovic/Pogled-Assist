# 000030 - Quick Actions Dwell Selection Fix

## Original Prompt

quick actions are bit buggy, they are applying gaze when picking action. Also make sure that gaze must be applied when selection action in quick actions.

Please make adjustments there

## Files Changed

- `gaze_mouse/quick_action_menu.py`
- `gaze_mouse/mouse_controller.py`
- `gaze_mouse/toolbar.py`
- `README.md`

## What Was Done

### Quick Action Radial Menu

- Changed radial gaze selection from a short permissive sector timer to stable gaze dwell selection.
- Added configurable quick-menu selection settings:
  - Uses normal gaze dwell time from `GazeSettings.dwell_ms`.
  - Uses normal gaze stability radius from `GazeSettings.dwell_radius_px`.
- Added a larger center dead zone so tracker jitter near the original target point is less likely to accidentally select a sector.
- Added a short open grace period before sector selection starts, reducing accidental selection immediately after the menu appears.
- Added stable sector anchoring:
  - If gaze changes sector, selection dwell restarts.
  - If gaze moves too far inside the same sector, selection dwell restarts.
  - The action only fires when the gaze remains stable long enough.
- Added sector selection progress state and drawing around the selected sector icon.
- Added signals from the radial menu:
  - `selection_progress_changed(QPoint, float, str)`
  - `selection_cancelled()`
- Mouse clicks on the radial sectors still select immediately for classic mouse support.

### Mouse Controller

- While the quick-action menu is open, gaze position updates still emit to the gaze bubble and radial menu.
- Actual mouse cursor movement is now paused while selecting a quick action.
- Added a snapshot guard so a gaze sample that started while the quick menu was open cannot continue into normal cursor movement or quick-action dwell after the menu closes synchronously from that same sample.

### Toolbar Wiring

- Connected quick-menu selection progress to the existing interaction overlay.
- Connected quick-menu selection cancel to the existing overlay clear behavior.
- Passed the current Gaze settings dwell time and dwell radius into the quick menu when it opens.
- Clears the selection overlay when a sector is selected or cancelled before executing/cancelling the stored quick action.

### README

- Updated Quick actions documentation to explain that sector selection requires stable gaze dwell.
- Documented that the real mouse cursor does not move by gaze while the quick-action menu is open.

## What Should Work Now

- Quick actions still open by gazing steadily at a desktop/app target.
- The click target remains the original stored target point.
- Looking around while choosing a sector should not move the real mouse cursor.
- Looking into a quick-action sector should show dwell progress and only select after stable gaze dwell completes.
- Moving too much within the same sector should restart sector selection dwell.
- Moving into another sector should restart sector selection dwell for that sector.
- Cancel requires the same gaze dwell when selected by gaze.
- Normal mouse clicks on radial sectors still select immediately.

## Not Fully Verified

- Runtime PySide6 rendering and Tobii gaze behavior were not tested in this Linux workspace.
- The final feel of the dwell radius and center dead zone should be tested on the Windows Tobii machine; they now follow the existing Gaze settings instead of hard-coded short quick-action timing.

## Validation

Ran syntax validation without bytecode generation:

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

- Key code locations:
  - `gaze_mouse/quick_action_menu.py`: `QuickActionRadialMenu.handle_gaze()`
  - `gaze_mouse/mouse_controller.py`: `GazeMouseController.handle_gaze()`
  - `gaze_mouse/toolbar.py`: `_open_quick_action_menu()` and `_quick_action_selected()`
- If the user still reports accidental sector selection, tune `INNER_RADIUS`, `OPEN_GAZE_GRACE_MS`, or the Gaze settings dwell/radius values.
- If the user reports selection feels too slow, adjust Gaze settings dwell time first because quick-menu selection now intentionally follows the same setting.
