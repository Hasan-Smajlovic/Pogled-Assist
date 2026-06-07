# 000034 - In-App Keyboard Sidebar

## Original Prompt

the hotbar on the top, when keyboard is selected let's not use the window keyabord. Use the one we have in speech. SO settings that are applied to it ust be applied on this one as well. 

But, when keyabord is selected, it has to act as toggle as well. When it's selected on the right side of the screen create separate section same as it's for the hotbar. Render button groups in the columns. 
Make sure to add backspace button and space buttons. 
Also make sure that user has numpad as well 
And user must have access for to the all special characters like .,@/?!@$%... and rest of them 

to make that more easily accesable there should be tabs for selection of that on the top row of this right sidebar keyabord. 

Make sure that buttons and tabs here have same style as ones on hotbar

## Files Changed

- `gaze_mouse/keyboard_window.py`
- `gaze_mouse/toolbar.py`
- `gaze_mouse/windows_input.py`
- `gaze_mouse/appbar.py`
- `setup_windows.ps1`
- `README.md`

## What Was Done

### New Keyboard Sidebar

- Added `gaze_mouse/keyboard_window.py`.
- The hotbar `Keyboard` button now toggles an in-app right-side keyboard panel instead of opening Windows `osk.exe`.
- The keyboard panel is styled like the hotbar:
  - Dark background.
  - Dark buttons.
  - Blue checked tabs.
  - Yellow/green gaze highlight states through existing `set_gaze_feedback()`.
- The keyboard panel has top tabs:
  - `Letters`
  - `Numpad`
  - `Symbols`
- `Letters` reuses the Bosnian alphabet from `speech_window.BOSNIAN_LETTERS`.
- `Letters` uses the same `SpeechSettings.letters_per_group` value as the Speech window.
- The first letter level renders letter groups in columns.
- Selecting a group opens that group's individual letter buttons.
- Selecting a letter types it and returns to the group level.
- Bottom utility buttons:
  - `Groups`, visible only while inside a letter group.
  - `Space`.
  - `Backspace`.
- `Numpad` includes digits, decimal point, Enter, and common operators.
- `Symbols` includes common special characters:
  - `. , @ / ? ! $ % & * ( ) - _ + = : ; ' " # \ | < > [ ] { } ~ \` ^`

### Gaze And Mouse Integration

- Added `KEYBOARD_WINDOW_ACTION_PREFIX = "keyboard_window:"`.
- `HotbarWindow.action_at_global_point()`, `action_center_at_global_point()`, and `contains_global_point()` now include the keyboard sidebar.
- Keyboard sidebar controls are registered as gaze-selectable actions.
- Keyboard sidebar controls also work with normal mouse clicks.
- The hotbar `Keyboard` button is now checkable and stays checked while the sidebar is open.
- Opening Settings hides the keyboard sidebar.
- Hiding the hotbar hides the keyboard sidebar.
- Quitting closes/hides the keyboard sidebar.

### Right AppBar Reservation

- Extended `WindowsAppBar` to support multiple edges:
  - `ABE_LEFT`
  - `ABE_TOP`
  - `ABE_RIGHT`
  - `ABE_BOTTOM`
- Existing top hotbar behavior still uses `ABE_TOP` by default.
- The keyboard sidebar uses `ABE_RIGHT` to reserve a right-side work area on Windows.
- On non-Windows, the AppBar call remains unsupported and the panel simply shows as a topmost Qt tool window.

### Windows Text Input

- Extended `WindowsInputController` with:
  - `type_text(text)`
  - `press_key(key)`
- `type_text()` uses Windows `SendInput` with Unicode scan codes.
- `press_key()` supports keys such as:
  - `backspace`
  - `enter`
  - `space`
  - `tab`
- This lets the in-app keyboard type characters without using the Windows on-screen keyboard.

### Setup And Docs

- Added `gaze_mouse\keyboard_window.py` to `setup_windows.ps1` required project-file checks.
- Updated `README.md` to describe:
  - In-app Keyboard panel.
  - Right-side AppBar panel.
  - Shared Bosnian letter grouping setting.
  - Numpad and Symbols tabs.
  - Space and Backspace.

## What Should Work Now

- Clicking or gazing at the hotbar `Keyboard` button toggles the right-side keyboard panel.
- The Windows OSK should no longer be launched by this app.
- The keyboard panel should reserve a right-side screen strip on Windows, similar to how the hotbar reserves the top strip.
- Letters should use the same grouping size configured in Settings -> Speech settings.
- Changing the letter group size in Settings should update both Speech and the keyboard sidebar.
- Buttons in the sidebar should work with gaze dwell and mouse clicks.
- Text/symbol/numpad buttons should type into the active Windows application, assuming the keyboard panel does not steal focus.

## Not Fully Verified

- PySide6 UI rendering and Windows focus behavior could not be tested in this Linux workspace.
- The right-side AppBar interaction with the existing top AppBar must be tested on Windows.
- The in-app keyboard window uses no-focus/tool-window flags to avoid stealing focus, but real typing into the last active Windows app must be verified on the Tobii machine.
- Symbol coverage may need expansion if the user needs additional locale-specific characters.

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

- Main implementation file: `gaze_mouse/keyboard_window.py`.
- The old `gaze_mouse/windows_keyboard.py` file still exists but is no longer imported by `toolbar.py`; it can remain as fallback history unless the user asks for cleanup.
- If typing does not go to the intended app on Windows, inspect Qt focus/activation behavior in `KeyboardWindow`:
  - `_keyboard_window_flags()`
  - `Qt.WA_ShowWithoutActivating`
  - `Qt.NoFocus`
  - per-button `Qt.NoFocus`
- If the right AppBar does not reserve correctly with the top AppBar active, inspect `WindowsAppBar.set_position()` and the `ABE_RIGHT` branch.
