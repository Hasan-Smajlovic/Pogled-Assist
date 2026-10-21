# UI development and review

This guide owns mouse gaze simulation, the design surface map, rendered UI review, and manual Windows and Tobii checks. Use the [development guide](DEVELOPMENT.md) for setup, automated checks, and test fakes. For publication setup, permissions, and recovery, use the [UI gallery guide](UI_GALLERY.md).

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

The [application design reference](design/speech-keyboard-reference.html) is the design source of truth for the visible Pogled Assist interface. That historical filename is now the entry point; old fragments such as `#tracking` open the matching standalone page. Open the HTML files directly in a browser; they use local styles and classic scripts, without a server or build step.

| Surface | HTML document | Styles and interaction |
| --- | --- | --- |
| Speech and its dialogs | [speech.html](design/speech.html) | `docs/design/assets/speech.css`, `docs/design/assets/speech.js` |
| Settings and learned words | [settings.html](design/settings.html) | `docs/design/assets/settings.css`, `docs/design/assets/settings.js` |
| Gaze check | [gaze-check.html](design/gaze-check.html) | `docs/design/assets/gaze-check.css`, `docs/design/assets/gaze-check.js` |
| Tracking notifications | [tracking.html](design/tracking.html) | `docs/design/assets/tracking.css`, `docs/design/assets/tracking.js` |
| Hotbar and gaze bubble | [hotbar.html](design/hotbar.html) | `docs/design/assets/hotbar.css`, `docs/design/assets/hotbar.js` |
| Selection progress overlay | [selection-progress.html](design/selection-progress.html) | `docs/design/assets/selection-progress.css`, `docs/design/assets/selection-progress.js` |
| Standalone keyboard | [keyboard.html](design/keyboard.html) | `docs/design/assets/keyboard.css`, `docs/design/assets/keyboard.js` |
| Controller keyboard | [controller-keyboard.html](design/controller-keyboard.html) | The same keyboard assets |
| Installation summary | [installation.html](design/installation.html) | Shared styles; illustrative actions only |

Shared navigation and preview session state live in `docs/design/assets/reference.js`; shared tokens and controls are in `docs/design/assets/reference.css`. `docs/design/assets/eye-policy.js` shares the eye-policy labels and preview choices across Settings, tracking feedback, the gaze check and selection progress. The tracking page also reuses Speech's layout styles. Keyboard data and the mouse gaze simulation have separate shared scripts, `docs/design/assets/keyboard-data.js` and `docs/design/assets/gaze-demo.js`. Preview state is separate from application data and settings. Each page owns its feature notes; the [reference notes](design/reference-notes.html) own shared language conventions. Other gaze overlays do not yet have their own pages. Add the relevant page before changing one of those surfaces.

Every change to visible layout, copy, control sizes, states, or interaction flow must update the matching page and its assets in the same pull request. When instructions name `docs/design/speech-keyboard-reference.html`, they refer to this collection through its entry point; edit the index only when navigation changes. Update and review the reference first, then implement the matching PySide6 change so the reference never describes an older UI. This rule applies to every window, sidebar, overlay, dialog, and system control, not only the Speech window. If a code change has no visible or interaction impact, state that explicitly in the pull request instead of editing the reference unnecessarily.

Review the HTML reference at the target display size before generating the Qt gallery. The reference documents the intended result; the gallery and real application checks confirm that the implementation matches it.

Application-owned labels and feedback use standard Bosnian. The [**O ovoj referenci** page](design/reference-notes.html) owns the UI terminology and language conventions; check these when adding or reviewing copy.

### Rendered UI gallery

Generate the gallery:

```powershell
.\dev.ps1 ui -Open
```

The CI `tests` job also uploads a `ui-gallery` artifact, using the screenshots already rendered by `tests/ui/test_ui_rendering.py`. Once Pages is configured, the separate **UI gallery** workflow publishes a browser gallery and updates one PR bot comment with main screenshots, resolution link, the rendered commit, and a download link. Status reporting, setup, permissions and cleanup are defined in [UI gallery publication](UI_GALLERY.md). To review the artifact offline, download and extract it from the workflow run, then open `index.html` inside `1280x720`. The single 1280 × 720 gallery contains 114 surfaces; the artifact is kept for 14 days and any available screenshots are uploaded even when the test suite fails. CI sets `POGLED_ASSIST_UI_GALLERY` to the artifact directory. Without that variable, rendering tests continue to use pytest's temporary directories. The Pages site uses a separate generated index and only checked PNG files; it does not publish the HTML supplied by a PR's CI artifact. Available screenshots from a failed CI run can appear, with the failure shown in the comment. A gallery is visual evidence, not a passing test or a Windows/Tobii verification result.

The command renders:

- Hotbar, including one-eye pause, waiting for fresh data, disconnected-device, mouse-simulation (normal, eye loss, paused gaze and disconnected), unsaved-settings states, experimental one-eye readiness and missing gaze, and a held selection
- General, gaze, speech, and learned-word Settings surfaces, including all three eye policies, the pointer/check tab, save failure and four version states: older selection, package preparation, unsaved-input warning, and failed release check
- Selection progress: active and frozen arc with pause mark
- Speech Settings during preparation/playback, Efendija Settings, ElevenLabs setup (connected, replacing key, Nema glasova, missing key, invalid key, missing permission, credential save failure, quota, low/critical credits and preparation/playback), and saved-audio controls
- Gaze check: unavailable data, unsupported positions, disconnected device, live position, eye positions without valid gaze, too-close/too-far/outside-frame guidance without valid gaze, eye loss, fixation target with and without gaze, incomplete results, optional measurements, measured misses, passed targets, three local dwell trial sizes, cancelled selection and wrong-neighbor feedback, trial results needing adjustment, a trial without gaze data, completed check, free check with and without live gaze, experimental one-eye free view, and a held button trial
- Speech keyboard, `speech-preparing`, `speech-speaking`, categories, answers, saved phrases, shared editor, and library read failure
- Speech tracking notifications: eye loss, missing gaze, disconnected device, repeated interruptions, recovery, letter selection and deletion confirmation
- Speech voice states: Efendija, quota/offline/timeout/invalid-key fallback, Standardni fallback, cached audio, partial playback and recovery
- Speech alarm, sleep, and exit confirmation dialogs
- Keyboard letters, numpad, and symbols tabs
- Controller general, keyboard, and settings tabs
- Latin Keyboard and Controller with two letters per group and page controls
- Arabic Speech, letters and vowel-mark dialogs, symbols, and phrase editor
- Arabic Settings and both sidebar keyboards, including their second symbols page

PNG capture uses a fixed Qt quality of 80 for lossless compression with less encoding work. Keep the image and gallery byte limits enforced by the publication script, and review the generated gallery when changing encoding.

The gallery uses 1280 × 720 logical pixels to review a 1920 × 1080 display at 150% scaling. In Settings, check equal action cells, the single-cell calibration control, voice choices below keyboard script, and aligned adjustment columns. The Latin pagination snapshots use 380 × 640 logical pixels to check the sidebar below the 76-pixel hotbar at 150% scaling.

The separate installation summary is documented in the HTML reference and covered by UI interaction tests; it is not part of the 114-surface gallery. Review it separately using `PogledAssist.exe --installation-check` after a build.

Check the gallery at 100 percent and at the scale used by the target machine. Look for clipped labels, overlapping controls, inconsistent spacing, low contrast, missing icons, unexpected scrollbars, and controls that are too small for gaze.

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
- The Controller Speech tab, hidden hotbar, Quick actions, precision zoom, and gaze feedback remain usable.
- Opening Keyboard closes Controller and opening Controller closes Keyboard.
- Settings survive an application restart.
- ElevenLabs setup fits 1280 × 720. Check saved, replaced, cancelled and removed credentials, masked input after a failed save, and refusal to use an unsaved key.
- The voice list matches My Voices. A missing selected ID requires explicit reselection before either Settings page can test it. An empty list says **Nema glasova**.
- Check all three Stability buttons and the Similarity slider/−/+ controls. Restart and confirm persistence. The [user guide](USER_GUIDE.md#efendija-voice-and-elevenlabs-setup) owns defaults, cache behavior and timing.
- Check credit warnings and unavailable balance without User: Read. A slow balance refresh leaves voice/model choices and an unrelated dwell usable.
- During preparation/playback, check the indicator, Stop, preserved text and no repeated paid test until gaze leaves its completed button. Stop and immediately speak again; the new request must reach ElevenLabs without a false timeout.
- Check missing catalog permissions. The read-only check must not generate speech. Separately listen to the intended Fikret clone, Eleven v4 and sentence-case text.
- Check quota/offline fallback, recovery after a top-up, saved-entry repetition offline, edit/deletion, tuning round trips and cache clearing. Free-form messages leave no cache. Record audible quality separately from process/network fakes.
- Change the active Efendija voice/model/tuning while preparing and playing. Old audio must not start later. `test_stalled_decoder_fails_without_waiting_forever` covers the silent decoder watchdog; playback replacement tests cover stale native callbacks. Neither proves audible MP3 quality on the Windows machine.
- Tracking notifications are initially enabled, can be disabled in Gaze Settings, leave targets fixed in Speech and its letter/deletion dialogs, and restore the message field after recovery. Check that Rest, Settings and Gaze check suppress them without changing policy eligibility or the desktop both-eye gate.
- Logs appear under `logs` only when logging is enabled.
- Closing the app removes AppBar reservations and child windows.
- Bosnian suggestions complete a partial word and offer a next word offline.
- Moving the caret or selecting text disables suggestions; returning to the end restores them without changing the message.
- Suggestion undo, punctuation spacing, phrase or answer editor restoration, and individual learned-word removal work with mouse and simulated gaze.
- Closing and reopening preserves `data\speech_learning.json`; a forced write failure leaves the previous file intact and can be retried from Settings.
- Switch Latin/Arabic from Settings and each keyboard, including an unfinished phrase or answer. The shared choice survives restart without changing existing text or entries. Review Arabic shaping, mixed text, both digit forms, mark entry/removal, and sidebar pagination at 1920 × 1080 with 150% scaling (1280 × 720 logical pixels). Arabic has no suggestions; returning to Latin restores them. Test Hamed playback and unavailable/offline errors separately.

### Manual Tobii checks

On the Tobii machine, additionally verify:

- In Gaze check, confirm the actual runtime supplies normalized positions before accepting movement guidance. Move the attached display nearer/further and sideways, verify both eye markers and depth, and confirm unavailable data has no checkmark. Test five fixations near the screen edges, the nine-point free check and all three local dwell trials, including wrong-neighbor selection, a blink, sustained one-eye loss, disconnect/reconnect and normal control after closing. Record OS, tracker, installed Tobii app/driver versions and selected application backend. Test the user's existing Tobii Core installation, including calibration settings launch, named-profile recalibration and return. Confirm that this settings action never starts Guest calibration. Verify Display setup uses the primary display and tracker alignment; this feature must not require a switch to Tobii Experience.
- The hotbar status distinguishes connecting, unavailable device, waiting for fresh data, a held selection, normal readiness and experimental one-eye selection. Actual eye indicators remain truthful. Readiness follows the selected policy and fresh gaze; it does not certify calibration accuracy.
- Both labeled eye indicators reflect real validity. Hide removes the whole status with the hotbar; Show restores its current state.
- Losing one eye cancels dwell progress and stops pointer movement.
- In Speech and its letter/deletion dialogs, check short blinks, sustained one-eye loss, repeated losses, missing gaze and disconnect/reconnect under all three policies. Notifications follow eligibility and do not change it. Turning them off must never bypass the selected policy.
- With Tobii 4C, verify whether finite SDK-valid combined gaze actually arrives with just one tracked eye. Keep the experimental choice selectable when it does not; the app must wait without using cached coordinates or claiming unsupported hardware. Check both directions of sole-eye switches, loss of both eyes, first-sample recovery, unchanged versus changed targets, and the 50/150/500 ms hold values. Verify all keyboards, dialogs and Controller click buttons, plus the independent both-eye desktop/Quick-action/precision-zoom boundary. Report observed device behavior separately from fake-input results.
- At 150% scaling, select Speech, Keyboard, and Settings from the top screen edge without a mouse. Gaps between buttons must not select either neighbor.
- In Speech, the hotbar, and standalone Keyboard, a brief movement just beyond a button edge freezes progress without selecting either button. Returning resumes it; a sustained or farther move starts a new selection. Check letters, suggestions, and `Izgovori`, including deliberate fast switches and the leave-before-repeat rule. Record selection errors and switching delay before and after the change on the user's display.
- Disconnect and reconnect the tracker while dwelling. Progress must cancel, the connection must recover, and the first new selection must start from zero. Confirm that normal invalid-eye samples do not repeatedly restart the backend.
- With the x86 bridge, resume after Windows sleep and confirm that old dwell progress cannot fire an action. A direct native connection pauses until data returns and does not start a replacement native subscription during an outage.
- Pointer mapping reaches all corners of the calibrated display.
- Left, right, double-click, precision zoom, and Quick actions work.
- Default and human-like speech are tested separately.
- Select Arabic groups, letters, marks, and the script switch by Tobii. Eye loss and script/page changes must cancel pending dwell; a replacement label must require leaving and returning before another action. Record actual Hamed audio playback and pronunciation separately from process startup and fake speech.

Record software-only and hardware results separately in the pull request.
