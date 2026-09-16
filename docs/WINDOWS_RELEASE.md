# Windows release installation and validation

The versioned Windows x64 release is a ZIP containing a PyInstaller one-folder
application, an installer, a launcher, this guide, and the release `VERSION`.
The package includes Python, PySide6, QtAwesome resources, the app icon, the
Settings checkbox asset, the Tobii Pro SDK Python package, and the source needed
by the optional 32-bit Stream Engine bridge.

## Install a release

1. Download `TobiiGazeMouse-v<version>-windows-x64.zip` and its matching
   `.sha256` file from the same GitHub Release.
2. Verify the checksum:

   ```powershell
   $expected = (Get-Content .\TobiiGazeMouse-v0.1.0-windows-x64.zip.sha256).Split()[0]
   $actual = (Get-FileHash .\TobiiGazeMouse-v0.1.0-windows-x64.zip -Algorithm SHA256).Hash
   if ($actual -ne $expected) { throw "Checksum mismatch" }
   ```

3. Extract the ZIP, open the `TobiiGazeMouse` folder, and run:

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass -Force
   .\install_windows.ps1 -Launch
   ```

The installer requests Administrator access, mirrors application files to
`C:\TobiiExec`, preserves `data` and `logs`, and creates the `Tobii Gaze Mouse`
desktop shortcut. Before replacing files, it rejects a running application,
creates and smoke-tests a staging copy, and backs up the current application
files. If the copy or installed smoke test fails, it restores the backup. Run
`C:\TobiiExec\start_gaze_mouse.ps1` or the shortcut later.

The extracted folder is also portable. Run its `start_gaze_mouse.ps1` without
installing if a portable copy is preferred.

## Components installed separately

- Tobii runtime and calibration: install the official software appropriate for
  the tracker, connect the device, and complete calibration. The package cannot
  safely install or calibrate hardware.
- Tobii Stream Engine: Tobii Eye Tracker 4C setups commonly obtain
  `tobii_stream_engine.dll` from Tobii Core or Game Hub. The app searches common
  install locations. Set `TOBII_STREAM_ENGINE_DLL` when the DLL is elsewhere.
- 32-bit bridge: a 32-bit Tobii DLL cannot load in the packaged 64-bit process.
  Install 32-bit Python 3.10 and set `TOBII_GAZE_MOUSE_X86_PYTHON` to its
  `python.exe`. The package already contains the bridge source.
- Default speech: install eSpeak NG 1.52 with the Bosnian `bs` voice. Set
  `ESPEAK_NG_EXE` if `espeak-ng.exe` is outside the standard install folders.
- Human-like speech: install the `edge-tts` package so `edge-playback.exe` is on
  `PATH`, or set `EDGE_PLAYBACK_EXE` directly. This voice uses Microsoft's online
  service and needs internet access at runtime.

The application launches without these external components. Missing Tobii
software disables gaze input while the provider retries. Missing speech tools
disable their corresponding voice preset.

## Build locally

Use Windows x64 and Python 3.10:

```powershell
.\dev.ps1 setup
.\dev.ps1 package
```

The build reads `VERSION`, uses the checked-in PyInstaller spec, checks required
assets, executes the packaged `--package-smoke-test`, installs an extracted copy
in an isolated directory, and creates:

```text
dist\TobiiGazeMouse-v<version>-windows-x64.zip
```

No physical tracker, Tobii runtime, eSpeak NG, or network speech service is used
by the package smoke test.

## Automated release

Pull requests targeting `development` or `master` run:

- `code-quality`
- `tests`
- `windows-package`

The first two checks include Ruff formatting, focused PSScriptAnalyzer rules,
hardware-independent UI rendering, and the enforced Python coverage floor.

After an approved merge to `master`, the release workflow checks out exactly
`github.sha`, repeats all software checks, builds the package, and creates the
`v<version>` tag at that commit. It uploads the ZIP and a SHA-256 file to a draft,
then publishes the draft only after both assets exist.

Rerunning the same commit is idempotent. A complete public release is left
unchanged. An incomplete draft for the same commit is repaired and published.
If the version tag points to any other commit, the workflow fails and requires a
new `VERSION`. It never moves or overwrites an existing version tag.

## Manual release validation

Report software-only and Tobii hardware checks separately.

Software-only checks on a clean Windows x64 environment:

- Verify the SHA-256 file before extraction.
- Run `install_windows.ps1` and confirm installation under `C:\TobiiExec`.
- Start the app from the desktop shortcut and confirm the toolbar appears.
- Open Settings, Speech, Keyboard, and Controller.
- Close and reopen the app and confirm settings persist under `data`.
- Confirm logs are written under `logs` when logging is enabled.

Hardware checks on the target Tobii machine:

- Confirm Tobii software detects and calibrates the tracker.
- Confirm the runtime log reports Tobii Pro SDK, Stream Engine, or the x86 bridge.
- Confirm both-eye tracking moves the pointer and dwell actions fire.
- Confirm left, right, double-click, keyboard, controller, and calibration actions.
- Confirm default eSpeak NG speech and optional human-like speech separately.

## Known limits

- The package supports Windows x64. AppBar behavior and Windows input do not work
  on other operating systems.
- The executable is not code-signed, so Windows may show an unknown-publisher
  warning.
- Multi-monitor mapping assumes the Tobii-calibrated display is primary.
- Physical Tobii behavior cannot be proven by GitHub-hosted runners.
- The human-like voice depends on an external online service.

## Rollback

Download an earlier immutable release, verify its checksum, extract it, and run
its `install_windows.ps1`. Close Tobii Gaze Mouse first. The installer validates
the older package before replacing application binaries, preserves
`C:\TobiiExec\data` and `C:\TobiiExec\logs`, and restores the previous binaries if
installation fails. If saved settings from a newer version are incompatible,
back up `data`, remove only the affected JSON file, and restart the older version.
Never move or recreate an existing release tag during rollback.
