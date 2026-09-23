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
| `.\dev.ps1 ui` | Not required | Rendering of 19 main UI surfaces without external services |
| `.\dev.ps1 test` | Not required | Unit, integration, and UI workflow tests with simulated inputs |
| `.\dev.ps1 test-ui` | Not required | UI workflow and rendering tests selected by the `e2e` marker |
| `.\dev.ps1 coverage` | Not required | Test suite, 60 percent floor, and `dist\coverage-html` report |
| `.\dev.ps1 lint` | Not required | Actions, Ruff, Python compilation, and PowerShell checks |
| `.\dev.ps1 format` | Not required | Ruff safe fixes, import ordering, and source formatting |
| `.\dev.ps1 check` | Not required | Lint, tests, coverage, package build, and frozen executable smoke test |
| `.\dev.ps1 package` | Not required | Clean PyInstaller build and frozen executable smoke test |

The supporting scripts are grouped by purpose: `scripts/checks/` validates
source and workflows, `scripts/release/` builds and publishes releases,
`scripts/ui/` renders the UI gallery, and `scripts/speech_suggestions/`
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
The bundled general model was rebuilt from the verified archive with the current
preparation script and tokenizer. Its source and code checksums are recorded in
the [model metadata](../pogled_assist/assets/bosnian-model.meta.json). Keep the
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

Use `.\dev.ps1 check` before pushing a pull request. It runs with Python 3.10
and covers the same three categories enforced by the required `code-quality`,
`tests`, and `windows-package` pull request checks.

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

Automated tests live under `tests/app/`, `tests/gaze/`, `tests/speech/`,
`tests/suggestions/`, `tests/ui/`, `tests/release/`, and `tests/tooling/`.
Shared pytest setup stays in `tests/conftest.py`, and fixed speech evaluation
data stays in `tests/fixtures/speech_suggestions/`. Run the whole suite from
the repository root; pytest discovers all of these folders through `tests/`.

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

### Application design reference workflow

[`design/speech-keyboard-reference.html`](design/speech-keyboard-reference.html)
is the design source of truth for the visible Pogled Assist interface. The
historical filename is retained so existing links remain stable, but the file
also documents Settings and any other application surface changed in the
future.
It currently has main views for Speech and Settings. Hotbar, standalone
Keyboard and Controller, and gaze overlays do not yet have their own main
views there. Add the relevant view before changing one of those surfaces.

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

The command renders:

- Hotbar
- General, gaze, speech, and learned-word Settings surfaces
- Speech keyboard, categories, answers, saved phrases, and shared editor
- Speech alarm, sleep, and exit confirmation dialogs
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
