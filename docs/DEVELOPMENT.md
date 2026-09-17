# Development guide

This project runs on Windows and Python 3.10.

## First setup

Run PowerShell from the repository root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\dev.ps1 setup
```

Setup creates `.venv`, installs the application, test and packaging dependencies,
and downloads actionlint 1.7.12 and PSScriptAnalyzer 1.25.0 into the ignored
`.dev-tools` directory. It does not install Tobii software or change the
system-wide Python environment.

## Command reference

Run these commands in Windows PowerShell. The automated checks do not require a
Tobii tracker, calibrated display, eSpeak NG, or the online speech service.
Only the real gaze and external speech checks listed below require those
components.

| Command | Tobii hardware | What it verifies |
| --- | --- | --- |
| `.\dev.ps1 run` | Optional to start, required for real gaze checks | The real source application, tracker discovery, and Windows input |
| `.\dev.ps1 simulate` | Not required | Mouse-driven gaze feedback, dwell timing, UI selection, and click flows |
| `.\dev.ps1 ui` | Not required | Rendering of 12 main UI surfaces without external services |
| `.\dev.ps1 test` | Not required | Unit, integration, and UI workflow tests with simulated inputs |
| `.\dev.ps1 test-ui` | Not required | UI workflow and rendering tests selected by the `e2e` marker |
| `.\dev.ps1 coverage` | Not required | Test suite, 60 percent floor, and `dist\coverage-html` report |
| `.\dev.ps1 lint` | Not required | Actions, Ruff, Python compilation, and PowerShell checks |
| `.\dev.ps1 format` | Not required | Ruff safe fixes, import ordering, and source formatting |
| `.\dev.ps1 check` | Not required | Lint, tests, coverage, package build, and frozen executable smoke test |
| `.\dev.ps1 package` | Not required | Clean PyInstaller build and frozen executable smoke test |

Use `.\dev.ps1 check` before pushing a pull request. It runs the same three
categories enforced by the required PR checks.

Documentation-only work still runs `check` to confirm the runtime baseline. Its
links and commands also need a manual documentation review. If a required device
check cannot run, record it as not run. Never infer a hardware result from a
mocked test or a package smoke test.

## Test strategy

The suite uses five layers:

1. Unit tests cover coordinate mapping, dwell state, settings validation, speech
   commands, phrase storage, and Windows helper behavior.
2. Integration tests cover provider fallback, app startup, logging, packaging
   paths, release publication recovery, and the optional x86 bridge discovery
   logic.
3. UI tests use `pytest-qt` with mocked speech and Windows input. They exercise
   Settings, Speech, Keyboard, Controller, Hotbar, zoom, and radial-menu flows.
4. Repository tests check required guides and templates, local documentation
   links, and the minimum sections agents need for issues and pull requests.
5. Manual Tobii checks verify the device runtime, calibration, gaze quality,
   AppBar behavior, clicks, and speech on the target machine.

Coverage is a regression floor, not a quality score. The initial floor is 60
percent because hardware DLL calls and Windows shell behavior cannot run safely
in a normal test process. New pure-Python behavior should include tests, and the
floor should only move upward as meaningful cases are added.

High-value future test work:

- Fake the Stream Engine C API to cover device creation, subscriptions, reconnect,
  and shutdown without loading a Tobii DLL.
- Add failure-path tests around the x86 subprocess protocol and timeouts.
- Add dedicated tests for AppBar registration and cleanup behind a fake `user32`
  boundary.

Pixel baselines are intentionally not enforced in CI. Qt rendering changes with
Windows fonts, scaling, and GPU backends, which would make strict image diffs
noisy. CI confirms that every surface renders. A human reviews the generated
gallery for clipping, overlap, spacing, contrast, and consistency.

## Mouse gaze simulation

Run the interactive simulator when Tobii hardware is unavailable:

```powershell
.\dev.ps1 simulate
```

The primary-screen mouse position is emitted through the same normalized gaze
signal used by the Tobii providers. Both eyes remain valid, so holding the cursor
over a gaze-selectable control shows the gaze bubble and dwell progress before
activating it. Pointer movement is disabled in this mode because the mouse is the
gaze source. If a click mode is armed, completed dwell actions still perform the
real Windows click.

This mode does not validate Tobii discovery, calibration, eye-loss behavior,
sample quality, latency, or hardware accuracy. Report those checks as not run.

## UI review

### Speech design reference workflow

[`design/speech-keyboard-reference.html`](design/speech-keyboard-reference.html)
is the design source of truth for the Speech window. When a change affects its
layout, visible copy, control sizes, or interaction flow, update and review the
HTML reference first, then implement the matching PySide6 change. Keep both
changes in the same pull request so the reference never describes an older UI.
If a Speech change has no visible or interaction impact, state that explicitly
in the pull request instead of editing the reference unnecessarily.

Review the HTML reference at the target display size before generating the Qt
gallery. The reference documents the intended result; the gallery and real
application checks confirm that the implementation matches it.

Generate the gallery:

```powershell
.\dev.ps1 ui -Open
```

The command renders:

- Hotbar
- General, gaze, and speech Settings tabs
- Speech keyboard, categories, answers, saved phrases, and shared editor
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

actionlint checks GitHub Actions YAML syntax and workflow expressions before a
push.

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
runs `--package-smoke-test` from the frozen executable, installs an extracted copy
in an isolated directory, and writes the versioned ZIP under `dist`.

The build does not prove that a physical Tobii device or external speech engine
works. Follow the manual checks in [WINDOWS_RELEASE.md](WINDOWS_RELEASE.md) before
approving a release.
