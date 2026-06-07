# 000025 - Gaze Interaction Action Overlay

Date: 2026-06-07

## Original Prompt

```text
next we need some sort of overlay on the actual screen when interactoin is happening with selected actions of left click, right click, double click as well 

especially on the actions, buttons and desktop icons

It also must be animated so gaze interaction is noticable

Make sure we na turn it on and off in the settings as well
```

## Changes Made

Added `gaze_mouse/interaction_overlay.py`.

- Adds `InteractionOverlayWindow`, a click-through animated top-level overlay.
- Shows a circular dwell progress ring while a gaze interaction is charging.
- Briefly flashes a completed state when the action fires.
- Uses translucent painting so the target remains visible underneath.
- Uses Qt transparent input flags and Windows extended styles:
  - `WS_EX_LAYERED`
  - `WS_EX_TRANSPARENT`
  - `WS_EX_NOACTIVATE`
- This is intended to make the overlay visual-only and avoid blocking desktop icons, app buttons, or other windows.

Updated `gaze_mouse/mouse_controller.py`.

- Added `show_interaction_overlay: bool = True` to `GazeSettings`.
- Added interaction overlay signals:
  - `interaction_progress_changed(QPoint, float, str)`
  - `interaction_finished(QPoint, str)`
  - `interaction_cancelled()`
- Emits progress for hotbar dwell actions.
- Emits progress for Speech-window actions because Speech actions are routed through the same toolbar dwell path.
- Emits progress for armed `Left click`, `Right click`, and `Double click` target dwell.
- For desktop/app/icon click targets, the overlay locks onto the stable gaze anchor while the dwell timer charges.
- The click target overlay only flashes completed after the Windows input click succeeds.
- If Windows input is unavailable or a click fails, the overlay is cancelled instead of displaying success.

Updated `gaze_mouse/toolbar.py`.

- Creates and owns one `InteractionOverlayWindow`.
- Connects mouse-controller interaction progress, finished, and cancelled signals to the overlay.
- Passes `action_center_at_global_point()` into `GazeMouseController`.
- For hotbar buttons, overlay progress appears centered on the actual hotbar button.
- For Speech buttons, overlay progress appears centered on the actual Speech button.
- Connects Settings-window interaction progress, finished, and cancelled signals to the same overlay.
- Applies `show_interaction_overlay` updates from Settings.
- Disables and closes the overlay when the hotbar exits.

Updated `gaze_mouse/speech_window.py`.

- Added `action_center_at_global_point()` so the shared controller can place the overlay on the selected Speech button.

Updated `gaze_mouse/settings_window.py`.

- Added interaction overlay signals matching the mouse controller.
- Emits overlay progress for all Settings gaze-selectable controls and tabs.
- Emits a completed overlay state when a Settings gaze action fires.
- Cancels the overlay when gaze leaves Settings controls or the Settings window closes.
- Added a gaze-selectable and mouse-clickable `Show action overlay` toggle in `Gaze settings`.
- The toggle updates `GazeSettings.show_interaction_overlay`.
- The toggle is checkable and refreshed with the current setting.

Updated `setup_windows.ps1`.

- Added `gaze_mouse\interaction_overlay.py` to required project-file checks.

Updated `README.md`.

- Documents the animated click-through action overlay.
- Documents that `Gaze settings` can turn the animated action overlay on and off.
- Documents that desktop targets/icons use the stable gaze point for the overlay while an armed click is charging.

## What Should Work Now

- Looking at any hotbar button should show:
  - Existing button pulse animation.
  - New action-overlay dwell progress ring centered on the button.
- Opening Speech and looking at Speech keys/buttons should show:
  - Existing button pulse animation.
  - New action-overlay dwell progress ring centered on the Speech button.
- Opening Settings and looking at Settings controls/tabs should show:
  - Existing button pulse animation.
  - New action-overlay dwell progress ring centered on the Settings control.
- Selecting `Left click`, `Right click`, or `Double click`, then looking at a desktop icon or app target should show the animated progress ring at the stable gaze target while the click is charging.
- After a successful click action, the overlay should briefly flash completed.
- `Settings` -> `Gaze settings` -> `Show action overlay` should turn this overlay on and off.
- The setting should work with both Tobii gaze dwell selection and normal mouse clicks.
- The overlay should not block mouse clicks because it is configured as click-through.

## What Is Not Confirmed

The actual overlay rendering and Windows click-through behavior could not be visually tested in this Linux workspace because PySide6 and the Windows Tobii runtime are not available here.

Desktop icon rectangles are not queried from Windows. For desktop icons and other external app targets, the overlay uses the stable gaze anchor rather than the real target bounds. This avoids fragile Windows shell scraping and keeps the click path aligned with the actual gaze dwell target.

Runtime settings are still not persisted across app restarts. `show_interaction_overlay` defaults to `True` each time the program starts, matching the current non-persistent settings behavior.

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

- `gaze_mouse/interaction_overlay.py`
- `InteractionOverlayWindow`
- `show_interaction_overlay`
- `Show action overlay`
- `interaction_progress_changed`
- `interaction_finished`
- `interaction_cancelled`
- `gaze_mouse\interaction_overlay.py` in `setup_windows.ps1`

## Next Real-Machine Check

On Windows:

1. Rerun setup so the local install folder receives `interaction_overlay.py`:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1
```

2. Start the app:

```powershell
.\start_gaze_mouse.ps1
```

3. Look at each hotbar button and confirm the animated progress ring appears centered on it.
4. Open Speech and confirm the ring appears centered on Speech buttons.
5. Open Settings and confirm the ring appears centered on Settings controls and tabs.
6. Select `Left click`, look at a desktop icon, and confirm the ring appears at the stable gaze target until the click fires.
7. Repeat for `Right click` and `Double click`.
8. Toggle `Show action overlay` off and confirm the overlay stops appearing.
9. Toggle it back on and confirm it appears again.
10. Confirm mouse clicks still pass through the overlay to targets underneath.
