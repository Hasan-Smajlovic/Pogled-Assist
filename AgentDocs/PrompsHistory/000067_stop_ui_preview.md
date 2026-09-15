# Stop UI preview

## Original prompt

> kako da sad ovo ugasim

## Requested outcome

Explain how to stop the UI-only preview process.

## Resolution

- Focus the same PowerShell terminal used to launch the preview and press `Ctrl+C`.
- If the terminal interrupt does not close the Qt application, use `Settings` and select `Quit application` from inside the UI.

## What is working

- The preview is running as a foreground Python process, so the terminal interrupt is the simplest shutdown method.

## What is not working

- Nothing reported about shutdown yet.
