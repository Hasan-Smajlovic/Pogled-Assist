# 000042 - Tobii Calibration Launcher Fix

## Original Prompt

tobii calibration does not start when selected in the settings! It must open up tobii driver calibration when it's selected in the settings

## What Was Done

- Reworked `gaze_mouse/tobii_calibration.py`.
- The previous implementation only sent Tobii's `Ctrl+Shift+F10` guest calibration shortcut.
- The new implementation now tries a stronger Windows launch sequence:
  - Supports an override command through `TOBII_CALIBRATION_COMMAND`.
  - Searches Tobii Start Menu shortcuts under:
    - `%ProgramData%\Microsoft\Windows\Start Menu\Programs`
    - `%AppData%\Microsoft\Windows\Start Menu\Programs`
  - Searches common Tobii install roots under:
    - `%ProgramFiles%\Tobii`
    - `%ProgramFiles(x86)%\Tobii`
    - `%LocalAppData%\Tobii`
    - `%ProgramData%\Tobii`
  - Ranks likely Tobii UI/configuration executables higher than service/engine/updater executables.
  - Launches the best Tobii UI/configuration target with Windows `ShellExecuteW`.
  - Falls back to likely Tobii URI/protocol targets if no installed UI target was found.
  - Sends `Ctrl+Shift+F10` multiple times after launching the Tobii UI so the calibration shortcut has a better chance of being handled by Tobii Core.
- Updated `gaze_mouse/toolbar.py`.
  - The fullscreen Settings window is now hidden before launching Tobii calibration.
  - This avoids the previous situation where Tobii calibration could start behind the app's fullscreen topmost Settings window and look like it did nothing.
- Updated `README.md`.
  - Documented the new calibration launch behavior.
  - Documented `TOBII_CALIBRATION_COMMAND` for machine-specific Tobii launch commands.

## Files Changed

- `gaze_mouse/tobii_calibration.py`
- `gaze_mouse/toolbar.py`
- `README.md`
- `AgentDocs/PrompsHistory/000042_tobii_calibration_launcher_fix.md`

## What Is Working

- The Settings calibration button still emits `calibration_requested`.
- The toolbar still handles that request through `launch_tobii_guest_calibration()`.
- The launch helper now actively opens a Tobii UI/configuration target instead of relying only on a global hotkey.
- The helper logs:
  - Candidate Tobii targets and scores.
  - Which target was started.
  - Whether `Ctrl+Shift+F10` was sent.
  - Any ShellExecute failure codes.
- Settings hides before external Tobii calibration launch, so the Tobii UI should be visible if it starts successfully.

## What Was Not Runtime-Tested

- Actual Tobii Core/Experience calibration launch could not be tested in this Linux workspace.
- Windows runtime confirmation is required on the Tobii machine.

## Validation

- Python syntax compilation passed with `PYTHONDONTWRITEBYTECODE=1`.
- Checked for generated `__pycache__`, `.pyc`, and `.pyo` files; none were present.

## Windows Testing Notes

- Rerun `setup_windows.ps1` so the local installed folder receives the updated files.
- Start the app with `start_gaze_mouse.ps1`.
- Open Settings and select `Start Tobii calibration`.
- Expected behavior:
  - Settings disappears.
  - Tobii Core/Experience or EyeX configuration UI opens.
  - Calibration starts or the Tobii UI receives the calibration shortcut.
- If it still does not open calibration directly, inspect `logs\latest.txt` for:

```text
Best Tobii launch candidates
ShellExecute started Tobii launch target
Sent Tobii calibration shortcut Ctrl+Shift+F10
Tobii calibration launch requested through
```

- If the selected candidate is wrong for that machine, set this before starting the app:

```powershell
$env:TOBII_CALIBRATION_COMMAND = "C:\Path\To\Correct\TobiiCalibrationOrConfig.exe"
.\start_gaze_mouse.ps1
```
