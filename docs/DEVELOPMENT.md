# Development guide

Development and release checks run on Windows x64 with Python 3.10.

This guide owns setup, commands, automated verification, and test strategy. Read the sections relevant to the task; use these guides for conditional detail:

| Work | Guide |
| --- | --- |
| Visible UI, mouse simulation, screenshots, or manual Windows/Tobii checks | [UI development and review](UI_DEVELOPMENT.md) |
| Gallery publication, Pages setup, permissions, or recovery | [UI gallery publication](UI_GALLERY.md) |
| Bosnian model preparation, evaluation, or benchmarks | [Bosnian language guide](../language/bs/README.md#preparation-and-evaluation) |
| A failing local check | [Development troubleshooting](DEVELOPMENT_TROUBLESHOOTING.md) |

For a fresh checkout, start with [setup](#first-setup). For an existing branch, use [verification modes](#verification-modes) to choose a command, the [test boundary map](#test-strategy) to find reusable inputs, and [diagnostic analysis](#diagnostic-log-analysis) to interpret a captured problem. Implemented behavior and ownership live in [architecture](ARCHITECTURE.md), rather than in test-run summaries.

## First setup

Run PowerShell from the repository root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\dev.ps1 setup
```

Setup creates `.venv`, installs the application, test and packaging dependencies, and downloads actionlint 1.7.12 and PSScriptAnalyzer 1.25.0 into the ignored `.dev-tools` directory. It does not install Tobii software or change the system-wide Python environment. The `.venv` always uses Python 3.10. If `.venv` points to a removed or unsupported interpreter, setup moves it to `.dev-tools\venv-backups` before creating a fresh one. To use a specific installed interpreter, pass `-BasePython C:\Path\To\python.exe` to setup. Interpreter probes start executables directly without the Windows shell, so a broken interpreter returns an error without an interactive security warning.

Setup, PR CI and release verification share `scripts/checks/install_powershell_analyzer.ps1`. It downloads the pinned package from the official `PowerShell/PSScriptAnalyzer` GitHub release and checks its fixed SHA-256 before extraction. Before publishing a download or reusing the cache under `.dev-tools`, it checks the manifest version, expected root-module name and presence of both files. The explicit root-file check is required because Windows PowerShell 5.1 can accept a manifest whose root module is missing. An incomplete cache is replaced only after the new package passes validation. Downloads have a 30-second request timeout and at most three attempts; download, checksum or module failures stop setup rather than skipping the analyzer. This works in Windows PowerShell 5.1 without PSGallery registration or a package-manager bootstrap.

Cache validation checks that module structure; it does not rehash every extracted file. The PowerShell source check then imports the analyzer and requires its command to be available. See [tool setup recovery](DEVELOPMENT_TROUBLESHOOTING.md#powershell-analyzer-setup-fails) for a failed download or cache.

`tobii-research==2.1.0` has a Windows wheel for Python 3.10, so the same interpreter is used for development, Tobii Pro discovery, automated checks, and Windows packaging.

## Command reference

Run these commands in Windows PowerShell. The automated checks do not require a Tobii tracker, calibrated display, eSpeak NG, or the online speech service. Only the [manual gaze and external speech checks](UI_DEVELOPMENT.md#manual-tobii-checks) require those components.

| Command | Tobii hardware | What it verifies |
| --- | --- | --- |
| `.\dev.ps1 run` | Optional to start, required for real gaze checks | The real source application, tracker discovery, and Windows input |
| `.\dev.ps1 simulate` | Not required | Mouse-driven gaze feedback, dwell timing, UI selection, and click flows |
| `.\dev.ps1 ui` | Not required | Rendering of 69 representative UI screenshots at 1280 × 720 without external services |
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

`coverage` and `check` temporarily clear `PYTEST_ADDOPTS` so environment options cannot omit tests or override the coverage floor. This also ignores diagnostic options supplied through that variable. The commands restore its original value after testing, including on failure. Use `test` or `test-ui` for custom pytest options while investigating a failure.

`check -Parallel` collects coverage independently for each test group without generating partial reports or enforcing a partial-suite floor. After the overlapping stages finish, installer tests collect the remaining coverage. The final report combines all three data files, enforces the same 60 percent floor and writes the terminal and HTML reports once. Missing group data fails the report rather than silently using incomplete coverage. Test failures still allow the remaining stages and report to run, but fail the complete check. A failed coverage collection can prevent the report; partial data remains under that run's log directory for diagnosis.

The supporting scripts are grouped by purpose: `scripts/checks/` validates source and workflows, `scripts/release/` builds and publishes releases, `scripts/ui/` renders and prepares UI galleries, and `scripts/speech_suggestions/` prepares and evaluates Bosnian prediction models.

Model preparation, provenance, benchmarks, and evaluation commands are maintained in the [Bosnian language guide](../language/bs/README.md#preparation-and-evaluation). Run those commands from the repository root with the same Python 3.10 `.venv` created by `dev.ps1 setup`. Documented model and diagnostic commands may invoke that interpreter directly; standard lint, test, and package verification uses `dev.ps1`. Do not substitute system Python, a temporary environment, or ad hoc tool installation.

## Verification before a pull request

### Verification modes

| Mode | Execution | Evidence and limits |
| --- | --- | --- |
| `check-fast` | Python quality checks and affected PowerShell/Actions checks, then changed-path test selection | Iteration feedback; no coverage or package. A large branch or unknown/shared path can select the full suite. |
| `check` | Lint, the full suite with coverage, then packaging, sequentially | Complete local verification; useful for diagnosing contention. Coverage defaults to one test process. |
| `check -Parallel` | Lint, overlapping test groups and packaging, then deferred installer tests and combined coverage | The same complete local verification. Each test group defaults to one process. |
| PR CI | Independent `code-quality`, `tests` and `windows-package` jobs, plus PR-only dependency review | The `tests` job uses two xdist workers grouped by file. CI does not invoke local `check -Parallel`. |
| Release verification | Quality checks, the suite and packaging before publication | Tests run sequentially in the release job; no physical Tobii or audible playback validation. |

`-Parallel` overlaps local check stages; `-Workers` controls pytest processes within a test invocation. They are independent. Passing either complete local mode does not prove hardware behavior or substitute for the required PR checks and review. Some tests are [conditional](#conditional-tests), including in complete runs.

### Final verification and fast selection

Run full verification in a Windows session with access to the checkout and temporary files, local HTTP test servers, child processes, process inspection, and Windows Installer for package asset extraction. Restricted agent sessions can block these operations even when Python starts and tests collect successfully. See [restricted verification sessions](DEVELOPMENT_TROUBLESHOOTING.md#restricted-windows-verification-sessions) before diagnosing unrelated failures as application regressions.

During development, run `.\dev.ps1 check-fast` after each meaningful change and repeat it after fixes. Prefer `.\dev.ps1 check -Parallel` against the final diff before marking a pull request ready for review; rerun it after subsequent changes. It uses Python 3.10 and covers the same three categories enforced by the required `code-quality`, `tests`, and `windows-package` pull request checks.

An implementation handoff or draft pull request can precede complete verification. Record unfinished work and skipped checks as Not run with a reason; neither handoff nor draft status establishes readiness for review. When the user defers execution, finish the implementation and documentation, inspect the diff, and report "Implemented; verification not run" with the outstanding checks. Required CI checks and human review remain prerequisites for merge, as defined in [CONTRIBUTING.md](../CONTRIBUTING.md#review-and-merge-responsibility).

The fast command compares committed topic-branch changes against the merge base of `origin/development`, then adds staged, unstaged and untracked files. It includes both paths of a rename and deleted paths. Fetch `origin/development` before starting a topic branch; the fast command does not fetch automatically. Use `-BaseRef <ref>` when deliberately comparing another base. Missing Git history or an unavailable ref selects the full suite instead of skipping tests.

Selection rules live in `scripts/checks/select_tests.py`. Changes to gaze, speech, suggestions, UI, Windows or release code select the boundary's tests and its application/UI consumers. Changed and new test modules are included. Documentation selects repository documentation/link tests. Unknown paths, shared test helpers, deleted tests, dependencies, workflow/check configuration, model data and bundled assets select every test. Maintain the mapping when adding consumers; use the full-suite fallback whenever the impact is uncertain. This is a development feedback aid; the final check and CI always run all tests.

`check-fast` prints changed paths, selection reasons and selected test files. It runs Ruff lint, formatting and Python compilation across the repository, but checks only changed PowerShell scripts and affected Actions workflows. A full-suite fallback also checks all PowerShell and Actions files. It omits coverage and packaging even when all tests are selected. With no changes, it still checks Python source and explicitly reports that no tests were selected. All verification commands report stage and total durations, including failures.

Tests without coverage default to two pytest-xdist processes with `--dist=loadfile`, keeping each test file on one worker. Each worker has its own QApplication and temporary directories. With the default `-Workers 0`, fast selections of fewer than four test files use one process to avoid startup overhead. `-Workers 1` disables parallel execution for debugging; `-Workers 2` uses two processes even for a small selection.

The full `coverage` and sequential `check` commands default to one test process because parallel coverage slowed repeated Qt sidebar interactions on Windows/Python 3.10. Each test group in `check -Parallel` also defaults to one process, keeping application/Qt tests together while release/tooling tests run separately. `-Workers 2` explicitly enables xdist within each test invocation; it can increase contention and should be measured before use. Coverage commands list the 30 slowest tests. PR CI still runs every test with coverage in two worker processes, grouped by file, and lists the 30 slowest tests so suite changes can be compared run to run. Its existing quality, test and packaging jobs continue to run independently.

PR CI and release verification run Ruff and Python compilation before downloading PowerShell tools. Their tool caches cover only the analyzer and actionlint directories, with a key tied to the operating system, architecture and installer scripts containing their pinned versions. The `code-quality` job installs only Ruff from PyPI and does not restore the application dependency cache. Test and packaging jobs retain their pip caches; the already compressed Windows package is uploaded without additional artifact compression. Compare one and two test workers on the same commit over repeated Windows runs before changing CI's worker count.

`check -Parallel` keeps lint first, then overlaps three stages:

- Application tests: the suite except `tests/release/` and `tests/tooling/`. New test folders join this group automatically.
- Release/tooling tests: those two folders except `tests/release/test_windows_installer.py`.
- Windows packaging and installer smoke tests.

Installer integration tests run after all three stages finish. They and the package smoke checks inspect running application processes and use the installer lock, so they must not overlap. All tests, packaging and combined coverage still have to pass; a failure waits for the other running stages and the deferred installer tests. Each overlapping stage writes separate stdout and stderr logs under a unique `dist/check-<id>/` directory and prints their paths, stage durations and total elapsed time. The test logs include verbose test names and durations and can be read during execution; see [parallel test diagnosis](DEVELOPMENT_TROUBLESHOOTING.md#debugging-parallel-test-failures). Separate coverage files and `combined.coverage` remain in that directory. Both report commands use that isolated combined file, preventing coverage.py from automatically including stale checkout shards. The combined data is also copied to `.coverage` (or the incoming `COVERAGE_FILE` destination), replacing earlier combined data.

While parallel stages run, a status line every five seconds lists the active stages, their elapsed times and the number of finished stages. These lines also appear in captured agent output; elapsed time indicates a running process, not a guarantee of progress. The stages share CPU, memory and disk, so parallel execution is not guaranteed to be faster on every machine. Prefer this mode first and compare stage and total timings; use plain sequential `check` if resource contention slows the run or to diagnose a failure, and record the reason. Keep the default worker count unless measurements justify an override. Run only one check or package command per checkout at a time, and keep source files unchanged during verification.

For manual focused work, `test` and `test-ui` accept `-TestPaths` (one or more pytest paths); add `-Workers 1` for a small selection. `coverage`, `check` and `check-fast` reject `-TestPaths` so a partial selection cannot be mistaken for their documented checks.

Documentation-only work follows the same verification requirements before review. Its links and commands also need a manual documentation review. For runtime changes, follow the applicable [manual Windows and Tobii checks](UI_DEVELOPMENT.md#manual-windows-checks). Record every applicable hardware check as passed, failed, or Not run with a reason. Never infer a hardware result from a mocked test or a package smoke test.

If a local check fails, use the [local checks troubleshooting guide](DEVELOPMENT_TROUBLESHOOTING.md) to identify common Windows and pytest causes.

## Test strategy

The suite uses five layers:

1. Unit tests cover coordinate mapping, dwell state, settings validation, speech commands, phrase storage, and Windows helper behavior.
2. Integration tests cover provider fallback, app startup, logging, packaging paths, release publication recovery, release download and checksum failures, transactional installation and rollback, and the optional x86 bridge discovery logic.
3. UI tests use `pytest-qt` with mocked speech and Windows input. They exercise Settings, Speech, Keyboard, Controller, Hotbar, zoom, and radial-menu flows.
4. Repository tests check required guides and templates, local documentation links, skill metadata, and the minimum sections agents need for issues and pull requests.
5. Manual Tobii checks verify the device runtime, calibration, gaze quality, AppBar behavior, clicks, and speech on the target machine.

Provider regressions also exercise worker-thread eye notifications arriving before Qt has dispatched them, shutdown/reconnect with pending callbacks, and stale gaze queued during a GUI stall. These cases use the real provider and controller with fake device inputs; sequential callback tests alone cannot verify their dispatch ordering. Speech UI tests cover gaze, button and Return activation and check that source diagnostics omit the message text.

Automated tests live under `tests/app/`, `tests/gaze/`, `tests/speech/`, `tests/suggestions/`, `tests/ui/`, `tests/release/`, and `tests/tooling/`. Shared pytest setup stays in `tests/conftest.py`, and fixed speech evaluation data stays in `tests/fixtures/speech_suggestions/`. Run the whole suite from the repository root; pytest discovers all of these folders through `tests/`.

Qt cleanup closes top-level widgets and delivers their deferred deletion before the next test. Layout tests dispatch posted layout requests rather than sleeping; asynchronous operations still wait for their actual state or signal. Most diagnostic-recording UI tests use a shorter status polling interval, with a separate integration case retaining the production timer and real background writes. Release rejection decisions share one PowerShell driver; native command shims remain in the successful publication, draft repair and public-release no-op tests to exercise Windows argument quoting, stderr and exit handling.

UI layout matrices keep both scripts and the full group-size range at 1280 × 720, with representative larger-screen cases. Controller row tests keep both scripts at each sidebar size; the separate sidebar inventory test covers every group size and page. Mouse and gaze actions run across those layout cases without repeating both routes for every combination. Edge-duration UI tests exercise off, expiry and resume on Speech, then resume through Hotbar and Keyboard targets. Exact timing boundaries remain in `tests/gaze/test_gaze_selection.py`. Gaze-check advice branches stay in the direct `result_advice` table, with successful and problematic trials also checked through the window.

Settings-limit tests start one adjustment from each tested limit, reach it and attempt to cross it, rather than repeating already clamped updates. The large gaze-check report case retains 150 trials, a payload over 128 KiB, a real save/load and ZIP export; a rejected save is checked against the original file bytes without reparsing the report again.

Logging concurrency tests keep the sink blocked until the test explicitly releases it. Producer completion must precede that release; the wait timeout guards against a hang rather than imposing a throughput target on a CI runner. The shared Efendija service fixture and account fixture cancel account checks and join their speech, account and network workers before their Qt owners leave scope. Unhandled worker-thread exceptions fail the suite instead of remaining warnings.

`tests/tooling/test_repository_docs.py` checks every `.agents/skills/*/SKILL.md`. Each skill must start with a closed YAML metadata block containing non-empty text fields `name` and `description`; `name` must match the skill directory. Mapping keys must be unique. Quoted values, multiline descriptions, and additional metadata are supported. Each skill also needs a pointer at `.claude/skills/<name>/SKILL.md` with identical metadata that links to its source, so Claude Code discovers the same skills as Codex. PyYAML is a development dependency.

Tests that control `time.monotonic` across modules use `freeze_monotonic` from `tests/_clock.py`. It sets one process-wide value because gaze timestamps cross the provider, controller and window modules, and its clock cannot run out when an unrelated widget's Qt timer reads it during teardown. A test that needs only one module's clock replaces that module's `time` attribute with `SimpleNamespace(monotonic=...)`. `tests/tooling/test_clock_patches.py` rejects any other `time.monotonic` replacement.

Independent PowerShell probes share module-scoped drivers through `tests/_powershell.py`. Each case keeps a named parametrized pytest result, its own working directory and child scope, and explicit environment overrides. The driver captures all output streams and restores the environment and location even after a case throws. Batch only bodies that return or throw; `exit` would terminate the driver. Full installer/updater transactions, concurrent updaters and `dev.ps1` initialization/environment-recovery tests retain separate processes. Process probes keep their own deadlines and PID cleanup assertions; the shared harness also has a 120-second deadline and kills its process tree on timeout. Assertions about production environment recovery run before the harness restores state.

Worker selection, coverage arguments and failed-stage environment restoration share one PowerShell process, reloading `dev.ps1` in each case's child scope to reset its variables and functions. Analyzer download rejection cases share a second process with separate packages, caches and download counters. Real parallel-stage and child-process cleanup tests retain separate processes. Gallery publication tests live in `tests/tooling/test_ui_gallery_site.py`; they use synthetic GitHub responses and archives, so they run with infrastructure tests rather than the `test-ui` selection. `check-fast` includes them for changes under `scripts/ui/`.

Real Git hotfix cases copy a module-scoped base history, including independent Git objects and refs, before making case-specific commits and pushes. They still exercise both commit parent shapes, conflicts, already-applied changes, version preservation and reruns against real Git; no mutable repository is shared between cases.

When removing or combining coverage, name the remaining test and temporarily introduce the corresponding production fault to confirm it fails. Restore the original bytes in `finally` and inspect the diff; do not use a Git reset that could discard unrelated local work. Keep inexpensive branch tables parametrized. Hotbar gaze tests use 1280 × 720 logical pixels mapped to 1920 × 1080 physical pixels, retaining the scaled-coordinate boundary; separate 1440 × 900 layout cases remain.

Updater tests use deterministic native and source-process records so another worker's installer smoke executable cannot block an unrelated update test. They still verify rejection before network access or app-data changes. Installer tests retain their real executable/process checks, and the final package build also verifies running-source rejection.

Use these existing fakes and regression tests when changing a runtime boundary:

| Boundary or flow | Tests and reusable inputs |
| --- | --- |
| Gaze mapping, pointer and dwell actions | `tests/gaze/test_mouse_controller.py` (`FakeInput`) and `tests/gaze/test_gaze_selection.py` |
| Provider fallback, stale delivery and reconnect | `tests/gaze/test_gaze_provider.py` and `tests/gaze/test_gaze_provider_recovery.py` |
| Eye policy, interruption deadlines and the independent desktop gate | `tests/gaze/test_eye_tracking_policy.py` and `tests/ui/test_eye_tracking_policy_e2e.py` |
| Edge departure, neighboring targets, return timing and repeat blocking | `tests/gaze/test_gaze_selection.py` and `tests/ui/test_edge_stability_e2e.py` |
| Gaze-check measurements and caregiver flow | `tests/gaze/test_gaze_check.py` and `tests/ui/test_gaze_check_e2e.py` |
| Aggregate reports, storage, history and ZIP export | `tests/gaze/test_gaze_check_store.py`, `tests/ui/test_gaze_check_reports_e2e.py` and `tests/ui/test_file_workers.py` |
| Recording admission, loss accounting, crash recovery, retention and support ZIPs | `tests/app/test_diagnostic_recording.py`, `tests/app/test_diagnostic_report.py` and `tests/ui/test_diagnostics_e2e.py` |
| Logging equivalence, blocked sinks and input responsiveness | `tests/app/test_diagnostics.py`, `tests/app/test_logging_async.py` and `tests/ui/test_gaze_diagnostics_e2e.py` |
| Parallel checks, coverage merging and pinned tool installation | `tests/tooling/test_dev_environment.py` and `tests/tooling/test_dev_coverage.py` |
| Tracking notice timing, context and geometry | `tests/gaze/test_tracking_feedback.py`, `tests/ui/test_tracking_feedback_e2e.py` and `tests/ui/test_hotbar_tracking_e2e.py` |
| Native Stream Engine startup, callbacks and cleanup | `tests/gaze/test_stream_engine_native.py` (`FakeLibrary`, without a Tobii DLL or streaming thread) |
| x86 bridge messages and shutdown | `tests/gaze/test_bridge_protocol.py` and `tests/gaze/test_bridge_entrypoint.py` |
| AppBar reservation and foreground thread cleanup | `tests/app/test_windows_native.py` (`FakeShell` and `FakeFocusApi`) |
| External window and cursor tracking | `tests/ui/test_foreground_tracker.py` |
| ElevenLabs account, requests and cancellation | `tests/speech/test_eleven_account.py`, `tests/speech/test_elevenlabs.py` and `tests/speech/test_elevenlabs_cancellation.py` |
| Efendija routing, cache and playback | `tests/speech/test_voice_router.py`, `tests/speech/test_audio_cache.py`, `tests/speech/test_audio_playback.py`, `tests/speech/test_efendija_service.py` and `tests/ui/test_elevenlabs_e2e.py` |
| Speech focus, Arabic, library and modal flows | `tests/ui/test_speech_focus_e2e.py`, `tests/ui/test_speech_arabic_e2e.py`, `tests/ui/test_speech_library_e2e.py`, and `tests/ui/test_speech_dialogs_e2e.py` |
| Speech layout and stale prediction delivery | `tests/ui/test_ui_e2e.py` and `tests/ui/test_speech_predictions.py` |
| Learning checkpoints and ranking selection rules | `tests/suggestions/test_speech_evaluation.py` |

Shared speech and library fakes live in `tests/_speech_fakes.py`; the service fixture is in `tests/_speech_service_fakes.py`. Windows and other UI fakes live in `tests/ui/_ui_fakes.py`. Hotbar fixtures live in `tests/ui/_hotbar_fixtures.py`, and Speech fixtures in `tests/ui/_speech_fixtures.py`. Import shared fixtures from these helper modules, never from another test module, so `check-fast` recognizes changes to shared inputs and selects all consumers. Version-selection UI tests live in `tests/ui/test_release_update_e2e.py`. Global pytest setup remains in `tests/conftest.py`. `.\dev.ps1 test-ui` selects tests marked `e2e`; use `.\dev.ps1 test` or `.\dev.ps1 check` to include the unmarked prediction, tracker, and native API tests as well.

Coverage is a regression floor, not a quality score. The initial floor is 60 percent because hardware DLL calls and Windows shell behavior cannot run safely in a normal test process. New pure-Python behavior should include tests, and the floor should only move upward as meaningful cases are added.

The native API fakes check arguments, callback filtering, failure cleanup, and resource ownership. They do not load a real DLL, exercise a native streaming thread, reserve an actual Windows work area, or prove cross-application focus. Provider and bridge tests cover delivery gaps, terminal protocol failures, and reconnect decisions separately. Use the [manual checks](UI_DEVELOPMENT.md#manual-windows-checks) for the real Windows and Tobii boundaries.

Pixel baselines are intentionally not enforced in CI. Qt rendering changes with Windows fonts, scaling, and GPU backends, which would make strict image diffs noisy. CI confirms that the representative screenshot set renders. Extended variants remain available for targeted review through the [gallery profiles](UI_DEVELOPMENT.md#rendered-ui-gallery); functional UI tests continue to exercise their behavior. A human reviews the generated gallery for clipping, overlap, spacing, contrast, and consistency.

### Conditional tests

A complete run discovers the suite, but a test can still require an unavailable capability or explicit opt-in. Record the actual skip reason; a skip is not a pass for that boundary.

| Test | When it runs | What remains unproven |
| --- | --- | --- |
| `test_native_buffer_replacement_and_completion_keep_qt_responsive` in `tests/speech/test_audio_playback.py` | When Qt finds an audio output. A probe exits with code 77 and pytest skips it otherwise. | A passing muted, isolated native-decoder probe checks replacement/stop/completion and Qt responsiveness, not audible speech or MP3 quality. |
| `test_gaze_logging_performance` in `tests/ui/test_gaze_performance.py` | Windows, explicit environment opt-in and `-Workers 1`. Ordinary CI does not enable it. | Software logging overhead under synthetic input, not physical Tobii latency or the overhead of manual recording. |

To run the software benchmark on the reference Windows PC, close competing workloads and use:

```powershell
$env:POGLED_ASSIST_RUN_GAZE_BENCHMARK = '1'
try {
    .\dev.ps1 test -Workers 1 -TestPaths tests/ui/test_gaze_performance.py
} finally {
    Remove-Item Env:\POGLED_ASSIST_RUN_GAZE_BENCHMARK
}
```

It compares logging off/basic/trace in three rotated repeats with 60 Hz synthetic input. Reports and synthetic logs go under a unique `dist/gaze-benchmark/<id>/` directory. Compare repeated runs on the same machine and Qt platform; do not turn those measurements into universal CI speed thresholds. Manual-recording overhead still needs the separate [target-machine comparison](UI_DEVELOPMENT.md#manual-tobii-checks).

## Mouse gaze simulation

See [mouse gaze simulation](UI_DEVELOPMENT.md#mouse-gaze-simulation) for the interactive simulator, failure controls, and hardware limits.

## UI review

See the [UI development guide](UI_DEVELOPMENT.md#ui-review) for rendered surfaces and manual Windows and Tobii checks.

### Application design reference workflow

The [design surface map and workflow](UI_DEVELOPMENT.md#application-design-reference-workflow) identify the reference page and assets to update before changing Qt UI.

## UI gallery publication

See the [UI gallery guide](UI_GALLERY.md) for status reporting, Pages setup, permissions, cleanup, and recovery.

## Diagnostic log analysis

The [architecture](ARCHITECTURE.md#diagnostic-logging) owns schema, clocks, queue, privacy and session limits. The [user guide](USER_GUIDE.md#diagnostic-log-collection) owns explicit recording, ZIP export and the older launch-time trace. For source launches, set the same `POGLED_ASSIST_GAZE_DIAGNOSTICS=trace` variable before `dev.ps1 run`; that trace requires ordinary logging, unlike explicit recording.

An offline reader imports neither Qt nor a Tobii backend:

```powershell
.\.venv\Scripts\python.exe -m pogled_assist.log_reader .\logs\diagnostics\<session-id>.jsonl
```

It counts provider rejection reasons from summaries and selection-end reasons from events. It reports process-cumulative writer health separately from a manual recording's footer health and end reason; do not sum cumulative loss counts repeatedly. The [architecture contract](ARCHITECTURE.md#short-diagnostic-recordings-and-support-packages) defines when a recording is complete. The same command accepts a recording's `snimak.jsonl`, including one extracted from a support ZIP. Basic event counts can be lower than actual transitions; check suppressed counters in the summaries. Missing start/end, malformed or partial last lines, dropped records and size limits constrain the conclusion. Read the requested time range's raw events when explaining a specific attempt. Compare event timestamps with video time; file rotation names are not session start timestamps. Do not infer tracking accuracy without a known intended target.

For a reported selection failure:

1. Establish the app version, `build_revision`, `build_dirty`, backend, policy, timing settings and simulation flag. Old logs cannot validate a newer implementation; a dirty revision does not identify an exact clean build. Missing metadata stays unknown.
2. Check `complete`, `lifecycle_complete`, parse warnings, `session_end_reason` and the applicable health counters before interpreting event counts. A closing record proves neither loss-free data nor successful intended selection.
3. Find the time range and intended target. Follow native eye receipt, provider rejection/delivery, applied application gate and selection events in order. Application eligibility is distinct from actual both-eye validity and from fresh gaze; an eligible-eye event alone cannot confirm a selection. Older events without explicit application eligibility retain the reader's both-eye interpretation.
4. Separate observed evidence from explanations needing a new recording or target-machine check. A change of target may be intentional; it is not proof of jitter. Aggregate gaze-check reports provide measurements for their own dated attempts, not a replay of the recorded interaction. An optionally attached report may be from another time or policy.

Support ZIP hashes describe the payload files listed in the manifest. Check them when transferring a package, and keep its recording identity separate from an optional report identity. Never attach whole local data folders or raw user logs to the repository as test fixtures; use synthetic inputs.

For changes to diagnostics, test the same provider/controller/Qt input sequence with logging off, basic, trace and a blocked writer. Include the existing gaze check and tracking-feedback suites: their snapshots, coverage, interruption counts and UI state must agree. Test actual blocked file/console sinks, overflow, runtime rotation, missing streams, exceptions and bounded shutdown. Keep stdout IPC atomic and independent of droppable logging. Use the existing pytest fakes and repository verification commands; Mac-only checks are not Windows or Tobii hardware verification. Measure producer/Qt latency, CPU, memory and output size on the same reference Windows device before release. A background thread still shares Python scheduling and the GIL, so asynchronous output alone does not establish zero overhead.

The manual recording lifecycle and support ZIP use `tests/app/test_diagnostic_recording.py` and `tests/ui/test_diagnostics_e2e.py`; existing gaze-equivalence scenarios also run with manual recording. Durations and file caps use fake clocks/small limits rather than waiting minutes or creating 32 MiB test files. History reads only bounded metadata and lifecycle edges. Full JSONL analysis and compression run during export on a file worker. These checks protect behavior and bounded work; reference-device overhead remains a separate manual measurement.

## Lint and formatting

actionlint checks GitHub Actions YAML syntax and workflow expressions before a push.

Ruff is the Python equivalent of the ESLint, Prettier, and import-sorting parts of a JavaScript toolchain. The repository enables syntax and import checks, Pyflakes, pyupgrade, bugbear, simplify, and Ruff-specific correctness rules.

PSScriptAnalyzer uses a focused settings file. It checks unsafe or ambiguous PowerShell patterns without enforcing naming preferences that would cause large, low-value rewrites of the existing setup scripts.

`scripts/checks/check_powershell.ps1` also rejects `Start-Process` (including its `start` and `saps` aliases) for ordinary executable launches. Windows PowerShell 5.1 defaults to the Windows shell, which can show **Open File – Security Warning** before the caller receives a process or starts its timeout. Use `ProcessStartInfo` with explicit `UseShellExecute = $false`; background console probes also use `CreateNoWindow = $true`. Keep normal window creation for the Qt application and installation summary. Drain redirected stdout and stderr concurrently before waiting, and bound output completion as well as process completion.

The guard permits explicit `-Verb RunAs` for UAC and the exact `dev.ps1` command that opens the generated `index.html` in a browser. Splatting executable arguments does not exempt a call; elevation must state `-Verb RunAs` at the call site. The guard checks PowerShell command ASTs, not arbitrary dynamically constructed code or Python shell calls. Windows OSK and Tobii document/protocol launches retain their existing shell semantics. These exceptions do not authorize shell launching of downloaded application or test executables.

Installer regressions compile an unsigned synthetic executable, attach an Internet `Zone.Identifier` stream, and exercise staging, installation, launch, failure and cleanup without clicking a warning. A separate harness timeout kills the test process tree if the production launch blocks. Source bootstrap installers use a private Windows job: the process starts suspended, joins the job before resuming, and the caller waits for descendants too. A 15-minute limit closes the tree on timeout; the root exit code, including `3010` (reboot requested), is preserved. This native start consumes the explicit `ProcessStartInfo` configuration because .NET Framework cannot suspend and assign a new child to a job through `Process.Start` alone. The standalone source setup keeps this helper inline so historical/source installations need no new support file.

Mypy is not enforced yet. Much of the UI depends on PySide signals, dynamic Qt objects, and Windows ctypes boundaries, so introducing strict type checking should start as a separate change with a defined module-by-module adoption plan.

## Packaging

Build the same Windows ZIP checked by CI:

```powershell
.\dev.ps1 package
```

The command uses the checked-in PyInstaller spec, verifies required assets, runs `--package-smoke-test` from the frozen executable, installs an extracted copy in an isolated directory, and writes the versioned ZIP under `dist`.

The build includes and verifies the speech tools described in the [release guide](WINDOWS_RELEASE.md#included-speech-tools). It does not prove physical Tobii behavior, audio-device playback, or online voice availability. Follow the manual checks in [WINDOWS_RELEASE.md](WINDOWS_RELEASE.md) before approving a release.
