# Prompt 000048 - Application Icon Asset

## Original Prompt

I have added assets/icon.png. Make sure that is used as icon for this application!

## Changes Made

- Added `gaze_mouse/app_icon.py`.
  - Resolves `assets/icon.png` from the runtime project root, source tree, installed app folder, or future bundled executable folder.
  - Provides `load_app_icon()` for Qt.

- Updated `gaze_mouse/main.py`.
  - Loads `assets/icon.png` when the Qt application starts.
  - Applies it with `QApplication.setWindowIcon(...)`.
  - Applies it directly to the main hotbar window as well.
  - Logs the icon path or `missing` during startup.

- Updated setup/install behavior in `setup_windows.ps1`.
  - Copies the root `assets` folder into the local install folder.
  - Adds `assets\icon.png` and `gaze_mouse\app_icon.py` to required file validation.
  - Creates `assets\icon.ico` from `assets\icon.png` with Windows `System.Drawing` when generating the desktop shortcut.
  - Uses the generated `.ico` as the `Tobii Gaze Mouse` desktop shortcut icon.

- Updated normal launcher behavior in `start_gaze_mouse.ps1`.
  - When recreating the desktop shortcut, it finds `assets\icon.png`.
  - Prefers the local installed icon asset, then falls back to the original source/network folder if needed.
  - Creates or refreshes `assets\icon.ico` from the PNG.
  - Uses the generated `.ico` for the desktop shortcut, falling back to the PowerShell icon only if conversion fails.

- Updated README.
  - Documented that `assets\icon.png` is the app icon source.
  - Documented that launchers create `assets\icon.ico` for Windows shortcuts.

## What Should Work Now

- The running PySide6/Qt app should use `assets/icon.png` as the application icon.
- The desktop shortcut created by setup should use the app icon.
- The desktop shortcut recreated by `start_gaze_mouse.ps1` should use the app icon.
- The icon asset should survive installation to `%LocalAppData%\TobiiGazeMouse` because setup now copies the root `assets` folder.

## Important Notes

- Windows shortcut icons are generated as `.ico` files because `.lnk` files handle `.ico` paths more reliably than raw PNG paths.
- The `.ico` conversion uses Windows `System.Drawing`, so it can only be runtime-tested on the Windows test machine.

## Validation Performed

- Syntax-checked `gaze_mouse/app_icon.py` and `gaze_mouse/main.py` with `compile(...)` under `PYTHONDONTWRITEBYTECODE=1` and `python -B`.
- Confirmed no `__pycache__`, `.pyc`, or `.pyo` files were created.
- PowerShell parsing/runtime validation was not available in this Linux workspace because neither `pwsh` nor `powershell.exe` is installed.
