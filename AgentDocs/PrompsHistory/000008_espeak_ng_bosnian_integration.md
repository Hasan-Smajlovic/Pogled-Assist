# 000008 - eSpeak NG Bosnian Integration

Date: 2026-06-06

## Original Prompt

```text
Add `espeak-ng` with Bosnian language support to the project. Make integration so it works with python!
```

## What Was Added

Implemented eSpeak NG Bosnian speech integration through the existing Python speech service and Windows setup script.

Updated `gaze_mouse/speech_service.py`:

- Uses Bosnian language code `bs`.
- Defines default Bosnian test phrase:

```text
Zdravo. Ovo je test govora na bosanskom jeziku.
```

- Finds `espeak-ng.exe` from:
  - `ESPEAK_NG_EXE`
  - `PATH`
  - bundled `tools\espeak-ng` folder if added later
  - common Windows install locations under `ProgramFiles`, `ProgramFiles(x86)`, and `LocalAppData`
- Validates that an eSpeak NG candidate is executable.
- Validates that the candidate reports Bosnian voice support by checking `--voices=bs`, then falling back to `--voices`.
- Starts speech with eSpeak NG command-line arguments:

```text
-v bs -s 155 -p 50 -a 120 <text>
```

- Hides the console window for the spawned eSpeak process on Windows.
- Tracks and stops any active speech process.

Updated `gaze_mouse/toolbar.py`:

- Imports and uses `SpeechService`.
- Creates the speech service during hotbar startup.
- Stops any active speech process when the toolbar closes.
- Wires the Speech toolbar button to speak the default Bosnian test phrase.
- Shows status if eSpeak NG is missing or could not start.

Updated `setup_windows.ps1`:

- Adds eSpeak NG install parameters and defaults:
  - package id: `eSpeak-NG.eSpeak-NG`
  - version: `1.52.0`
  - MSI asset: `espeak-ng.msi`
- Adds `gaze_mouse\speech_service.py` to required project-file checks.
- Finds an existing eSpeak NG install before trying to install.
- Verifies Bosnian support with `espeak-ng.exe --voices=bs`.
- Installs eSpeak NG automatically:
  - first through `winget install --id eSpeak-NG.eSpeak-NG --exact --source winget --silent --accept-package-agreements --accept-source-agreements --version 1.52.0`
  - then by downloading `https://github.com/espeak-ng/espeak-ng/releases/download/1.52.0/espeak-ng.msi` and running `msiexec.exe /i <msi> /quiet /norestart`
- Writes the verified eSpeak path into generated launchers:
  - `run_gaze_mouse.bat` sets `ESPEAK_NG_EXE`
  - `run_gaze_mouse.ps1` sets `$env:ESPEAK_NG_EXE`
- Prints the selected eSpeak NG executable in final setup instructions.

Updated `README.md`:

- Documents eSpeak NG as a requirement.
- Explains that Windows setup installs and verifies eSpeak NG with Bosnian support.
- Documents the winget and MSI install order.
- Documents the Speech button behavior and the current test phrase.
- Updates limitations to say full speech phrase entry is not implemented yet.

Removed the temporary duplicate wrapper:

- `gaze_mouse/speech_engine.py` was removed after discovering the project already had `gaze_mouse/speech_service.py`.
- Runtime now has one speech integration path.

## Important Files

- `gaze_mouse/speech_service.py` - Python eSpeak NG service and Bosnian voice validation.
- `gaze_mouse/toolbar.py` - Speech button integration.
- `setup_windows.ps1` - automated eSpeak NG install, verification, and launcher environment wiring.
- `README.md` - usage and setup documentation.
- `AgentDocs/PrompsHistory/000008_espeak_ng_bosnian_integration.md` - this handoff file.

## What Is Working

- Python source syntax validation passes.
- No `__pycache__`, `.pyc`, or `.pyo` files were present after validation.
- The toolbar Speech button is now wired to the Python eSpeak NG service.
- Runtime eSpeak discovery validates Bosnian voice support before accepting an executable.
- The Windows setup script now attempts to install and verify eSpeak NG automatically.
- Generated launchers are designed to set `ESPEAK_NG_EXE` so the app uses the exact verified executable.

## What Is Not Confirmed / Needs Real Windows Testing

- PowerShell parsing/execution could not be tested in this Linux workspace because neither `pwsh` nor `powershell` is installed.
- eSpeak NG installation through winget/MSI must be tested on the Windows Tobii machine.
- The actual audio output from the Tobii machine speakers has not been confirmed.
- If the direct MSI fallback requires elevation on the target machine, Windows may still require an administrator/UAC approval. The script logs this failure but cannot bypass Windows security.
- Full speech phrase input is not implemented yet; only the toolbar test phrase is wired.

## Validation Performed

Python syntax validation without bytecode:

```text
PYTHONDONTWRITEBYTECODE=1 python - <<'PY'
from pathlib import Path
paths = [Path('run_gaze_mouse.py'), *sorted(Path('gaze_mouse').glob('*.py'))]
for path in paths:
    compile(path.read_text(encoding='utf-8'), str(path), 'exec')
print('python syntax ok')
PY
```

Result:

```text
python syntax ok
```

Cache check:

```text
find . -name '__pycache__' -o -name '*.pyc' -o -name '*.pyo'
```

Result: no output.

PowerShell availability check:

```text
command -v pwsh || command -v powershell || true
```

Result: no output.

## Expected Windows Test

Run setup:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1
```

Expected setup behavior:

- It logs a step named `Finding eSpeak NG with Bosnian voice support`.
- If eSpeak NG is missing, it tries winget first.
- If winget is unavailable or fails, it downloads `espeak-ng.msi`.
- It verifies the Bosnian voice before continuing.
- It creates launchers that set `ESPEAK_NG_EXE`.
- Final setup instructions include:

```text
eSpeak NG used for Bosnian speech: <path-to-espeak-ng.exe>
```

Expected app behavior:

- Start the app with `run_gaze_mouse.bat`.
- Click the Speech toolbar button.
- The app should speak:

```text
Zdravo. Ovo je test govora na bosanskom jeziku.
```

## Notes For Next Agent

- If setup fails during eSpeak install, inspect `setup_windows.log` around the `Installing eSpeak NG` steps.
- If winget succeeds but verification fails, check where winget placed `espeak-ng.exe` and add that path to both `setup_windows.ps1` and `gaze_mouse/speech_service.py`.
- If eSpeak launches but produces no sound, verify Windows default audio output and run:

```powershell
& $env:ESPEAK_NG_EXE -v bs "Zdravo"
```

- If future work adds real speech phrase input, reuse `SpeechService.speak(text)` instead of introducing another wrapper.
