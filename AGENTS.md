# Agent guide

Pogled Assist is a Windows desktop application used through a Tobii Eye
Tracker 4C. A person relies on the current installed behavior, so preserving
working gaze, input, speech, settings, and installation flows is the first
constraint for every change.

## Start here

- [README.md](README.md) covers installation, launch commands, requirements,
  data, and known limits.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) maps the runtime and lists the
  behavior that must remain stable.
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) defines setup, checks, UI review,
  and hardware test boundaries.
- [CONTRIBUTING.md](CONTRIBUTING.md) defines branches, reviews, merges, and
  releases.
- [docs/WINDOWS_RELEASE.md](docs/WINDOWS_RELEASE.md) covers packaging,
  installation, rollback, and clean-machine validation.

## Change rules

- Treat the current `development` behavior as the compatibility baseline. Keep
  the flows listed in the architecture compatibility contract working unless a
  linked issue explicitly changes one of them.
- Preserve everything under `data/` and `logs/` across installation, update,
  and rollback work. The
  [persistent data section](docs/ARCHITECTURE.md#persistent-data-and-logs)
  lists each file, including the ones older releases still read.
- Keep gaze safety rules intact: both eyes must be valid before pointer movement
  or gaze actions can continue, and losing either eye must cancel dwell state.
- Keep Qt logical coordinates separate from Windows physical coordinates when
  changing gaze mapping or input.
- Do not store prompt archives, conversation logs, or any other assistant
  history in the repository. Record only lasting project knowledge in maintained
  documentation.
- Keep each fact in the document that owns it, then link to that document. Do not
  copy architecture, setup, workflow, or release instructions into new files.
- Reuse the pytest suite and its fake inputs. Do not add another test framework.
- Before accepting that a change cannot be tested without hardware, look for a
  fake of the same boundary: `FakeInput` in `tests/test_mouse_controller.py`,
  the fakes in `tests/test_ui_e2e.py`, the backend stubs in
  `tests/test_gaze_provider.py`, and the `Preview*` services in
  `scripts/capture_ui.py`. Leave only what those cannot reach to the manual
  hardware checks.
- Follow the application design reference workflow in
  [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) before changing any visible UI
  layout, copy, control size, state, or interaction flow. Every UI change must
  update `docs/design/speech-keyboard-reference.html` in the same pull request.
- Do not claim Tobii, AppBar, calibration, or speech hardware validation unless
  it ran on the target Windows machine. Report software-only and hardware results
  separately.
- Do not change setup, runtime, packaging, or dependency behavior as part of a
  documentation-only task.

## Maintenance matrix

| When you change | Also update |
| --- | --- |
| Visible UI in `gaze_mouse/*_window.py`, `gaze_mouse/toolbar.py`, `gaze_mouse/quick_action_*.py`, `gaze_mouse/gaze_bubble.py`, or `gaze_mouse/interaction_overlay.py` | `docs/design/speech-keyboard-reference.html` first, then `tests/test_ui_e2e.py`, and `docs/USER_GUIDE.md` when the user flow changes |
| The surfaces rendered by `scripts/capture_ui.py` | The snapshot count in `tests/test_ui_rendering.py` and the surface count and list in `docs/DEVELOPMENT.md` |
| A runtime file under `gaze_mouse/assets/` or `assets/` | `datas` in `packaging/windows/PogledAssist.spec`, `$requiredFiles` in `scripts/build_windows_package.ps1`, and a `binary` entry in `.gitattributes` for binary files |
| A field of `GazeSettings` in `gaze_mouse/mouse_controller.py` or `SpeechSettings` in `gaze_mouse/speech_service.py` | The clamp in `gaze_mouse/settings_store.py`, the same range in `gaze_mouse/settings_window.py`, `tests/test_settings_store.py`, and `docs/USER_GUIDE.md` |
| Model inputs under `language/bs/model/`, `gaze_mouse/suggestion_text.py`, or `scripts/prepare_*_model.py` | The prepared `gaze_mouse/assets/bosnian-*-model.*` files and the reports under `language/bs/`, regenerated with the commands in `docs/DEVELOPMENT.md` |
| A file under `data/` | The data lists in `README.md` and `docs/ARCHITECTURE.md`, and the preserved files in `tests/test_windows_installer.py` |
| An action in `dev.ps1` | `Write-Help` in `dev.ps1` and the command reference in `docs/DEVELOPMENT.md` |
| A job name in `.github/workflows/ci.yml` | The required checks in `CONTRIBUTING.md` and `docs/WINDOWS_RELEASE.md`. Hasan updates both branch rulesets |
| A required guide or template | `REQUIRED_FILES` or `REQUIRED_TEMPLATE_SECTIONS` in `tests/test_repository_docs.py` |

## Verification

Set up the local environment once, then use the repository entry point:

```powershell
.\dev.ps1 setup
.\dev.ps1 check
```

Use the focused commands documented in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
while iterating. Inspect the full diff before review, and follow the manual
checklist in the development guide whenever runtime behavior changes.

## Done means

- `.\dev.ps1 check` exits with code 0, and the required `code-quality`,
  `tests`, and `windows-package` pull request checks pass.
- Every behavior change includes a pytest test that fails without the change.
- Every maintenance matrix row that matches a changed path is updated in the
  same diff.
- The pull request Verification section lists each command that actually ran
  and marks every manual Windows and Tobii check as passed, failed, or Not run.

## Never merges without a human

A person has to have **read this diff** before it lands. Telling an agent "merge
it when you're done" is approving a goal, not this change, so it does not count
for anything on this list. Everywhere else it counts fine, which is the point of
having a list.

- Any change under `.github/workflows/` or `packaging/windows/`, or to
  `scripts/build_windows_package.ps1`, `scripts/publish_github_release.ps1`, or
  `VERSION`.
- Any change to `update_windows.ps1`, `setup_windows.ps1`, or
  `gaze_mouse/release_update.py`.
- Any change to `gaze_mouse/settings_store.py`, `gaze_mouse/speech_library.py`,
  or `gaze_mouse/suggestion_learning.py`.
- Any change to `gaze_mouse/gaze_provider.py`, `gaze_mouse/mouse_controller.py`,
  `gaze_mouse/gaze_selection.py`, `gaze_mouse/windows_input.py`, or
  `gaze_mouse/tobii_stream_engine*.py`.
- Any added or changed text under `language/` or
  `tests/fixtures/speech_suggestions/`.
