# Gaze check

For everyday controls, return to the [user guide](../USER_GUIDE.md).

Open **Postavke > Pogled i odabir > Pokazivač i provjera > Provjera pogleda** to adjust the display and check gaze. A helper operates this optional screen by mouse or keyboard; the gaze user looks at the targets. The selected eye policy is labeled throughout the test. Normal gaze input stays paused while the check is open, including while minimized. **Zatvori** or Escape returns to Settings; the speech message is retained.

## Position and tracking

**Položaj i praćenje** shows each eye, gaze delivery and recent tracking continuity. Adjust the screen with its attached tracker. When the runtime supplies positions, the frame shows the eyes and the bar shows depth from **Bliže uređaju** to **Dalje od uređaja**. A checkmark means inside the reported tracking area, not verified accuracy; a dash means unavailable or stale data. Depth is not measured in centimetres. Position guidance can work before valid gaze returns. If positions are unsupported, use the Tobii app's positioning display; the target tests remain available.

## Per-eye tracking

**Praćenje po oku · zadnjih 10 s** stays visible in the right card while positioning. It is hidden during both tests, which still measure it for the results. It shows the share of the last ten seconds in which the device reported the left eye, the right eye and both eyes, so one lost eye still shows the other eye's value. This is tracking availability reported by the device, not a Tobii confidence score. Colours start after three seconds, so the first blink does not look like a large loss.

**Prekidi** counts each loss of valid gaze or of eyes usable under the selected eye policy, including blinks and losses too short to appear between two updates; a continuous loss counts once, and **najduži** gives the longest one. With the experimental one-eye policy, losing only the other eye is not an interruption. **Isto mjesto** shows how often the left-eye and right-eye gaze points were within 36 logical pixels of each other, and their median distance, while both eyes were valid. The Tobii 4C through Stream Engine sends one combined gaze point, so there it shows as unavailable instead of an estimate. Beside positioning, advice names an eye that is often lost, both eyes lost or eyes that often disagree. These values do not establish the cause.

## Running the check

**Pokreni provjeru** runs two tests in a row: five targets, then a word written by gaze. **Prekini test** or **Prekini i prikaži rezultat** stops either test and shows the completed parts.

**Tačke** presents five automatic targets, about three seconds each, at the centre and near the screen corners. Look at each cross; no gaze click is required. When the fifth target finishes, the word test starts.

**Riječ** asks the gaze user to write **VODA** from one row of large letters: the word's letters and a few others. The letters use the current selection pause, dwell time and eye policy, and no click goes to another program. The line above the letters shows what has been written; a letter whose time ran out stays crossed out in amber, so it never looks typed. Progress is green on the requested letter and amber on another; a selection of another letter counts as a wrong letter. A permitted short eye loss freezes progress with a pause mark; other ineligible or missing gaze cancels pending selection. Already completed selections cannot repeat without looking away. Its instructions use larger text than the target test so they stay readable on a laptop screen.

## Results

Precision results distinguish **Pogled blizu mete**, **Pogled izvan mete** and **Premalo podataka**. Missing data is not a measured miss. **Riječ „VODA“** counts correct letters, and the advice covers wrong letters, interrupted selections and timeouts. A timed-out letter with insufficient gaze coverage directs the helper to restore tracking. A few isolated samples do not justify asking for a longer stare. Below the summary, **Tačke** and **Riječ** show each test's left, right and both-eye share, interruptions and longest interruption, so the two tests can be compared. **Prikaži mjerenja** reveals data coverage, error and spread, with explanations.

**Ponovi test riječi** repeats only the word test and keeps the target results. **Ponovi provjeru** runs both tests again as a new dated attempt, and **Podesi položaj** returns to positioning. Follow the advice to restore tracking, check calibration, retry or try the speech keyboard. Individual application controls still need checking in actual use.

## Free check and measurement limits

**Slobodna provjera** shows nine targets and a green ring for fresh gaze allowed by the selected policy, without timing or a score. Missing or off-screen gaze hides the ring. **Vrati na položaj** returns to positioning. This follows the visual feedback idea in Tobii Core's [Test and recalibrate](https://help.tobii.com/hc/en-us/articles/213891645-Test-and-recalibrate); use the timed test when a measured result is needed.

The [architecture guide](../ARCHITECTURE.md#gaze-check-measurements) defines the measurement rules and thresholds. They are application heuristics, not Tobii-certified or clinical assessments. A short loss may be a blink; the app does not diagnose tears, lighting or illness. Recognized positions, the per-eye panel and the both-eye continuity indicator do not change the selected input policy. Connection loss, minimizing an active test or resizing interrupts it. Simulator results are labeled and are not Tobii measurements.

## Saved gaze-check results

Results have three tabs: **Preciznost**, **Test riječi** and **Postavke i uređaj**. A precision result is created as soon as its five targets finish, before the word test starts. Each word test is a separate dated attempt under the same precision result. Each test also saves its per-eye shares, interruption count and longest interruption. Results saved by earlier versions show the three-button trial as **Probni izbor** and no per-eye values. **Prekini i prikaži rezultat** keeps completed parts, marks the attempt **Prekinuto** and leaves unfinished targets **Nije izmjereno**. Missing gaze data is shown as **Premalo podataka**, without claiming a measured miss. Closing, repeating, resizing, minimizing or disconnecting also retains completed parts with the reason for interruption.

If **Uključi zapisivanje** was enabled when the check opened, completed and interrupted reports are automatically saved in the background. Otherwise, new results remain in memory until the application closes. This choice is copied with the check's other settings. **Sačuvani rezultati** lists disk and current-session results by date, eye policy and state; selecting a result opens a read-only view of its measurements and the settings used. Viewing an older result never applies its settings. A failed disk read or unsupported report is shown explicitly. **Pokušaj ponovo** retries a failed automatic save; the result remains available in memory.

**Izvezi ZIP** is available independently of logging and opens Windows Save As. The ZIP contains `rezultat.json` for analysis and `izvjestaj.txt`, a readable Bosnian report of the same measurements, per-eye tracking, settings and available environment information. Unknown device/build values stay unavailable. It includes no raw gaze stream, typed messages, saved speech or credentials.

Export status is separate from automatic-save status. Up to 100 automatic reports and 10 MiB are retained; after a successful save, the oldest supported reports are removed when needed. Manually exported ZIPs are never automatically removed. [Persistent storage](../ARCHITECTURE.md#persistent-data-and-logs) owns the file locations. The broader diagnostic-log bundle remains separate; see [Diagnostic log collection](../USER_GUIDE.md#diagnostic-log-collection).

## Calibration handoff

**Otvori Tobii postavke** opens the installed Tobii settings and minimizes the check. In Tobii Core, select the user's profile, then **Test and recalibrate > Recalibrate** if needed. This action does not use `TOBII_CALIBRATION_COMMAND` or Ctrl+Shift+F10. Tobii documents that shortcut as [Guest calibration](https://help.tobii.com/hc/en-us/articles/209530409-Create-a-new-user-profile), which uses a temporary profile and does not recalibrate the saved one. The existing installation **Pokreni kalibraciju** and Settings **Pokreni Tobii kalibraciju** actions retain that Guest flow.

Check [Display setup](https://help.tobii.com/hc/en-us/articles/209529969-Display-setup) too: Tobii must use Windows' primary display with correct tracker alignment. If settings cannot open, use the Tobii tray icon beside the clock. Return via the Windows taskbar or **Postavke**, then run a new check. Opening Tobii settings does not confirm calibration completed or change saved app settings. Keep the installed Core or Experience software; this feature requires no switch.
