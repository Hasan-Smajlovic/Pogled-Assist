# Prompt 000044 - Windows Startup Admin Setting

## Original Prompt

In Settings screen, add checkbox which can be toggled to start the application on windows startup!
When it's checked it should start up the program after windows starts
When it's unchecked it will be started up manually

Make sure it starts as Administrator always!

## Changes Made

- Added a new Windows startup helper module: `gaze_mouse/windows_startup.py`.
  - Creates a per-user Windows Scheduled Task named `Tobii Gaze Mouse`.
  - Uses `New-ScheduledTaskPrincipal -LogonType Interactive -RunLevel Highest` so the app starts elevated at user logon.
  - Points the task at the installed `start_gaze_mouse.ps1` script with `-NoPause`.
  - Can query whether the startup task exists and is enabled.
  - Can remove the scheduled task when startup is disabled.

- Added `start_with_windows` to `GazeSettings`.
  - Persisted through `data/app_settings.json`.
  - Old settings files continue to load because missing fields fall back to defaults.

- Added a gaze-selectable checkbox to the fullscreen Settings screen.
  - Label: `Start with Windows as Administrator`.
  - Located in `Gaze settings`.
  - Works with classic mouse clicks and Tobii gaze dwell selection through the existing settings gaze-action registry.
  - Syncs the checkbox state from the actual Windows Scheduled Task when Settings opens.
  - Toggling it creates/removes the scheduled task and saves the resulting setting.

- Updated `start_gaze_mouse.ps1`.
  - The launcher now checks whether it is running as Administrator.
  - If not elevated, it restarts itself using `Start-Process -Verb RunAs`.
  - This means both manual desktop shortcut launches and scheduled-task launches enter the app through the same elevated launcher path.

- Updated setup validation and docs.
  - `setup_windows.ps1` now requires `gaze_mouse/windows_startup.py`.
  - README documents the `Start with Windows as Administrator` behavior.

## What Should Work Now

- Checking `Start with Windows as Administrator` in Settings should create the Windows Scheduled Task.
- After Windows logon, the task should start `start_gaze_mouse.ps1`, which starts the Python app elevated.
- Unchecking the setting should remove the scheduled task, so the app only starts manually.
- Starting the app from the desktop shortcut should also relaunch as Administrator before Python starts.

## Important Notes

- The scheduled task uses highest available privileges for the current Windows user. If the Windows account is not an administrator, Windows cannot silently turn it into a full administrator account without credentials.
- Creating the elevated startup task is expected to work when the app was launched through the updated `start_gaze_mouse.ps1`, because that launcher self-elevates first.
- This Linux workspace cannot execute Windows PowerShell ScheduledTasks commands, so the PowerShell path was statically inspected but not runtime-tested here.

## Validation Performed

- Syntax-checked changed Python files with `compile(...)` under `PYTHONDONTWRITEBYTECODE=1` and `python -B`.
- Confirmed no `__pycache__`, `.pyc`, or `.pyo` files were created.

