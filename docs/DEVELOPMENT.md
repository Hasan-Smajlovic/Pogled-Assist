# Development guide

This project runs on Windows and Python 3.10. Automated development checks do not
need a Tobii tracker, eSpeak NG, or the online speech service.

## First setup

Run PowerShell from the repository root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\dev.ps1 setup
```

Setup creates `.venv`, installs the application, test and packaging dependencies,
and downloads PSScriptAnalyzer 1.25.0 into the ignored `.dev-tools` directory.
It does not install Tobii software or change the system-wide Python environment.

## Command reference

| Command | What it verifies |
| --- | --- |
| `.\dev.ps1 run` | The real source application, tracker discovery, and Windows input |
| `.\dev.ps1 ui` | Rendering of 12 main UI surfaces without external services |
| `.\dev.ps1 test` | Unit, integration, and UI workflow tests |
| `.\dev.ps1 test-ui` | UI workflow and rendering tests selected by the `e2e` marker |
| `.\dev.ps1 coverage` | Test suite, 60 percent floor, and `dist\coverage-html` report |
| `.\dev.ps1 lint` | Ruff lint/format, Python compilation, PowerShell parse/analyzer checks |
| `.\dev.ps1 format` | Ruff safe fixes, import ordering, and source formatting |
| `.\dev.ps1 check` | Lint plus tests and coverage, matching the required PR checks |
| `.\dev.ps1 package` | Clean PyInstaller build and frozen executable smoke test |

Use `.\dev.ps1 check` before pushing a pull request.

## Test strategy

The suite uses four layers:

1. Unit tests cover coordinate mapping, dwell state, settings validation, speech
   commands, phrase storage, and Windows helper behavior.
2. Integration tests cover provider fallback, app startup, logging, packaging
   paths, and the optional x86 bridge discovery logic.
3. UI tests use `pytest-qt` with mocked speech and Windows input. They exercise
   Settings, Speech, Keyboard, Controller, Hotbar, zoom, and radial-menu flows.
4. Manual Tobii checks verify the device runtime, calibration, gaze quality,
   AppBar behavior, clicks, and speech on the target machine.

Coverage is a regression floor, not a quality score. The initial floor is 60
percent because hardware DLL calls and Windows shell behavior cannot run safely
in a normal test process. New pure-Python behavior should include tests, and the
floor should only move upward as meaningful cases are added.

High-value future test work:

- Fake the Stream Engine C API to cover device creation, subscriptions, reconnect,
  and shutdown without loading a Tobii DLL.
- Add failure-path tests around the x86 subprocess protocol and timeouts.
- Test release publishing against a fake `gh` executable so draft recovery and
  immutable-tag behavior can be exercised without changing GitHub.
- Add dedicated tests for AppBar registration and cleanup behind a fake `user32`
  boundary.

Pixel baselines are intentionally not enforced in CI. Qt rendering changes with
Windows fonts, scaling, and GPU backends, which would make strict image diffs
noisy. CI confirms that every surface renders. A human reviews the generated
gallery for clipping, overlap, spacing, contrast, and consistency.

## UI review

Generate the gallery:

```powershell
.\dev.ps1 ui -Open
```

The command renders:

- Hotbar
- General, gaze, and speech Settings tabs
- Speech keyboard and saved phrases
- Keyboard letters, numpad, and symbols tabs
- Controller general, keyboard, and settings tabs

Check the gallery at 100 percent and at the scale used by the target machine.
Look for clipped labels, overlapping controls, inconsistent spacing, low contrast,
missing icons, unexpected scrollbars, and controls that are too small for gaze.

Then run the real application:

```powershell
.\dev.ps1 run
```

On a normal development machine, verify:

- The hotbar spans the primary screen and does not cover maximized windows.
- Hide and Show restore the Windows work area.
- Settings, Speech, Keyboard, and Controller open at the expected size.
- Opening Keyboard closes Controller and opening Controller closes Keyboard.
- Settings survive an application restart.
- Logs appear under `logs` only when logging is enabled.
- Closing the app removes AppBar reservations and child windows.

On the Tobii machine, additionally verify:

- The connection indicator changes from waiting to tracking.
- Both eye indicators reflect real validity.
- Losing one eye cancels dwell progress and stops pointer movement.
- Pointer mapping reaches all corners of the calibrated display.
- Left, right, double-click, precision zoom, and Quick actions work.
- Default and human-like speech are tested separately.

Record software-only and hardware results separately in the pull request.

## Lint and formatting

Ruff is the Python equivalent of the ESLint, Prettier, and import-sorting parts of
a JavaScript toolchain. The repository enables syntax and import checks,
Pyflakes, pyupgrade, bugbear, simplify, and Ruff-specific correctness rules.

PSScriptAnalyzer uses a focused settings file. It checks unsafe or ambiguous
PowerShell patterns without enforcing naming preferences that would cause large,
low-value rewrites of the existing setup scripts.

Mypy is not enforced yet. Much of the UI depends on PySide signals, dynamic Qt
objects, and Windows ctypes boundaries, so introducing strict type checking should
start as a separate change with a defined module-by-module adoption plan.

## Packaging

Build the same Windows ZIP checked by CI:

```powershell
.\dev.ps1 package
```

The command uses the checked-in PyInstaller spec, verifies required assets,
runs `--package-smoke-test` from the frozen executable, and writes the versioned
ZIP under `dist`.

The build does not prove that a physical Tobii device or external speech engine
works. Follow the manual checks in [WINDOWS_RELEASE.md](WINDOWS_RELEASE.md) before
approving a release.
