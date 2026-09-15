# Fix UI-only launch command

## Original prompt

> > > ^C
> > > (.venv) PS C:\Users\smajl\OneDrive\Desktop\Github\TobiiEyeTrackerTool> ^C
> > > (.venv) PS C:\Users\smajl\OneDrive\Desktop\Github\TobiiEyeTrackerTool> ^C
> > > (.venv) PS C:\Users\smajl\OneDrive\Desktop\Github\TobiiEyeTrackerTool> Set-Location 'C:\Users\smajl\OneDrive\Desktop\Github\TobiiEyeTrackerTool'; $env:PYTHONDONTWRITEBYTECODE='1'; ..venv\Scripts\pythonw\.exe -c "import gaze\_mouse.toolbar as t; t.TobiiGazeProvider.start=lambda self: None; from gaze\_mouse.main import main; raise SystemExit(main())"
> > > (.venv) PS C:\Users\smajl\OneDrive\Desktop\Github\TobiiEyeTrackerTool>
> >
> > nista mi ne pokrece

## Diagnosis

The pasted command differs from the intended command in several important places:

- `..venv` was used instead of `.\.venv`.
- `pythonw\.exe` contains an invalid extra backslash before `.exe`.
- `gaze\_mouse` contains invalid backslashes in the Python package name.
- The prompt already shows `(.venv)`, so an explicit interpreter path is unnecessary.

## Resolution

Provide a shorter PowerShell command that uses the already active virtual environment's `python` executable. Keeping the terminal attached also makes any startup error visible instead of hiding it through `pythonw.exe`.

The command still sets `PYTHONDONTWRITEBYTECODE=1` and replaces `TobiiGazeProvider.start()` with a no-op only for that process, so it does not search for a Tobii device.

## What is working

- The repository directory and virtual environment are already active.
- The corrected command has no fragile executable path or escaped Python identifiers.

## What is not working

- The previous malformed command did not launch the application.
