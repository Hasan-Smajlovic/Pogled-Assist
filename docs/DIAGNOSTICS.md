# Diagnostic logging and recordings

This guide owns log transport, recording lifecycle, support ZIPs and offline analysis. For collecting a problem in the app, use the [user guide](USER_GUIDE.md#diagnostic-log-collection). [Architecture](ARCHITECTURE.md) owns gaze/input behavior and persistent storage; [testing](TESTING.md#test-boundary-map) lists reusable fakes.

- [Logging and privacy](#diagnostic-logging)
- [Recording lifecycle and export](#short-diagnostic-recordings-and-support-packages)
- [Build identity](#build-identity)
- [Read and interpret a recording](#diagnostic-log-analysis)

## Diagnostic logging

`logging_setup.py` owns the existing logging switch and standard-stream/Qt hooks. `log_transport.py` owns one persistent daemon writer in the main process. Both the text file and console run behind its bounded queue. Producers copy bounded primitive fields and never wait for output, queue space or a shared thread pool. The writer releases the queue mutex before formatting, archiving, writing and flushing. Overflow drops log records, with cumulative process counts and the time span of loss in `logging_health`; it never drops input packets. The x86 bridge uses a separate bounded stderr writer, while its stdout input protocol retains its existing lock, JSON, newline and flush contract.

The queue admits at most 1,024 records of approximately 8 KiB including copied object overhead; 64 slots are reserved for lifecycle, error and summary records. Priority records also drop when full. Output flushes about every 250 ms. Shutdown waits at most two seconds for the worker; file objects are owned only by that daemon, so Python's handler shutdown cannot synchronously close a blocked sink. The OS may finish an already-started write after logging is disabled. Pending ordinary records are discarded on disable. Queued stream, selection and marker summaries finish in their original session before its end record, including partial intervals collected at disable or rotation. These retained records share the same queue capacity; overflow remains explicit in logging health. A new enable creates a new session and archives the previous text log on the same writer. A crash or blocked writer can leave an incomplete last batch. Existing archives are never automatically deleted.

`diagnostics.py` collects separate native input, provider delivery, application gate and selection observations. Native valid-time accounting expires after 500 ms without another eye sample; application gate time records the gate's actual state at Qt delivery, separately from native receipt. Validity is a reported SDK measurement, not physical eye closure. Provider replacement is intentional sampling for Qt, not a disconnect. Basic summaries run about once per second, with their actual interval duration. Basic state events allow four records per event type per second and report suppressed counts. Trace records the fuller sequence subject to queue and file limits.

JSONL schema version 1 uses `event`, `session_id`, `process_instance`, `event_seq`, `wall_time` with timezone, `monotonic_s` and an explicit `data` payload. Event time is captured before queueing. `data` supplies stream generations, context and attempt IDs where applicable. Sequence numbers also include text records, so a gap in JSONL alone is not proof of a dropped event. SDK timestamps keep their own source and microsecond unit; they are not subtracted from main-process time. The runtime record reports source/frozen mode and known versions; absent build revision is explicitly unknown. Structured sessions are capped at 64 MiB.

Basic events include stream/selection summaries, gate receipt/application, delivery gaps, settings, screen mapping, dialog lifecycle, UI action origin, tracking notices and input suspension during the caregiver check. Trace adds native/provider samples, actual target bounds, selection timing, normalized track-box positions and already-computed fixation/trial results. Logging never activates or recalculates gaze-check telemetry. Native eye measurements remain actual SDK values; application eye eligibility follows the selected policy. Each `eye_gate_applied` event records that policy and its `application_gate_open` eye eligibility, independently of gaze freshness or a held selection. Offline analysis uses this explicit eligibility; older events without it retain the both-eye interpretation. Settings events include the policy and interruption duration. Generation guards remain in place. The existing invalid-gaze callback cannot distinguish SDK-invalid from nonfinite input, so it is labeled `sdk_invalid_or_nonfinite`. Notice timing stays independent of input cancellation. Settings construction and the Windows startup query are timed separately.

Typed text, suggestions, phrases, key labels and content action IDs are excluded from added events. Such actions receive random IDs local to the current context; safe control names such as `confirm:accept` remain readable. Exception snapshots retain their type and bounded frame locations, without traceback locals or exception text. Trace coordinates and target geometry can still reveal activity; these local recordings are not anonymous. Trace is explicitly enabled, lasts at most ten minutes or 32 MiB of additional records, then returns to basic logging. See [collection instructions](USER_GUIDE.md#diagnostic-log-collection) and [developer analysis](DIAGNOSTICS.md#diagnostic-log-analysis).

## Short diagnostic recordings and support packages

| Owner | Responsibility |
| --- | --- |
| `ui/diagnostic_recordings.py` (`DiagnosticRecordings`) | Application-lifetime status, start/stop requests, Qt delivery, history/export queue and the shared indicator |
| `diagnostics.py` and `log_transport.py` | Existing observations and the persistent `LogWriter`; recording admission, event order, deadlines, byte cap and final drain |
| `diagnostic_recording.py` (`RecordingStore`) | Metadata validation, crash recovery, retention, full inspection and atomic support ZIP export |
| `ui/recording_badge.py` | One shared `RecordingIndicator` and passive `RecordingBadge` views; no recording or input decisions |
| `build_info.py` | Cached source identity shared by ordinary logs, recordings and gaze-check reports |

### Window and indicator ownership

The hotbar owns `DiagnosticRecordings`; closing the recording window keeps recording active. Opening that window suspends normal input until returning. The gaze-check shortcut is unavailable during precision/button measurement. Hiding the check for diagnostics stops its UI timer and telemetry collection without discarding its report; returning restores the check and its existing input suspension.

All badges bind to the same indicator, including windows opened later. The indicator's saved-confirmation timer and accessibility announcement identity are shared; reopening a window must not restart them. Badges reserve space or overlay an existing control, take no focus and pass mouse events through. They never move gaze targets or replace tracking/speech notices. The [collection guide](USER_GUIDE.md#diagnostic-log-collection) owns visible messages and durations; the [design workflow](UI_DEVELOPMENT.md#application-design-reference-workflow) maps their references.

### Recording admission and completion

Manual recording reuses `diagnostics.py` observations and the persistent `LogWriter` queue. The writer snapshots a recording identity with each event, so normal-log toggles cannot discard recording events or mix segments. Only structured events enter the recording; text logging and console output are excluded. Normal logging retains its current switch and independent session cap. Manual trace can start without ordinary logging, without a restart, and after a normal session reaches 64 MiB. It never changes saved settings, eye eligibility, input decisions, or measurement calculations.

The selected duration is 1, 2, 5 or 10 minutes (default 2); a monotonic deadline, manual stop, shutdown, write failure or the 32 MiB total cap ends admission. One recording remains busy through the writer's confirmed drain/close, including a blocked sink; another cannot start during that interval. Queue pressure and truncated snapshots are counted for this recording rather than copied from process-cumulative normal-log health. A reserved footer stays inside the file cap. Status distinguishes start/record/finish, end reason, lifecycle footer and completeness. Shutdown or a missing footer is incomplete even when some data was saved. No file/console wait or worker join is added to gaze/Qt callbacks. Application logging retains its existing two-second shutdown bound.

The status progresses from `starting` to `recording` to `finishing` while the writer drains. An inactive status or a present closing record alone does not establish completeness. For a `manual_trace` stream, the offline reader requires lifecycle records, no parse warnings or size-limit event, a `manual` or `time` end reason, and valid footer `recording_health` without dropped records, writer errors or bounded snapshots. Missing or invalid recording health leaves it incomplete. Process-cumulative `logging_health` remains separately reported and does not make a clean later recording incomplete. Ordinary log sessions keep their existing process-health checks.

### History, recovery and retention

`diagnostic_recording.py` owns atomic metadata, history, retention and ZIP export. After successful final metadata storage, the oldest recording folders are removed to retain five and at most 200 MiB; the active recording is excluded. Known unreadable recordings share that budget. Unrelated files, manually exported ZIPs and folders containing additional files are preserved; such external content is outside this managed budget. History reads bounded metadata and lifecycle edges, while full JSONL analysis happens only for inspection/export on a file worker. A separate worker with a four-task queue serializes history and export requests. Pruning and export serialize file access. A force-killed process can leave a partial stream or initial metadata; recovery labels it interrupted and never certifies completeness. Readable partial recordings can be exported with `complete=false`; unsupported or unreadable recordings remain visible but cannot be exported.

On history load, readable crash remnants are atomically stored as confirmed partial recordings, with unknown duration kept distinct from zero. Recovery then restores retention, including a process killed after final metadata but before pruning. A process-local active-identity registry prevents a queued history job from recovering, exporting or pruning the current recording. That registry uses no file-worker lock on input/Qt producers. A failed recovery leaves older recordings intact and blocks another start until the history check succeeds. Ordinary basic suppression counts stay independent of manual trace; deliberate basic exclusions never become false queue-loss reports. Rotation preserves recording-event order even while ordinary summary footers finish separately.

### Support ZIP contents and privacy

The local ZIP includes these files; it does not copy a settings or logs folder:

| File | Contents |
| --- | --- |
| `snimak.jsonl` | The chosen detailed recording |
| `kontekst.json` | Allowlisted gaze settings and environment |
| `sazetak.txt` | Readable Bosnian technical summary |
| `manifest.json` | Version 1 manifest, recording lifecycle/completeness and each payload file's byte size and SHA-256; the manifest does not hash itself |
| `provjera/rezultat.json`, `provjera/izvjestaj.txt` | Only when explicitly selected: one current-memory or saved gaze-check report, with its own date, policy, simulation flag and state |

Nothing is attached automatically or sent over the network. Export uses an adjacent temporary file and atomic replacement of the exact Windows Save As destination, without appending an extension after overwrite confirmation. Failures preserve an existing destination. Trace coordinates/geometry can reveal activity; composed/spoken text, key labels, credentials, the speech library, audio, screenshots and device serial numbers are excluded. `GAZE_KEYS` and `recording_context` in `diagnostic_recording.py` own recording-context selection; `SETTING_KEYS` and `ENVIRONMENT_KEYS` in `tracking/gaze_check_report.py` own report context. Extend those explicit allowlists rather than serializing whole settings or device objects.

### Build identity

`build_info.py` provides one cached build identity to normal logs, recordings and gaze-check reports. Source startup resolves the Git revision and dirty state before UI work; missing Git information stays unknown. Package preparation embeds `BUILD_INFO.json` beside `VERSION`, with the full source revision and a separate dirty flag. Frozen runtime reads that file without invoking Git; the package smoke check rejects a missing/invalid revision. A dirty build is explicitly different from an exact clean revision. The runtime log-root override never changes the source used for build identity.

## Diagnostic log analysis

The [logging contract](#diagnostic-logging) owns schema, clocks, queue, privacy and session limits. The [user guide](USER_GUIDE.md#diagnostic-log-collection) owns explicit recording, ZIP export and the older launch-time trace. For source launches, set the same `POGLED_ASSIST_GAZE_DIAGNOSTICS=trace` variable before `dev.ps1 run`; that trace requires ordinary logging, unlike explicit recording.

An offline reader imports neither Qt nor a Tobii backend:

```powershell
.\.venv\Scripts\python.exe -m pogled_assist.log_reader .\logs\diagnostics\<session-id>.jsonl
```

It counts provider rejection reasons from summaries and selection-end reasons from events. It reports process-cumulative writer health separately from a manual recording's footer health and end reason; do not sum cumulative loss counts repeatedly. The [recording contract](#short-diagnostic-recordings-and-support-packages) defines when a recording is complete. The same command accepts a recording's `snimak.jsonl`, including one extracted from a support ZIP. Basic event counts can be lower than actual transitions; check suppressed counters in the summaries. Missing start/end, malformed or partial last lines, dropped records and size limits constrain the conclusion. Read the requested time range's raw events when explaining a specific attempt. Compare event timestamps with video time; file rotation names are not session start timestamps. Do not infer tracking accuracy without a known intended target.

For a reported selection failure:

1. Establish the app version, `build_revision`, `build_dirty`, backend, policy, timing settings and simulation flag. Old logs cannot validate a newer implementation; a dirty revision does not identify an exact clean build. Missing metadata stays unknown.
2. Check `complete`, `lifecycle_complete`, parse warnings, `session_end_reason` and the applicable health counters before interpreting event counts. A closing record proves neither loss-free data nor successful intended selection.
3. Find the time range and intended target. Follow native eye receipt, provider rejection/delivery, applied application gate and selection events in order. Application eligibility is distinct from actual both-eye validity and from fresh gaze; an eligible-eye event alone cannot confirm a selection. Older events without explicit application eligibility retain the reader's both-eye interpretation.
4. Separate observed evidence from explanations needing a new recording or target-machine check. A change of target may be intentional; it is not proof of jitter. Aggregate gaze-check reports provide measurements for their own dated attempts, not a replay of the recorded interaction. An optionally attached report may be from another time or policy.

Support ZIP hashes describe the payload files listed in the manifest. Check them when transferring a package, and keep its recording identity separate from an optional report identity. Never attach whole local data folders or raw user logs to the repository as test fixtures; use synthetic inputs.

For changes to diagnostics, test the same provider/controller/Qt input sequence with logging off, basic, trace and a blocked writer. Include the existing gaze check and tracking-feedback suites: their snapshots, coverage, interruption counts and UI state must agree. Test actual blocked file/console sinks, overflow, runtime rotation, missing streams, exceptions and bounded shutdown. Keep stdout IPC atomic and independent of droppable logging. Use the existing pytest fakes and repository verification commands; Mac-only checks are not Windows or Tobii hardware verification. Measure producer/Qt latency, CPU, memory and output size on the same reference Windows device before release. A background thread still shares Python scheduling and the GIL, so asynchronous output alone does not establish zero overhead.

The manual recording lifecycle and support ZIP use `tests/app/test_diagnostic_recording.py` and `tests/ui/test_diagnostics_e2e.py`; existing gaze-equivalence scenarios also run with manual recording. Durations and file caps use fake clocks/small limits rather than waiting minutes or creating 32 MiB test files. History reads only bounded metadata and lifecycle edges. Full JSONL analysis and compression run during export on a file worker. These checks protect behavior and bounded work; reference-device overhead remains a separate manual measurement.
