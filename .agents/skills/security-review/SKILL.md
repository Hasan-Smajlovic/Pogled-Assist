---
name: security-review
description: Security and privacy rules specific to Pogled Assist - release update trust, typed-message privacy, external process launches, workflow permissions, and public language data. Use when changing gaze_mouse/release_update.py, update_windows.ps1, packaging/windows/install_windows.ps1, gaze_mouse/speech_service.py, logging, process launches, .github/workflows/, or text under language/ or tests/fixtures/.
---

# Security review

## Trust boundaries in this repo

- **GitHub Releases to the installed app.** `gaze_mouse/release_update.py` and
  `update_windows.ps1` accept only the latest stable release of
  `Hasan-Smajlovic/Pogled-Assist` and its exact ZIP and `.sha256`
  assets. The package installer they start requests Administrator access.
  [docs/WINDOWS_RELEASE.md](../../../docs/WINDOWS_RELEASE.md#update-an-installed-release)
  owns the full update behavior.
- **Typed messages to speech engines.** `gaze_mouse/speech_service.py` passes
  the message to eSpeak NG or `edge-playback`. eSpeak NG stays offline. The
  human-like voice sends the message to Microsoft's online service.
- **Machine environment to executables.** `TOBII_STREAM_ENGINE_DLL`,
  `POGLED_ASSIST_X86_PYTHON`, `ESPEAK_NG_EXE`, `EDGE_PLAYBACK_EXE`, and
  `TOBII_CALIBRATION_COMMAND` choose what the app loads or runs.
- **The x86 bridge process.** `gaze_mouse/tobii_stream_engine_bridge_backend.py`
  parses JSON lines from the 32-bit bridge and discards invalid payloads.
- **The public repository.** Everything under `language/` and
  `tests/fixtures/speech_suggestions/` is published.

## Rules

- Log typed text only as the `<text>` placeholder, as
  `SpeechService._start_process` does. Personal learning keeps word counts in
  `data/speech_learning.json`, never message transcripts.
- Pass user text to processes as one list element with the shell off. The
  shell launch in `gaze_mouse/tobii_calibration.py` is reserved for the
  operator-set `TOBII_CALIBRATION_COMMAND`.
- Verify before changing files: a checksum, metadata, or network failure
  leaves the installed app unchanged.
- Change the pinned release source in both places together:
  `RELEASE_API_URL` and `RELEASE_DOWNLOAD_ROOT` in `gaze_mouse/release_update.py`,
  and `$OfficialReleaseApiUrl` and `$OfficialReleaseAssetRoot` in
  `update_windows.ps1`.
- Keep `C:\TobiiExec` rejected by `packaging/windows/install_windows.ps1` and
  `update_windows.ps1`.
- Keep `.github/workflows/ci.yml` on `pull_request` with `contents: read`.
  Only `.github/workflows/release.yml`, triggered by a push to `master`, gets
  `contents: write`.
- Commit only synthetic or project-authored text under `language/` and
  `tests/fixtures/`, as the language data rules in
  [docs/DEVELOPMENT.md](../../../docs/DEVELOPMENT.md) require.

## Before merging

- Updater or installer change: `tests/test_release_updater.py` and
  `tests/test_windows_installer.py` pass without weakened assertions, including
  `test_checksum_mismatch_stops_before_installer_runs` and
  `test_legacy_install_root_is_never_modified`. The pull request records the
  manual update, invalid-checksum, and rollback checks from the release guide
  as run or Not run.
- Speech or logging change: no new `logger` call formats message text, phrase
  text, or suggestion input.
- Workflow change: `permissions` did not widen, no `pull_request_target`
  trigger was added, and `scripts/check_github_actions.ps1` passes.
