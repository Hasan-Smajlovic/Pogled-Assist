# Architecture

Pogled Assist is one Windows desktop process built with Python and PySide6. It turns Tobii gaze samples into pointer movement, dwell actions, speech, and on-screen controls while keeping all settings and phrases on the local machine.

- [Runtime flow and components](#runtime-flow)
- [Gaze and input](#gaze-and-input-path)
- [Eye-tracking policy](#eye-tracking-policy) and [edge selection hold](#edge-selection-hold)
- [Gaze-check measurements](#gaze-check-measurements) and [saved reports](#gaze-check-reports)
- [UI and service ownership](#ui-and-service-ownership)
- [Persistent data and diagnostic logging](#persistent-data-and-logs)
- [Short recordings and support packages](#short-diagnostic-recordings-and-support-packages)
- [Packaging and installation](#packaging-and-installation)
- [Compatibility contract](#compatibility-contract)

## Runtime flow

```text
run_gaze_mouse.py
  -> pogled_assist.main
  -> QApplication
  -> HotbarWindow
       -> TobiiGazeProvider
            -> tobii-research
            -> direct Tobii Stream Engine fallback
            -> 32-bit Stream Engine bridge fallback
       -> GazeMouseController
            -> WindowsInputController
       -> SpeechService
       -> SuggestionService
            -> bundled Bosnian model
            -> local personal learning
       -> Settings, Speech, Keyboard, and Controller windows
       -> gaze bubble, interaction overlay, precision zoom, and Quick actions
       -> WindowsAppBar
```

`pogled_assist/main.py` acquires a per-user Qt lock before logging or services; a second interactive launch exits without activating any window. Qt recovers locks left by terminated processes. Package and installation diagnostics bypass this interactive lock. Startup failure and normal exit release it. The entry point then enables Windows DPI awareness, configures logging, creates the Qt application, and shows `HotbarWindow`. The hotbar is the composition root: it creates the runtime services, connects their Qt signals, starts them after the window appears, and stops child windows, Tobii backends, speech, overlays, and the AppBar reservation during shutdown.

The Python package is named `pogled_assist`. The existing `run_gaze_mouse.py` and `start_gaze_mouse.ps1` entry points keep their names so source installations and shortcuts continue to launch after an update.

## Component map

| Area | Main files | Responsibility |
| --- | --- | --- |
| Entry points | `run_gaze_mouse.py`, `pogled_assist/main.py` | Source and packaged startup, Qt setup, package smoke test |
| Runtime composition | `pogled_assist/toolbar.py` | Hotbar UI, service wiring, child-window ownership, status, cleanup |
| Gaze acquisition | `pogled_assist/tracking/` | Tracker discovery, development simulation, backend fallback, sample bounds, retry, x86 bridge, calibration |
| Gaze interaction | `pogled_assist/interaction/` | Logical/physical coordinate mapping in `screen_mapping.py`, UI target lookup through `GazeTarget`, smoothing, shared selection timing, click and Quick action requests |
| Gaze-check reports | `pogled_assist/tracking/gaze_check_report.py`, `pogled_assist/tracking/gaze_check_store.py`, `pogled_assist/ui/gaze_check_reports.py` | Aggregate report schema, atomic storage/export, application-lifetime memory and file-worker results |
| Diagnostic recording | `pogled_assist/diagnostics.py`, `pogled_assist/log_transport.py`, `pogled_assist/diagnostic_recording.py`, `pogled_assist/ui/diagnostic_recordings.py` | Observations, bounded writer, recording storage/retention/export and Qt-facing lifecycle |
| Windows integration | `pogled_assist/windows/` | Physical input, work-area reservation, keyboard, startup, external foreground/cursor tracking, focus, z-order |
| User surfaces | `pogled_assist/ui/` | Settings, speech, keyboard, controller, radial menu, precision zoom, gaze feedback |
| Speech | `pogled_assist/speech/` | eSpeak NG, Edge and ElevenLabs playback, saved-entry audio, saved categories, answers and phrases, and the repeating local alarm |
| Suggestions | `pogled_assist/suggestions/`, `pogled_assist/assets/bosnian-*-model.*` | Offline Bosnian tokenisation, general and reviewed Islamic vocabulary layers, completion and next-word ranking, input-scoped undo, and reversible personal learning |
| Persistent data | `pogled_assist/settings_store.py`, `pogled_assist/suggestions/learning.py`, `pogled_assist/speech/speech_library.py`, `pogled_assist/logging_setup.py` | Settings, phrase and personal-learning data, logs, safe defaults, and atomic writes |
| Distribution | `setup_windows.ps1`, `start_gaze_mouse.ps1`, `update_windows.ps1`, `packaging/`, `scripts/` | Source setup, launch, verified release update, package build, install, release |
| Verification | `dev.ps1`, `tests/`, `.github/workflows/` | Local checks, simulated hardware inputs, UI flows, CI, release checks |

## Gaze and input path

`TobiiGazeProvider` tries the available backends in this order:

1. `tobii-research`
2. direct Tobii Stream Engine
3. Tobii Stream Engine through a 32-bit Python bridge

If none starts, the provider reports a retry state and scans again every three seconds. Raw samples may arrive faster than the UI can safely process them, so the provider keeps the newest sample and emits at a bounded interval. This keeps the Qt event loop responsive instead of replaying stale gaze positions.

Stream Engine `position_xy` values are normalized display coordinates in both the direct backend and the x86 bridge. Finite off-screen values are clamped to the same screen edge; their magnitude never changes their units to pixels. The bridge serializes each JSON message, newline, and flush under one lock. Unexpected end-of-output or a bridge error invalidates both eyes and triggers the provider's normal retry path. Stream Engine eye-status delivery older than 500 ms clears pending gaze and dwell; after three seconds without eye-status samples the provider stops the x86 bridge and schedules a fresh connection. Direct native streaming stays paused until fresh data arrives: a stuck DLL thread cannot be forcibly stopped safely and must not acquire a second device subscription. Callbacks from an earlier Stream Engine or Pro SDK connection are ignored after stop, failed startup, or replacement. Bridge failure is terminal for that bridge instance, even if more buffered messages follow the failure. Invalid-eye samples still count as live delivery, so absence or a blink does not trigger a reconnect. Diagnostics record delivery age and connection state, never typed text.

Before delivering gaze after a gap of at least 500 ms, the provider cancels pending interactions through the eye gate and restores current valid status. This also covers a stalled Qt event loop or fresh eyes arriving before the watchdog runs. The first new gaze starts a full dwell; completed selections retain their leave-before-repeat lock.

Eye-status notifications are delivered on the Qt thread before the next gaze sample. A backlog retains an intervening invalid-eye state even if both eyes are valid again; coalescing must never hide a blink or let queued validity from before stop reopen the gate. Pending gaze also carries its local receive time: fresh eye status cannot make a gaze sample older than 500 ms usable again. The watchdog publishes recovery status on Qt only after checking the current connection, so a delayed worker notification cannot overwrite a newer failure.

Providers publish a typed `TrackingStatus` lifecycle separately from diagnostic text. The hotbar status combines that lifecycle with eye validity and the local receive time of the last delivered gaze sample. Its own display timer expires readiness after 500 ms without gaze; it does not change the input gate, dwell, backend subscriptions, or reconnect policy. See the [status guide](USER_GUIDE.md#before-starting) for the visible states.

`TrackingFeedback` observes the same delivered lifecycle, eye and gaze signals for passive Speech notifications. `TrackingFeedbackState` owns presentation timing separately from input safety. Only the message header and active letter or confirmation header display a notice; no gaze target or modal action is added. The [notification guide](USER_GUIDE.md#tracking-notifications-in-speech) owns the setting, timing and suppressed contexts. Neither notification timing nor turning the setting off changes pointer movement, dwell cancellation or retries.

Each backend reports actual left and right eye validity. Direct desktop pointer movement, direct clicks, Quick actions and precision zoom require both eyes. Losing either eye closes those overlays and leaves the pointer at its last position. Application controls follow the [eye-tracking policy](#eye-tracking-policy). The gaze bubble follows eligible application gaze and expires after 500 ms without a delivered point. Eye validity alone cannot restore a cached marker.

### Eye-tracking policy

`interaction/eye_tracking_policy.py` owns eligibility, the local monotonic interruption deadline and gaze freshness notifications. `GazeSettings.eye_tracking_policy` accepts `both` (default), `hold`, or experimental `any`; missing or unrecognized values load as `both`. `eye_tracking_hold_ms` sets the interruption duration. The [Settings guide](USER_GUIDE.md#settings) owns timing defaults/ranges and the [visible policy choices](USER_GUIDE.md#eye-tracking-policy).

| Boundary | Rule |
| --- | --- |
| Application controls | `both` requires two valid eyes; `hold` can freeze an existing attempt during single-eye loss; `any` allows selection with one valid eye. Every selection needs fresh valid gaze. |
| Direct desktop input | Pointer movement, direct clicks, Quick actions and precision zoom always require both eyes, regardless of application policy. |
| Controller click buttons | Selecting the button follows the application policy. Its Windows click uses the existing cached external target. |
| Gaze check | Precision, free view and button trials follow copied policy/settings. Eye indicators and both-eye availability report actual data. |
| Status and notifications | Observe eligibility and freshness; their display delays never extend input eligibility. |

#### Provider delivery and clocks

The provider retains SDK-valid finite coordinates for one tracked eye only in `any`. Stream Engine still supplies its [combined, interaction-filtered point](https://developer.tobii.com/how-to-get-started-with-developing-software-for-the-eye-tracker-with-the-pdk/); separate per-eye screen points are a different, advanced stream. Normalized eye origins are never converted to screen gaze. Pro SDK averages available valid screen points and discards [invalid gaze data](https://developer.tobiipro.com/commonconcepts/validitycodes.html). Tobii's [profile eye choice](https://help.tobii.com/hc/en-us/articles/210247825-Calibration-options) is independent of this application's policy; the policy does not alter the profile or calibration. Usable one-eye gaze accuracy on the installed Tobii 4C remains a hardware check. Missing gaze never selects a control and never changes the chosen mode automatically.

Qt receives timestamped eye transitions before gaze. A bounded queue retains both-invalid states and sole-eye switches; overflow forces cancellation before delivering the final state. Stream generations discard old callbacks and queued transitions. The interruption deadline starts at native receipt, so a busy Qt loop cannot extend it. Invalid gaze clears pending coordinates and breaks selection continuity, except during an existing unexpired hold. Its first native receipt time is retained: an invalid point before the eye loss cancels earlier credit even if Qt processes the later eye loss first. A provider delivery gap of 500 ms cancels before the first resumed point.

The provider's `gaze_received_at` carries the delivered point's local monotonic receipt time alongside its existing signal. The hotbar forwards that age to the controller, Settings and tracking feedback; Qt dispatch never renews freshness. SDK timestamps remain separate and are not compared with the local clock. The provider checks gaps in both native receipt and Qt delivery, so a delayed point cannot bridge a native gap of 500 ms before the expiry timer runs. The mouse simulator uses its sample time at the same boundary.

#### Selection interruption and recovery

The controller, Settings and caregiver trial each use the shared `EyeTrackingGate` and existing `GazeSelectionTimer`. The gate decides whether a sample is eligible and when to freeze or cancel; the selection timer owns target identity, credited time and repeat blocking.

- In `hold`, loss of one eye freezes the current target without accumulating time. Repeated reports cannot extend the deadline; a Qt timer expires it without another gaze sample.
- Recovery requires both eyes and a fresh point inside the same target, with unchanged context and geometry. The first returning sample restores credited progress but cannot activate.
- In `any`, a change from one sole eye to the other cancels progress unless a fresh both-eye point established continuity between them.
- Both-invalid state, connection loss, stale gaze, suspended input, and policy or hold-duration changes cancel pending progress. Completed selections keep their leave-before-repeat lock.

Application gaze and desktop-overlay gaze use separate signals. Controller buttons intentionally retain their existing cached external click target, while selecting those buttons follows the application policy. Coordinate mapping remains in Qt logical and Windows physical coordinates at their existing boundaries. A held interaction keeps its arc with a pause mark and no pulsing; disabling progress hides that feedback without changing eligibility.

The source-only mouse gaze simulator bypasses discovery and feeds primary-screen cursor coordinates into the same application path. It follows the selected eye policy, including one-eye coordinates in `any`; development shortcuts change either eye, pause gaze, disconnect, or reset. Gaze gaps cancel before resumed coordinates. Automatic pointer movement is disabled so the cursor remains the input. The hotbar always labels synthetic input as simulation; Tobii notifications remain suppressed. The [UI development guide](UI_DEVELOPMENT.md#mouse-gaze-simulation) owns its controls and limits.

### Coordinates and pointer movement

The controller keeps two coordinate spaces separate:

- Qt logical coordinates are used for hit testing buttons and windows.
- Windows physical coordinates are used for pointer movement and real clicks.

Smoothing affects visible pointer movement. Click targeting uses the current gaze target so smoothing does not move the requested click away from the selected point.

### Edge selection hold

An edge hold handles a fresh gaze point just outside a target; an eye-tracking hold handles loss of one eye under `hold`. These are separate conditions and deadlines. Neither permits an activation while held, and a tracking hold cannot extend an existing edge deadline.

The controller opts Speech, hotbar, and standalone Keyboard controls into edge retention using their current visible, enabled button rectangles in Qt logical coordinates. Settings controls, Controller controls and direct desktop actions do not opt in. The caregiver button trial copies the setting. `GazeSettings.edge_hold_ms` controls the duration; the [user guide](USER_GUIDE.md#selection-stability-near-edges) owns defaults, limits and adjustment. The margin remains at most 24 logical pixels and a quarter of each target dimension. Hotbar hit rectangles extend vertically to the top screen edge, keeping button widths and neutral horizontal gaps.

| Gaze movement | Selection result |
| --- | --- |
| Just outside A, within its margin and deadline | Keep A's pause/progress frozen; a nearby B earns no time. |
| Back inside unchanged A before expiry | Resume A, excluding outside time and the interval up to the first returning sample. |
| First eligible sample at or after expiry | Discard A's retained progress. The sampled target starts its full pause and dwell, including if it is A again. |
| Farther outside A's margin | Switch immediately using the normal selection rules. |

Zero duration disables edge retention. Changing the duration cancels unfinished application selection and preserves its repeat lock. Context or target-geometry changes cancel progress. A completed target stays blocked through a brief edge departure; an expired departure can release that lock, including when the next sample returns to A. Speech also blocks a suggestion replaced beneath gaze; that rejection must not count as leaving its button. See [Speech selection behavior](USER_GUIDE.md#speech) for the user flow.

### Gaze-check measurements

The provider collects ephemeral `CheckTelemetry` only while `GazeCheckWindow` is open and clears it on close or stream invalidation. Coalesced snapshots reach the Qt thread after pending eye-loss signals. Raw normalized diagnostic gaze is kept separate from the clamped control stream. Native Stream Engine reuses its eye-position subscription; the x86 bridge validates the optional position and invalid-gaze messages. Pro SDK uses valid normalized track-box origins, never millimetre coordinates. Position capability, freshness and connection state are separate; fresh positions can remain visible without valid gaze.

`tracking/gaze_check.py` owns the measurement rules:

- Eye, position and gaze samples expire independently after 500 ms.
- Eye availability is time-weighted over at most ten seconds. After three seconds, at least 85% availability with no loss longer than 500 ms is shown as mostly continuous tracking.
- Position and depth checks use the reported [0, 1] bounds, without a centimetre conversion or invented central zone. Movement guidance uses only fresh positions and takes priority over missing-gaze guidance when outside the box. Recognizing an eye from its position never enables input.
- Each fixation target has one second to settle and two seconds to measure. A result requires 12 distinct fresh samples and 60% temporal coverage. Consecutive samples contribute at most 100 ms; an invalid or stale snapshot breaks the interval. An interruption counter preserves losses coalesced before Qt delivery. Earlier valid intervals remain counted across a blink.
- A near result requires 90% of samples inside the displayed 36 logical-pixel radius. Median error and 90th-percentile spread are descriptive heuristics, not Tobii-certified or clinical scores. The result map retains the normalized median centre; clipping off-screen centres affects painting only.
- The eye check (`EyeTrackingRun`) measures a fixed 30-second run. `CheckTelemetry` integrates cumulative valid time separately for the left eye, the right eye and both eyes; each eye report counts until the next report or for at most 500 ms, so stale or missing data counts as not tracked. The run subtracts the cumulative values at its start from those at its end, so percentages are time-weighted rather than sample counts. Time before the first snapshot, after the last one or across a telemetry restart is not bridged. A one-eye result is still reported, and no eye data reports 0% for both.
- Left/right gaze agreement uses the per-eye display-area points that the Pro SDK reports. The provider records them for the check before applying the eye gate; input still uses the average of both valid eyes and remains gated by the selected policy. Pairs count only while both per-eye points are valid and finite. Agreement requires at least 12 pairs and reports the share within the 36 logical-pixel precision radius and the median distance. Stream Engine delivers one combined gaze point, so agreement is reported as unsupported there; eye positions or gaze origins are never presented as agreement. Advice warns when one eye is below 85% and at least 20 percentage points below the other, when both are below 85%, or when fewer than 80% of pairs agree. Results stay ephemeral; a priority `gaze_check_eye_tracking` diagnostic event records the aggregate numbers only.
- Each button trial measures coverage from its ready time until selection or timeout. Only distinct fresh gaze samples allowed by the selected policy count, including gaze outside the buttons. Consecutive samples contribute at most 100 ms; known losses and stale gaps break the interval. A timed-out target needs at least 60% coverage before advice can attribute failure to fixation or calibration. Isolated samples never count as sustained tracking. This threshold only selects advice; it does not change dwell, the eye gate or trial success.

`gaze_check_window.py` owns the flow; `gaze_check_views.py` owns painting and geometry. Result advice prioritizes missing precision data, measured misses, then trial coverage, interrupted selections, wrong selections and timeout. Successful trials with a brief loss still suggest actual use if precision passed. The local trial reuses `GazeSelectionTimer`, the same spatial edge margin and copied pause/dwell and edge-hold settings, without Windows input. Its three groups have 136 × 64, 96 × 88 and 180 × 72 logical-pixel controls, each with two neighbors. The edge margin is bounded by a quarter of each dimension. Wrong selections retain the leave-before-repeat lock across tracking loss. Departures include direct jumps to a neighbor. Precision, trial and free view follow the selected eye policy; the labeled mode stays fixed with the check's copied settings and results. Both-eye continuity remains an actual metric. The free check paints nine targets and fresh eligible gaze without timing, scoring, smoothing or input.

The hotbar owns diagnostic signal connections, Settings return, shutdown and Tobii settings handoff. Entry and exit clear pending actions; normal controller input is suspended while the check is open without changing saved settings. Suspension also applies while minimized and is checked again after synchronous gaze slots, so the triggering sample cannot move the pointer.

`launch_tobii_settings` tries discovered UI candidates in rank order, excluding maintenance, Guest, calibration and test targets. A rejected candidate does not block later candidates; exhaustion returns the manual tray-icon route. Existing Guest calibration entry points retain their behavior and also exclude maintenance targets. The [user guide](USER_GUIDE.md#gaze-check) owns calibration instructions and the caregiver flow.

Coordinates follow Tobii's [Stream Engine API](https://developer.tobii.com/product-integration/) and [track-box description](https://developer.tobii.com/wp-content/uploads/2016/03/Developers-Guide-DotNet.pdf). Normalized-position availability and movement guidance still require validation on the installed 4C runtime; synthetic tests cannot establish hardware accuracy.

### Gaze-check reports

`tracking/gaze_check_report.py` owns version 1 aggregate reports, used by the UI, local JSON storage and ZIP export. They are separate from detailed [diagnostic recordings](#short-diagnostic-recordings-and-support-packages).

- Precision finalizes once, immediately on completion or interruption; rendering never emits another fixation result. Completed targets remain, with explicit insufficient-data and unmeasured states.
- Each optional trial has its own identity, timestamps, state, interruption reason, environment snapshot and per-group coverage, duration, wrong/cancelled selections and departures. Repeated trials update the same precision report without remeasuring precision.
- Coverage describes eligible gaze during the measured interval, not the positioning screen's rolling both-eye indicator. Distances and target sizes use Qt logical pixels; gaze/target centres are normalized, never physical Windows input coordinates.
- Context includes the copied eye policy, hold/pause/dwell/edge/cooldown/overlay settings and available version, backend, SDK, device model, firmware, primary-screen geometry, pixel ratio and logical DPI. Missing metadata is null; simulator results carry an explicit flag. No serial numbers, credentials, typed text, speech data or raw sample stream are collected.

`ui/gaze_check_reports.py` owns application-lifetime memory and one serial daemon file worker, separate from diagnostic transport and its trace limits. Immutable copies go to that worker and outcomes return to Qt. Version counters prevent an older save acknowledgement from marking a newer revision saved. Auto-save follows the check's copied logging setting; manual export and history reads work when logging is off. Failed writes retain the in-memory result and expose retry.

`tracking/gaze_check_store.py` owns the file operations:

- Save UTF-8 JSON through a flushed temporary file and atomic replacement, then prune supported reports to the newest 100 and 10 MiB. Unknown, corrupt, unrelated and symlink entries are not deletion candidates.
- Limit reads to 10 MiB per report and validate version, structure and key-specific allowlisted context. Unreadable reports remain visible but cannot be opened/exported. Repeated trials have no fixed count limit; a report over the automatic storage budget stays in memory and can still be manually exported.
- Export JSON and Bosnian TXT from the same snapshot in a separate atomic ZIP, without modifying auto-save status. Use exactly the caregiver-selected path confirmed by the native dialog; never append an extension after its overwrite check.

Shutdown drains the worker for at most two seconds; a blocked disk, crash or forced termination can leave a pending result unsaved. Temporary files are ignored on history reads. Normal gaze input remains suspended across history, read-only report views, minimization and the native save dialog.

## UI and service ownership

`HotbarWindow` owns all long-lived services and top-level UI surfaces. It opens the full-screen Speech and Settings windows, the right-side Keyboard and Controller panels, the radial Quick actions menu, and precision zoom. Keyboard and Controller panels are mutually exclusive. Feedback windows remain topmost without taking focus from the application the user is controlling.

Settings changes update the live mouse and speech services and attempt to save immediately. The hotbar tracks failed saves across surfaces; retries use the latest live values. `SuggestionService` is also owned by the hotbar and shared by Speech and Settings. It loads and queries the immutable base model away from the Qt event loop, coalesces pending requests, and writes personal counts through a separate worker. The prediction worker builds a personal prefix and context index only when the learning revision changes; ordinary typing reuses it. Storage recovery also advances that revision, so merged disk data cannot leave a stale index. Context-free candidates use the combined base and personal unigram ranking, while both sources supply their relevant contextual candidates. The Speech input validates the request owner, revision, text, caret, and selection before displaying a result. Closing the hotbar closes every child surface, flushes suggestion learning, stops speech and gaze workers, and unregisters the AppBar so Windows restores the full work area.

`SpeechPredictions` owns the Speech input's request identity, revision, displayed text, and the guard for a suggestion replaced beneath gaze. It is a Qt object owned by that input, so prediction delivery remains on the UI thread. `SpeechDialogs` owns the Speech modal windows, backdrop, and active actions; the Speech window retains the conversation and library editing behavior.

`ForegroundTracker` owns the polling timer and the last external window and physical cursor position. It ignores foreground windows belonging to this process and cursor samples over application controls. The hotbar passes these targets to Keyboard and Controller and stops polling during shutdown.

Speech playback logs identify whether the request came from gaze, button activation, or Return in the message field, without recording the message. Process startup and UI acknowledgement do not confirm audible playback. Speech launch, exit monitoring, and cleanup run on a serialized worker boundary. Cancelling a request invalidates queued notifications and closes its process tree before a replacement starts. On Windows a suspended child is assigned to a private kill-on-close job before execution. Engine output is discarded because it can include typed text; diagnostics record the engine and exit code. No UI thread waits for speech completion or stderr EOF.

For Efendija, `speech/eleven_account.py` owns the saved credential and read-only catalog checks. Voice choices use `/v2/voices?voice_type=saved` to match My Voices, including voices saved from the library, without adding the default catalog. It also owns a separate bounded, read-only subscription refresh. Catalog delivery does not wait on the optional subscription endpoint. Missing optional User: Read access never changes catalog availability. Qt queues discard balance responses after key replacement/removal or cancellation. Balance refresh runs on opening ElevenLabs settings and after completed or failed Efendija requests. Passive balance refresh never resets a provider cooldown; only the explicit connection check can permit an early recovery attempt after an improved balance. Settings pages own their controls and value rendering; `ui/settings_window.py` owns shared settings, signals, gaze selection and page navigation. Speech library actions and playback controls are separate responsibilities of the Speech window.

Persisted integer tuning values are coerced through `settings_limits.py`. The [user guide](USER_GUIDE.md#efendija-voice-and-elevenlabs-setup) owns the defaults, preparation limits, fallback order and recovery behavior. `speech/elevenlabs.py` builds authenticated requests and catalog choices. `speech/eleven_transport.py` bounds HTTPS response sizes, deadlines and network workers. It closes active sockets on cancellation or abandonment and checks cancellation after connection setup, before sending authenticated requests. An occupied worker slot is distinct from a provider timeout and never starts a cooldown. Billable POSTs are never automatically replayed; an already sent request may still consume credits after cancellation. `speech/voice_router.py` prepares whole audio before playback. Its Prirodni fallback uses in-process `edge_tts` and the same Qt playback boundary; `EDGE_PLAYBACK_EXE` affects explicitly selected Prirodni/Arabic process playback, not this fallback. Subscription metadata is optional and cannot block a later user-requested recovery attempt. Only successful Efendija playback announces recovery; neither a catalog check nor a cached clip can. The explicit voice test bypasses cache and fallback.

`speech/audio_playback.py` owns QMediaPlayer, audio output and memory buffers on Qt's thread. Workers wait on a result without blocking Qt; request identities reject stale audio and notifications. Playback that has started never replays through another provider after a failure. Completion settles the worker result before native cleanup. The player and its QBuffer source are destroyed together with Qt's deferred deletion; clearing the active source synchronously can deadlock the Windows FFmpeg backend. Old-player callbacks cannot update a replacement's state. `speech/audio_cache.py` retains downloaded audio for whole saved phrases or answers, including after stopped playback or output failures, unless the decoder rejects it. Text, voice, model, generation parameters and text-preparation version determine clip identity. Generation tickets reject late writes after clear, entry changes, disabled library access or configuration changes.

`SpeechSettings.keyboard_script` is a shared, persisted Latin/Arabic selection. The hotbar propagates Settings and keyboard switch signals to all three input surfaces. `ui/keyboard_grid.py` renders shared group, key, and page cells for Keyboard and Controller; each window owns its controls, spacing, state, and action prefixes. `keyboard_layouts.py` owns the script-specific Unicode keys and display-only combining-mark labels. Qt shapes and displays Arabic; Windows input receives the original characters. Arabic bypasses Bosnian suggestions and new learning, and selects the existing Edge playback boundary with the Hamed voice. The Bosnian voice preference and existing model/profile remain intact. See the [Arabic keyboard guide](USER_GUIDE.md#arabic-keyboard) for controls and limitations.

`windows/startup_tasks.py` owns startup queries and writes outside Qt, with one active request and one replaceable pending request per Settings window. The worker owns writes after the window is deleted and drains its latest choice under the shared startup lock before a reopened window can query the state. Closed windows cancel pending read-only queries and ignore late UI results. An unresolved startup state stays distinct from disabled, so a launcher change can first query the task and update it only when enabled.

Numeric setting bounds live in `settings_limits.py` and are shared by storage validation and Settings controls. Selection-pause bounds remain in `interaction/gaze_selection.py`. Settings dataclasses own defaults; existing persisted timing values are preserved. The [Settings guide](USER_GUIDE.md#settings) lists current defaults and ranges.

## Persistent data and logs

The runtime root is the executable directory for a packaged build and the repository root during source development. `POGLED_ASSIST_LOG_ROOT` can override it for controlled launch and test scenarios.

```text
data/app_settings.json   gaze, interaction, startup, logging, and speech settings
data/speech_library.json saved categories, answers, phrases, and phrase use counts
data/speech_phrases.json rollback-compatible standalone phrases for older releases
data/speech_learning.json versioned local word and short-context counts
data/version-history/*/ immutable pre-install copies of saved data
logs/latest.txt          current application log when logging is enabled
logs/diagnostics/*.jsonl bounded structured diagnostic sessions
logs/gaze-check/gaze-check-<uuid>.json versioned aggregate gaze-check reports
logs/diagnostic-recordings/<id>/recording.json versioned short-recording lifecycle and context
logs/diagnostic-recordings/<id>/snimak.jsonl bounded detailed recording
```

Missing or malformed settings fall back safely to defaults, with supported values clamped to the same ranges as the Settings UI. Installation, update, and rollback work must preserve `data/` and `logs/`. The transactional installer verifies the copied data and logs byte for byte before swapping directories, and keeps a dated data snapshot under `data/version-history`. Snapshots exclude earlier snapshots to avoid recursive growth. Settings loading fills fields omitted by older writers from these snapshots; current fields and supported edits from the older version take precedence. Settings saves retain unknown fields and reject unreadable or unsupported formats. Snapshots contain personal saved data and belong with the user's local data, never in source control or diagnostic uploads.

ElevenLabs credentials use the current user's Windows Credential Manager target `PogledAssist/ElevenLabs` through `windows/credentials.py`. The API key is absent from settings JSON, logs, installer payloads and version-history snapshots. Settings persist voice/model IDs and Stability/Similarity, never the API key. The optional audio cache is `%LOCALAPPDATA%\PogledAssist\speech-audio`; files have hashed names and checksums, without a plaintext message index. Each filename combines separate text and audio-identity hashes so entry deletion removes all configuration variants. The clips themselves contain the spoken saved text and are private user data. They remain outside installation snapshots. Free-form messages are held in memory for playback and are not cached. The [user guide](USER_GUIDE.md#efendija-voice-and-elevenlabs-setup) owns setup, permissions, service text transfer, fallback and deletion controls.

Unreadable speech-library files block all library writes, including rollback synchronization and phrase use counts. Only a successful reload clears this guard; fallback categories must never overwrite the original after a read error.

The bundled suggestion model and writable learning profile have independent version 1 schemas. A base-model release can therefore be replaced without rewriting personal counts. An unreadable personal profile is reported and kept unchanged until an explicit retry can merge new in-memory learning with readable disk data.

### Diagnostic logging

`logging_setup.py` owns the existing logging switch and standard-stream/Qt hooks. `log_transport.py` owns one persistent daemon writer in the main process. Both the text file and console run behind its bounded queue. Producers copy bounded primitive fields and never wait for output, queue space or a shared thread pool. The writer releases the queue mutex before formatting, archiving, writing and flushing. Overflow drops log records, with cumulative process counts and the time span of loss in `logging_health`; it never drops input packets. The x86 bridge uses a separate bounded stderr writer, while its stdout input protocol retains its existing lock, JSON, newline and flush contract.

The queue admits at most 1,024 records of approximately 8 KiB including copied object overhead; 64 slots are reserved for lifecycle, error and summary records. Priority records also drop when full. Output flushes about every 250 ms. Shutdown waits at most two seconds for the worker; file objects are owned only by that daemon, so Python's handler shutdown cannot synchronously close a blocked sink. The OS may finish an already-started write after logging is disabled. Pending ordinary records are discarded on disable. Queued stream, selection and marker summaries finish in their original session before its end record, including partial intervals collected at disable or rotation. These retained records share the same queue capacity; overflow remains explicit in logging health. A new enable creates a new session and archives the previous text log on the same writer. A crash or blocked writer can leave an incomplete last batch. Existing archives are never automatically deleted.

`diagnostics.py` collects separate native input, provider delivery, application gate and selection observations. Native valid-time accounting expires after 500 ms without another eye sample; application gate time records the gate's actual state at Qt delivery, separately from native receipt. Validity is a reported SDK measurement, not physical eye closure. Provider replacement is intentional sampling for Qt, not a disconnect. Basic summaries run about once per second, with their actual interval duration. Basic state events allow four records per event type per second and report suppressed counts. Trace records the fuller sequence subject to queue and file limits.

JSONL schema version 1 uses `event`, `session_id`, `process_instance`, `event_seq`, `wall_time` with timezone, `monotonic_s` and an explicit `data` payload. Event time is captured before queueing. `data` supplies stream generations, context and attempt IDs where applicable. Sequence numbers also include text records, so a gap in JSONL alone is not proof of a dropped event. SDK timestamps keep their own source and microsecond unit; they are not subtracted from main-process time. The runtime record reports source/frozen mode and known versions; absent build revision is explicitly unknown. Structured sessions are capped at 64 MiB.

Basic events include stream/selection summaries, gate receipt/application, delivery gaps, settings, screen mapping, dialog lifecycle, UI action origin, tracking notices and input suspension during the caregiver check. Trace adds native/provider samples, actual target bounds, selection timing, normalized track-box positions and already-computed fixation/trial results. Logging never activates or recalculates gaze-check telemetry. Native eye measurements remain actual SDK values; application eye eligibility follows the selected policy. Each `eye_gate_applied` event records that policy and its `application_gate_open` eye eligibility, independently of gaze freshness or a held selection. Offline analysis uses this explicit eligibility; older events without it retain the both-eye interpretation. Settings events include the policy and interruption duration. Generation guards remain in place. The existing invalid-gaze callback cannot distinguish SDK-invalid from nonfinite input, so it is labeled `sdk_invalid_or_nonfinite`. Notice timing stays independent of input cancellation. Settings construction and the Windows startup query are timed separately.

Typed text, suggestions, phrases, key labels and content action IDs are excluded from added events. Such actions receive random IDs local to the current context; safe control names such as `confirm:accept` remain readable. Exception snapshots retain their type and bounded frame locations, without traceback locals or exception text. Trace coordinates and target geometry can still reveal activity; these local recordings are not anonymous. Trace is explicitly enabled, lasts at most ten minutes or 32 MiB of additional records, then returns to basic logging. See [collection instructions](USER_GUIDE.md#diagnostic-log-collection) and [developer analysis](DEVELOPMENT.md#diagnostic-log-analysis).

### Short diagnostic recordings and support packages

| Owner | Responsibility |
| --- | --- |
| `ui/diagnostic_recordings.py` (`DiagnosticRecordings`) | Application-lifetime status, start/stop requests, Qt delivery, history/export queue and the shared indicator |
| `diagnostics.py` and `log_transport.py` | Existing observations and the persistent `LogWriter`; recording admission, event order, deadlines, byte cap and final drain |
| `diagnostic_recording.py` (`RecordingStore`) | Metadata validation, crash recovery, retention, full inspection and atomic support ZIP export |
| `ui/recording_badge.py` | One shared `RecordingIndicator` and passive `RecordingBadge` views; no recording or input decisions |
| `build_info.py` | Cached source identity shared by ordinary logs, recordings and gaze-check reports |

#### Window and indicator ownership

The hotbar owns `DiagnosticRecordings`; closing the recording window keeps recording active. Opening that window suspends normal input until returning. The gaze-check shortcut is unavailable during precision/button measurement. Hiding the check for diagnostics stops its UI timer and telemetry collection without discarding its report; returning restores the check and its existing input suspension.

All badges bind to the same indicator, including windows opened later. The indicator's saved-confirmation timer and accessibility announcement identity are shared; reopening a window must not restart them. Badges reserve space or overlay an existing control, take no focus and pass mouse events through. They never move gaze targets or replace tracking/speech notices. The [collection guide](USER_GUIDE.md#diagnostic-log-collection) owns visible messages and durations; the [design workflow](UI_DEVELOPMENT.md#application-design-reference-workflow) maps their references.

#### Recording admission and completion

Manual recording reuses `diagnostics.py` observations and the persistent `LogWriter` queue. The writer snapshots a recording identity with each event, so normal-log toggles cannot discard recording events or mix segments. Only structured events enter the recording; text logging and console output are excluded. Normal logging retains its current switch and independent session cap. Manual trace can start without ordinary logging, without a restart, and after a normal session reaches 64 MiB. It never changes saved settings, eye eligibility, input decisions, or measurement calculations.

The selected duration is 1, 2, 5 or 10 minutes (default 2); a monotonic deadline, manual stop, shutdown, write failure or the 32 MiB total cap ends admission. One recording remains busy through the writer's confirmed drain/close, including a blocked sink; another cannot start during that interval. Queue pressure and truncated snapshots are counted for this recording rather than copied from process-cumulative normal-log health. A reserved footer stays inside the file cap. Status distinguishes start/record/finish, end reason, lifecycle footer and completeness. Shutdown or a missing footer is incomplete even when some data was saved. No file/console wait or worker join is added to gaze/Qt callbacks. Application logging retains its existing two-second shutdown bound.

The status progresses from `starting` to `recording` to `finishing` while the writer drains. An inactive status or a present closing record alone does not establish completeness. For a `manual_trace` stream, the offline reader requires lifecycle records, no parse warnings or size-limit event, a `manual` or `time` end reason, and valid footer `recording_health` without dropped records, writer errors or bounded snapshots. Missing or invalid recording health leaves it incomplete. Process-cumulative `logging_health` remains separately reported and does not make a clean later recording incomplete. Ordinary log sessions keep their existing process-health checks.

#### History, recovery and retention

`diagnostic_recording.py` owns atomic metadata, history, retention and ZIP export. After successful final metadata storage, the oldest recording folders are removed to retain five and at most 200 MiB; the active recording is excluded. Known unreadable recordings share that budget. Unrelated files, manually exported ZIPs and folders containing additional files are preserved; such external content is outside this managed budget. History reads bounded metadata and lifecycle edges, while full JSONL analysis happens only for inspection/export on a file worker. A separate worker with a four-task queue serializes history and export requests. Pruning and export serialize file access. A force-killed process can leave a partial stream or initial metadata; recovery labels it interrupted and never certifies completeness. Readable partial recordings can be exported with `complete=false`; unsupported or unreadable recordings remain visible but cannot be exported.

On history load, readable crash remnants are atomically stored as confirmed partial recordings, with unknown duration kept distinct from zero. Recovery then restores retention, including a process killed after final metadata but before pruning. A process-local active-identity registry prevents a queued history job from recovering, exporting or pruning the current recording. That registry uses no file-worker lock on input/Qt producers. A failed recovery leaves older recordings intact and blocks another start until the history check succeeds. Ordinary basic suppression counts stay independent of manual trace; deliberate basic exclusions never become false queue-loss reports. Rotation preserves recording-event order even while ordinary summary footers finish separately.

#### Support ZIP contents and privacy

The local ZIP includes these files; it does not copy a settings or logs folder:

| File | Contents |
| --- | --- |
| `snimak.jsonl` | The chosen detailed recording |
| `kontekst.json` | Allowlisted gaze settings and environment |
| `sazetak.txt` | Readable Bosnian technical summary |
| `manifest.json` | Version 1 manifest, recording lifecycle/completeness and each payload file's byte size and SHA-256; the manifest does not hash itself |
| `provjera/rezultat.json`, `provjera/izvjestaj.txt` | Only when explicitly selected: one current-memory or saved gaze-check report, with its own date, policy, simulation flag and state |

Nothing is attached automatically or sent over the network. Export uses an adjacent temporary file and atomic replacement of the exact Windows Save As destination, without appending an extension after overwrite confirmation. Failures preserve an existing destination. Trace coordinates/geometry can reveal activity; composed/spoken text, key labels, credentials, the speech library, audio, screenshots and device serial numbers are excluded. `GAZE_KEYS` and `recording_context` in `diagnostic_recording.py` own recording-context selection; `SETTING_KEYS` and `ENVIRONMENT_KEYS` in `tracking/gaze_check_report.py` own report context. Extend those explicit allowlists rather than serializing whole settings or device objects.

#### Build identity

`build_info.py` provides one cached build identity to normal logs, recordings and gaze-check reports. Source startup resolves the Git revision and dirty state before UI work; missing Git information stays unknown. Package preparation embeds `BUILD_INFO.json` beside `VERSION`, with the full source revision and a separate dirty flag. Frozen runtime reads that file without invoking Git; the package smoke check rejects a missing/invalid revision. A dirty build is explicitly different from an exact clean revision. The runtime log-root override never changes the source used for build identity.

## Packaging and installation

`dev.ps1` is the developer entry point. The PyInstaller specification under `packaging/windows/` builds the frozen application and includes the icons, bridge files, and versioned Bosnian model needed at runtime. The package smoke test loads that model and computes an offline prediction. The release package contains its own installer and launcher and installs under `C:\PogledAssist`. Release-owned speech executables live under `speech/`, with a private 32-bit Python bridge runtime under `runtime/`, separate from preserved user-provided `.venv` and `tools` components. The frozen smoke test verifies them without audio playback, tracker access, or network access. `--installation-check` opens a separate readiness summary without creating the hotbar or gaze services. See the [included speech tools](WINDOWS_RELEASE.md#included-speech-tools) for packaging, discovery, and installation behavior.

`update_windows.ps1` reads the installed version, resolves the selected stable release (or the latest stable release for a manual update) from `Hasan-Smajlovic/Pogled-Assist`, downloads the exact Windows ZIP and checksum assets, and verifies them before invoking the package installer. The first packaged installer migrates an older source layout. The installer stages and smoke-tests the new package, carries persistent data and external runtime components into it, swaps sibling directories, and retains the previous directory until the installed smoke test passes. A transaction marker lets the next installer restore or finish an update interrupted during the directory swap.

## Design reference

The [HTML design reference](design/speech-keyboard-reference.html) is separate from the runtime and package. The [UI development guide](UI_DEVELOPMENT.md#application-design-reference-workflow) owns its page map and review workflow.

## Compatibility contract

The current `development` behavior is the baseline for a user who already relies on the application. Unless a linked issue explicitly changes a behavior, a review-ready change must preserve:

- launch from the installed `C:\PogledAssist` location and from the development entry point;
- keep the previous installation under `C:\TobiiExec` independent and untouched;
- hotbar placement, AppBar work-area reservation, hide and restore behavior;
- tracker fallback, retry, x86 bridge, the desktop both-eye gate and selected application policy, and responsive gaze flow;
- pointer mapping and left, right, and double-click actions;
- dwell timing, precision zoom, Quick actions, gaze bubble, and action feedback;
- Speech, Keyboard, Controller, Settings, calibration, and quit flows;
- saved settings, saved phrases, logs, and user data during upgrades and rollbacks;
- clean shutdown of tracker subscriptions, bridge workers, speech processes, overlays, child windows, and AppBar state.

Automated tests use fake gaze, Windows input, speech, and external processes to protect these flows without physical hardware. They do not prove real Tobii tracking, calibration, Windows work-area behavior, gaze accuracy, or speech playback. Record those checks separately and never report them as passed unless they ran on the target Windows and Tobii setup.
