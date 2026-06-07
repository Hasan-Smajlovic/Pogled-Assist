# Prompt 000045 - General Settings Logging Toggle

## Original Prompt

In Settings make sure that logging can be disabled, as that should boost up paerformance a bit as well
It should be checkbox same as Startup on windows Startup

Make sure that there is X in the checkbox as well

Add new Tab in settings called general settings in there there should be this checkbox and checkbox for statup

## Changes Made

- Added `logging_enabled` to `GazeSettings`.
  - Defaults to `true`.
  - Saved and loaded through `data/app_settings.json`.
  - Existing settings files still load because missing fields fall back to defaults.

- Added runtime logging enable/disable support in `gaze_mouse/logging_setup.py`.
  - On app startup, `setup_application_logging()` reads `data/app_settings.json` before creating `logs/latest.txt`.
  - If logging is disabled, the app does not create/rotate `logs/latest.txt`, does not attach file/console logging handlers, restores stdout/stderr, disables captured warnings, and globally disables Python logging.
  - If logging is enabled again at runtime, logging handlers are recreated and a fresh `logs/latest.txt` is started.

- Added a new `General settings` tab in fullscreen Settings.
  - Added a navigation button for `General settings`.
  - The tab contains:
    - `Start with Windows as Administrator`
    - `Enable logging`
  - Both controls are real `QCheckBox` widgets and are registered in the existing gaze-action registry, so they work with classic mouse clicks and Tobii gaze dwell selection.

- Moved `Start with Windows as Administrator` out of `Gaze settings` and into the new `General settings` tab.

- Added an X-style checked checkbox indicator.
  - New asset: `gaze_mouse/assets/checkbox_x.svg`.
  - Settings QSS uses the asset for `QCheckBox::indicator:checked`.

- Updated README to describe the new General settings tab and logging toggle.

## What Should Work Now

- Settings opens to the new `General settings` tab.
- Startup and logging checkboxes are both selectable with gaze and mouse.
- Checked checkboxes show an X inside the indicator.
- Turning off `Enable logging` takes effect immediately and persists for future app starts.
- Turning `Enable logging` back on starts writing a new `logs/latest.txt`.

## Important Notes

- Disabling logging also means normal diagnostic logs will not be available until logging is turned back on.
- The PowerShell launcher transcript `start_gaze_mouse.log` is separate from Python app logging and is not controlled by this setting.
- Runtime behavior of Qt styling and Windows startup task creation was not tested on the Windows Tobii machine from this Linux workspace.

## Validation Performed

- Syntax-checked changed Python files with `compile(...)` under `PYTHONDONTWRITEBYTECODE=1` and `python -B`.
- Confirmed no `__pycache__`, `.pyc`, or `.pyo` files were created.

