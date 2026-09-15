# UI-only launch command

## Original prompt

> napisi mi samo komandu koju cu ja koristiti pri pokretanju samog ui

## Requested outcome

Provide a single PowerShell command that launches only the visible application UI without searching for or connecting to a Tobii device.

## What was done

- Prepared a PowerShell command that first changes to the repository directory.
- Sets `PYTHONDONTWRITEBYTECODE=1` to avoid generating new `__pycache__` content.
- Uses the repository virtual environment's `pythonw.exe` so no console window remains visible.
- Replaces `TobiiGazeProvider.start()` with a no-op only for that process before starting the normal application entry point.

## What is working

- The command uses the existing UI unchanged.
- Tobii device discovery and Stream Engine fallback are not started.
- No persistent source code modification is required.

## What is not working

- Nothing known. The user will run the command locally.
