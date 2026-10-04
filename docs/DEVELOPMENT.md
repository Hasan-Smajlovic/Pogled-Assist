# Development guide

Development and release checks run on Windows x64 with Python 3.10.

## First setup

Run PowerShell from the repository root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\dev.ps1 setup
```

Setup creates `.venv`, installs the application, test and packaging dependencies,
and downloads actionlint 1.7.12 and PSScriptAnalyzer 1.25.0 into the ignored
`.dev-tools` directory. It does not install Tobii software or change the
system-wide Python environment. The `.venv` always uses Python 3.10.
If `.venv` points to a removed or unsupported interpreter, setup moves it to
`.dev-tools\venv-backups` before creating a fresh one. To use a specific
installed interpreter, pass `-BasePython C:\Path\To\python.exe` to setup.

`tobii-research==2.1.0` has a Windows wheel for Python 3.10, so the same
interpreter is used for development, Tobii Pro discovery, automated checks,
and Windows packaging.

## Command reference

Run these commands in Windows PowerShell. The automated checks do not require a
Tobii tracker, calibrated display, eSpeak NG, or the online speech service.
Only the real gaze and external speech checks listed below require those
components.

| Command | Tobii hardware | What it verifies |
| --- | --- | --- |
| `.\dev.ps1 run` | Optional to start, required for real gaze checks | The real source application, tracker discovery, and Windows input |
| `.\dev.ps1 simulate` | Not required | Mouse-driven gaze feedback, dwell timing, UI selection, and click flows |
| `.\dev.ps1 ui` | Not required | Rendering of 38 main UI surfaces without external services |
| `.\dev.ps1 test` | Not required | All unit, integration, and UI workflow tests in two worker processes, without coverage |
| `.\dev.ps1 test -TestPaths tests/gaze -Workers 1` | Not required | An explicit focused selection in one process |
| `.\dev.ps1 test-ui` | Not required | UI workflow and rendering tests selected by the `e2e` marker |
| `.\dev.ps1 coverage` | Not required | Test suite, 60 percent floor, and `dist\coverage-html` report |
| `.\dev.ps1 lint` | Not required | Actions, Ruff, Python compilation, and PowerShell checks |
| `.\dev.ps1 format` | Not required | Ruff safe fixes, import ordering, and source formatting |
| `.\dev.ps1 check-fast` | Not required | Complete Python lint/format/compilation and relevant changed tests; no coverage or package |
| `.\dev.ps1 check-fast -BaseRef origin/development` | Not required | Fast checks using an explicit Git comparison ref |
| `.\dev.ps1 check-fast -Workers 2` | Not required | Fast checks with two workers even for a small selection |
| `.\dev.ps1 check` | Not required | Lint, tests, coverage, package build, and frozen executable smoke test |
| `.\dev.ps1 check -Workers 1` | Not required | The same complete verification with sequential tests |
| `.\dev.ps1 coverage -Workers 2` | Not required | Explicit parallel coverage measurement; slower Qt runs are possible |
| `.\dev.ps1 package` | Not required | Clean PyInstaller build and frozen executable smoke test |

`coverage` and `check` temporarily clear `PYTEST_ADDOPTS` so environment options
cannot omit tests or override the coverage floor. This also ignores diagnostic
options supplied through that variable. The commands restore its original value
after testing, including on failure. Use `test` or `test-ui` for custom pytest
options while investigating a failure.

The supporting scripts are grouped by purpose: `scripts/checks/` validates
source and workflows, `scripts/release/` builds and publishes releases,
`scripts/ui/` renders and prepares UI galleries, and `scripts/speech_suggestions/`
prepares and evaluates Bosnian prediction models.

Before running the model commands below in Windows PowerShell, use UTF-8 for
Python's output so printed Bosnian text works with older console encodings:

```powershell
$env:PYTHONIOENCODING = "utf-8"
```

Reproduce the frozen Bosnian suggestion measurements from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts\speech_suggestions\evaluate_speech_model.py --dataset development --output language\bs\evaluation\reports\development.json
.\.venv\Scripts\python.exe scripts\speech_suggestions\evaluate_speech_model.py --dataset heldout --output language\bs\evaluation\reports\heldout.json
```

The development set is available for model decisions. Do not tune from the
held-out result. The scoring contract and frozen hashes are under
`tests\fixtures\speech_suggestions`.

The original held-out messages have now been inspected in repeated reviews;
keep their frozen text as a regression set, not a fresh blind quality estimate.
The frozen fixture protocol records the rules used for the first comparison;
its instruction to withhold those messages no longer describes their current
status.
An independently authored and reviewed set, withheld until model selection is
complete, is still needed for that claim. Reports separate sentence starters,
exact next-word hits before the first letter, and completion queries along the
simulated typing path. Their percentages are not interchangeable.

When changing the prepared language data, compare the supported vocabulary
sizes in one corpus pass before rebuilding the bundled model:

```powershell
.\.venv\Scripts\python.exe scripts\speech_suggestions\benchmark_speech_models.py .dev-tools\corpora\CLASSLA-web.bs.2.0.jsonl.gz --output-dir .dev-tools\speech-model-benchmark --report language\bs\benchmarks\model.json
.\.venv\Scripts\python.exe scripts\speech_suggestions\prepare_speech_model.py .dev-tools\corpora\CLASSLA-web.bs.2.0.jsonl.gz
.\.venv\Scripts\python.exe scripts\speech_suggestions\compare_speech_ranking.py --output language\bs\benchmarks\ranking.json
```

The ranking comparison holds language data fixed and compares the original fixed
weights with adaptive discounts of 2, 10, and 40 on development messages only.
It rejects latency or quality regressions, checks that sparse contexts back off
while supported contexts remain useful, and records its selection rule and
recommendation. If changing the chosen discount, update
`WordModel.context_discount` and rerun the vocabulary comparison before
evaluating the regression set.

The verified CLASSLA archive is a local development input and is not downloaded
by setup or included in a release. Its source URL and integrity hashes are in the
bundled model metadata. Candidate selection uses only the development set; run
the held-out evaluation once after the model choice is fixed.
The [model metadata](../pogled_assist/assets/bosnian-model.meta.json) records the
archive, inputs, preparation script, and tokenizer used for that build. Compare
those recorded checksums with the files being reviewed; the presence of a bundled
model does not establish that it was built from the current source. Keep the
archive outside the repository's tracked files for future rebuilds.

`language\bs\model\core\conversation.tsv`, `starters.tsv`, and `spelling.tsv`
are build inputs that the installed application does not load. Rebuild the
bundled model after changing them or the preparation script. Spelling
replacements apply only to web training data; personal spelling and typed text
are preserved. The vocabulary budget
reserves space for reviewed words, and reviewed word combinations survive the
web-only pruning limits. Run the commands above to refresh the generated model,
metadata, and comparison reports before review. An old report does not validate
a model with a different checksum.

Preparation and tokenizer checksums cover the complete source files. A refactor
or formatting change therefore requires rebuilding the affected model even when
prediction behavior is intended to stay the same. Run `.\dev.ps1 format` before
preparation so formatting cannot immediately invalidate the new metadata. Never
replace a recorded checksum by hand to make a test pass.

The reviewed Islamic terminology is a separate offline layer, so it can be
rebuilt without downloading the 2.63 GB CLASSLA archive:

```powershell
.\.venv\Scripts\python.exe scripts\speech_suggestions\prepare_islamic_model.py
```

`language\bs\model\domains\islamic.tsv` contains project-authored examples informed by the
terminology of the Islamic Community in Bosnia and Herzegovina. The generated
`bosnian-islamic-model.json.gz` and metadata are packaged beside the general
model and merged in memory at startup. Rebuild the layer after changing its TSV,
tokenisation, or preparation script, then run both frozen evaluations and the
focused suggestion tests. Do not copy articles, sermons, private correspondence,
or a user's messages into the repository.

The evaluation report includes each exact-word miss before typing, classified
as missing vocabulary, missing context, or a word ranked below the five visible
candidates. Completion remains a separate metric. Compare these causes as well
as activation counts when choosing the next data change.

Measure personal learning and large synthetic profiles separately:

```powershell
.\.venv\Scripts\python.exe scripts\speech_suggestions\evaluate_speech_learning.py --stress-sizes 0 10000 50000 150000 --output language\bs\evaluation\reports\learning.json
```

This uses synthetic scenarios from `language/bs/evaluation/learning.tsv`, with separate
profiles and checkpoints after zero, one, three, and ten message uses. It also
records unrelated control predictions and exits unsuccessfully if a target is
not visible after one use, not first after three uses, or displaces an unrelated
expected top-five result. The optional stress measurements report index
construction, the first query, and reused-index queries separately. They exclude
Qt dispatch, display, file I/O, and Tobii processing, so they cannot establish
the Windows end-to-end latency target.

For fresh quality validation, have a separate author prepare and freeze a TSV
with `id`, `category`, and `text` columns and its SHA-256 before the candidate is
selected. Use synthetic text with the same punctuation supported by the frozen
keyboard protocol. Keep those messages out of preparation and tuning. After
selecting the candidate, evaluate that exact file:

```powershell
.\.venv\Scripts\python.exe scripts\speech_suggestions\evaluate_speech_model.py --cases C:\Temp\speech-evaluation.tsv --expected-sha256 "<previously-frozen-sha256>" --output .dev-tools\speech-external-evaluation.json
```

The script verifies the supplied checksum and reports miss diagnostics. It does
not certify independent authorship or freeze a set retroactively. Do not add
private conversations to the repository. Existing regression fixtures remain
unchanged.

## Verification before a pull request

During development, run `.\dev.ps1 check-fast` after each meaningful change and
repeat it after fixes. Once the final diff is ready, run `.\dev.ps1 check` once
before pushing a pull request; rerun it if the diff changes afterwards. It runs
with Python 3.10
and covers the same three categories enforced by the required `code-quality`,
`tests`, and `windows-package` pull request checks.

The fast command compares committed topic-branch changes against the merge base
of `origin/development`, then adds staged, unstaged and untracked files. It
includes both paths of a rename and deleted paths. Fetch `origin/development`
before starting a topic branch; the fast command does not fetch automatically.
Use `-BaseRef <ref>` when deliberately comparing another base. Missing Git
history or an unavailable ref selects the full suite instead of skipping tests.

Selection rules live in `scripts/checks/select_tests.py`. Changes to gaze,
speech, suggestions, UI, Windows or release code select the boundary's tests
and its application/UI consumers. Changed and new test modules are included.
Documentation selects repository documentation/link tests. Unknown paths,
shared test helpers, deleted tests, dependencies, workflow/check configuration,
model data and bundled assets select every test. Maintain the mapping when
adding consumers; use the full-suite fallback whenever the impact is uncertain.
This is a development feedback aid; the final check and CI always run all tests.

`check-fast` prints changed paths, selection reasons and selected test files.
It runs Ruff lint, formatting and Python compilation across the repository,
but checks only changed PowerShell scripts and affected Actions workflows.
A full-suite fallback also checks all PowerShell and Actions files. It omits
coverage and packaging even when all tests are selected. With no changes, it
still checks Python source and explicitly reports that no tests were selected.
All verification commands report stage and total durations, including failures.

Tests without coverage default to two pytest-xdist processes with
`--dist=loadfile`, keeping each test file on one worker. Each worker has its own
QApplication and temporary directories. With the default `-Workers 0`, fast
selections of fewer than four test files use one process to avoid startup
overhead. `-Workers 1` disables parallel execution for debugging; `-Workers 2`
uses two processes even for a small selection.

The full `coverage` and `check` commands default to one test process. On the
measured Windows/Python 3.10 environment, parallel coverage made repeated Qt
sidebar interactions much slower: the full test stage took about 400 seconds,
compared with the earlier sequential baseline of 163 seconds. The suites differ
by 50 new regression cases, so this is diagnostic evidence rather than a precise
speedup comparison. Keep coverage sequential until a measured alternative helps.
`-Workers 2` explicitly enables parallel coverage; worker results are combined
before enforcing the same 60 percent floor and writing the HTML report. PR CI
continues to run every test with coverage in one process. Its existing quality,
test and packaging jobs continue to run independently.

For manual focused work, `test` and `test-ui` accept `-TestPaths` (one or more
pytest paths); add `-Workers 1` for a small selection. `coverage`, `check` and
`check-fast` reject `-TestPaths` so a partial selection cannot be mistaken for
their documented checks. Run `.\dev.ps1 setup` once after pulling the new
development dependency to install the pinned pytest-xdist plugin.

Documentation-only work also runs these checks to confirm the runtime baseline.
Its links and commands need a manual documentation review. If a required device
check cannot run, record it as not run. Never infer a hardware result from a
mocked test or a package smoke test.

If a local check fails, use the [local checks troubleshooting guide](DEVELOPMENT_TROUBLESHOOTING.md)
to identify common Windows and pytest causes.

## Test strategy

The suite uses five layers:

1. Unit tests cover coordinate mapping, dwell state, settings validation, speech
   commands, phrase storage, and Windows helper behavior.
2. Integration tests cover provider fallback, app startup, logging, packaging
   paths, release publication recovery, release download and checksum failures,
   transactional installation and rollback, and the optional x86 bridge
   discovery logic.
3. UI tests use `pytest-qt` with mocked speech and Windows input. They exercise
   Settings, Speech, Keyboard, Controller, Hotbar, zoom, and radial-menu flows.
4. Repository tests check required guides and templates, local documentation
   links, and the minimum sections agents need for issues and pull requests.
5. Manual Tobii checks verify the device runtime, calibration, gaze quality,
   AppBar behavior, clicks, and speech on the target machine.

Provider regressions also exercise worker-thread eye notifications arriving
before Qt has dispatched them, shutdown/reconnect with pending callbacks, and
stale gaze queued during a GUI stall. These cases use the real provider and
controller with fake device inputs; sequential callback tests alone cannot
verify their dispatch ordering. Speech UI tests cover gaze, button and Return
activation and check that source diagnostics omit the message text.

Automated tests live under `tests/app/`, `tests/gaze/`, `tests/speech/`,
`tests/suggestions/`, `tests/ui/`, `tests/release/`, and `tests/tooling/`.
Shared pytest setup stays in `tests/conftest.py`, and fixed speech evaluation
data stays in `tests/fixtures/speech_suggestions/`. Run the whole suite from
the repository root; pytest discovers all of these folders through `tests/`.

Updater tests use deterministic native and source-process records so another
worker's installer smoke executable cannot block an unrelated update test.
They still verify rejection before network access or app-data changes. Installer
tests retain their real executable/process checks, and the final package build
also verifies running-source rejection.

Use these existing fakes and regression tests when changing a runtime boundary:

| Boundary or flow | Tests and reusable inputs |
| --- | --- |
| Gaze mapping, pointer and dwell actions | `tests/gaze/test_mouse_controller.py` (`FakeInput`) and `tests/gaze/test_gaze_selection.py` |
| Provider fallback, stale delivery and reconnect | `tests/gaze/test_gaze_provider.py` and `tests/gaze/test_gaze_provider_recovery.py` |
| Native Stream Engine startup, callbacks and cleanup | `tests/gaze/test_stream_engine_native.py` (`FakeLibrary`, without a Tobii DLL or streaming thread) |
| x86 bridge messages and shutdown | `tests/gaze/test_bridge_protocol.py` and `tests/gaze/test_bridge_entrypoint.py` |
| AppBar reservation and foreground thread cleanup | `tests/app/test_windows_native.py` (`FakeShell` and `FakeFocusApi`) |
| External window and cursor tracking | `tests/ui/test_foreground_tracker.py` |
| Speech focus, Arabic, library and modal flows | `tests/ui/test_speech_focus_e2e.py`, `tests/ui/test_speech_arabic_e2e.py`, `tests/ui/test_speech_library_e2e.py`, and `tests/ui/test_speech_dialogs_e2e.py` |
| Speech layout and stale prediction delivery | `tests/ui/test_ui_e2e.py` and `tests/ui/test_speech_predictions.py` |
| Learning checkpoints and ranking selection rules | `tests/suggestions/test_speech_evaluation.py` |

Shared UI service fakes live in `tests/ui/_ui_fakes.py`. Speech window fixtures
live in `tests/ui/_speech_fixtures.py` and are imported by the Speech test modules;
global pytest setup remains in `tests/conftest.py`. `.\dev.ps1 test-ui` selects
tests marked `e2e`; use `.\dev.ps1 test` or `.\dev.ps1 check` to include the
unmarked prediction, tracker, and native API tests as well.

Coverage is a regression floor, not a quality score. The initial floor is 60
percent because hardware DLL calls and Windows shell behavior cannot run safely
in a normal test process. New pure-Python behavior should include tests, and the
floor should only move upward as meaningful cases are added.

The native API fakes check arguments, callback filtering, failure cleanup, and
resource ownership. They do not load a real DLL, exercise a native streaming
thread, reserve an actual Windows work area, or prove cross-application focus.
Provider and bridge tests cover delivery gaps, terminal protocol failures, and
reconnect decisions separately. Use the manual checks below for the real Windows
and Tobii boundaries.

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

### Application design reference workflow

[`design/speech-keyboard-reference.html`](design/speech-keyboard-reference.html)
is the design source of truth for the visible Pogled Assist interface. The
historical filename is retained so existing links remain stable, but the file
also documents Settings and any other application surface changed in the
future.
It currently has main views for Speech, Settings, the installation summary,
Hotbar, standalone Keyboard, and the Controller keyboard. Gaze overlays do not
yet have their own main views there. Add the relevant view before changing one
of those surfaces.

Every change to visible layout, copy, control sizes, states, or interaction flow
must update the matching HTML reference in the same pull request. Update and
review the reference first, then implement the matching PySide6 change so the
reference never describes an older UI. This rule applies to every window,
sidebar, overlay, dialog, and system control in the application, not only the
Speech window. If a code change has no visible or interaction impact, state that
explicitly in the pull request instead of editing the reference unnecessarily.

Review the HTML reference at the target display size before generating the Qt
gallery. The reference documents the intended result; the gallery and real
application checks confirm that the implementation matches it.

Generate the gallery:

```powershell
.\dev.ps1 ui -Open
```

The CI `tests` job also uploads a `ui-gallery` artifact, using the screenshots
already rendered by `tests/ui/test_ui_rendering.py`. Once Pages is configured,
the separate **UI gallery** workflow publishes a browser gallery and updates
one PR bot comment with main screenshots, resolution links, the rendered commit,
and a download link. Setup, publication permissions, and cleanup are defined in
[CONTRIBUTING.md](../CONTRIBUTING.md#ui-gallery-publication).
To review the artifact offline, download and extract it from the workflow run,
then open `index.html` inside `1280x720` or `1440x900`.
Each folder contains the same 38 surfaces; the artifact is kept for 14 days and
any available screenshots are uploaded even when the test suite fails.
CI sets `POGLED_ASSIST_UI_GALLERY` to the artifact directory. Without that
variable, rendering tests continue to use pytest's temporary directories.
The Pages site uses a separate generated index and only checked PNG files; it
does not publish the HTML supplied by a PR's CI artifact. Available screenshots
from a failed CI run can appear, with the failure shown in the comment. A gallery
is visual evidence, not a passing test or a Windows/Tobii verification result.

The command renders:

- Hotbar, including one-eye pause, waiting for fresh data, disconnected-device,
  mouse-simulation, and unsaved-settings states
- General, gaze, speech, and learned-word Settings surfaces, including save failure
- Speech keyboard, categories, answers, saved phrases, shared editor, and library read failure
- Speech alarm, sleep, and exit confirmation dialogs
- Keyboard letters, numpad, and symbols tabs
- Controller general, keyboard, and settings tabs
- Latin Keyboard and Controller with two letters per group and page controls
- Arabic Speech, letters and vowel-mark dialogs, symbols, and phrase editor
- Arabic Settings and both sidebar keyboards, including their second symbols page

Hotbar snapshots use at most 1280 logical pixels of width, and Settings snapshots
use at most 1280 × 720 logical pixels, to review the 1920 × 1080 display at 150%
scaling. Other surfaces use the requested gallery size. In Settings, check equal
action cells, the single-cell calibration control, the voice below keyboard
script, and aligned decrease/value/increase columns.
The Latin pagination snapshots use 380 × 640 logical pixels to check the sidebar
below the 76-pixel hotbar at 150% scaling.

The separate installation summary is documented in the HTML reference and
covered by UI interaction tests; it is not part of the 38-surface gallery.
Review it separately using `PogledAssist.exe --installation-check` after a build.

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
- The Controller Speech tab, hidden hotbar, Quick actions, precision zoom, and
  gaze feedback remain usable.
- Opening Keyboard closes Controller and opening Controller closes Keyboard.
- Settings survive an application restart.
- Logs appear under `logs` only when logging is enabled.
- Closing the app removes AppBar reservations and child windows.
- Bosnian suggestions complete a partial word and offer a next word offline.
- Moving the caret or selecting text disables suggestions; returning to the end
  restores them without changing the message.
- Suggestion undo, punctuation spacing, phrase or answer editor restoration, and
  individual learned-word removal work with mouse and simulated gaze.
- Closing and reopening preserves `data\speech_learning.json`; a forced write
  failure leaves the previous file intact and can be retried from Settings.
- Switch Latin/Arabic from Settings and each keyboard, including an unfinished
  phrase or answer. The shared choice survives restart without changing existing
  text or entries. Review Arabic shaping, mixed text, both digit forms, mark
  entry/removal, and sidebar pagination at 1920 × 1080 with 150% scaling (1280 ×
  720 logical pixels). Arabic has no suggestions; returning to Latin restores
  them. Test Hamed playback and unavailable/offline errors separately.

On the Tobii machine, additionally verify:

- The hotbar status distinguishes connecting, unavailable device, waiting for
  fresh data, and ready tracking. Readiness requires both eyes and fresh gaze;
  it does not certify calibration accuracy.
- Both labeled eye indicators reflect real validity. Hide removes the whole
  status with the hotbar; Show restores its current state.
- Losing one eye cancels dwell progress and stops pointer movement.
- At 150% scaling, select Speech, Keyboard, and Settings from the top screen edge
  without a mouse. Gaps between buttons must not select either neighbor.
- In Speech, the hotbar, and standalone Keyboard, a brief movement just beyond a button edge freezes progress without
  selecting either button. Returning resumes it; a sustained or farther move
  starts a new selection. Check letters, suggestions, and `Izgovori`, including
  deliberate fast switches and the leave-before-repeat rule. Record selection
  errors and switching delay before and after the change on the user's display.
- Disconnect and reconnect the tracker while dwelling. Progress must cancel,
  the connection must recover, and the first new selection must start from zero.
  Confirm that normal invalid-eye samples do not repeatedly restart the backend.
- With the x86 bridge, resume after Windows sleep and confirm that old dwell
  progress cannot fire an action. A direct native connection pauses until data
  returns and does not start a replacement native subscription during an outage.
- Pointer mapping reaches all corners of the calibrated display.
- Left, right, double-click, precision zoom, and Quick actions work.
- Default and human-like speech are tested separately.
- Select Arabic groups, letters, marks, and the script switch by Tobii. Eye loss
  and script/page changes must cancel pending dwell; a replacement label must
  require leaving and returning before another action. Record actual Hamed audio
  playback and pronunciation separately from process startup and fake speech.

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

The build includes and verifies the speech tools described in the
[release guide](WINDOWS_RELEASE.md#included-speech-tools). It does not prove
physical Tobii behavior, audio-device playback, or online voice availability.
Follow the manual checks in [WINDOWS_RELEASE.md](WINDOWS_RELEASE.md) before
approving a release.
