# Prompt 000062: Fixed Install Root Manual Update Script

## Original Prompt

Please review this and fix it.

Also make sure that when setup_windows.ps1 is run it installs the program at C:/TobiiExec folder always!

Please create update windows script which will download content of this git repository
[thePi314/TobiiEyeTrackerTool](https://github.com/thePi314/TobiiEyeTrackerTool)
As all code is stored there, make sure it ahs to be run manually to update it

## Reviewed Input

- Reviewed the pasted Windows setup transcript.
- The setup transcript showed that Edge TTS / `edge-playback` installation and `bs-BA-GoranNeural` verification succeeded.
- The real issue in that transcript was install location:
  - Setup was launched from a Desktop ZIP/extracted folder.
  - The installed/runtime folder stayed under that Desktop extracted path.
  - It did not normalize the installation to `C:\TobiiExec`.

## What Was Done

- Updated `setup_windows.ps1`.
  - Added fixed install root: `C:\TobiiExec`.
  - Setup now self-elevates as Administrator before it tries to install into `C:\TobiiExec`.
  - Setup always copies project files into `C:\TobiiExec` unless it is already running from that folder.
  - Existing `-InstallRoot` and `-UseSourceFolder` options are now ignored with warning logs, because install location is intentionally fixed.
  - `install_info.json` now records the installed app folder as the runtime log/source root and keeps the original launch folder as `OriginalSourceRoot`.
  - `setup_windows.log` is copied back into the install folder when setup was launched from another folder.
  - `update_windows.ps1` is treated as a required project file and is copied into the fixed install folder.
- Updated `start_gaze_mouse.ps1`.
  - Default install lookup now points to `C:\TobiiExec`.
  - Launcher log wording now says it is using the install metadata log folder instead of the old source-folder wording.
  - The installed `.venv\Scripts` folder is put on `PATH` before Python starts, preserving Edge TTS command lookup behavior.
- Added `update_windows.ps1`.
  - Manual updater for `https://github.com/thePi314/TobiiEyeTrackerTool.git`.
  - Self-elevates as Administrator.
  - Writes `C:\TobiiExec\update_windows.log`.
  - Downloads via Git when available.
  - Falls back to GitHub ZIP download for `main` and then `master`.
  - Mirrors repository content into `C:\TobiiExec`.
  - Preserves `.venv`, `data`, `logs`, generated launcher files, install metadata, and setup/update logs.
  - Runs `C:\TobiiExec\setup_windows.ps1 -NoPause` after updating, unless `-NoSetup` is passed.
- Updated `README.md`.
  - Documents that setup always installs to `C:\TobiiExec`.
  - Documents that old custom install-location options are ignored.
  - Documents how to manually run `C:\TobiiExec\update_windows.ps1`.
  - Documents the updater log path.

## What Is Working

- The setup script no longer uses the ZIP/Desktop/network launch folder as the runtime install folder.
- The normal install and launcher path is now consistently `C:\TobiiExec`.
- The new updater is manual-only and can refresh installed code from the GitHub repository.
- Runtime logs and launcher logs are documented as living under `C:\TobiiExec`.

## What Was Not Fully Verified

- PowerShell was not available in this Linux workspace, so `setup_windows.ps1` and `update_windows.ps1` could not be executed here.
- Actual admin elevation, GitHub download, `robocopy`, desktop shortcut refresh, and dependency installation still need a Windows test run.
- The update script depends on network access to GitHub.

## Verification Performed

- Parsed all `gaze_mouse/*.py` files with Python AST successfully.
- Ran `git diff --check` successfully.
- Confirmed no `__pycache__`, `.pyc`, or `.pyo` files were generated.
