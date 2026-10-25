# Development guide

Run development and release checks on Windows x64 with Python 3.10. Start with setup for a fresh checkout; use the command table and verification modes for an existing branch.

| Task | Guide |
| --- | --- |
| Write tests, find fakes or interpret a conditional skip | [Testing](TESTING.md) |
| Change UI, simulate gaze, render screenshots or check Windows/Tobii behavior | [UI development](UI_DEVELOPMENT.md) |
| Investigate a failed local check | [Troubleshooting](DEVELOPMENT_TROUBLESHOOTING.md) |
| Read diagnostic logs or understand recording/export ownership | [Diagnostics](DIAGNOSTICS.md) |
| Prepare and evaluate Bosnian models | [Language data](../language/bs/README.md#preparation-and-evaluation) |
| Publish the UI gallery | [Gallery publication](UI_GALLERY.md) |

## First setup

Run PowerShell from the repository root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\dev.ps1 setup
```

Setup creates a Python 3.10 `.venv`, installs application/test/package dependencies and downloads actionlint 1.7.12 and PSScriptAnalyzer 1.25.0 into ignored `.dev-tools`. It does not install Tobii software or change system Python. A stale or unsupported `.venv` moves to `.dev-tools\venv-backups` before replacement. To select an installed interpreter, pass `-BasePython C:\Path\To\python.exe`. The `tobii-research==2.1.0` Windows wheel requires this Python version.

Setup, PR CI and release checks share `scripts/checks/install_powershell_analyzer.ps1`. Downloads come from the official GitHub release and must match the pinned SHA-256 before extraction. Cache validation checks manifest version, root-module name and both files, but does not rehash every extracted file. An incomplete cache is replaced only after validation. Requests time out after 30 seconds and allow at most three attempts; download, checksum or module failures stop setup. The source check must import the analyzer successfully. See [tool recovery](DEVELOPMENT_TROUBLESHOOTING.md#powershell-analyzer-setup-fails).

## Command reference

Automated checks use fake inputs and require no Tobii tracker or external speech installation. `run` and `simulate` can produce real Windows input; [simulation controls and limits](UI_DEVELOPMENT.md#mouse-gaze-simulation) explain that boundary.

| Command | Tobii hardware | What it verifies |
| --- | --- | --- |
| `.\dev.ps1 run` | Optional to start, required for real gaze checks | The real source application, tracker discovery, and Windows input |
| `.\dev.ps1 simulate` | Not required | Mouse-driven gaze feedback, dwell timing, UI selection, and click flows |
| `.\dev.ps1 ui` | Not required | Core UI gallery at 1280 × 720 without external services; [profiles and surface counts](UI_DEVELOPMENT.md#rendered-ui-gallery) |
| `.\dev.ps1 ui -UiProfile full -UiGroup voice -Open` | Not required | Extended voice/account screenshots; [profiles and groups](UI_DEVELOPMENT.md#rendered-ui-gallery) |
| `.\dev.ps1 test` | Not required | All unit, integration, and UI workflow tests in two worker processes, without coverage |
| `.\dev.ps1 test -TestPaths tests/gaze -Workers 1` | Not required | An explicit focused selection in one process |
| `.\dev.ps1 test-ui` | Not required | UI workflow and rendering tests selected by the `e2e` marker |
| `.\dev.ps1 coverage` | Not required | Test suite, 60 percent floor, and `dist\coverage-html` report |
| `.\dev.ps1 lint` | Not required | Actions, Ruff, Python compilation, and PowerShell checks |
| `.\dev.ps1 format` | Not required | Ruff safe fixes, import ordering, and source formatting |
| `.\dev.ps1 check-fast` | Not required | Complete Python lint/format/compilation and relevant changed tests; no coverage or package |
| `.\dev.ps1 check-fast -BaseRef origin/development` | Not required | Fast checks using an explicit Git comparison ref |
| `.\dev.ps1 check-fast -Workers 2` | Not required | Fast checks with two workers even for a small selection |
| `.\dev.ps1 check` | Not required | The same complete checks as `check -Parallel`, with stages run sequentially |
| `.\dev.ps1 check -Parallel` | Not required | Lint, then overlapping application tests, release/tooling tests and packaging, followed by installer tests and combined coverage |
| `.\dev.ps1 coverage -Workers 2` | Not required | Explicit parallel coverage measurement; slower Qt runs are possible |
| `.\dev.ps1 package` | Not required | Clean PyInstaller build and frozen executable smoke test |

Supporting scripts live in `scripts/checks/`, `scripts/release/`, `scripts/ui/` and `scripts/speech_suggestions/`. Standard lint, test and package verification uses `dev.ps1`. Documented model and diagnostic commands may invoke the same `.venv` directly. Do not substitute system Python, another environment or ad hoc tool installation.

## Verification before a pull request

### Verification modes

| Mode | Work performed | Use |
| --- | --- | --- |
| `check-fast` | Python quality checks, affected PowerShell/Actions checks and changed-path test selection | Iteration; no coverage or packaging, even when all tests are selected |
| `check` | Lint, complete suite with coverage, then package/installer checks | Complete sequential verification |
| `check -Parallel` | Lint, overlapping test groups and packaging, then installer tests and combined coverage | Same complete verification with overlapping stages |
| PR CI | `code-quality`, `tests`, `windows-package`, plus PR-only `dependency-review` | Required checks are identified in [CONTRIBUTING](../CONTRIBUTING.md#ci-and-required-checks) |
| Release verification | Quality checks, full suite and packaging before publication | Software/package evidence; no physical Tobii or audible playback check |

`-Parallel` overlaps local stages; `-Workers` controls pytest processes within a test invocation. They are independent. A [conditional test](TESTING.md#conditional-tests) can still skip in a complete run; report its reason.

### Final verification and fast selection

Use `.\dev.ps1 check-fast` while iterating. Before marking a PR ready, run `.\dev.ps1 check -Parallel` against the final diff, then applicable [manual checks](UI_DEVELOPMENT.md#manual-windows-checks). Use sequential `.\dev.ps1 check` when diagnosing a parallel failure or when contention makes overlapping stages slower; record the reason and timings. Both modes must pass lint, all tests, coverage and packaging. Run only one check/package command per checkout and keep source files unchanged until it finishes.

The Windows session needs checkout/temp-file access, local HTTP test servers, child processes, process inspection and Windows Installer for package extraction. [Restricted sessions](DEVELOPMENT_TROUBLESHOOTING.md#restricted-windows-verification-sessions) can deny these operations even when tests collect successfully. Investigate the first underlying error before attributing a failure to the application or environment.

Documentation-only work has the same final verification requirement and also needs review of its links and commands. For runtime work, record each applicable manual Windows/Tobii check as passed, failed or Not run with a reason. Software checks cannot establish hardware results.

A handoff or draft PR may precede complete verification. If execution is deferred or unavailable, finish authorized implementation, inspect the diff and report **Implemented; verification not run**, naming outstanding checks and limitations. Required CI and [human review](../CONTRIBUTING.md#review-and-merge-responsibility) remain prerequisites for merge.

Fast selection compares the merge base of `origin/development` with committed, staged, unstaged and untracked changes, including both sides of renames and deletions. Fetch before starting a topic branch; the command does not fetch. Use `-BaseRef <ref>` for a deliberate alternate base. Missing history/ref selects the full suite.

`scripts/checks/select_tests.py` maps runtime changes to boundary tests and consumers. Documentation selects link/repository tests. Unknown paths, shared test helpers, deleted tests, dependencies, workflows/check configuration, model data and bundled assets select every test. Maintain the mapping for new consumers and prefer the full-suite fallback when impact is uncertain. The command prints paths, reasons and selected files; with no changes it still checks Python and explicitly reports no selected tests.

### Workers, coverage and logs

Without coverage, tests default to two xdist processes with `--dist=loadfile`, keeping a module on one worker. A fast selection of fewer than four files uses one process with the default `-Workers 0`. `-Workers 1` disables xdist; `-Workers 2` explicitly enables it, including small selections.

Coverage, sequential `check`, each parallel check group, PR CI and release verification default to one test process. Parallel coverage previously slowed Qt sidebar interactions; measure repeated runs on the same commit before increasing workers. CI prints verbose names, the 30 slowest tests and thread stacks when setup/call/teardown exceeds 120 seconds. The dump is diagnostic, not a timeout extension or cancellation.

`coverage` and `check` temporarily clear and then restore `PYTEST_ADDOPTS`, including on failure, so external options cannot omit tests or override coverage. Use `test` or `test-ui` with `-TestPaths` for focused/custom diagnosis. `coverage`, `check` and `check-fast` reject `-TestPaths`.

After lint, `check -Parallel` overlaps:

- Application tests: everything except `tests/release/` and `tests/tooling/`; new test folders join automatically.
- Release/tooling tests, excluding `tests/release/test_windows_installer.py`.
- Windows packaging and installer smoke checks.

Installer integration tests run after these stages because they share process detection and installer locks with package smoke checks. Failures do not cancel the other stages or deferred tests. Three isolated coverage files are combined once, with the same 60 percent floor; missing group data fails the report. Reports use that combined file, excluding stale checkout shards, and copy it to `.coverage` or the incoming `COVERAGE_FILE` destination.

Each parallel run keeps stdout/stderr and coverage under a unique `dist/check-<id>/`. Status lines every five seconds show active stages; all verification commands report stage/total durations, including failures. Elapsed time alone does not prove progress. See [parallel diagnosis](DEVELOPMENT_TROUBLESHOOTING.md#debugging-parallel-test-failures) for reading active logs and isolating contention.

## Test strategy

[Writing and selecting tests](TESTING.md) owns the boundary map, shared fixtures, Qt lifecycle, clocks and process probes.

### Conditional tests

[Conditional tests](TESTING.md#conditional-tests) lists the native audio probe and opt-in gaze benchmark, their commands and evidence limits.

## Mouse gaze simulation

See [mouse gaze simulation](UI_DEVELOPMENT.md#mouse-gaze-simulation) for synthetic input and real-click limits.

## UI review

See [UI development](UI_DEVELOPMENT.md#ui-review) for galleries and manual checks.

### Application design reference workflow

Use the [design surface map](UI_DEVELOPMENT.md#application-design-reference-workflow) before changing visible UI.

## UI gallery publication

[Gallery publication](UI_GALLERY.md) owns Pages setup, permissions and recovery.

## Diagnostic log analysis

[Diagnostic analysis](DIAGNOSTICS.md#diagnostic-log-analysis) owns the offline reader command, loss accounting and interpretation of a reported selection failure.

## Lint and formatting

Ruff checks Python correctness, imports and formatting. actionlint checks Actions syntax and expressions. PSScriptAnalyzer uses the focused repository settings rather than broad naming/style rules.

`scripts/checks/check_powershell.ps1` rejects ordinary executable launches using `Start-Process`, `start` or `saps`. Windows PowerShell 5.1 shell launching can display **Open File – Security Warning** before a caller receives the process or starts its timeout. Use `ProcessStartInfo` with `UseShellExecute = $false`; background console probes also use `CreateNoWindow = $true`. Keep normal windows for the app and installation summary. Drain stdout/stderr concurrently and bound output completion as well as process completion.

The AST guard permits explicit `-Verb RunAs` for UAC and the exact `dev.ps1` gallery-open command. Splatting does not exempt executable launches. It does not analyze dynamically constructed code or Python shell calls. Windows OSK and Tobii protocol/document launches retain their existing shell semantics; these exceptions do not authorize shell launching of downloaded executables.

Installer tests cover Internet-marked unsigned executables, failure cleanup and launch timeouts. Source bootstrap installers use a private Windows job: start suspended, assign the job, resume and wait for descendants. A 15-minute deadline closes the tree; the root exit code, including `3010`, is preserved. The standalone source setup keeps this helper inline for historical installations. See [launch trust limits](WINDOWS_RELEASE.md#windows-launch-warnings-and-signing).

Mypy is not enforced. Any adoption needs a separate plan for PySide signals, dynamic Qt objects and ctypes boundaries.

## Packaging

```powershell
.\dev.ps1 package
```

This uses the checked-in PyInstaller spec, verifies assets, runs the frozen `--package-smoke-test`, installs an extracted copy in isolation and writes the versioned ZIP under `dist`. [Windows releases](WINDOWS_RELEASE.md#build-locally) owns package contents and validation. A package pass does not prove tracker behavior, audible playback or online voice availability.
