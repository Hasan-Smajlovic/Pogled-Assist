# 000027 - Settings Quit Application

Date: 2026-06-07

## Original Prompt

```text
In Settings please add ability to quite application
Make sure it works with gaze as well
```

## Changes Made

Updated `gaze_mouse/settings_window.py`.

- Added a `quit_requested` signal to `SettingsWindow`.
- Added a `Quit app` button beside the existing top-left `Exit` button.
- The existing `Exit` button still only closes the Settings window.
- `Quit app` emits `quit_requested`.
- `Quit app` is created through `_make_button()`, so it is automatically:
  - Registered for gaze dwell selection.
  - Clickable with a normal mouse.
  - Styled with the existing danger-button gaze pulse animation.
  - Included in the Settings interaction overlay progress behavior.

Updated `gaze_mouse/toolbar.py`.

- Connects `SettingsWindow.quit_requested` to a new `_quit_application()` method.
- `_quit_application()` calls `self.close()` on the hotbar.
- This reuses the existing hotbar shutdown path, which closes child windows, disables overlays, stops speech, stops gaze tracking, unregisters the AppBar, and closes the restore button when present.
- `_quit_application()` also calls `QApplication.instance().quit()` after normal cleanup so the Qt event loop exits even if another helper window is still alive.

Updated `README.md`.

- Documents that `Exit` closes Settings.
- Documents that `Quit app` closes the whole application.
- Documents that both work with mouse clicks and Tobii gaze dwell selection.

## What Should Work Now

- Opening Settings should show both:
  - `Exit`
  - `Quit app`
- Looking at `Quit app` for the configured dwell time should close the whole application.
- Clicking `Quit app` with a normal mouse should close the whole application.
- Looking at `Exit` should still only close the Settings window.
- The `Quit app` button should show the same gaze pulse and action overlay feedback as other Settings controls.

## What Is Not Confirmed

The actual Settings UI and quit behavior could not be visually tested in this Linux workspace because PySide6 and the Windows Tobii runtime are not available here.

## Validation Performed

Python syntax validation passed with an in-memory compile check:

```text
PYTHONDONTWRITEBYTECODE=1 python - <<'PY'
from pathlib import Path
for path in sorted(Path('gaze_mouse').glob('*.py')):
    source = path.read_text(encoding='utf-8')
    compile(source, str(path), 'exec')
print('compiled gaze_mouse modules')
PY
```

Result:

```text
compiled gaze_mouse modules
```

Cache scan was clean:

```text
find . \( -name '__pycache__' -o -name '*.pyc' -o -name '*.pyo' \) -print
```

Result: no output.

Static scan confirmed the expected references:

- `Quit app`
- `quit_requested`
- `_request_quit`
- `_quit_application`

## Next Real-Machine Check

On Windows:

1. Run the app:

```powershell
.\start_gaze_mouse.ps1
```

2. Open Settings.
3. Confirm `Exit` closes Settings only.
4. Reopen Settings.
5. Confirm `Quit app` closes the whole application with a normal mouse click.
6. Start again, open Settings, and confirm `Quit app` closes the whole application using Tobii gaze dwell.
