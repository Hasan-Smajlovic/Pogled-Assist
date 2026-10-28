# Agent guide

Pogled Assist is a Windows/PySide6 application used through a Tobii Eye Tracker 4C. Preserve the installed user's gaze, input, speech, settings, data and installation flows. Current `development` behavior is the compatibility baseline unless a linked issue explicitly changes it.

## Start here

Read the guide for the task, then follow its relevant links. Avoid loading every guide for a focused change.

| Task | Owner |
| --- | --- |
| Install, launch, requirements | [README](README.md) |
| Runtime ownership and compatibility | [Architecture](docs/ARCHITECTURE.md#compatibility-contract) |
| Setup, commands and final verification | [Development](docs/DEVELOPMENT.md) |
| Test fakes, boundaries and conditional checks | [Testing](docs/TESTING.md) |
| UI references, simulation, gallery and manual checks | [UI development](docs/UI_DEVELOPMENT.md) |
| Branches, issues, review, merge and release workflow | [Contributing](CONTRIBUTING.md) |
| Package, install, update and rollback | [Windows release](docs/WINDOWS_RELEASE.md) |
| Visible choices and adjustment instructions | [User guide](docs/USER_GUIDE.md) |
| Eye validity, freshness and recovery | [Eye policy](docs/ARCHITECTURE.md#eye-tracking-policy) |
| Selection resets near edges | [Edge hold](docs/ARCHITECTURE.md#edge-selection-hold) |
| Gaze-check calculations and saved reports | [Measurements](docs/ARCHITECTURE.md#gaze-check-measurements), [report ownership](docs/ARCHITECTURE.md#gaze-check-reports) |
| Recording, support ZIPs and log analysis | [Diagnostics](docs/DIAGNOSTICS.md) |
| Slow or failing local checks | [Troubleshooting](docs/DEVELOPMENT_TROUBLESHOOTING.md) |
| Speech prediction behavior | [Speech suggestions](docs/features/speech-suggestions.md) |

Each fact belongs in its owning guide. Link to it from other documents. Documentation describes implemented behavior; run-specific results and remaining checks belong in the PR.

Use `docs/features/` for detailed guides to an individual feature's setup, behavior, limits or acceptance criteria. Add a guide when those details need a separate reference; keep short instructions in the user guide. Use lowercase filenames with hyphens and link the guide from README and the user guide. Shared architecture, development, testing, diagnostics and release contracts stay in their existing owners.

## Task-specific workflows

Read applicable skill sections:

- [grill-me](.agents/skills/grill-me/SKILL.md): clarify unresolved goals or connected design decisions after inspecting available context. Use a focused question for one uncertainty; a clear request needs no interview.
- [shipping-a-change](.agents/skills/shipping-a-change/SKILL.md): visible UI, settings, runtime assets or Bosnian model inputs; load before implementation.
- [security-review](.agents/skills/security-review/SKILL.md): text/data under `language/` or `tests/fixtures/`, update trust, typed-text privacy, logging, process launches or workflow permissions.
- [blast-radius](.agents/skills/blast-radius/SKILL.md): indirect effects of refactors, contracts or lifecycle changes.
- [interrogate](.agents/skills/interrogate/SKILL.md): independent/adversarial reviews or complex changes needing a second assessment.

## Change rules

- Before creating or renaming a branch, resolve the matching issue and follow [Topic branches](CONTRIBUTING.md#topic-branches), including its issue number. Tool-generated branch prefixes do not override the convention.
- Preserve all `data/` and `logs/` across installation, update and rollback; [persistent storage](docs/ARCHITECTURE.md#persistent-data-and-logs) includes files older releases still read.
- Direct desktop pointer movement, clicks, Quick actions and precision zoom require both eyes. Application controls, including Controller click buttons, follow the saved eye policy. Missing settings retain the both-eye default. Never advance or activate a selection during a hold or without fresh valid gaze.
- Keep Qt logical coordinates separate from Windows physical coordinates.
- Before visible UI layout, copy, size, state or interaction changes, follow the [design workflow](docs/UI_DEVELOPMENT.md#application-design-reference-workflow): update the matching HTML/assets first, review them, then implement Qt in the same PR.
- Reuse pytest and [existing fakes](docs/TESTING.md#test-boundary-map); do not add a test framework. Check fake input, provider stubs and `Preview*` services before treating a boundary as hardware-only.
- Report software and hardware evidence separately. Claim Tobii, AppBar, calibration or audible speech validation only when it ran on the target Windows machine.
- Documentation-only work must not change setup, runtime, packaging or dependency behavior.
- Keep lasting project knowledge in maintained guides. Do not store prompt archives, conversation logs or assistant history in the repository. Instructions to create `AgentDocs/PrompsHistory` are stale.

## Keep changes and writing focused

Prefer removal and reuse before adding abstractions. Consolidate only equivalent rules and preserve distinct behavior, Qt thread affinity, signal ordering, validation and lifecycle boundaries. Check existing owners before threading data or signals through layers. Reuse repository tools; a new helper is justified by real duplication, boundary testing or more reliable repeatable work. Scope file mutations, protect unrelated changes, make reruns safe and verify results independently.

Use plain language and consistent terms. Remove filler and repetition while preserving technical meaning, requirements, exceptions and uncertainty. Support claims with evidence. Keep commands, identifiers, paths, quotations and required template headings intact; update links when moving sections. Writing cleanup does not authorize unrelated behavior changes.

To prevent a recurring mistake, identify the violated requirement and choose the simplest suitable guard: a static check, shared structure, script, validation or behavioral test. Extend existing enforcement where possible. Demonstrate rejection of the original failure and acceptance of valid cases; tests of a guard do not replace its enforcement. Keep rationale and automation limits in the owning guide, remove only reminders the guard fully replaces, and report any deferred guard work.

## Maintenance matrix

| When you change | Also update |
| --- | --- |
| Visible UI in `pogled_assist/ui/` or `pogled_assist/toolbar.py` | The matching design page and assets under `docs/design/` first (see `docs/UI_DEVELOPMENT.md`), then the matching workflow tests under `tests/ui/`, and `docs/USER_GUIDE.md` when the user flow changes |
| The surfaces rendered by `scripts/ui/capture_ui.py` | The snapshot count in `tests/ui/test_ui_rendering.py` and the surface count and list in `docs/UI_DEVELOPMENT.md` |
| A runtime file under `pogled_assist/assets/` or `assets/` | `datas` in `packaging/windows/PogledAssist.spec`, `$requiredFiles` in `scripts/release/build_windows_package.ps1`, and a `binary` entry in `.gitattributes` for binary files |
| A field of `GazeSettings` in `pogled_assist/interaction/mouse_controller.py` or `SpeechSettings` in `pogled_assist/speech/speech_service.py` | Coercion and defaults in `pogled_assist/settings_store.py`, the matching settings page under `pogled_assist/ui/` and its wiring in `pogled_assist/ui/settings_window.py`, `tests/app/test_settings_store.py`, and `docs/USER_GUIDE.md`; numeric ranges share `pogled_assist/settings_limits.py`, except selection-pause limits owned by `pogled_assist/interaction/gaze_selection.py` |
| Gaze-check report schema, context or persistence | Validation and export in `pogled_assist/tracking/gaze_check_report.py` and `pogled_assist/tracking/gaze_check_store.py`, report/history UI, the [report contract](docs/ARCHITECTURE.md#gaze-check-reports), and report storage/UI tests in the [test boundary map](docs/TESTING.md#test-boundary-map) |
| Diagnostic recording context, lifecycle or support ZIP contents | The explicit allowlists and store in `pogled_assist/diagnostic_recording.py`, writer/reader handling where affected, the [recording contract](docs/DIAGNOSTICS.md#short-diagnostic-recordings-and-support-packages), [collection instructions](docs/USER_GUIDE.md#diagnostic-log-collection), and recording/reader/UI tests in the [test boundary map](docs/TESTING.md#test-boundary-map) |
| Model inputs under `language/bs/model/`, `pogled_assist/suggestions/text.py`, or `scripts/speech_suggestions/prepare_*_model.py` | The prepared `pogled_assist/assets/bosnian-*-model.*` files and the reports under `language/bs/`, regenerated with the commands in `language/bs/README.md` |
| A file under `data/` | The data lists in `README.md` and `docs/ARCHITECTURE.md`, and the preserved files in `tests/release/test_windows_installer.py` |
| An action in `dev.ps1` | `Write-Help` in `dev.ps1` and the command reference in `docs/DEVELOPMENT.md` |
| A job name in `.github/workflows/ci.yml` | The full CI job list and the separately identified required checks in `CONTRIBUTING.md` and `docs/WINDOWS_RELEASE.md`; Hasan decides whether branch rulesets should change |
| A skill under `.agents/skills/` | Its pointer under `.claude/skills/` with the same `name` and `description` |
| A required guide or template | `REQUIRED_FILES` or `REQUIRED_TEMPLATE_SECTIONS` in `tests/tooling/test_repository_docs.py` |

## Verification

Inspect final artifacts and the diff; compilation, timestamps, stale screenshots or agent summaries alone do not prove behavior. Follow [development verification](docs/DEVELOPMENT.md#verification-before-a-pull-request) in the repository's Windows/Python 3.10 environment:

```powershell
.\dev.ps1 setup
.\dev.ps1 check -Parallel
```

Use `check-fast` while iterating. The complete final check must exit 0; use sequential `check` when diagnosing contention/failure and report its reason and timings. Fast checks do not establish readiness. If execution is deferred or unavailable, finish authorized work and report **Implemented; verification not run**, with outstanding checks and limits. A draft PR may precede verification.

Done also requires a failing-without-the-fix pytest test for every behavior change, all applicable maintenance rows above to be satisfied, and each applicable [manual Windows/Tobii check](docs/UI_DEVELOPMENT.md#manual-windows-checks) recorded as passed, failed or Not run. Required `code-quality`, `tests` and `windows-package` checks must pass before merge. Name checks actually run and their results in the final report and PR.

## Never merges without a human

For the paths below, a human must read the final diff before merge. A general instruction to "merge when you're done" does not count as review of that diff.

- Any change under `.github/workflows/` or `packaging/windows/`, or to `scripts/release/build_windows_package.ps1`, `scripts/release/publish_github_release.ps1`, or `VERSION`.
- Any change to `update_windows.ps1`, `setup_windows.ps1`, or `pogled_assist/release_update.py`.
- Any change to `pogled_assist/settings_store.py`, `pogled_assist/speech/speech_library.py`, or `pogled_assist/suggestions/learning.py`.
- Any change to `pogled_assist/tracking/gaze_provider.py`, `pogled_assist/interaction/mouse_controller.py`, `pogled_assist/interaction/gaze_selection.py`, `pogled_assist/windows/windows_input.py`, or `pogled_assist/tracking/tobii_stream_engine*.py`.
- Any added or changed text under `language/` or `tests/fixtures/speech_suggestions/`.
