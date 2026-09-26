# Windows release installation and validation

The versioned Windows x64 release is a ZIP containing a PyInstaller one-folder
application, an installer, a launcher, a release updater, this guide, and the
release `VERSION`.
The package includes Python, PySide6, QtAwesome resources, the app icon, the
Settings checkbox asset, the Tobii Pro SDK Python package, speech tools, and
the isolated Python runtime and source for the 32-bit Stream Engine bridge.

## Install a release

1. Download `PogledAssist-v<version>-windows-x64.zip` and its matching
   `.sha256` file from the same GitHub Release.
2. Verify the checksum:

   ```powershell
   $expected = (Get-Content .\PogledAssist-v0.1.0-windows-x64.zip.sha256).Split()[0]
   $actual = (Get-FileHash .\PogledAssist-v0.1.0-windows-x64.zip -Algorithm SHA256).Hash
   if ($actual -ne $expected) { throw "Checksum mismatch" }
   ```

3. Extract the ZIP, open the `PogledAssist` folder, and run:

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass -Force
   .\install_windows.ps1 -Launch
   ```

The installer requests Administrator access, preserves `data`, `logs`, root log
files, `install_info.json`, local `.venv` speech tools, and local `tools`
components, and creates the `Pogled Assist` desktop shortcut. Before
replacing files, it rejects both packaged and source-based running applications,
creates and smoke-tests a sibling staging directory, and renames the existing
installation to a backup. The backup remains until the new installed application
passes its smoke test. If installation or verification fails, it restores the
previous directory. Run
`C:\PogledAssist\start_gaze_mouse.ps1` or the shortcut later.

The previous application under `C:\TobiiExec` remains independent. The Pogled
Assist installer and updater reject that legacy path even when it is supplied
explicitly, and use their own executable name, desktop shortcut, startup task,
process checks, locks, environment variables, data, and logs.

The extracted folder is also portable. Run its `start_gaze_mouse.ps1` without
installing if a portable copy is preferred.

## Update an installed release

Close Pogled Assist, open PowerShell in `C:\PogledAssist`, and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\update_windows.ps1
```

The updater reads the installed `VERSION` and calls GitHub's latest stable
release endpoint for `Hasan-Smajlovic/Pogled-Assist`. It accepts only a
stable `v<major>.<minor>.<patch>` tag and the exact
`PogledAssist-v<version>-windows-x64.zip` and matching `.sha256` assets from
that repository. It verifies the checksum and package `VERSION` before invoking
the package installer. A checksum, metadata, network, archive, or staging error
does not change application files. The updater refuses an automatic downgrade
when the installed version is newer than the latest stable release.

Only one updater and one installer can run at a time. Neither process stops a
running application automatically. Close the application and retry when the
updater reports a running process. Add `-Launch` to start the verified version
after a successful update. Update details are appended to
`C:\PogledAssist\update_windows.log`.

Before updating, close File Explorer windows showing the installation folder or
its subfolders. If another process still holds that folder open when the
installer swaps directories, the installer makes a few short attempts and then
stops with an instruction to close those windows and retry. An update started
from the app keeps its console open on failure so the instruction remains
visible. When the old directory could not be moved, the previous installation
stays in place. If a later step fails, the installer restores the backup or
keeps the transaction data for recovery if Windows also blocks the rollback.

## Upgrade a Pogled Assist source installation

An existing Pogled Assist source installation uses its older updater, so it
cannot download this replacement updater by itself. Download the first stable
release manually, verify its checksum, and run that package's
`install_windows.ps1`. The installer recognizes the source layout under
`C:\PogledAssist` and upgrades it only after staging succeeds.

The migration preserves `data`, `logs`, `install_info.json`, root log files,
local `.venv` speech tools, and local `tools` components. The packaged
`update_windows.ps1` then installs only immutable stable releases and never
downloads a Git branch or repository source archive.

## Interrupted update recovery

The installer writes a transaction marker beside `C:\PogledAssist` immediately
before the directory swap. If the process or machine stops during that swap,
rerun `update_windows.ps1` or the verified package's `install_windows.ps1`. The
installer examines the current, staging, and backup directories under the
installer lock. It keeps a current version that passes the package smoke test or
restores the backup when the current version is missing or fails verification.

Do not manually delete hidden `.PogledAssist.install-*` or
`.PogledAssist.backup-*` paths while recovery is pending. If automatic rollback
also fails, the error identifies the retained transaction marker and backup for
manual recovery.

## Included speech tools

The release includes eSpeak NG 1.52.0 with the Bosnian `bs` voice and standalone
`edge-playback.exe` and `edge-tts.exe` built from edge-tts 7.2.8. Installation
copies them under `speech/` along with their runtimes, licenses, and matching
source archives. Users do not need to install Python, use pip, or adjust PATH.
The portable ZIP also includes these tools. Standard speech works offline;
natural speech uses Microsoft's online service and requires internet when used.

The launcher and direct executable prefer these bundled tools over discovered
system installations. Explicit `ESPEAK_NG_EXE` and `EDGE_PLAYBACK_EXE` overrides
still take priority. Existing `.venv` and `tools` directories are preserved for
compatibility; versioned files under `speech/` are replaced with each release.

The installer verifies bundled speech during staging and after installation.
It generates a short Bosnian WAV without playing sound and starts both Edge
commands with `--help`, using no external speech installation or online service.
A missing or broken bundled component fails verification and uses the existing
installation rollback behavior. This does not prove online voice availability
or audio-device playback; test those separately after installation.

## Components installed separately

The package includes the official Python 3.10.11 32-bit embeddable distribution
under `runtime/python-x86/`, verified against its pinned SHA-256 at build time.
Its isolated path file exposes only the bundled standard library and bridge
sources under `_internal/`. No system Python, pip, PATH, or registry changes
are needed. The bridge honors valid new and legacy explicit Python overrides,
then tries the bundled runtime before system installations. Package verification
runs its actual entry point with `--check` to verify architecture and imports
without opening a tracker. `runtime/` is replaced transactionally with each
release; existing user-owned `tools/` remains preserved.

- Tobii runtime and calibration: install the official software appropriate for
  the tracker, connect the device, and complete calibration. The package cannot
  safely install or calibrate hardware.
- Tobii Stream Engine: Tobii Eye Tracker 4C setups commonly obtain
  `tobii_stream_engine.dll` from Tobii Core or Game Hub. The app searches common
  install locations. Set `TOBII_STREAM_ENGINE_DLL` when the DLL is elsewhere.

The application launches without these external components. Missing Tobii
software disables gaze input while the provider retries.

## Finish setup

Normal interactive installation opens **Provjera instalacije**. It checks
bundled speech, the 32-bit bridge, installed Tobii components, and present
Windows Plug and Play devices named Tobii or EyeChip. Presence is an indication,
not a gaze-stream test; detection errors are shown as unverified rather than
reported as missing hardware. Calibration always requires confirmation in the
Tobii software.

The summary offers the official device-specific Tobii download page, calibration,
and a repeat check. It does not silently download or install drivers and opens
calibration only on request. The check runs in the background; closing while
it is active waits for its bounded probes to finish. Local speech checks make
no sound or online request. The setup person uses mouse or keyboard; this
standalone summary does not start gaze tracking.

Use `-NoSetupWindow` for unattended installation. `-NoDesktopShortcut` also
suppresses the summary for existing automation. Missing Tobii software or a
disconnected tracker does not undo an otherwise verified installation. Reopen
the summary at any time with `PogledAssist.exe --installation-check`.

## Build locally

Use Windows x64 and Python 3.10:

```powershell
.\dev.ps1 setup
.\dev.ps1 package
```

The build reads `VERSION`, uses the checked-in PyInstaller spec, includes the
release updater, checks required assets, executes the packaged
`--package-smoke-test`, installs an extracted copy in an isolated directory, and
creates:

```text
dist\PogledAssist-v<version>-windows-x64.zip
```

The build downloads the pinned eSpeak MSI, Python x86 ZIP, and source archives into
`.dev-tools/speech-cache`, verifies SHA-256 checksums, extracts eSpeak without
installing it globally, and freezes both Edge commands with a shared Python
runtime. The first build needs internet; cached assets are rechecked on every
build. A checksum mismatch fails the build before extraction.

No physical tracker, Tobii runtime, system speech installation, or network speech
service is used by the package smoke test. It verifies bundled speech tools,
the bundled Bosnian model checksum, and a word completion from that model.

## Automated release

After normal changes have reached `development`, use the manual **Release**
workflow on `master` with a new version number. It prepares
`release/v<version>` from the latest `master`, merges `development`, updates
`VERSION`, and opens a draft release PR. Complete its verification and review
before merging with a merge commit. The full branch and first-run procedure is
in [CONTRIBUTING.md](../CONTRIBUTING.md#release-process).

Pull requests targeting `development` or `master` run:

- `code-quality`
- `tests`
- `windows-package`

The active branch rulesets, checked on 23 September 2026, require
`code-quality`, `tests`, and `windows-package`. Verify live rulesets before a
release. The checks cover Ruff formatting, focused PSScriptAnalyzer rules,
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
- Run `install_windows.ps1` and confirm installation under `C:\PogledAssist`.
- Put a sentinel file under a test `C:\TobiiExec` installation and confirm the
  installer and updater reject that path without changing the sentinel.
- Install an older release, run `update_windows.ps1`, and confirm `VERSION`
  matches the latest stable release.
- Confirm a deliberately invalid checksum leaves the older version unchanged.
- Confirm an installed smoke-test failure restores the older version.
- Hold the installation folder open in File Explorer during an update. Confirm
  the updater reports which folder to close, leaves the older version and user
  files intact, and succeeds after the Explorer window is closed and retried.
- Confirm `data`, including `speech_learning.json`, `logs`, `install_info.json`,
  and existing root logs other than the appended `update_windows.log` are
  byte-for-byte unchanged after update and rollback tests.
- Confirm any local `.venv` speech tools and `tools` bridge components remain
  available after source-install migration and release updates.
- On a clean Windows machine without Python or external speech tools, install
  the ZIP and verify Standard speech offline and Natural speech online. Also
  repeat both voice tests when starting `PogledAssist.exe` directly.
- Confirm the bundled x86 bridge imports after installation into a path with
  spaces, without a system Python or configured Python environment variables.
- Confirm the setup summary distinguishes missing software, absent devices,
  detection failures, and unverified calibration. Check its download and
  calibration buttons and repeat check. Verify unattended installs show no UI.
- Start the app from the desktop shortcut and confirm the toolbar appears.
- Open Settings, Speech, Keyboard, and Controller.
- Disconnect networking before first Speech use and confirm `Brzi izbor` still
  offers starting words, completions, and next words.
- Confirm suggestion selection and `Poništi riječ` produce the same text with
  mouse and simulated gaze, including Bosnian letters and punctuation spacing.
- Open a phrase or answer editor, use a suggestion, cancel, and confirm the
  conversation and its undo state return unchanged. Repeat with a successful save.
- Speak the same unchanged message twice, restart the app, and confirm personal
  learning was counted once and persists in `data\speech_learning.json`.
- Forget one learned word in Settings, restart, and confirm its personal boost
  remains removed while the message and saved library remain unchanged.
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
its `install_windows.ps1`. Close Pogled Assist first. The installer validates
the older package before replacing application binaries, preserves
`C:\PogledAssist\data` and `C:\PogledAssist\logs`, and restores the previous binaries if
installation fails.

Current releases keep the full Speech library in `data\speech_library.json` and
maintain a list-only `data\speech_phrases.json` for older releases. Do not delete
or rename either file during rollback. They also preserve
`data\speech_learning.json`; older releases ignore it, and a later compatible
release resumes using it. An older release reads and updates the
list-only file. When a current release is installed again, it imports newer
standalone phrase changes while retaining categories and answers from the full
library. If saved settings from a newer version are incompatible, back up `data`,
remove only `data\app_settings.json`, and restart the older version. Never move or
recreate an existing release tag during rollback.
