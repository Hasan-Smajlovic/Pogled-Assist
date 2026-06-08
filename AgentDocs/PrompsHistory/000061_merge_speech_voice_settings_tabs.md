# Prompt 000061: Merge Speech Voice Settings Tabs

## Original Prompt

In Settings merge Speech and Voice tab contents together!

## What Was Done

- Removed the separate `Voice settings` tab from the fullscreen Settings navigation.
- Removed the separate `_build_voice_page()` Settings page.
- Moved the voice preset dropdown into the existing `Speech settings` page.
- Kept the existing speech controls on the same page:
  - Speech speed.
  - Letters per group.
  - Voice dropdown.
  - Test speech button.
- Kept voice dropdown behavior unchanged.
  - Classic mouse selection still works.
  - Gaze dwell selection still works by cycling to the next voice option.
  - Changing the voice still emits `speech_settings_changed` and persists through existing settings save flow.
- Updated `README.md` so the Settings documentation lists the voice preset under `Speech settings` instead of a separate `Voice settings` tab.

## What Is Working

- Settings now shows only `General settings`, `Gaze settings`, and `Speech settings` tabs.
- The `Speech settings` tab contains both speech configuration and voice selection.
- Existing voice preset persistence remains unchanged.

## What Was Not Fully Verified

- The Settings UI was not launched in a Windows/Qt runtime from this Linux workspace.

## Verification Performed

- Parsed `gaze_mouse/settings_window.py` with Python AST without generating bytecode caches.
- Confirmed no old `Voice settings` tab/page references remain in `gaze_mouse/settings_window.py`.
- `git diff --check` passed.
- Confirmed no `__pycache__`, `.pyc`, or `.pyo` files were generated.
