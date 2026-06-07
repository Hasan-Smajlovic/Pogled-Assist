# 000004 - Runtime Latest Log Rotation

Date: 2026-06-06

## Original Prompt

```text
make sure that python program is pushing all of the logs in the project root when running in the logs/latest.txt, everytime program is started it has to copy latest.txt log to the current timestamp where name is in format <timestamp>.txt 
```

## What Was Done

- Added `gaze_mouse/logging_setup.py`.
- Updated `gaze_mouse/main.py` so logging is initialized before Qt imports and app startup.
- Runtime logs now go to:

```text
logs/latest.txt
```

- On each app start:
  - The app root is resolved.
  - `logs/` is created if missing.
  - Existing `logs/latest.txt` is copied before the new log is opened.
  - Archive files use timestamped names:

```text
logs/YYYYMMDD_HHMMSS_microseconds.txt
```

- Added file and console logging through Python `logging`.
- Captured `stdout` and `stderr` into the same log file.
- Installed an uncaught exception hook so unhandled Python exceptions are written to `logs/latest.txt`.
- Installed a Qt message handler so Qt warnings/errors are routed into Python logging.
- Added explicit runtime log entries in:
  - `gaze_mouse/appbar.py`
  - `gaze_mouse/gaze_provider.py`
  - `gaze_mouse/mouse_controller.py`
  - `gaze_mouse/toolbar.py`
- Updated `setup_windows.ps1` required project file checks to include `gaze_mouse\logging_setup.py`.
- Updated `README.md` with the runtime logging behavior.

## Important Files

- `gaze_mouse/logging_setup.py` - logging setup, latest-log rotation, stdout/stderr capture, Qt message handler, exception hook.
- `gaze_mouse/main.py` - calls `setup_application_logging()` at startup.
- `README.md` - documents log path and archive naming.
- `setup_windows.ps1` - now verifies `gaze_mouse\logging_setup.py` exists.

## What Is Working

- Python source syntax validation passes.
- No `__pycache__`, `.pyc`, or `.pyo` files were present after validation.
- The log rotation logic archives existing `logs/latest.txt` before opening the new latest log in write mode.
- If the program is later bundled as an `.exe`, logs will be written next to the executable because `get_project_root()` uses `sys.executable` when `sys.frozen` is set.

## What Is Not Confirmed / Needs Real Runtime Testing

- The full GUI app was not launched in this Linux workspace.
- Runtime log creation and rotation should be tested on the target Windows machine by running the app twice and checking:
  - `logs/latest.txt`
  - `logs/<timestamp>.txt`
- Qt message handling should be confirmed during real GUI runtime.
- Tobii connection logs still need real Eye Tracker 4C testing.

## Validation Performed

Python syntax validation:

```text
python - <<'PY'
from pathlib import Path
paths = [Path('run_gaze_mouse.py'), *sorted(Path('gaze_mouse').glob('*.py'))]
for path in paths:
    compile(path.read_text(encoding='utf-8'), str(path), 'exec')
    print(f'OK {path}')
PY
```

Result:

```text
OK run_gaze_mouse.py
OK gaze_mouse/__init__.py
OK gaze_mouse/appbar.py
OK gaze_mouse/dpi.py
OK gaze_mouse/gaze_provider.py
OK gaze_mouse/logging_setup.py
OK gaze_mouse/main.py
OK gaze_mouse/mouse_controller.py
OK gaze_mouse/toolbar.py
```

Cache check:

```text
find . -name '__pycache__' -o -name '*.pyc' -o -name '*.pyo'
```

Result: no output.

## Notes For Next Agent

- To test rotation on Windows:

```powershell
.\.venv\Scripts\python.exe .\run_gaze_mouse.py
```

- Close the app, run it again, then inspect:

```powershell
Get-ChildItem .\logs
Get-Content .\logs\latest.txt
```

- Expected result after the second run:
  - Fresh `logs/latest.txt` for the current run.
  - One archived timestamped `.txt` file copied from the previous `latest.txt`.
