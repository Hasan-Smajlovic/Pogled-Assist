# Architecture

Pogled Assist is one Windows desktop process built with Python and PySide6.
It turns Tobii gaze samples into pointer movement, dwell actions, speech, and
on-screen controls while keeping all settings and phrases on the local machine.

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

`pogled_assist/main.py` acquires a per-user Qt lock before logging or services;
a second interactive launch exits without activating any window. Qt recovers
locks left by terminated processes. Package and installation diagnostics bypass
this interactive lock. Startup failure and normal exit release it.
The entry point then enables Windows DPI awareness, configures logging, creates
the Qt application, and shows `HotbarWindow`. The hotbar is the composition root:
it creates the runtime services, connects their Qt signals, starts them after the
window appears, and stops child windows, Tobii backends, speech, overlays, and the
AppBar reservation during shutdown.

The Python package is named `pogled_assist`. The existing `run_gaze_mouse.py`
and `start_gaze_mouse.ps1` entry points keep their names so source installations
and shortcuts continue to launch after an update.

## Component map

| Area | Main files | Responsibility |
| --- | --- | --- |
| Entry points | `run_gaze_mouse.py`, `pogled_assist/main.py` | Source and packaged startup, Qt setup, package smoke test |
| Runtime composition | `pogled_assist/toolbar.py` | Hotbar UI, service wiring, child-window ownership, status, cleanup |
| Gaze acquisition | `pogled_assist/tracking/` | Tracker discovery, development simulation, backend fallback, sample bounds, retry, x86 bridge, calibration |
| Gaze interaction | `pogled_assist/interaction/` | Logical/physical coordinate mapping in `screen_mapping.py`, UI target lookup through `GazeTarget`, smoothing, shared selection timing, click and Quick action requests |
| Windows integration | `pogled_assist/windows/` | Physical input, work-area reservation, keyboard, startup, external foreground/cursor tracking, focus, z-order |
| User surfaces | `pogled_assist/ui/` | Settings, speech, keyboard, controller, radial menu, precision zoom, gaze feedback |
| Speech | `pogled_assist/speech/` | eSpeak NG and Edge playback, saved categories, answers and phrases, and the repeating local alarm |
| Suggestions | `pogled_assist/suggestions/`, `pogled_assist/assets/bosnian-*-model.*` | Offline Bosnian tokenisation, general and reviewed Islamic vocabulary layers, completion and next-word ranking, input-scoped undo, and reversible personal learning |
| Persistent data | `pogled_assist/settings_store.py`, `pogled_assist/suggestions/learning.py`, `pogled_assist/speech/speech_library.py`, `pogled_assist/logging_setup.py` | Settings, phrase and personal-learning data, logs, safe defaults, and atomic writes |
| Distribution | `setup_windows.ps1`, `start_gaze_mouse.ps1`, `update_windows.ps1`, `packaging/`, `scripts/` | Source setup, launch, verified release update, package build, install, release |
| Verification | `dev.ps1`, `tests/`, `.github/workflows/` | Local checks, simulated hardware inputs, UI flows, CI, release checks |

## Gaze and input path

`TobiiGazeProvider` tries the available backends in this order:

1. `tobii-research`
2. direct Tobii Stream Engine
3. Tobii Stream Engine through a 32-bit Python bridge

If none starts, the provider reports a retry state and scans again every three
seconds. Raw samples may arrive faster than the UI can safely process them, so
the provider keeps the newest sample and emits at a bounded interval. This keeps
the Qt event loop responsive instead of replaying stale gaze positions.

Stream Engine `position_xy` values are normalized display coordinates in both
the direct backend and the x86 bridge. Finite off-screen values are clamped to
the same screen edge; their magnitude never changes their units to pixels.
The bridge serializes each JSON message, newline, and flush under one lock.
Unexpected end-of-output or a bridge error invalidates both eyes and triggers
the provider's normal retry path. Stream Engine eye-status delivery older than
500 ms clears pending gaze and dwell; after three seconds without eye-status
samples the provider stops the x86 bridge and schedules a fresh connection.
Direct native streaming stays paused until fresh data arrives: a stuck DLL
thread cannot be forcibly stopped safely and must not acquire a second device
subscription. Callbacks from an earlier Stream Engine or Pro SDK connection are
ignored after stop, failed startup, or replacement. Bridge failure is terminal for that
bridge instance, even if more buffered messages follow the failure.
Invalid-eye samples still count as live delivery, so absence or a blink does
not trigger a reconnect. Diagnostics record delivery age and connection state,
never typed text.

Before delivering gaze after a gap of at least 500 ms, the provider cancels
pending interactions through the eye gate and restores current valid status.
This also covers a stalled Qt event loop or fresh eyes arriving before the
watchdog runs. The first new gaze starts a full dwell; completed selections
retain their leave-before-repeat lock.

Eye-status notifications are delivered on the Qt thread before the next gaze
sample. A backlog retains an intervening invalid-eye state even if both eyes
are valid again; coalescing must never hide a blink or let queued validity from
before stop reopen the gate. Pending gaze also carries its local receive time:
fresh eye status cannot make a gaze sample older than 500 ms usable again.
The watchdog publishes recovery status on Qt only after checking the current
connection, so a delayed worker notification cannot overwrite a newer failure.

Providers publish a typed `TrackingStatus` lifecycle separately from diagnostic
text. The hotbar status combines that lifecycle with eye validity and the local
receive time of the last delivered gaze sample. Its own display timer expires
readiness after 500 ms without gaze; it does not change the input gate, dwell,
backend subscriptions, or reconnect policy. See the
[status guide](USER_GUIDE.md#before-starting) for the visible states.

`TrackingFeedback` observes the same delivered lifecycle, eye and gaze signals
for passive Speech notifications. `TrackingFeedbackState` owns presentation
timing separately from input safety. Only the message header and active letter
or confirmation header display a notice; no gaze target or modal action is added.
The [notification guide](USER_GUIDE.md#tracking-notifications-in-speech) owns
the setting, timing and suppressed contexts. Neither notification timing nor
turning the setting off changes pointer movement, dwell cancellation or retries.

Each backend also reports left and right eye validity. Gaze movement and dwell
actions continue only while both eyes are valid. Losing either eye clears pending
gaze work, cancels active dwell interactions, closes active Quick action layers,
and leaves the pointer at its last position.

The source-only mouse gaze simulator bypasses tracker discovery and feeds the
primary-screen cursor position into the same gaze interaction path with both eyes
valid. Automatic pointer movement is disabled in that mode so the cursor can
remain the simulation input. It is a development aid, not hardware validation.

The controller keeps two coordinate spaces separate:

- Qt logical coordinates are used for hit testing buttons and windows.
- Windows physical coordinates are used for pointer movement and real clicks.

Smoothing affects visible pointer movement. Click targeting uses the current gaze
target so smoothing does not move the requested click away from the selected
point.

`GazeSelectionTimer` owns pause, dwell, and repeat blocking. The controller opts
Speech, hotbar, and standalone Keyboard controls into a bounded edge hold using
their current visible, enabled button rectangles in logical coordinates. Hotbar
hit rectangles extend vertically to the top screen edge, keeping button widths
and neutral horizontal gaps. Other surfaces retain their existing selection
rules. During an edge hold, neither elapsed outside time nor the
interval back to the first returning sample advances selection. Feedback stays
on the previous button, and a held update can never confirm it. Context changes
and eye loss discard the hold along with pending progress. Speech also blocks a
suggestion replaced beneath gaze; that rejection must not count as leaving its
button. See [Speech selection behavior](USER_GUIDE.md#speech) for the user flow.

### Gaze-check measurements

The provider collects ephemeral `CheckTelemetry` only while `GazeCheckWindow`
is open and clears it on close or stream invalidation. Coalesced snapshots reach
the Qt thread after pending eye-loss signals. Raw normalized diagnostic gaze is
kept separate from the clamped control stream. Native Stream Engine reuses its
eye-position subscription; the x86 bridge validates the optional position and
invalid-gaze messages. Pro SDK uses valid normalized track-box origins, never
millimetre coordinates. Position capability, freshness and connection state are
separate; fresh positions can remain visible without valid gaze.

`tracking/gaze_check.py` owns the measurement rules:

- Eye, position and gaze samples expire independently after 500 ms.
- Eye availability is time-weighted over at most ten seconds. After three
  seconds, at least 85% availability with no loss longer than 500 ms is shown as
  mostly continuous tracking.
- Position and depth checks use the reported [0, 1] bounds, without a centimetre
  conversion or invented central zone. Movement guidance uses only fresh
  positions and takes priority over missing-gaze guidance when outside the box.
  Recognizing an eye from its position never enables input.
- Each fixation target has one second to settle and two seconds to measure.
  A result requires 12 distinct fresh samples and 60% temporal coverage.
  Consecutive samples contribute at most 100 ms; an invalid or stale snapshot
  breaks the interval. An interruption counter preserves losses coalesced
  before Qt delivery. Earlier valid intervals remain counted across a blink.
- A near result requires 90% of samples inside the displayed 36 logical-pixel
  radius. Median error and 90th-percentile spread are descriptive heuristics,
  not Tobii-certified or clinical scores. The result map retains the normalized
  median centre; clipping off-screen centres affects painting only.

`gaze_check_window.py` owns the flow; `gaze_check_views.py` owns painting and
geometry. Five timed targets cover the centre and corners. The local trial
reuses `GazeSelectionTimer`, the speech edge-hold constants and the current pause
and dwell settings, without Windows input. Its three groups have 136 × 64,
96 × 88 and 180 × 72 logical-pixel controls, each with two neighbors. The edge
margin is bounded by a quarter of each dimension. Wrong selections retain the
leave-before-repeat lock across tracking loss. Departures include direct jumps
to a neighbor. The free check paints nine targets and fresh both-eye gaze,
without timing, scoring, smoothing or input.

The hotbar owns diagnostic signal connections, Settings return, shutdown and
Tobii settings handoff. Entry and exit clear pending actions; normal controller
input is suspended while the check is open without changing saved settings.
Suspension also applies while minimized and is checked again after synchronous
gaze slots, so the triggering sample cannot move the pointer.

`launch_tobii_settings` tries discovered UI candidates in rank order, excluding
maintenance, Guest, calibration and test targets. A rejected candidate does not
block later candidates; exhaustion returns the manual tray-icon route. Existing
Guest calibration entry points retain their behavior and also exclude
maintenance targets. The [user guide](USER_GUIDE.md#gaze-check) owns calibration
instructions and the caregiver flow. No diagnostic history or result is saved.

Coordinates follow Tobii's [Stream Engine API](https://developer.tobii.com/product-integration/)
and [track-box description](https://developer.tobii.com/wp-content/uploads/2016/03/Developers-Guide-DotNet.pdf).
Normalized-position availability and movement guidance still require validation
on the installed 4C runtime; synthetic tests cannot establish hardware accuracy.

## UI and service ownership

`HotbarWindow` owns all long-lived services and top-level UI surfaces. It opens
the full-screen Speech and Settings windows, the right-side Keyboard and
Controller panels, the radial Quick actions menu, and precision zoom. Keyboard
and Controller panels are mutually exclusive. Feedback windows remain topmost
without taking focus from the application the user is controlling.

Settings changes update the live mouse and speech services and attempt to save
immediately. The hotbar tracks failed saves across surfaces; retries use the
latest live values. `SuggestionService` is also owned by the hotbar and shared by Speech
and Settings. It loads and queries the immutable base model away from the Qt event
loop, coalesces pending requests, and writes personal counts through a separate
worker. The prediction worker builds a personal prefix and context index only
when the learning revision changes; ordinary typing reuses it. Storage recovery
also advances that revision, so merged disk data cannot leave a stale index.
Context-free candidates use the combined base and personal unigram ranking,
while both sources supply their relevant contextual candidates. The Speech input
validates the request owner, revision, text, caret, and
selection before displaying a result. Closing the hotbar closes every child
surface, flushes suggestion learning, stops speech and gaze workers, and
unregisters the AppBar so Windows restores the full work area.

`SpeechPredictions` owns the Speech input's request identity, revision, displayed
text, and the guard for a suggestion replaced beneath gaze. It is a Qt object
owned by that input, so prediction delivery remains on the UI thread.
`SpeechDialogs` owns the Speech modal windows, backdrop, and active actions;
the Speech window retains the conversation and library editing behavior.

`ForegroundTracker` owns the polling timer and the last external window and
physical cursor position. It ignores foreground windows belonging to this
process and cursor samples over application controls. The hotbar passes these
targets to Keyboard and Controller and stops polling during shutdown.

Speech playback logs identify whether the request came from gaze, button
activation, or Return in the message field, without recording the message.
Process startup and UI acknowledgement do not confirm audible playback.
Speech launch, exit monitoring, and cleanup run on a serialized worker boundary.
Cancelling a request invalidates queued notifications and closes its process
tree before a replacement starts. On Windows a suspended child is assigned to
a private kill-on-close job before execution. Engine output is discarded because
it can include typed text; diagnostics record the engine and exit code. No UI
thread waits for speech completion or stderr EOF.

`SpeechSettings.keyboard_script` is a shared, persisted Latin/Arabic selection.
The hotbar propagates Settings and keyboard switch signals to all three input
surfaces. `keyboard_layouts.py` owns the script-specific Unicode keys and
display-only combining-mark labels. Qt shapes and displays Arabic; Windows input
receives the original characters. Arabic bypasses Bosnian suggestions and new
learning, and selects the existing Edge playback boundary with the Hamed voice.
The Bosnian voice preference and existing model/profile remain intact. See the
[Arabic keyboard guide](USER_GUIDE.md#arabic-keyboard) for controls and limitations.

## Persistent data and logs

The runtime root is the executable directory for a packaged build and the
repository root during source development. `POGLED_ASSIST_LOG_ROOT` can
override it for controlled launch and test scenarios.

```text
data/app_settings.json   gaze, interaction, startup, logging, and speech settings
data/speech_library.json saved categories, answers, phrases, and phrase use counts
data/speech_phrases.json rollback-compatible standalone phrases for older releases
data/speech_learning.json versioned local word and short-context counts
logs/latest.txt          current application log when logging is enabled
```

Missing or malformed settings fall back safely to defaults, with supported
values clamped to the same ranges as the Settings UI. Installation, update, and
rollback work must preserve `data/` and `logs/`.

Unreadable speech-library files block all library writes, including rollback
synchronization and phrase use counts. Only a successful reload clears this
guard; fallback categories must never overwrite the original after a read error.

The bundled suggestion model and writable learning profile have independent
version 1 schemas. A base-model release can therefore be replaced without
rewriting personal counts. An unreadable personal profile is reported and kept
unchanged until an explicit retry can merge new in-memory learning with readable
disk data.

## Packaging and installation

`dev.ps1` is the developer entry point. The PyInstaller specification under
`packaging/windows/` builds the frozen application and includes the icons, bridge
files, and versioned Bosnian model needed at runtime. The package smoke test
loads that model and computes an offline prediction. The release package contains
its own installer and launcher and installs under `C:\PogledAssist`.
Release-owned speech executables live under `speech/`, with a private 32-bit
Python bridge runtime under `runtime/`, separate from preserved user-provided
`.venv` and `tools` components. The frozen smoke test verifies them without
audio playback, tracker access, or network access. `--installation-check` opens
a separate readiness summary without creating the hotbar or gaze services. See the
[included speech tools](WINDOWS_RELEASE.md#included-speech-tools) for packaging,
discovery, and installation behavior.

`update_windows.ps1` reads the installed version, resolves the latest stable
release from `Hasan-Smajlovic/Pogled-Assist`, downloads the exact Windows
ZIP and checksum assets, and verifies them before invoking the package installer.
The first packaged installer migrates an older source layout. The installer
stages and smoke-tests the new package, carries persistent data and external
runtime components into it, swaps sibling directories, and retains the previous
directory until the installed smoke test passes. A transaction marker lets the
next installer restore or finish an update interrupted during the directory swap.

## Design reference

The [HTML design reference](design/speech-keyboard-reference.html) is separate
from the runtime and package. The [development guide](DEVELOPMENT.md#application-design-reference-workflow)
owns its page map and review workflow.

## Compatibility contract

The current `development` behavior is the baseline for a user who already relies
on the application. Unless a linked issue explicitly changes a behavior, a
review-ready change must preserve:

- launch from the installed `C:\PogledAssist` location and from the development
  entry point;
- keep the previous installation under `C:\TobiiExec` independent and untouched;
- hotbar placement, AppBar work-area reservation, hide and restore behavior;
- tracker fallback, retry, x86 bridge, both-eye gate, and responsive gaze flow;
- pointer mapping and left, right, and double-click actions;
- dwell timing, precision zoom, Quick actions, gaze bubble, and action feedback;
- Speech, Keyboard, Controller, Settings, calibration, and quit flows;
- saved settings, saved phrases, logs, and user data during upgrades and
  rollbacks;
- clean shutdown of tracker subscriptions, bridge workers, speech processes,
  overlays, child windows, and AppBar state.

Automated tests use fake gaze, Windows input, speech, and external processes to
protect these flows without physical hardware. They do not prove real Tobii
tracking, calibration, Windows work-area behavior, gaze accuracy, or speech
playback. Record those checks separately and never report them as passed unless
they ran on the target Windows and Tobii setup.
