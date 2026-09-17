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
- Preserve `data/app_settings.json`, `data/speech_phrases.json`, and user logs
  across installation, update, and rollback work.
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
- Follow the Speech design reference workflow in
  [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) before changing the Speech window's
  visible layout, copy, control sizes, or interaction flow.
- Do not claim Tobii, AppBar, calibration, or speech hardware validation unless
  it ran on the target Windows machine. Report software-only and hardware results
  separately.
- Do not change setup, runtime, packaging, or dependency behavior as part of a
  documentation-only task.

## Verification

Set up the local environment once, then use the repository entry point:

```powershell
.\dev.ps1 setup
.\dev.ps1 check
```

Use the focused commands documented in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
while iterating. Before review, inspect the full diff, record the commands that
actually ran, and list every skipped hardware check as a known limit. Follow the
manual checklist in the development guide whenever runtime behavior changes.
