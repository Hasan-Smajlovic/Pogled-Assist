# 000010 - Fullscreen Gaze Settings Screen

Date: 2026-06-06

## Original Prompt

```text
When settings is clicked in hotbar it must open fullscreen settings screen. selection in the settings screen must work with gaze
with tobii eye tracker 4c!

In the settings add following tabs:
1) Gaze settings
2) Speach settings 

In Gaze settings it must have ability to set how long it must stare at something to apply action (left click, right click, double left click, selection, etc)
It msut have settings for that. Also it must be able start up tobii eye tracker 4c driver calibration session trough this settings window

In the speach settings, it must be able to set the speed of speach, amount of letters per letter group

Make sure the it exit button on top left side of the window, which must works with gaze!
```

## What Was Added

Added a full-screen settings surface that can be operated by Tobii gaze dwell selection.

New file `gaze_mouse/settings_window.py`:

- Defines `SettingsWindow`, a frameless full-screen `QWidget`.
- Has a large Exit button at the top-left side.
- Provides two large tab buttons:
  - `Gaze settings`
  - `Speech settings`
- Tracks gaze dwell internally from `GazeMouseController.gaze_position_changed`.
- Highlights the current gaze target with a yellow border.
- Activates registered settings controls after the current dwell time.
- Uses the same dwell and cooldown settings that drive toolbar and click actions.
- Supports normal mouse clicks and gaze dwell for:
  - Exit
  - tab switching
  - plus/minus adjustment buttons
  - pointer movement toggle
  - Tobii calibration launch
  - speech test

`Gaze settings` includes:

- `Stare time` (`dwell_ms`) for toolbar buttons, settings selections, and armed click actions.
- `Stable target radius` (`dwell_radius_px`) for gaze stability before firing an armed action.
- `Repeat delay` (`click_cooldown_ms`) for cooldown between gaze actions.
- `Pointer smoothing` (`smoothing`) for gaze-to-pointer movement.
- `Move pointer from gaze` toggle.
- `Start Tobii calibration` button.

`Speech settings` includes:

- `Speech speed` (`SpeechSettings.speed`) for eSpeak NG speech speed.
- `Letters per group` (`SpeechSettings.letters_per_group`) for the full-screen Bosnian speech keyboard grouping.
- `Test speech` button.

New file `gaze_mouse/tobii_calibration.py`:

- Defines `launch_tobii_guest_calibration()`.
- On Windows, sends Tobii's documented guest calibration shortcut:

```text
Ctrl+Shift+F10
```

- Uses `pyautogui.hotkey(...)` first.
- Falls back to Windows `user32.keybd_event(...)` if pyautogui fails.
- Raises a clear error on non-Windows platforms.

Updated `gaze_mouse/toolbar.py`:

- Replaces the old modal `SettingsDialog` with `SettingsWindow`.
- Keeps the existing full-screen `SpeechWindow` behavior from prompt `000009`.
- Opens settings full-screen when the Settings hotbar button is selected.
- Connects settings gaze handling to `GazeMouseController.gaze_position_changed`.
- Updates `GazeMouseController` live when gaze settings change.
- Updates `SpeechService` live when speech settings change.
- Updates an existing `SpeechWindow` live when speech speed or letters-per-group changes.
- Launches Tobii calibration from the settings window.
- Runs the speech test from the settings window.
- Treats the settings window as foreground for gaze containment so background click actions do not fire while settings are open.
- Closes settings cleanly when the hotbar closes.

Updated `gaze_mouse/speech_service.py`:

- Restored `DEFAULT_SPEECH_TEXT`.
- Added `letters_per_group` to `SpeechSettings`.
- Added `settings` property returning a copy of current settings.
- Added `update_settings(...)`.
- `speak(...)` now uses the service's current settings when no explicit settings are passed.

Updated `gaze_mouse/speech_window.py`:

- Initializes from the shared `SpeechService.settings`.
- Adds `update_settings(...)`.
- Rebuilds Bosnian letter groups when `letters_per_group` changes.
- Uses current speech settings when playing speech.

Updated `setup_windows.ps1`:

- Added `gaze_mouse\settings_window.py` and `gaze_mouse\tobii_calibration.py` to required project-file checks.

Updated `README.md`:

- Documents that Settings opens a full-screen gaze-selectable settings surface.
- Documents Gaze settings and Speech settings behavior.
- Documents that Tobii calibration launch uses `Ctrl+Shift+F10`.
- Updates limitations to say settings are runtime-only and not persisted yet.

## Important Files

- `gaze_mouse/settings_window.py` - full-screen gaze-selectable settings UI.
- `gaze_mouse/tobii_calibration.py` - Tobii guest calibration launcher.
- `gaze_mouse/toolbar.py` - opens settings, wires gaze, routes settings changes.
- `gaze_mouse/speech_service.py` - shared speech settings storage and defaults.
- `gaze_mouse/speech_window.py` - speech keyboard updates from settings.
- `setup_windows.ps1` - required file checks include new modules.
- `README.md` - updated behavior documentation.
- `AgentDocs/PrompsHistory/000010_fullscreen_gaze_settings_screen.md` - this handoff file.

## What Is Working

- Python source syntax validation passes.
- No `__pycache__`, `.pyc`, or `.pyo` files were present after validation.
- Settings button now opens a full-screen settings window in code.
- Settings window has the requested tabs.
- Settings window controls are gaze-selectable through the same Tobii gaze stream used by the hotbar.
- Exit button is top-left and registered for gaze dwell activation.
- Gaze dwell time can be adjusted from the settings screen.
- Speech speed can be adjusted from the settings screen.
- Letters per group can be adjusted from the settings screen and propagated to the speech keyboard.
- Tobii calibration launch is wired to the settings screen through the documented global shortcut.

## What Is Not Confirmed / Needs Real Windows Testing

- The full-screen settings UI could not be visually inspected in this Linux/headless workspace.
- Tobii gaze dwell selection on the settings screen must be tested on the Windows Tobii machine.
- Tobii calibration launch must be tested with Tobii software installed and running.
- PowerShell parsing/execution could not be tested here because neither `pwsh` nor `powershell` is installed.
- Settings are runtime-only and are not persisted across program restarts.
- The calibration launcher uses Tobii's guest calibration shortcut. If the installed Tobii software does not listen for that shortcut, a product-specific launcher path may need to be added later after inspecting the target Windows machine.

## Validation Performed

Python syntax validation without bytecode:

```text
PYTHONDONTWRITEBYTECODE=1 python - <<'PY'
from pathlib import Path
paths = [Path('run_gaze_mouse.py'), *sorted(Path('gaze_mouse').glob('*.py'))]
for path in paths:
    compile(path.read_text(encoding='utf-8'), str(path), 'exec')
print('python syntax ok')
PY
```

Result:

```text
python syntax ok
```

Cache check:

```text
find . -name '__pycache__' -o -name '*.pyc' -o -name '*.pyo'
```

Result: no output.

PowerShell availability check:

```text
command -v pwsh || command -v powershell || true
```

Result: no output.

## Expected Windows Test

Run:

```powershell
.\run_gaze_mouse.bat
```

Expected behavior:

- Settings hotbar button opens a full-screen settings window.
- Exit appears at the top left.
- Looking at Exit for the dwell time closes settings.
- Looking at `Gaze settings` and `Speech settings` switches tabs.
- Looking at `Less`/`More` buttons changes values.
- Changing `Stare time` changes how long gaze dwell takes for toolbar, settings controls, and armed click actions.
- Changing `Speech speed` changes eSpeak NG playback speed.
- Changing `Letters per group` changes the speech keyboard grouping the next time the speech window is shown, or immediately if it already exists.
- Looking at `Start Tobii calibration` sends the Tobii guest calibration shortcut.

## Notes For Next Agent

- If the settings screen opens but gaze selection does nothing, inspect whether `GazeMouseController.gaze_position_changed` is connected to `SettingsWindow.handle_gaze`.
- If Tobii calibration does not launch, test the shortcut manually on the Windows machine:

```text
Ctrl+Shift+F10
```

- If the manual shortcut works but the app does not, inspect `gaze_mouse/tobii_calibration.py`.
- If the manual shortcut does not work, inspect the installed Tobii software and add a product-specific executable/URI launch path.
- Future persistence can be added by saving `GazeSettings` and `SpeechSettings` to a small JSON file under the project root or user config directory.
