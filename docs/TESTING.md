# Writing and selecting tests

Use the existing pytest suite and its boundary fakes. [Development](DEVELOPMENT.md#verification-before-a-pull-request) owns commands and final verification; [UI development](UI_DEVELOPMENT.md#manual-windows-checks) owns manual Windows/Tobii checks.

- [Test boundary map](#test-boundary-map)
- [Shared fixtures and lifecycle](#shared-fixtures-and-lifecycle)
- [Clocks, processes and blocked work](#clocks-processes-and-blocked-work)
- [Conditional tests](#conditional-tests)

## Test strategy

Tests under `tests/app/`, `gaze/`, `speech/`, `suggestions/`, `ui/`, `release/` and `tooling/` cover pure logic, service integration, UI workflows and repository rules. Global setup stays in `tests/conftest.py`; fixed speech evaluation inputs stay in `tests/fixtures/speech_suggestions/`. The `e2e` marker selects UI workflows for `dev.ps1 test-ui`; unmarked prediction, tracker and native-API tests require `test` or `check`.

Test the observable result at the changed boundary, including relevant ordering, failure and recovery. Every behavior change needs a pytest test that fails without it. When removing or combining coverage, name the remaining case and temporarily introduce the corresponding production fault to confirm it fails. Restore original bytes in `finally` and inspect the diff; never reset unrelated work.

Keep inexpensive branch tables parametrized. Layout coverage retains both scripts, representative group sizes and limits at 1280 × 720, plus relevant larger-screen and narrow-sidebar cases. Exercise mouse and gaze routes without repeating every route for every layout. Exact timing boundaries belong in the selection tests; UI tests verify that the real controls use them. Preserve logical-to-physical coordinate cases, including 1280 × 720 mapped to 1920 × 1080.

Coverage is a regression floor, not a quality score. The configured floor is 60 percent and should rise only with meaningful coverage. Native fakes verify arguments, filtering, cleanup and ownership; they do not load a real Tobii DLL, reserve a Windows work area or prove cross-application focus. Leave those boundaries to manual checks. Pixel baselines are not enforced because fonts, scaling and GPU backends vary; the rendered gallery still requires visual review.

## Test boundary map

| Boundary or flow | Tests and reusable inputs |
| --- | --- |
| Gaze mapping, pointer and dwell actions | `tests/gaze/test_mouse_controller.py` (`FakeInput`) and `tests/gaze/test_gaze_selection.py` |
| Provider fallback, stale delivery and reconnect | `tests/gaze/test_gaze_provider.py`, `tests/gaze/test_gaze_provider_recovery.py` and `tests/gaze/test_gaze_connection_lifecycle.py` (Qt responsiveness, pending startup/cleanup and child-process disposal) |
| Eye policy, interruption deadlines and the independent desktop gate | `tests/gaze/test_eye_tracking_policy.py` and `tests/ui/test_eye_tracking_policy_e2e.py` |
| Edge departure, neighboring targets, return timing and repeat blocking | `tests/gaze/test_gaze_selection.py` and `tests/ui/test_edge_stability_e2e.py` |
| Gaze-check measurements and caregiver flow | `tests/gaze/test_gaze_check.py` and `tests/ui/test_gaze_check_e2e.py` |
| Aggregate reports, storage, history and ZIP export | `tests/gaze/test_gaze_check_store.py`, `tests/ui/test_gaze_check_reports_e2e.py` and `tests/ui/test_file_workers.py` |
| Recording admission, loss accounting, crash recovery, retention and support ZIPs | `tests/app/test_diagnostic_recording.py`, `tests/app/test_diagnostic_report.py` , `tests/app/test_diagnostic_regressions.py`, `tests/ui/test_diagnostics_e2e.py` and `tests/ui/test_diagnostic_reasons_e2e.py` |
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

## Shared fixtures and lifecycle

| Reusable input | Owner |
| --- | --- |
| Speech and library fakes | `tests/_speech_fakes.py` |
| Speech service fixture | `tests/_speech_service_fakes.py` |
| Windows and UI fakes | `tests/ui/_ui_fakes.py` |
| Hotbar fixtures | `tests/ui/_hotbar_fixtures.py` |
| Speech fixtures | `tests/ui/_speech_fixtures.py` |
| Synthetic gallery services | `scripts/ui/capture_ui.py` (`Preview*` services) |

Import fixtures from helper modules, not other test modules, so changed-path selection can identify consumers. Qt cleanup closes top-level widgets and delivers deferred deletion before the next test. Wait for actual geometry, visibility, state or signals through the event loop; sleeps or layout requests alone can miss pending child visibility and polish.

Service fixtures cancel requests and join speech, account and network workers before their Qt owners leave scope. Unhandled worker-thread exceptions fail the suite. Provider regressions must exercise queued eye transitions, stale gaze after a GUI stall, and callbacks pending during reconnect/shutdown; sequential callbacks cannot prove their dispatch ordering.

Repository documentation tests check required guides/templates, local links and anchors, skill metadata and Claude pointers. Skill metadata requires unique YAML keys, non-empty `name` and `description`, a name matching the folder, and a pointer with identical metadata linking to the source. Generated reports and model checksums follow the [language guide](../language/bs/README.md).

## Clocks, processes and blocked work

- For a clock shared across modules, use `freeze_monotonic` from `tests/_clock.py`. Gaze timestamps cross component boundaries, and unrelated Qt teardown timers may read that same clock. For one module only, replace its `time` attribute with `SimpleNamespace(monotonic=...)`. `tests/tooling/test_clock_patches.py` rejects other `time.monotonic` replacements.
- Keep deliberately blocked log sinks blocked until the producer finishes. The timeout detects a hang; it is not a throughput target. Compare logging off/basic/trace and manual recording through the same input sequence. [Diagnostic verification](DIAGNOSTICS.md#diagnostic-log-analysis) covers the remaining lifecycle and loss cases.
- Independent PowerShell probes may share the module-scoped driver in `tests/_powershell.py`. Each case keeps its own working directory, child scope and environment. Batch only bodies that return or throw: `exit` terminates the driver. The harness restores streams, environment and location and kills the process tree on its 120-second deadline. Assert production environment recovery before harness cleanup.
- Full installer/updater transactions, concurrent updaters, real parallel-stage cleanup and `dev.ps1` initialization/environment-recovery tests retain separate processes and their own cleanup assertions. Updater decisions use deterministic process records; installer tests retain real running-executable checks.
- Git hotfix cases copy a base history with independent objects and refs. Never share a mutable repository across cases; preserve merge shapes, conflicts, already-applied changes, version preservation and reruns.

## Conditional tests

A complete run discovers the suite, but a test can still require an unavailable capability or explicit opt-in. Record the actual skip reason; a skip is not a pass for that boundary.

| Test | When it runs | What remains unproven |
| --- | --- | --- |
| `test_native_buffer_replacement_and_completion_keep_qt_responsive` in `tests/speech/test_audio_playback.py` | When Qt finds an audio output. A probe exits with code 77 and pytest skips it otherwise. | A passing muted, isolated native-decoder probe checks replacement/stop/completion and Qt responsiveness, not audible speech or MP3 quality. |
| `test_gaze_logging_performance` in `tests/ui/test_gaze_performance.py` | Windows, explicit environment opt-in and `-Workers 1`. Ordinary CI does not enable it. | Software logging overhead under synthetic input, not physical Tobii latency, native input correctness or audible speech. |

To run the software benchmark on the reference Windows PC, close competing workloads and use:

```powershell
$env:POGLED_ASSIST_RUN_GAZE_BENCHMARK = '1'
try {
    .\dev.ps1 test -Workers 1 -TestPaths tests/ui/test_gaze_performance.py
} finally {
    Remove-Item Env:\POGLED_ASSIST_RUN_GAZE_BENCHMARK
}
```

It compares logging off/basic/trace and manual recording with ordinary logging off/on, in three rotated repeats with the same 60 Hz synthetic input. Each report includes build identity, producer/controller/Qt latency, CPU, sampled memory and total output bytes; capture reports before and after a diagnostics change on the same reference PC. Reports and synthetic logs go under a unique `dist/gaze-benchmark/<id>/` directory. Compare repeated runs on the same machine and Qt platform; do not turn those measurements into universal CI speed thresholds. The [target-machine comparison](UI_DEVELOPMENT.md#manual-tobii-checks) remains necessary for Windows/Tobii evidence.
