# Prompt 000047 - Launcher Window Visibility Setting

## Original Prompt

Make sure powershell for starting application is running in background so there is no window for It.
Add checkbox for that in Settings menu as well!
When it's on it should be showend (so no silience)
When it's off it should be silenced in background!

## Changes Made

- Added a persisted gaze/general setting named `show_launcher_window`.
  - Default is `false`, so the PowerShell launcher runs silently in the background unless the user enables the visible launcher window.
  - The setting is loaded, coerced, saved, and restored with the rest of `data/app_settings.json`.

- Updated the fullscreen Settings UI.
  - Added `Show PowerShell launcher window` to the `General settings` tab.
  - The checkbox works with normal mouse clicks and gaze selection because it uses the existing gaze-selectable checkbox helper.
  - Checked means future launcher windows stay visible.
  - Unchecked means future launcher windows are hidden/silent.

- Updated `start_gaze_mouse.ps1`.
  - Reads `show_launcher_window` from `data/app_settings.json`.
  - Checks settings in the installed app folder, script folder, explicit install root, `TOBII_GAZE_MOUSE_LOG_ROOT`, and the original source/network folder recorded in `install_info.json`.
  - Syncs the current console visibility early: hides it when the setting is off, and shows it when the setting is on even if an older shortcut started PowerShell with `-WindowStyle Hidden`.
  - Avoids waiting for Enter when running in hidden mode.
  - Recreates the desktop shortcut with `-WindowStyle Hidden` when launcher visibility is off.
  - Keeps the visible behavior available when the checkbox is on.

- Updated `setup_windows.ps1`.
  - The first desktop shortcut created by setup now uses `-WindowStyle Hidden` by default.
  - If an existing `data/app_settings.json` has `show_launcher_window` enabled, setup keeps the generated shortcut visible.

- Updated Windows startup scheduled-task creation.
  - The `Start with Windows as Administrator` task now includes `-WindowStyle Hidden` unless `show_launcher_window` is enabled.
  - If startup is already enabled and the launcher visibility checkbox changes, the task is refreshed with the new visibility mode.

- Updated README documentation.
  - Documented the new `Show PowerShell launcher window` checkbox under `General settings`.
  - Clarified that hidden mode still writes `start_gaze_mouse.log`.

## What Should Work Now

- By default, `start_gaze_mouse.ps1` should hide its PowerShell console and run the application in the background.
- Turning on `Show PowerShell launcher window` in Settings should make future manual/startup launches visible.
- Turning it off should make future manual/startup launches silent again.
- The generated desktop shortcut should follow the saved launcher visibility setting after the launcher is run once and recreates the shortcut.
- The setup-generated desktop shortcut should also follow the saved launcher visibility setting.
- Windows startup should follow the same setting when the scheduled task is created or refreshed.

## Important Notes

- Windows UAC consent prompts cannot be hidden by the application. Manual launches still need elevation when required, so Windows may still show the UAC prompt even when the PowerShell console itself is hidden.
- Runtime PowerShell behavior could not be executed from this Linux workspace, so final verification still needs to be performed on the Windows test machine.

## Validation Performed

- Syntax-checked changed Python files with `compile(...)` under `PYTHONDONTWRITEBYTECODE=1` and `python -B`.
- Confirmed no `__pycache__`, `.pyc`, or `.pyo` files were created.
- PowerShell parsing/runtime validation was not available in this Linux workspace because neither `pwsh` nor `powershell.exe` is installed.
