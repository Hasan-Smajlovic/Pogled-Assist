# 000009 - Fullscreen Bosnian Speech Keyboard

Date: 2026-06-06

## Original Prompt

```text
Please continue working on this propmp
"""

When Speach button is pressed it has to open speach window
In this window It must have Bosnian Letter keyboard with split letters in groups of 5 at first level
Buttons must be arranged nicely, it must be nice UI. 
This window must be open in full screen, with button on the top right side of screen to close this window
The input must be on the top middle part

Under it it must have buttons, next to the input it must have clear key, and play key

When Play is hit it must play the input with `espeak-ng` tool then clear the text

Make sure buttons are selectable with `gaze` via tobii eye tracker 4c
"""
```

## What Was Added

Added a full-screen Bosnian speech entry window and connected it to the existing Tobii gaze dwell selection path.

New file `gaze_mouse/speech_window.py`:

- Defines `SpeechWindow`, a frameless full-screen `QWidget`.
- Uses the existing `SpeechService` to speak typed text with eSpeak NG.
- Places a close button on the top-right side of the screen.
- Places a large centered input near the top.
- Places Clear and Play buttons next to the input.
- Shows a first-level Bosnian letter keyboard split into groups of five:

```text
A B C Č Ć
D Dž Đ E F
G H I J K
L Lj M N Nj
O P R S Š
T U V Z Ž
```

- Selecting a group opens a second level with that group's five letters.
- Selecting a letter appends it to the input and returns to the first-level group view.
- Adds utility keys:
  - Space
  - Backspace
  - Period
  - Groups, when inside a letter group
- Handles multi-character Bosnian letters (`Dž`, `Lj`, `Nj`) correctly when Backspace is pressed.
- Play sends the current input to `SpeechService.speak(...)`.
- Play clears the input after eSpeak NG starts successfully.
- All buttons are connected to normal mouse clicks.
- All buttons expose action rectangles so Tobii gaze dwell can select them.

Updated `gaze_mouse/toolbar.py`:

- Speech toolbar action now opens `SpeechWindow` instead of speaking a fixed test phrase.
- Hotbar keeps a single shared `SpeechService` instance.
- Hotbar tracks the speech window instance.
- While the speech window is visible, gaze hit-testing checks the speech window first.
- Gaze actions with prefix `speech_window:` are routed back into `SpeechWindow.handle_gaze_action(...)`.
- The speech window blocks background hotbar/target actions while it is visible.
- On hotbar close, the speech window is closed and active speech is stopped.

Updated `setup_windows.ps1`:

- Added `gaze_mouse\speech_window.py` to required project-file checks.

Updated `README.md`:

- Replaced the old test-phrase speech behavior with the full-screen speech keyboard behavior.
- Documented the Bosnian letter groups.
- Documented that Clear and Play are next to the input.
- Documented that Play sends the input to eSpeak NG and clears the input after speech starts.
- Documented that speech-window buttons work with both normal mouse clicks and Tobii gaze dwell selection.
- Updated limitations to remove the old "full speech phrase entry is not implemented" note.

## Important Files

- `gaze_mouse/speech_window.py` - full-screen speech keyboard and gaze-selectable speech controls.
- `gaze_mouse/toolbar.py` - opens speech window and routes gaze actions into it.
- `gaze_mouse/speech_service.py` - eSpeak NG runtime wrapper used by the speech window.
- `setup_windows.ps1` - setup validation includes the new speech window file.
- `README.md` - updated user-facing behavior documentation.
- `AgentDocs/PrompsHistory/000009_fullscreen_bosnian_speech_keyboard.md` - this handoff file.

## What Is Working

- Python source syntax validation passes.
- No `__pycache__`, `.pyc`, or `.pyo` files were present after validation.
- Speech button opens a full-screen speech window in code.
- Speech window has top-right close, top input, Clear, Play, grouped Bosnian letters, and utility keys.
- Speech window controls are wired for normal mouse clicks.
- Speech window controls are exposed through gaze hit-testing and routed through the existing dwell selection signal.
- Play calls eSpeak NG through the existing Python `SpeechService`.
- The input is cleared after speech starts successfully.

## What Is Not Confirmed / Needs Real Windows Testing

- The full-screen UI could not be visually inspected in this Linux/headless workspace.
- Tobii gaze selection must be tested on the Windows Tobii machine.
- eSpeak NG audio output must be tested on the Windows Tobii machine.
- PowerShell parsing/execution could not be tested here because neither `pwsh` nor `powershell` is installed.
- The current workspace includes fullscreen settings support for speech speed and letters per group. This turn focused on the speech window and made sure it consumes those speech settings.

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

- Speech button opens a full-screen window.
- Close button appears on the top-right side.
- Input appears near the top middle.
- Clear and Play are next to the input.
- First keyboard level shows six groups of five Bosnian letters.
- Looking at a group for the configured dwell time opens that group.
- Looking at a letter for the configured dwell time appends it to the input and returns to groups.
- Normal mouse clicks do the same actions.
- Play speaks the input through eSpeak NG and clears the input after speech starts.

## Notes For Next Agent

- `000008` described the older fixed test-phrase behavior; this file supersedes that part.
- Speech settings are stored in `SpeechService.settings` and pushed into `SpeechWindow.update_settings(...)`.
- Letter group size is read from `SpeechSettings.letters_per_group`.
- For future settings-window gaze support, reuse the same pattern:
  - expose `action_at_global_point(...)`
  - expose `contains_global_point(...)`
  - route prefixed actions from `HotbarWindow._run_toolbar_action(...)`
