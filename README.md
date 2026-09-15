# Tobii Gaze Mouse

Windows desktop controls for a Tobii Eye Tracker 4C. The app turns gaze into
pointer movement, dwell clicks, a Bosnian speech keyboard, an on-screen keyboard,
and a compact controller panel.

[Download a Windows release](https://github.com/Hasan-Smajlovic/TobiiEyeTrackerTool/releases)
| [User guide](docs/USER_GUIDE.md)
| [Development](docs/DEVELOPMENT.md)
| [Contributing](CONTRIBUTING.md)

## Features

- A top hotbar that reserves desktop space through the Windows AppBar API.
- Pointer movement and dwell actions only while both eyes have valid tracking.
- Left, right, and double-click modes with an optional precision zoom step.
- A radial Quick actions menu for choosing a click at the current gaze target.
- A visible gaze bubble and action progress overlay.
- A full-screen Bosnian speech keyboard with reusable phrases.
- Right-side Keyboard and Controller panels for typing and common shortcuts.
- Gaze-selectable settings for timing, smoothing, speech, startup, and logging.
- Tobii Pro SDK, Stream Engine, and optional 32-bit Stream Engine bridge support.

## Install

### Windows release

Download the versioned ZIP and matching `.sha256` file from
[GitHub Releases](https://github.com/Hasan-Smajlovic/TobiiEyeTrackerTool/releases).
Verify the checksum, extract the ZIP, then run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\install_windows.ps1 -Launch
```

The installer copies the app to `C:\TobiiExec`, verifies that the packaged
executable starts, and creates a desktop shortcut. The release includes Python
and the application dependencies. Tobii software, tracker calibration, speech
engines, and the optional 32-bit bridge runtime remain separate.

See the [Windows release guide](docs/WINDOWS_RELEASE.md) for checksum verification,
external components, rollback, and clean-machine checks.

### Source installation

The source setup installs Python 3.10 when needed, eSpeak NG, the optional 32-bit
Python bridge, a local `.venv`, launchers, and the desktop shortcut:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1
```

Source installations live under `C:\TobiiExec`. Add `-Launch` to start the app
after setup or `-NoPause` when running from an existing terminal.

## Run

Installed release or source setup:

```powershell
.\start_gaze_mouse.ps1
```

Development checkout:

```powershell
.\dev.ps1 setup
.\dev.ps1 run
```

The real application starts Tobii discovery and enables Windows input. Use the UI
preview command when you only want to inspect layout and styling.

## Local development

The repository uses one PowerShell entry point instead of Make because Windows
does not include Make by default:

```powershell
.\dev.ps1 help
```

| Command | Purpose |
| --- | --- |
| `.\dev.ps1 setup` | Create `.venv` and install test, lint, and build tools |
| `.\dev.ps1 run` | Run the real application from source |
| `.\dev.ps1 ui` | Render 12 hardware-free UI screenshots and an HTML gallery |
| `.\dev.ps1 ui -Open` | Render and open the UI gallery |
| `.\dev.ps1 test` | Run every hardware-independent test |
| `.\dev.ps1 test-ui` | Run UI workflow and rendering tests only |
| `.\dev.ps1 coverage` | Run tests with the coverage floor and HTML report |
| `.\dev.ps1 lint` | Run Python and PowerShell code checks |
| `.\dev.ps1 format` | Apply Ruff import fixes and Python formatting |
| `.\dev.ps1 check` | Run the complete pre-PR verification |
| `.\dev.ps1 package` | Build and smoke-test the Windows release ZIP |

`Ruff` handles Python linting, import ordering, modernization checks, and
formatting. `PSScriptAnalyzer` checks PowerShell for selected correctness and
security problems. A separate Black, isort, Flake8, ESLint, or Prettier setup
would duplicate those checks.

For a visual review without a tracker or speech engine:

```powershell
.\dev.ps1 ui -Open
```

The gallery is written to `dist\ui-preview\index.html`. It renders the actual Qt
widgets with hardware and Windows input disabled. Review it at the target Windows
scale as well, because automated screenshots cannot prove DPI, font, AppBar, or
multi-monitor behavior on another machine.

The full workflow and UI checklist are in the
[development guide](docs/DEVELOPMENT.md).

## Runtime requirements

| Component | Why it is needed |
| --- | --- |
| Tobii runtime and calibration | Device discovery and calibrated gaze data |
| `tobii-research` | Preferred tracker API, included in Python and release installs |
| Tobii Stream Engine | Fallback for consumer trackers such as Eye Tracker 4C |
| Python 3.10 x86 | Optional bridge when only a 32-bit Stream Engine DLL is available |
| eSpeak NG with `bs` voice | Default offline Bosnian speech |
| `edge-playback` | Optional online Bosnian neural voice |

The app searches common install locations. These environment variables override
discovery when needed:

| Variable | Value |
| --- | --- |
| `TOBII_STREAM_ENGINE_DLL` | Full path to `tobii_stream_engine.dll` |
| `TOBII_GAZE_MOUSE_X86_PYTHON` | Full path to 32-bit Python 3.10 |
| `TOBII_CALIBRATION_COMMAND` | Custom Tobii calibration command |
| `ESPEAK_NG_EXE` | Full path to `espeak-ng.exe` |
| `EDGE_PLAYBACK_EXE` | Full path to `edge-playback.exe` |

## Data and logs

User data is kept outside the packaged binaries so upgrades and rollbacks can
preserve it:

```text
data\app_settings.json
data\speech_phrases.json
logs\latest.txt
```

The launcher also writes `start_gaze_mouse.log`. Source setup and updates write
their own logs in the installation directory.

## Current limitations

- Windows x64 is the supported application platform.
- The release executable is not code-signed, so Windows may show an
  unknown-publisher warning.
- Multi-monitor mapping assumes the Tobii-calibrated display is primary.
- GitHub-hosted runners cannot verify a physical tracker, calibration, AppBar
  behavior, speech playback, or real Windows input.
- The human-like voice uses an external online service.

## CI and releases

Pull requests to `development` and `master` run `code-quality`, `tests`, and
`windows-package`. Tests run without Tobii hardware and enforce the current
coverage floor. Every merge to `master` repeats the checks, builds the exact
merged commit, and publishes one immutable `v<version>` release with a Windows
ZIP and SHA-256 checksum.

Release construction, manual hardware validation, and rollback are documented in
the [Windows release guide](docs/WINDOWS_RELEASE.md).
