# Prompt 000059: Voice Selection Edge Playback

## Original Prompt

Oke now let's add ability to change voice. In the settings in voice tab add dropdown for selecting voice

Current one can be called "default" and should be selected by default

Also add new one called "Human like"

```text
edge-playback   --voice bs-BA-GoranNeural   --rate=-10%   --pitch=-2Hz   --text "Dobar dan. Ovo zvuči mnogo prirodnije."
```

This is command I used on ubuntu terminal to make it work, but make changes so tihs can work on windows.

Make sure it's automaticlly installed via setup_windows.ps1 as well

## What Was Done

- Added voice preset support to `SpeechSettings`.
- Added two presets:
  - `Default`, stored as `default`, using existing eSpeak NG behavior.
  - `Human like`, stored as `human_like`, using `edge-playback --voice bs-BA-GoranNeural --rate=-10% --pitch=-2Hz --text <input>`.
- Added `edge-playback` discovery in `gaze_mouse/speech_service.py`.
  - Checks `EDGE_PLAYBACK_EXE`.
  - Checks PATH.
  - Checks the current Python environment folder.
  - Checks the project `.venv` folders.
- Kept eSpeak NG as the default selected voice.
- Added a new `Voice settings` tab in fullscreen Settings.
  - Contains a `QComboBox` dropdown with `Default` and `Human like`.
  - Dropdown can be changed by classic mouse.
  - Gaze dwell on the dropdown cycles to the next voice option.
  - Added a gaze-selectable `Test voice` button.
- Updated settings persistence so `voice_preset` is saved in `data/app_settings.json` and loaded/clamped safely on startup.
- Updated speech failure messages so they refer to the selected voice engine instead of only eSpeak NG.
- Added `edge-tts>=7.2.6` to `requirements.txt`.
- Updated `setup_windows.ps1`.
  - Installs `edge-tts` through normal `requirements.txt` installation.
  - Verifies `edge_tts` can be imported.
  - Verifies `edge-playback.exe` exists in `.venv\Scripts`.
  - Exports `EDGE_PLAYBACK_EXE` in generated `run_gaze_mouse.bat` and `run_gaze_mouse.ps1`.
  - Shows the Edge playback executable path in final setup instructions.
- Updated `start_gaze_mouse.ps1`.
  - Resolves `.venv\Scripts\edge-playback.exe`.
  - Sets `EDGE_PLAYBACK_EXE` before launching the Python app.
  - Warns if Human like voice support is missing.
- Updated `README.md` with the new dependency, setup behavior, and Voice settings usage.

## What Is Working

- Default voice remains backward-compatible with existing eSpeak NG speech.
- Human like voice launches `edge-playback` with:
  - Voice: `bs-BA-GoranNeural`
  - Rate: `-10%`
  - Pitch: `-2Hz`
- The selected voice is persisted with other speech settings.
- Setup installs the required Python package and wires the generated command path into launchers.
- Runtime launcher also finds and exports `EDGE_PLAYBACK_EXE`.
- Python syntax was validated with AST parsing without generating bytecode caches.
- `git diff --check` passes.

## What Was Not Fully Verified

- PowerShell syntax parsing could not be run in this Linux workspace because `pwsh`/Windows PowerShell is not installed here.
- Actual audio playback for `Human like` must be verified on the target Windows machine after rerunning `setup_windows.ps1`, because it depends on Windows audio output and network access to the Edge TTS service.

## Follow-Up Notes

- Rerun `setup_windows.ps1` on Windows so `.venv` receives `edge-tts` and launchers are regenerated with `EDGE_PLAYBACK_EXE`.
- If the Human like voice fails on Windows, inspect `logs/latest.txt` and `start_gaze_mouse.log`; the app should log the resolved `edge-playback` command and any process stderr.
