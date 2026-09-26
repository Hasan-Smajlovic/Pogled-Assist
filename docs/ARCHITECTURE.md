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

`pogled_assist/main.py` enables Windows DPI awareness, configures logging, creates
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
| Gaze interaction | `pogled_assist/interaction/` | Coordinate mapping, smoothing, shared selection timing, click and Quick action requests |
| Windows integration | `pogled_assist/windows/` | Physical input, work-area reservation, keyboard, startup, focus, z-order |
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

## UI and service ownership

`HotbarWindow` owns all long-lived services and top-level UI surfaces. It opens
the full-screen Speech and Settings windows, the right-side Keyboard and
Controller panels, the radial Quick actions menu, and precision zoom. Keyboard
and Controller panels are mutually exclusive. Feedback windows remain topmost
without taking focus from the application the user is controlling.

Settings changes update the live mouse and speech services and are saved
immediately. `SuggestionService` is also owned by the hotbar and shared by Speech
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
Release-owned speech executables live under `speech/`, separate from preserved
user-provided `.venv` and `tools` components. The frozen smoke test verifies them
without audio playback or network access. See the
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

[`design/speech-keyboard-reference.html`](design/speech-keyboard-reference.html)
is the self-contained visual and interaction reference used while developing
the visible PySide6 interface. Its historical filename is retained for stable
links. It is not loaded by the application, included by the PyInstaller build,
or required to install or run Pogled Assist.

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
