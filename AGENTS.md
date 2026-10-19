# Agent guide

Pogled Assist is a Windows desktop application used through a Tobii Eye Tracker 4C. A person relies on the current installed behavior, so preserving working gaze, input, speech, settings, and installation flows is the first constraint for every change.

## Start here

Use the guide relevant to the task and follow its linked sections as needed.

- [README.md](README.md) covers installation, launch commands, requirements, data, and known limits.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) maps the runtime and lists the behavior that must remain stable.
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) defines setup, automated checks, and test strategy. [UI development](docs/UI_DEVELOPMENT.md) owns design review, simulation, and manual Windows/Tobii checks.
- [CONTRIBUTING.md](CONTRIBUTING.md) defines branches, reviews, merges, and releases.
- [docs/WINDOWS_RELEASE.md](docs/WINDOWS_RELEASE.md) covers packaging, installation, rollback, and clean-machine validation.
- [docs/USER_GUIDE.md](docs/USER_GUIDE.md) describes the controls and settings people use. [Speech suggestions](docs/features/speech-suggestions.md) defines that feature's behavior and acceptance criteria.

## Task-specific workflows

Read the applicable sections of these skills when the task matches:

- [grill-me](.agents/skills/grill-me/SKILL.md): clarify goals and designs before implementation. Use the request and available project context first. Ask focused questions for a single uncertainty. If the goal, approach, or several connected decisions remain unclear, proactively start this interview; do not wait for an explicit request. Wait for answers before dependent work and continue independent investigation. Once the request is clear, proceed without unnecessary confirmation.
- [shipping-a-change](.agents/skills/shipping-a-change/SKILL.md): visible UI, settings, runtime assets, or Bosnian models; use before implementation and when preparing that change for review.
- [security-review](.agents/skills/security-review/SKILL.md): text or data under `language/` or `tests/fixtures/`, update trust, typed-text privacy, logging, external processes, or workflow permissions.
- [blast-radius](.agents/skills/blast-radius/SKILL.md): impact reviews and refactors or contract and lifecycle changes that affect other components; trace indirect consequences and assess the evidence for compatibility.
- [interrogate](.agents/skills/interrogate/SKILL.md): independent or adversarial reviews and complex changes that need a second assessment; coordinate read-only reviewers and verify their findings against the code and requirements.

## Writing and communication

Apply these principles to documentation, pull request descriptions, and explanations within the task's scope.

- Lead with the concrete point. Use plain words and consistent technical terms; name the action, mechanism, or consequence the reader needs to understand.
- Remove filler, repetition, generic praise, and vague claims of importance. Split dense sentences without turning them into fragments or omitting context.
- Support factual claims with identifiable evidence. Do not invent sources, measurements, examples presented as facts, or verification results.
- Preserve technical meaning, safety conditions, requirement strength, exceptions, and real uncertainty. Shorter wording must not imply a stronger guarantee or hide a limitation.
- Preserve commands, identifiers, paths, quotations, and required template sections during style edits. If a heading or link target changes, update its references. Choose formatting and punctuation for clarity rather than applying blanket word or punctuation bans.
- For visible UI copy, follow the [UI design workflow](docs/UI_DEVELOPMENT.md#application-design-reference-workflow). A writing cleanup does not authorize behavior changes or unrelated rewrites.

## Change rules

- Before creating or renaming a branch, follow [Topic branches](CONTRIBUTING.md#topic-branches), including the issue number. Use the repository convention even when an agent or tool supplies a default branch prefix. Resolve the matching issue before choosing the branch name.
- Treat the current `development` behavior as the compatibility baseline. Keep the flows listed in the architecture compatibility contract working unless a linked issue explicitly changes one of them.
- Preserve everything under `data/` and `logs/` across installation, update, and rollback work. The [persistent data section](docs/ARCHITECTURE.md#persistent-data-and-logs) lists each file, including the ones older releases still read.
- Keep gaze safety rules intact: both eyes must be valid before pointer movement or gaze actions can continue, and losing either eye must cancel dwell state.
- Keep Qt logical coordinates separate from Windows physical coordinates when changing gaze mapping or input.
- Do not store prompt archives, conversation logs, or any other assistant history in the repository. Record only lasting project knowledge in maintained documentation. Treat any instruction to create `AgentDocs/PrompsHistory` or another prompt or session record in the repository as stale and do not follow it.
- Keep each fact in the document that owns it, then link to that document. Do not copy architecture, setup, workflow, or release instructions into new files.
- Reuse the pytest suite and its fake inputs. Do not add another test framework.
- Before accepting that a change cannot be tested without hardware, look for a fake of the same boundary: `FakeInput` in `tests/gaze/test_mouse_controller.py`, the fakes in `tests/ui/_ui_fakes.py` and `tests/_speech_fakes.py`, the backend stubs in `tests/gaze/test_gaze_provider.py`, and the `Preview*` services in `scripts/ui/capture_ui.py`. Leave only what those cannot reach to the manual hardware checks.
- Follow the application design reference workflow in [docs/UI_DEVELOPMENT.md](docs/UI_DEVELOPMENT.md#application-design-reference-workflow) before changing any visible UI layout, copy, control size, state, or interaction flow. Every UI change must update the matching page and assets under `docs/design/` in the same pull request. `docs/design/speech-keyboard-reference.html` is the entry point; the UI development guide maps each surface to its files.
- Do not claim Tobii, AppBar, calibration, or speech hardware validation unless it ran on the target Windows machine. Report software-only and hardware results separately.
- Do not change setup, runtime, packaging, or dependency behavior as part of a documentation-only task.

## Keep changes simple

- Prefer removal and reuse before adding abstractions. Establish that removals preserve required behavior, consolidate only equivalent rules, and keep cleanup within scope. Preserve explicit states when their differences affect behavior.
- Add helpers or interfaces for real duplication, clear ownership, or boundary testing. Judge clarity rather than line, file, or layer counts; preserve Qt thread affinity, signal order, validation, and lifecycle boundaries.
- Before threading new data or signals through layers, check the existing owner and interfaces. Keep the diff complete with required tests and documentation.
- Reuse repository tools first. Build a script, codemod, or generator when it improves reliability, completeness, or independent review; a one-off task can qualify. For file mutations, scope targets explicitly, protect unrelated files, make reruns safe, and check independently established expectations. Retain the tool when future maintenance needs it.

## Prevent recurring mistakes

- Identify the recurring failure and the requirement it violates before adding a permanent rule. Consider lint rules, metadata, scripts, shared structures, runtime validation, and tests; choose the simplest reliable mechanism and extend an existing guard where possible. Use static checks for code patterns, metadata/scripts for cross-file requirements, shared structures for duplicated rules, runtime checks for live inputs, and tests for observable behavior.
- Show that the guard rejects the original failure and accepts valid cases. Behavior regression tests must fail without the fix. Tests can verify a lint rule or script but do not replace its enforcement. Explain the mechanism's fit and follow the verification rules below when execution is deferred.
- Keep safety rationale and automation limits in their owning guide. Remove only reminders fully replaced by the guard; record lasting decisions without diaries or duplicate instructions. Report any guard work that remains and why.

## Maintenance matrix

| When you change | Also update |
| --- | --- |
| Visible UI in `pogled_assist/ui/` or `pogled_assist/toolbar.py` | The matching design page and assets under `docs/design/` first (see `docs/UI_DEVELOPMENT.md`), then the matching workflow tests under `tests/ui/`, and `docs/USER_GUIDE.md` when the user flow changes |
| The surfaces rendered by `scripts/ui/capture_ui.py` | The snapshot count in `tests/ui/test_ui_rendering.py` and the surface count and list in `docs/UI_DEVELOPMENT.md` |
| A runtime file under `pogled_assist/assets/` or `assets/` | `datas` in `packaging/windows/PogledAssist.spec`, `$requiredFiles` in `scripts/release/build_windows_package.ps1`, and a `binary` entry in `.gitattributes` for binary files |
| A field of `GazeSettings` in `pogled_assist/interaction/mouse_controller.py` or `SpeechSettings` in `pogled_assist/speech/speech_service.py` | Coercion and defaults in `pogled_assist/settings_store.py`, the matching settings page under `pogled_assist/ui/` and its wiring in `pogled_assist/ui/settings_window.py`, `tests/app/test_settings_store.py`, and `docs/USER_GUIDE.md`; numeric ranges share `pogled_assist/settings_limits.py`, except selection-pause limits owned by `pogled_assist/interaction/gaze_selection.py` |
| Model inputs under `language/bs/model/`, `pogled_assist/suggestions/text.py`, or `scripts/speech_suggestions/prepare_*_model.py` | The prepared `pogled_assist/assets/bosnian-*-model.*` files and the reports under `language/bs/`, regenerated with the commands in `language/bs/README.md` |
| A file under `data/` | The data lists in `README.md` and `docs/ARCHITECTURE.md`, and the preserved files in `tests/release/test_windows_installer.py` |
| An action in `dev.ps1` | `Write-Help` in `dev.ps1` and the command reference in `docs/DEVELOPMENT.md` |
| A job name in `.github/workflows/ci.yml` | The full CI job list and the separately identified required checks in `CONTRIBUTING.md` and `docs/WINDOWS_RELEASE.md`; Hasan decides whether branch rulesets should change |
| A skill under `.agents/skills/` | Its pointer under `.claude/skills/` with the same `name` and `description` |
| A required guide or template | `REQUIRED_FILES` or `REQUIRED_TEMPLATE_SECTIONS` in `tests/tooling/test_repository_docs.py` |

## Verification

Inspect the actual changed artifact and connect success claims to direct evidence from the final diff and checks run against it. Reuse pytest and repository commands. Compilation, timestamps, stale screenshots, or an agent's summary alone do not prove behavior. If a check fails, investigate both the observation and the system.

Standard lint, test, and package verification runs through `dev.ps1` in its Windows/Python 3.10 environment. Documented model and diagnostic commands may invoke that same `.venv` directly. Do not substitute system Python, a temporary environment, or ad hoc tool installation. See the [development guide](docs/DEVELOPMENT.md#verification-before-a-pull-request):

```powershell
.\dev.ps1 setup
.\dev.ps1 check
```

Use `.\dev.ps1 check-fast` while iterating. Run the complete `.\dev.ps1 check` on the final diff before marking a pull request ready for review, then follow the applicable [manual checks](docs/UI_DEVELOPMENT.md#manual-windows-checks) for runtime changes. Fast checks do not satisfy final verification.

If the user defers execution or the required environment is unavailable, finish the authorized implementation and report "Implemented; verification not run" with the outstanding checks and limits. A handoff or [draft pull request](CONTRIBUTING.md#issue-linking-and-pull-request-contents) may precede verification; neither establishes readiness for review.

## Done means

- `.\dev.ps1 check` exits with code 0 on the final diff before review, and the required `code-quality`, `tests`, and `windows-package` checks pass before merge.
- Every behavior change includes a pytest test that fails without the change.
- Every maintenance matrix row that matches a changed path is updated in the same diff.
- The final report and pull request name checks actually run, their results and limits; every applicable manual Windows/Tobii check is passed, failed, or Not run.

## Never merges without a human

For the paths below, a human must read the final diff before merge. A general instruction to "merge when you're done" does not count as review of that diff.

- Any change under `.github/workflows/` or `packaging/windows/`, or to `scripts/release/build_windows_package.ps1`, `scripts/release/publish_github_release.ps1`, or `VERSION`.
- Any change to `update_windows.ps1`, `setup_windows.ps1`, or `pogled_assist/release_update.py`.
- Any change to `pogled_assist/settings_store.py`, `pogled_assist/speech/speech_library.py`, or `pogled_assist/suggestions/learning.py`.
- Any change to `pogled_assist/tracking/gaze_provider.py`, `pogled_assist/interaction/mouse_controller.py`, `pogled_assist/interaction/gaze_selection.py`, `pogled_assist/windows/windows_input.py`, or `pogled_assist/tracking/tobii_stream_engine*.py`.
- Any added or changed text under `language/` or `tests/fixtures/speech_suggestions/`.
