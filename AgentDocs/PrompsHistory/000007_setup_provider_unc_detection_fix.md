# 000007 - Setup Provider UNC Detection Fix

Date: 2026-06-06

## Original Prompt

```text
setup_windows  script failed again!
inspect setpu_windows.log and mae neccecary changes. 
Everything must be auotmated  
```

## Setup Log Analysis

The newest `setup_windows.log` section showed the script still used the network share instead of copying to the local install folder:

```text
[INFO] Source root: \\192.168.0.30\Tobii
[INFO] Repository root: Microsoft.PowerShell.Core\FileSystem::\\192.168.0.30\Tobii
```

Then it reused the bad network-share virtual environment:

```text
[STEP] Preparing virtual environment
[OK] Using existing virtual environment at Microsoft.PowerShell.Core\FileSystem::\\192.168.0.30\Tobii\.venv
Program 'python.exe' failed to run: Access is denied
```

Root cause:

- PowerShell resolved the UNC path into a provider-qualified path:

```text
Microsoft.PowerShell.Core\FileSystem::\\192.168.0.30\Tobii
```

- The script's network path check only checked whether the path started with `\\`.
- Because the provider-qualified path started with `Microsoft.PowerShell.Core\FileSystem::`, the network path was not detected.
- The script did not copy to `%LocalAppData%\TobiiGazeMouse`.
- It then tried to reuse/run the old network `.venv`, causing another access denied error.

## What Was Fixed

Updated `setup_windows.ps1`:

- Added `Remove-FileSystemProviderPrefix`.
- Updated `Get-NormalizedFullPath` to strip `Microsoft.PowerShell.Core\FileSystem::`.
- Updated `Test-IsNetworkPath` to strip the provider prefix before checking for UNC paths.
- Moved `Start-SetupTranscript` before `Initialize-WorkingRoot` so setup log captures:
  - working-folder preparation
  - network path detection
  - local install copy
- Stopped changing `LogPath` to the local install folder during `Initialize-WorkingRoot`; setup logs stay visible at the original source path where the user is already inspecting them.
- Hardened `Ensure-VirtualEnvironment`:
  - If `.venv\Scripts\python.exe` exists, the script probes it.
  - If the existing venv is broken, inaccessible, or not Python 3.10, it deletes and recreates the venv automatically.
  - Verification now uses safe native-command probing instead of direct invocation that can terminate PowerShell setup unexpectedly.

## Important Files

- `setup_windows.ps1` - fixed provider-qualified UNC detection and venv reuse.
- `setup_windows.log` - analyzed latest failure.
- `AgentDocs/PrompsHistory/000007_setup_provider_unc_detection_fix.md` - this handoff file.

## Expected Next Windows Run

Run from the network share as before:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1
```

Expected behavior:

- `setup_windows.log` should include a `Preparing setup working folder` step.
- The script should detect `\\192.168.0.30\Tobii` even if PowerShell resolves it as `Microsoft.PowerShell.Core\FileSystem::\\192.168.0.30\Tobii`.
- The script should copy the project to:

```text
%LocalAppData%\TobiiGazeMouse
```

- `.venv` should be created or reused under the local install folder, not under the network share.
- If any stale local `.venv` is broken, it should be recreated automatically.

## What Is Working

- Python source syntax validation passes.
- No `__pycache__`, `.pyc`, or `.pyo` files were present after validation.
- The script now treats provider-qualified UNC paths as network paths.
- Existing venv reuse is now verified before use.

## What Is Not Confirmed / Needs Real Windows Testing

- PowerShell execution/parsing could not be tested in this Linux workspace because neither `pwsh` nor `powershell` is installed.
- The local-copy path must be tested on the Windows machine by rerunning `setup_windows.ps1`.
- Dependency installation still needs to be confirmed after the setup reaches that step.

## Validation Performed

Python syntax validation:

```text
python - <<'PY'
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

## Notes For Next Agent

- If the next setup log still shows `Repository root: Microsoft.PowerShell.Core\FileSystem::\\192.168.0.30\Tobii`, provider-prefix stripping did not run as expected.
- The next expected `Repository root` should be a local path such as:

```text
C:\Users\Korisnik\AppData\Local\TobiiGazeMouse
```

- If package installation fails after venv creation, inspect the pip error and patch the setup script around dependency installation.
