# 000011 - Fullscreen Settings Prompt Verification

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

## What Was Checked

The requested functionality is implemented in the current workspace. This prompt was handled by verifying the active code paths and validating Python syntax.

Important implementation files:

- `gaze_mouse/settings_window.py`
- `gaze_mouse/toolbar.py`
- `gaze_mouse/mouse_controller.py`
- `gaze_mouse/speech_service.py`
- `gaze_mouse/tobii_calibration.py`
- `README.md`
- `setup_windows.ps1`

## Verified Behavior In Code

Settings hotbar action:

- `gaze_mouse/toolbar.py` imports `SettingsWindow`.
- `HotbarWindow._open_settings()` creates `SettingsWindow(self._mouse.settings, self._speech.settings, self)`.
- The settings window is shown with `show_fullscreen_on_primary()`.
- If settings is already visible, it is raised and activated instead of creating duplicates.
- While settings is visible, `HotbarWindow.contains_global_point(...)` returns `True`, so background target clicks are suppressed.

Gaze selection:

- `GazeMouseController.handle_gaze(...)` emits `gaze_position_changed` for every gaze point.
- `HotbarWindow._open_settings()` connects `self._mouse.gaze_position_changed` to `window.handle_gaze`.
- `SettingsWindow.handle_gaze(...)` finds the gaze target, waits for the current `dwell_ms`, respects `click_cooldown_ms`, then calls the target action.
- Settings controls are also normal `QToolButton` controls, so classic mouse clicks work too.

Tabs:

- `SettingsWindow` has two tab buttons:
  - `Gaze settings`
  - `Speech settings`
- The tabs switch a `QStackedWidget`.

Gaze settings tab:

- `Stare time` adjusts `GazeSettings.dwell_ms`.
- `Stable target radius` adjusts `GazeSettings.dwell_radius_px`.
- `Repeat delay` adjusts `GazeSettings.click_cooldown_ms`.
- `Pointer smoothing` adjusts `GazeSettings.smoothing`.
- `Move pointer from gaze` toggles `GazeSettings.move_mouse`.
- `Start Tobii calibration` emits `calibration_requested`.
- Toolbar connects `calibration_requested` to `launch_tobii_guest_calibration()`.

Tobii calibration:

- `gaze_mouse/tobii_calibration.py` defines `launch_tobii_guest_calibration()`.
- On Windows it sends Tobii's guest calibration shortcut:

```text
Ctrl+Shift+F10
```

- It uses `pyautogui.hotkey(...)` first.
- It falls back to Windows `user32.keybd_event(...)` if pyautogui fails.
- It raises a clear error on non-Windows platforms.

Speech settings tab:

- `Speech speed` adjusts `SpeechSettings.speed`.
- `Letters per group` adjusts `SpeechSettings.letters_per_group`.
- `Test speech` uses the current speech settings.
- `HotbarWindow._update_speech_settings(...)` updates `SpeechService`.
- If the speech window already exists, its settings are updated too.

Exit button:

- `SettingsWindow` creates an `Exit` button at the top-left of the screen.
- The button is registered for gaze dwell via `_register_gaze(...)`.
- It also works with a normal mouse click.
- `Esc` also closes the settings screen.

Setup and docs:

- `setup_windows.ps1` includes required-file checks for:
  - `gaze_mouse\settings_window.py`
  - `gaze_mouse\tobii_calibration.py`
  - `gaze_mouse\speech_window.py`
- `README.md` documents the fullscreen settings surface, gaze controls, calibration shortcut, speech speed, and letters-per-group settings.

## What Is Working

- Python syntax validation passes.
- No `__pycache__`, `.pyc`, or `.pyo` files were present after validation.
- The requested settings functionality is present in code.
- Settings screen controls are wired for both gaze selection and normal mouse clicks.
- Gaze setting changes update the live `GazeMouseController`.
- Speech setting changes update `SpeechService` and the speech keyboard when it exists.

## What Is Not Confirmed / Needs Real Windows Testing

- PySide6 is not installed in the Linux system Python in this workspace.
- The existing `.venv` is a Windows-style virtual environment, so it cannot be executed from this Linux shell.
- Import-level Qt checks and visual UI checks could not be run here.
- Tobii calibration shortcut behavior must be tested on the Windows Tobii machine with Tobii software installed.
- Real Tobii gaze selection in the settings screen must be tested on the Windows Tobii machine.

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

PySide6 availability check:

```text
PYTHONDONTWRITEBYTECODE=1 python - <<'PY'
import importlib.util
print('PySide6 available:', importlib.util.find_spec('PySide6') is not None)
PY
```

Result:

```text
PySide6 available: False
```

## Expected Windows Test

Run the app:

```powershell
.\run_gaze_mouse.bat
```

Expected behavior:

- Settings hotbar button opens a fullscreen settings window.
- Exit button appears at the top-left side.
- `Gaze settings` and `Speech settings` tabs are available.
- Looking at a settings button/control for the configured dwell time activates it.
- Clicking controls with a normal mouse also activates them.
- `Stare time` changes how long gaze must remain on toolbar buttons, settings controls, and armed click targets.
- `Start Tobii calibration` sends the Tobii calibration shortcut.
- `Speech speed` changes the eSpeak NG speed used by speech.
- `Letters per group` changes how many Bosnian letters are shown per speech-keyboard group.

## Notes For Next Agent

- Do not recreate the settings UI from scratch; it already exists in `gaze_mouse/settings_window.py`.
- If visual issues appear on Windows, patch layout/style in `SettingsWindow`.
- If Tobii calibration does not launch, inspect whether Tobii software on that machine supports the `Ctrl+Shift+F10` guest calibration shortcut.
- Runtime settings are not persisted yet; `README.md` currently documents this limitation.
