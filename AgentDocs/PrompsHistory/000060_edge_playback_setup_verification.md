# Prompt 000060: Edge Playback Setup Verification

## Original Prompt

setup_windows.ps1 windows script must install and configure everything neccecary for the

edge-playback and bs-BA-GoranNeural to work correctly

Currently there's an issuw with that, that voice is not working at all!

## What Was Done

- Inspected `setup_windows.log`, `start_gaze_mouse.log`, and `logs/latest.txt` for Edge TTS / `edge-playback` failures.
  - Existing logs did not show a current failed Edge voice run; most entries were from before the voice preset existed.
  - The setup weakness was that it only checked whether `edge-playback.exe` existed.
- Updated `requirements.txt` to require `edge-tts>=7.2.8`.
- Strengthened `setup_windows.ps1`.
  - Added Edge TTS constants:
    - Voice: `bs-BA-GoranNeural`
    - Rate: `-10%`
    - Pitch: `-2Hz`
    - Smoke-test text: `Dobar dan.`
  - Added a timeout-capable native command runner for setup checks.
  - Added detection for both `.venv\Scripts\edge-tts.exe` and `.venv\Scripts\edge-playback.exe`.
  - Added `Verify-EdgeTtsVoiceSupport`.
    - Runs `edge-tts --version`.
    - Runs `edge-playback --help`.
    - Uses the `edge_tts` Python module to query voices from the online service.
    - Fails setup if `bs-BA-GoranNeural` is not returned.
    - Generates a temporary MP3 with `bs-BA-GoranNeural`, `--rate=-10%`, and `--pitch=-2Hz`.
    - Fails setup if the generated media file is missing or too small.
    - Runs a short `edge-playback` smoke test with the same voice, rate, and pitch.
  - Adds `.venv\Scripts` to `PATH` before Edge TTS verification.
  - Adds `.venv\Scripts` to `PATH` in generated `run_gaze_mouse.bat` and `run_gaze_mouse.ps1`.
  - Final setup instructions now state that the human-like voice was verified during setup.
- Updated `start_gaze_mouse.ps1`.
  - Adds the installed app's `.venv\Scripts` folder to `PATH` before launching Python.
  - Keeps resolving and exporting `EDGE_PLAYBACK_EXE`.
- Updated `gaze_mouse/speech_service.py`.
  - After launching a speech command, waits briefly for immediate failures.
  - If `edge-playback` exits immediately with a non-zero code, the app now logs stderr and returns failure instead of showing a false success.
- Updated `README.md`.
  - Documents that the human-like voice requires internet access to Microsoft's online TTS service.
  - Documents the new setup checks for voice listing, MP3 generation, and `edge-playback` smoke test.

## What Is Working

- Setup no longer treats `edge-playback.exe` existing as enough.
- Setup now verifies the actual `bs-BA-GoranNeural` voice through the Edge TTS service.
- Setup now verifies a temporary audio file can be synthesized.
- Setup now verifies `edge-playback` can run with the configured Bosnian neural voice.
- Runtime launchers now run with `.venv\Scripts` on `PATH`, matching setup verification more closely.
- Immediate `edge-playback` startup failures should now be visible to the app and logs.

## What Was Not Fully Verified

- PowerShell execution could not be run in this Linux workspace.
- Actual `edge-playback` audio playback must be verified on the target Windows machine.
- The Edge TTS service requires internet access; setup will now fail clearly if the target machine cannot reach the service or if Microsoft changes/removes the voice.

## Verification Performed

- Python AST syntax check passed for `gaze_mouse/speech_service.py`.
- `git diff --check` passed.
- Confirmed no `__pycache__`, `.pyc`, or `.pyo` files were generated.

## Follow-Up Notes

- Rerun `setup_windows.ps1` on the Windows test machine.
- During setup, a short `Dobar dan.` playback should happen during the `edge-playback` smoke test.
- If setup fails at Edge TTS verification, inspect `setup_windows.log`; it should now identify whether the missing piece is CLI installation, voice listing, synthesis, or playback.
