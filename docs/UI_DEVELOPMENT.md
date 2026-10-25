# UI development and review

This guide owns mouse gaze simulation, the design surface map, rendered UI review, and manual Windows and Tobii checks. Use the [development guide](DEVELOPMENT.md) for setup and automated checks; use [Testing](TESTING.md) for boundary fakes. For publication setup, permissions, and recovery, use the [UI gallery guide](UI_GALLERY.md).

Read the sections needed for the change:

- [Mouse gaze simulation](#mouse-gaze-simulation) for interactive synthetic input.
- [Design reference workflow](#application-design-reference-workflow) before any visible UI change.
- [Rendered UI gallery](#rendered-ui-gallery) for screenshots and the surface list.
- [Manual Windows checks](#manual-windows-checks) for real application behavior.
- [Manual Tobii checks](#manual-tobii-checks) for the target tracker and speech setup.

## Mouse gaze simulation

Run the interactive simulator when Tobii hardware is unavailable:

```powershell
.\dev.ps1 simulate
```

The primary-screen mouse position is emitted through the same normalized gaze signal used by the Tobii providers. The simulator starts with both eyes valid, an active connection, and gaze delivery enabled. Pointer movement is disabled because the mouse is the gaze source. Armed dwell actions still perform real Windows clicks.

With the application active and the hotbar visible, use these development-only shortcuts:

| Key | Simulated input |
| --- | --- |
| F6 | Toggle left-eye validity |
| F7 | Toggle right-eye validity |
| F8 | Pause or resume gaze samples without changing eye validity |
| F9 | Disconnect or reconnect; retain the selected eye and gaze states |
| F10 | Restore both eyes, the connection, and gaze delivery; cancel pending dwell |

Failures can be combined. The selected eye policy applies to synthetic gaze: the experimental mode emits coordinates with one eye; the hold mode preserves progress without emitting coordinates during a single-eye loss. Restoring an eye or connection never shows a cached marker. A gaze gap of at least 500 ms cancels pending dwell before the first resumed sample. Failure shortcuts do not change saved settings. The hotbar keeps **Simulacija mišem**, with the active failure beneath it. Tobii-specific notifications remain suppressed in simulation.

Use this to inspect selection cancellation, the gaze marker, and the caregiver check with synthetic input. It does not validate Tobii discovery, calibration, physical eye detection, automatic backend reconnection, sample quality, latency, or hardware accuracy. Report those hardware checks as Not run.

## UI review

### Application design reference workflow

The [application design reference](design/speech-keyboard-reference.html) is the design source of truth for the visible Pogled Assist interface. That historical filename is now the entry point; old fragments such as `#tracking` open the matching standalone page. Serve the static files from the repository root, then open [the reference index](http://127.0.0.1:8000/speech-keyboard-reference.html) or [Settings](http://127.0.0.1:8000/settings.html):

```powershell
.\.venv\Scripts\python.exe -m http.server 8000 --bind 127.0.0.1 --directory docs/design
```

On macOS, use `python3 -m http.server 8000 --bind 127.0.0.1 --directory docs/design`. No build step is needed. Keep the server in its terminal and stop it with Ctrl+C. Prefer HTTP when browser tools block `file://` URLs. After edits, use a hard refresh or disable the browser cache; cached CSS can show an older layout even when the HTML is current. If port 8000 is occupied, select a free port and use that port in the URL.

| Surface | HTML document | Styles and interaction |
| --- | --- | --- |
| Visual direction, fonts and component states | [design-system.html](design/design-system.html) | `docs/design/assets/design-system.css`, `docs/design/assets/design-system.js`; palette, typography and control-state reference |
| Speech and its dialogs | [speech.html](design/speech.html) | `docs/design/assets/speech.css`, `docs/design/assets/speech.js` |
| Settings and learned words | [settings.html](design/settings.html) | `docs/design/assets/settings.css`, `docs/design/assets/settings.js` |
| Gaze check | [gaze-check.html](design/gaze-check.html) | `docs/design/assets/gaze-check.css`, `docs/design/assets/gaze-check.js` |
| Diagnostic recording and support export | [diagnostics.html](design/diagnostics.html) | `docs/design/assets/diagnostics.css`, `docs/design/assets/diagnostics.js` |
| Tracking notifications | [tracking.html](design/tracking.html) | `docs/design/assets/tracking.css`, `docs/design/assets/tracking.js` |
| Hotbar and gaze bubble | [hotbar.html](design/hotbar.html) | `docs/design/assets/hotbar.css`, `docs/design/assets/hotbar.js` |
| Selection progress overlay | [selection-progress.html](design/selection-progress.html) | `docs/design/assets/selection-progress.css`, `docs/design/assets/selection-progress.js` |
| Standalone keyboard | [keyboard.html](design/keyboard.html) | `docs/design/assets/keyboard.css`, `docs/design/assets/keyboard.js` |
| Controller keyboard | [controller-keyboard.html](design/controller-keyboard.html) | The same keyboard assets |
| Installation summary | [installation.html](design/installation.html) | Shared styles; illustrative actions only |

Every visible layout, copy, control-size, state or interaction change must update its matching reference and assets in the same pull request. Review the HTML at the target size before implementing Qt, then compare the generated gallery with it. This applies to every window, sidebar, overlay, dialog and system control. Add a reference before changing a surface absent from the map. Edit the index only when navigation changes. For changes with no visible or interaction impact, state that in the pull request instead of editing the reference.

[Boje i komponente](design/design-system.html#review-title) owns the palette and control states; [O ovoj referenci](design/reference-notes.html) owns standard Bosnian terminology. Each feature page owns its detailed design notes. Platform fonts and native behavior still require the manual Windows checks below.

Use this review matrix alongside those notes:

| Surface | Required visual and interaction checks |
| --- | --- |
| Speech and Tracking | Dividers separate message, predictions, letters and utility actions. A vertical divider separates Space/Delete from keyboard/script changes. The first three utility buttons share the letter area; the script button aligns with the system column above, including its 280–480-pixel width limits. Utility height stays fixed in both scripts; letter groups take the remaining height. Dense editors, Arabic and library pages fit without overlap. Main controls reserve recording status space; letter/confirmation dialogs keep a 36-pixel title row and a 32-pixel tracking row. Recording and eye notices must not move targets. Letter characters are 56 pixels, or 44 for twelve-letter groups. Selection feedback is a steady cyan ring. |
| Settings | The title, recording slot and Close share a header separated from the content. Help text stays with its control; adjustment columns and test/stop cells align. Only the active page determines scrolling. Scrolling cancels pending selection and clipped controls are excluded from hit testing. Review switches, the Arabic voice card and ElevenLabs voice/tuning versus preview/credits/privacy groups at 1280 × 720 and 800-pixel window width. Narrow key setup stacks its heading, input and actions, with no horizontal scrolling; reflow cancels pending selection. |
| Optional help | Connection checking remains an action beside its information disclosure; Gaze check has a position/distance disclosure. Open help with mouse and keyboard, close with Escape and verify focus return and narrow containment. Required warnings remain outside disclosures. |
| Gaze check | At 1280 × 720, review preparation, completed/interrupted results, all tabs, measurements, history and save/export failures. Distinguish insufficient/unmeasured data from measured misses; keep the five-target table in the first result view. Preserve the 760 × 168 measurement panel, target clearance and 16-pixel action gaps. Keep policy and simulation text beside the title, with the paused-input notice in the header. Archive/diagnostics and Close share a 60-pixel action row; separate them with a divider. Device setup stays separate from the next check. Calibration and recovery notices remain visible. |
| Diagnostics | Underlined navigation tabs remain distinct from start/stop/export actions and support keyboard navigation. Recording states preserve action geometry. Privacy and incomplete-recording warnings remain visible. Check narrow HTML overflow as well. |
| Keyboard and Controller | At a 380-pixel sidebar width, tab words stay intact. Recording uses a fixed bottom status slot without moving keys. |

Selection rings use at most 64 logical pixels and shrink to the smaller control dimension minus 16 pixels. Keep at least 8 pixels clear of each control edge, including short Settings tabs and narrow sidebar controls. The pause mark stays inside the ring. `tests/ui/test_selection_feedback_e2e.py` checks painted bounds across the application, including the Settings gaze path; it does not establish native overlay stacking or Tobii behavior.

For unobstructed screenshots, add `preview=clean`, for example `speech.html?preview=clean`. This hides reference menus and shared notes, while ordinary views retain preview tools. Repeatable Speech parameters are `state=keyboard`, `single`, `editor-single`, `phrases` or `answers`, and `script=latin` or `arabic`. Keyboard and Controller accept `group-size=1`, `2`, `5` or `12`. Dense Speech keyboards paginate at twelve keys; libraries at four entries. Preview controls never change application settings.

Shared assets under `docs/design/assets/` have these owners:

- `reference.js`: navigation and preview session state; `reference.css`: tokens and shared controls.
- `eye-policy.js`: shared eye-policy choices and labels.
- `diagnostic-preview.js`: synthetic recording states and badges; [Diagnostics](design/diagnostics.html) owns their placement. The preview records no real input and creates no files.
- `keyboard-data.js`: keyboard data; `gaze-demo.js`: mouse gaze simulation. Tracking also reuses Speech layout styles.

The reference describes intended behavior; it is not an implementation status report. Where a reference still differs from Qt, state the concrete difference in its notes. Verify Qt through the gallery, automated checks and applicable Windows/Tobii checks.

### Rendered UI gallery

Generate the gallery:

```powershell
.\dev.ps1 ui -Open
```

The CI `tests` job also uploads a `ui-gallery` artifact, using the screenshots already rendered by `tests/ui/test_ui_rendering.py`. Once Pages is configured, the separate **UI gallery** workflow publishes a browser gallery and updates one PR bot comment with main screenshots, resolution link, the rendered commit, and a download link. Status reporting, setup, permissions and cleanup are defined in [UI gallery publication](UI_GALLERY.md). To review the artifact offline, download and extract it from the workflow run, then open `index.html` inside `1280x720`. The default 1280 × 720 gallery contains 72 representative screenshots; the artifact is kept for 14 days and any available screenshots are uploaded even when the test suite fails. CI sets `POGLED_ASSIST_UI_GALLERY` to the artifact directory. Without that variable, rendering tests continue to use pytest's temporary directories. The Pages site uses a separate generated index and only checked PNG files; it does not publish the HTML supplied by a PR's CI artifact. Available screenshots from a failed CI run can appear, with the failure shown in the comment. A gallery is visual evidence, not a passing test or a Windows/Tobii verification result.

The local and published galleries share six review groups, a six-image Overview, thumbnail grids and full-size image links. Overview reuses existing PNGs. Groups show their screenshot counts and order representative states before extended variants; unknown images from older or newer CI artifacts appear under Other previews. Images load lazily. No application UI or interaction behavior changes when selecting a gallery profile.

The default `core` profile renders:

| Group (`-UiGroup`) | Screenshots | Representative coverage |
| --- | --- | --- |
| Speech (`speech`) | 13 | Main keyboard, categories, answers, phrases, editor, alarm/sleep/exit, Arabic letters/symbols/marks/editor |
| Keyboard and Controller (`keyboards`) | 12 | All main tabs, narrow Latin pagination, Arabic keyboards and second symbols pages |
| Settings (`settings`) | 11 | Application, Support, all three eye policies, pointer/check, edge stability enabled/disabled, speech, learned words and unsaved-input update warning |
| Tracking and selection (`tracking`) | 8 | Hotbar normal/eye loss/disconnected/simulation/one-eye readiness/hold, calm active and paused Speech selection rings |
| Gaze check and diagnostics (`gaze-check`) | 18 | Position and its information disclosure, fixation, detailed precision, saved trial attempts, context, interrupted result, history, save failure, three trial sizes, held trial, wrong-neighbor feedback, free view, and diagnostic recording ready/active/history |
| Voice and account (`voice`) | 10 | Connection-check information disclosure, Preparing speech, Standardni fallback, cached/partial playback, connected account, key replacement, long permission error, critical credits and saved audio |

The other 77 screenshots remain available through the `full` profile. Use extended groups when reviewing their layout or copy:

```powershell
.\dev.ps1 ui -UiProfile full -Open
.\dev.ps1 ui -UiProfile full -UiGroup voice -Open
.\dev.ps1 ui -UiGroup settings,tracking -Open
```

`-UiGroup` accepts one or more keys from the table and filters the chosen profile. The equivalent diagnostic CLI is `.\.venv\Scripts\python.exe -m scripts.ui.capture_ui --profile full --group voice`; repeat `--group` for multiple groups. Each successful capture replaces the local gallery and removes only known PNGs omitted by that selection, so a previous full run does not leave extra screenshots in a later core gallery. Unrelated files are preserved. CI renders only the core profile; it does not render the full set and then hide images. The existing functional tests still exercise the alternative states. Before release or after changes to an extended state, generate and review the affected full group.

<details>
<summary>Full profile: all 149 states</summary>


- Hotbar, including one-eye pause, waiting for fresh data, disconnected-device, mouse-simulation (normal, eye loss, paused gaze and disconnected), unsaved-settings states, experimental one-eye readiness and missing gaze, and a held selection
- Application, Support, gaze, speech, and learned-word Settings surfaces, including all three eye policies, the pointer/check tab, edge-stability settings with retention enabled and disabled, save failure and four version states: older selection, package preparation, unsaved-input warning, and failed release check
- Diagnostic recording: ready, recording, finishing, saved history with optional report, incomplete with omitted events, write failure and export failure; passive badges in the hotbar, Settings, Speech and its letters dialog, Keyboard, Controller, gaze-check header and free view. Speech also previews finishing, saved, incomplete and error indicator states.
- Speech selection progress: calm active ring and frozen ring with pause mark
- Speech Settings during preparation/playback, Efendija Settings, ElevenLabs setup (connected, replacing key, Nema glasova, missing key, invalid key, missing permission, credential save failure, quota, low/critical credits and preparation/playback), and saved-audio controls
- Gaze check: unavailable data, unsupported positions, disconnected device, live position, eye positions without valid gaze, too-close/too-far/outside-frame guidance without valid gaze, eye loss, fixation target with and without gaze, incomplete results, optional measurements, measured misses, passed targets, three local dwell trial sizes, cancelled selection and wrong-neighbor feedback, trial results needing adjustment, a trial without gaze data, completed check, free check with and without live gaze, experimental one-eye free view, held button trial, saved trial attempts, settings/device context, save pending/failure, logging off, export failure, interrupted precision, history, read-only archived result, empty history and history read error
- Speech keyboard, `speech-preparing`, `speech-speaking`, categories, answers, saved phrases, shared editor, and library read failure
- Speech tracking notifications: eye loss, missing gaze, disconnected device, repeated interruptions, recovery, letter selection and deletion confirmation during diagnostic recording
- Speech voice states: Efendija, quota/offline/timeout/invalid-key fallback, Standardni fallback, cached audio, partial playback and recovery
- Speech alarm, sleep, and exit confirmation dialogs
- Keyboard letters, numpad, and symbols tabs
- Controller general, keyboard, and settings tabs
- Latin Keyboard and Controller with two letters per group and page controls
- Arabic Speech, letters and vowel-mark dialogs, symbols, and phrase editor
- Arabic Settings and both sidebar keyboards, including their second symbols page

</details>

PNG capture uses a fixed Qt quality of 80 for lossless compression with less encoding work. Keep the image and gallery byte limits enforced by the publication script, and review the generated gallery when changing encoding.

The gallery uses 1280 × 720 logical pixels to review a 1920 × 1080 display at 150% scaling. In Settings, check the four navigation choices, grouped switches, voice choices below keyboard script, aligned adjustment columns, equal test/stop buttons and the separate ElevenLabs groups. Keep 12 logical pixels between ordinary rows and between voice controls and their help, with 16 pixels from that help to the next setting. Titles and descriptions stay closer together; dense gaze adjustment rows retain 6 pixels between rows. Preserve 58-pixel controls and allow vertical scrolling when content needs more height. Check both information disclosures with mouse, gaze where supported, keyboard and Escape; optional help must not hide required warnings. The Latin pagination snapshots use 380 × 640 logical pixels to check the sidebar below the 76-pixel hotbar at 150% scaling.

The separate installation summary is documented in the HTML reference and covered by UI interaction tests; it is not part of either screenshot profile. Review it separately using `PogledAssist.exe --installation-check` after a build.

Check the gallery at 100 percent and at the scale used by the target machine. Look for clipped labels, overlapping controls, inconsistent spacing, low contrast, missing icons, unexpected scrollbars, and controls that are too small for gaze. Compact Settings rows end at their last control, with no trailing inset; preserve the 12-pixel gaps within adjustment groups. Hidden key actions must not leave an empty spacer at the end of the wide API-key row. Diagnostics uses 16 pixels between its footer actions and between content columns.

Static gaze-setting guidance uses a left border, short bold lead-ins and wrapped paragraphs with a maximum width of 860 pixels. Keep it next to the setting it explains; retain the eye-policy scope, edge-hold limits and calibration caveat. Do not turn permanent instructions into dismissible alerts or hover-only help.

### Manual Windows checks

Run the real application:

```powershell
.\dev.ps1 run
```

On a normal development machine, verify:

- The hotbar spans the primary screen and does not cover maximized windows.
- Hide and Show restore the Windows work area.
- Settings, Speech, Keyboard, and Controller open at the expected size.
- Gaze check opens from Settings, fits 1280 × 720 logical pixels, retains speech text, blocks normal gaze input while open/minimized, and returns to Settings using mouse or Escape. Check target timing, cancellation, resizing, calibration handoff and taskbar return. Check all nine free targets, live-gaze expiry, the result map and visible metrics, and all three neighbor-control sizes. Confirm the caregiver panel covers no target. Simulator results must be labeled as synthetic.
- For gaze-check reports, finish and interrupt precision and repeated trials. Check all result tabs, history after restart, logging off, save failure/retry and read-only older settings. Export completed and interrupted results using the native Windows Save As dialog, including cancel, overwrite and write failure; open the JSON/TXT pair from the ZIP and compare it with the UI. Normal gaze input must remain suspended during the dialog and history. The native dialog is reviewed on Windows rather than captured in the offscreen gallery.
- The Controller Speech tab, hidden hotbar, Quick actions, precision zoom, and gaze feedback remain usable.
- Opening Keyboard closes Controller and opening Controller closes Keyboard.
- Settings survive an application restart.
- ElevenLabs setup fits 1280 × 720. Check saved, replaced, cancelled and removed credentials, masked input after a failed save, and refusal to use an unsaved key.
- The voice list matches My Voices. A missing selected ID requires explicit reselection before either Settings page can test it. An empty list says **Nema glasova**.
- Check all three Stability buttons and the Similarity slider/−/+ controls. Restart and confirm persistence. The [user guide](features/elevenlabs.md) owns defaults, cache behavior and timing.
- Check credit warnings and unavailable balance without User: Read. A slow balance refresh leaves voice/model choices and an unrelated dwell usable.
- During preparation/playback, check the indicator inside the lower part of the Speech button, alignment with Fraze, stable text/target geometry, Stop, preserved text and no repeated paid test until gaze leaves its completed button. Check the static activity mark when the platform style disables widget animations. Stop and immediately speak again; the new request must reach ElevenLabs without a false timeout.
- Check missing catalog permissions. The read-only check must not generate speech. Separately listen to the intended Fikret clone, Eleven v4 and sentence-case text.
- Check quota/offline fallback, recovery after a top-up, saved-entry repetition offline, edit/deletion, tuning round trips and cache clearing. Free-form messages leave no cache. Record audible quality separately from process/network fakes.
- Change the active Efendija voice/model/tuning while preparing and playing. Old audio must not start later. `test_stalled_decoder_fails_without_waiting_forever` covers the silent decoder watchdog; playback replacement tests cover stale native callbacks. Neither proves audible MP3 quality on the Windows machine.
- Tracking notifications are initially enabled, can be disabled in Gaze Settings, leave targets fixed in Speech and its letter/deletion dialogs, and restore the message field after recovery. Check that Rest, Settings and Gaze check suppress them without changing policy eligibility or the desktop both-eye gate.
- Ordinary logs follow the logging switch; explicit diagnostic recording also works with that switch off and leaves its saved value unchanged.
- Closing the app removes AppBar reservations and child windows.
- Bosnian suggestions complete a partial word and offer a next word offline.
- Moving the caret or selecting text disables suggestions; returning to the end restores them without changing the message.
- Suggestion undo, punctuation spacing, phrase or answer editor restoration, and individual learned-word removal work with mouse and simulated gaze.
- Closing and reopening preserves `data\speech_learning.json`; a forced write failure leaves the previous file intact and can be retried from Settings.
- Switch Latin/Arabic from Settings and each keyboard, including an unfinished phrase or answer. The shared choice survives restart without changing existing text or entries. Review Arabic shaping, mixed text, both digit forms, mark entry/removal, and sidebar pagination at 1920 × 1080 with 150% scaling (1280 × 720 logical pixels). Arabic has no suggestions; returning to Latin restores them. Test Hamed playback and unavailable/offline errors separately.

For short diagnostic recordings, verify the Settings and gaze-check entry points, default 2-minute and manual stops, continued recording after closing its window, and the unchanged logging switch. Check readable recording/countdown labels in all referenced surfaces, stable control geometry, click-through overlays, finishing until writer acknowledgment, one shared five-second saved confirmation, and persistent incomplete/error warnings. Open another window during recording and during the saved confirmation; its timer must not restart. Check screen-reader state announcements without countdown repeats. Review a local ZIP's source identity, hashes and optional report. Check incomplete results after forced termination, slow/full/unwritable disk and export failure, then restart and verify retention. Normal input must remain paused throughout a check/diagnostics handoff and resume after leaving it. Record these Windows results separately from fake-input tests.

### Manual Tobii checks

On the Tobii machine, additionally verify:

- Repeat the same intended-target task with manual recording off and on, including one-eye loss, a hold, an edge departure and reconnect. Compare selections, tracking continuity, UI latency, CPU, memory and output size on the reference machine. Badges must not obscure existing labels or notices. Background writes and passing fakes do not establish zero performance cost or improved accuracy.

- In Gaze check, confirm the actual runtime supplies normalized positions before accepting movement guidance. Move the attached display nearer/further and sideways, verify both eye markers and depth, and confirm unavailable data has no checkmark. Test five fixations near the screen edges, the nine-point free check and all three local dwell trials, including wrong-neighbor selection, a blink, sustained one-eye loss, disconnect/reconnect and normal control after closing. Record OS, tracker, installed Tobii app/driver versions and selected application backend. Test the user's existing Tobii Core installation, including calibration settings launch, named-profile recalibration and return. Confirm that this settings action never starts Guest calibration. Verify Display setup uses the primary display and tracker alignment; this feature must not require a switch to Tobii Experience.
- The hotbar status distinguishes connecting, unavailable device, waiting for fresh data, a held selection, normal readiness and experimental one-eye selection. Actual eye indicators remain truthful. Readiness follows the selected policy and fresh gaze; it does not certify calibration accuracy.
- Both labeled eye indicators reflect real validity. Hide removes the whole status with the hotbar; Show restores its current state.
- Under the default **Oba oka** policy, losing one eye cancels dwell progress. Pointer movement stops on either-eye loss in every policy.
- In Speech and its letter/deletion dialogs, check short blinks, sustained one-eye loss, repeated losses, missing gaze and disconnect/reconnect under all three policies. Notifications follow eligibility and do not change it. Turning them off must never bypass the selected policy.
- With Tobii 4C, verify whether finite SDK-valid combined gaze actually arrives with just one tracked eye. Keep the experimental choice selectable when it does not; the app must wait without using cached coordinates or claiming unsupported hardware. Check both directions of sole-eye switches, loss of both eyes, first-sample recovery, unchanged versus changed targets, and the 50/150/500 ms hold values. Verify all keyboards, dialogs and Controller click buttons, plus the independent both-eye desktop/Quick-action/precision-zoom boundary. Report observed device behavior separately from fake-input results.
- At 150% scaling, select Speech, Keyboard, and Settings from the top screen edge without a mouse. Gaps between buttons must not select either neighbor.
- In Speech, the hotbar, and standalone Keyboard, compare edge retention disabled, the existing 120 ms baseline and a longer trial value using the same pause/dwell and eye policy. A brief movement just beyond a button edge freezes progress without selecting either button. Returning before expiry resumes it; a sustained or farther move starts a new selection. A nearby B earns no time while A is held and needs its full pause and dwell after expiry. Check letters, suggestions, and `Izgovori`, deliberate fast switches, repeat blocking, context changes and eye-loss overlap. Confirm the caregiver trial follows the saved value. Record intended targets, correct/wrong/cancelled selections and switching delay on the user's display; ordinary target-change counts alone cannot distinguish jitter from intentional moves.
- Disconnect and reconnect the tracker while dwelling. Progress must cancel, the connection must recover, and the first new selection must start from zero. Confirm that normal invalid-eye samples do not repeatedly restart the backend.
- With the x86 bridge, resume after Windows sleep and confirm that old dwell progress cannot fire an action. A direct native connection pauses until data returns and does not start a replacement native subscription during an outage.
- Pointer mapping reaches all corners of the calibrated display.
- Left, right, double-click, precision zoom, and Quick actions work.
- Default and human-like speech are tested separately.
- Select Arabic groups, letters, marks, and the script switch by Tobii. Eye loss and script/page changes must cancel pending dwell; a replacement label must require leaving and returning before another action. Record actual Hamed audio playback and pronunciation separately from process startup and fake speech.

Record software-only and hardware results separately in the pull request.
