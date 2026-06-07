# 000012 - Settings Prompt Status Confirmation

Date: 2026-06-06

## Original Prompt

```text
Have you finished work on this promp
"""
When settings is clicked in hotbar it must open fullscreen settings screen. selection in the settings screen must work with gaze
with tobii eye tracker 4c!

In the settings add following tabs:
1) Gaze settings
2) Speach settings 

In Gaze settings it must have ability to set how long it must stare at something to apply action (left click, right click, double left click, selection, etc)
It msut have settings for that. Also it must be able start up tobii eye tracker 4c driver calibration session trough this settings window

In the speach settings, it must be able to set the speed of speach, amount of letters per letter group

Make sure the it exit button on top left side of the window, which must works with gaze!
""" ???
```

## Status

The prompt is complete from the code implementation side.

Implemented and verified in code:

- Settings hotbar action opens a full-screen settings window.
- Settings screen has `Gaze settings` and `Speech settings` tabs.
- Settings controls are normal Qt buttons, so classic mouse clicks work.
- Settings controls are registered for Tobii gaze dwell selection through `SettingsWindow.handle_gaze(...)`.
- Top-left Exit button exists and is gaze-selectable.
- Gaze settings can adjust stare/dwell time, stable target radius, repeat delay, pointer smoothing, and gaze pointer movement.
- Tobii calibration button is wired through `launch_tobii_guest_calibration()`.
- Speech settings can adjust speech speed and letters per group.
- Speech settings are propagated into `SpeechService` and the full-screen speech keyboard.

## Important Files

- `gaze_mouse/settings_window.py`
- `gaze_mouse/toolbar.py`
- `gaze_mouse/tobii_calibration.py`
- `gaze_mouse/speech_service.py`
- `gaze_mouse/speech_window.py`
- `AgentDocs/PrompsHistory/000010_fullscreen_gaze_settings_screen.md`
- `AgentDocs/PrompsHistory/000011_fullscreen_settings_prompt_verification.md`

## What Is Not Confirmed

Real Windows/Tobii runtime behavior is not confirmed in this Linux workspace:

- PySide6 is not installed in the local system Python.
- The `.venv` is a Windows-style virtual environment and cannot be run from this Linux shell.
- The Tobii device and Tobii calibration software are not available here.

## Validation Already Performed

Python syntax validation passed:

```text
python syntax ok
```

Cache scan was clean:

```text
find . -name '__pycache__' -o -name '*.pyc' -o -name '*.pyo'
```

Result: no output.

## Next Required Real-Machine Check

On the Windows Tobii machine:

```powershell
.\run_gaze_mouse.bat
```

Then verify:

- Settings opens full-screen.
- Looking at Exit closes settings.
- Looking at tabs switches tabs.
- Looking at `Less`/`More` changes settings.
- Stare time changes dwell behavior.
- Start Tobii calibration opens Tobii calibration.
- Speech speed and letters-per-group affect speech behavior.
