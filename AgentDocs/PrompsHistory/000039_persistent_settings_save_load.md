# 000039 - Persistent Settings Save Load

## Original Prompt

Make sure that configured settings are saved from and loaded correcly. Right now they reset every time

## What Was Done

- Added `gaze_mouse/settings_store.py`.
- Settings are now stored as UTF-8 JSON at:

```text
data/app_settings.json
```

- Added `load_app_settings()`:
  - Loads saved gaze settings and speech settings.
  - Falls back to defaults if the file does not exist.
  - Falls back field-by-field when values are missing or malformed.
  - Clamps saved values to the same ranges used by the Settings UI.
- Added `save_app_settings()`:
  - Saves both gaze and speech settings.
  - Writes atomically via a temporary file and then replaces the real settings file.
  - Creates the `data` directory if needed.
- Updated `gaze_mouse/toolbar.py`:
  - Loads saved settings during `HotbarWindow` startup.
  - Applies saved speech settings to `SpeechService`.
  - Applies saved gaze settings to `GazeMouseController` before gaze bubble and overlay state are initialized.
  - Saves settings immediately whenever gaze settings change.
  - Saves settings immediately whenever speech settings change.
- Updated `setup_windows.ps1`:
  - Added `gaze_mouse\settings_store.py` to required project files so setup copies/install checks include the new module.
- Updated `README.md`:
  - Documented `data\app_settings.json`.
  - Removed the old limitation saying runtime settings are not persisted.

## Files Changed

- `gaze_mouse/settings_store.py`
- `gaze_mouse/toolbar.py`
- `setup_windows.ps1`
- `README.md`
- `AgentDocs/PrompsHistory/000039_persistent_settings_save_load.md`

## What Is Working

- Gaze settings now persist:
  - Stare time
  - Stable target radius
  - Repeat delay
  - Pointer smoothing
  - Move pointer from gaze
  - Show gaze bubble
  - Show action overlay
- Speech settings now persist:
  - Language
  - Speech speed
  - Pitch
  - Amplitude
  - Letters per group
- Saved settings are loaded automatically the next time the app starts.
- Settings are saved from both mouse/gaze-driven and normal mouse-click interactions because both paths use the same `SettingsWindow` signals.

## What Was Not Runtime-Tested

- A full runtime save/load test could not be executed in this Linux workspace because PySide6 is not installed here and importing the runtime dataclasses imports PySide modules.
- Python syntax compilation was still performed successfully without generating bytecode.
- Final confirmation should be done on the Windows target by changing settings, closing the app, starting again, and confirming the UI shows the changed values.

## Validation

- Python syntax compilation passed with `PYTHONDONTWRITEBYTECODE=1`.
- Checked for generated `__pycache__`, `.pyc`, and `.pyo` files; none were present.

