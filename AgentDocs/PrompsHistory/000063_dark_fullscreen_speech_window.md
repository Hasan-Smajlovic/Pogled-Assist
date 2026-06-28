# Prompt 000063: Dark Fullscreen Speech Window

## Original Prompt

You have missunderstud me, the fullscreen window (Speech window), which opens when Speech tab is pressed. That window is too bright! Make sure it's color scheme is dark, same as in the Settings Fullscreen, same as the hotbar is. So adjust colors in the Speech fullscreen to be same as in the Settings Fullscreen window and as the Hotbar colors!

## What Was Done

- Updated `gaze_mouse/speech_window.py`.
- Changed the fullscreen `SpeechWindow` root background from a light gray/blue palette to the same near-black palette used by the hotbar:
  - Root background: `#111318`.
  - Input background: `#0b0d11`.
  - Button background: `#1c2029`.
  - Hover background: `#262c38`.
  - Accent/pressed blue: `#245f9f`.
  - Accent border blue/cyan: `#67b7dc`.
- Darkened all main fullscreen speech controls:
  - Speech input.
  - Letter group buttons.
  - Letter buttons.
  - Space and Backspace utility buttons.
  - Phrases toggle.
  - Clear and Play buttons.
  - Phrase action buttons.
  - Previous/Next phrase buttons.
  - Phrase list buttons.
  - Delete phrase buttons.
  - Close button.
- Updated tool-button icon colors for dark backgrounds so phrase, clear, page, save, cancel, and new-phrase icons stay readable.
- Kept gaze feedback colors visible and consistent:
  - Yellow dwell pulse.
  - Green completed dwell pulse.
  - Red close/delete danger tone.
- Added placeholder text color for the dark speech input.

## What Is Working

- The fullscreen Speech window no longer uses bright white/pale-blue backgrounds.
- The Speech window now visually matches the hotbar/settings dark style much more closely.
- Gaze pulse styling remains present for speech buttons.
- Text and icons are configured for light-on-dark contrast.

## What Was Not Fully Verified

- The Qt window was not visually launched in this Linux workspace.
- Final appearance should be checked on the Windows test machine with the real fullscreen Speech window.

## Verification Performed

- Parsed `gaze_mouse/speech_window.py` successfully with Python AST.
- Ran `git diff --check` successfully.
- Confirmed no `__pycache__`, `.pyc`, or `.pyo` files were generated.
