# Gaze check

For everyday controls, return to the [user guide](../USER_GUIDE.md).

Open **Postavke > Pogled i odabir > Pokazivač i provjera > Provjera pogleda** to adjust the display and check gaze. A helper operates this optional screen by mouse or keyboard; the gaze user looks at the targets. The selected eye policy is labeled throughout the test. Normal gaze input stays paused while the check is open, including while minimized. **Zatvori** or Escape returns to Settings; the speech message is retained.

## Position and tracking

**Položaj i praćenje** shows each eye, gaze delivery and recent tracking continuity. Adjust the screen with its attached tracker. When the runtime supplies positions, the frame shows the eyes and the bar shows depth from **Bliže uređaju** to **Dalje od uređaja**. A checkmark means inside the reported tracking area, not verified accuracy; a dash means unavailable or stale data. Depth is not measured in centimetres. Position guidance can work before valid gaze returns. If positions are unsupported, use the Tobii app's positioning display; the target tests remain available.

## Precision check

**Provjeri preciznost** presents five automatic targets, about three seconds each, at the centre and near the screen corners. Look at each cross; no gaze click is required. Results distinguish **Pogled blizu mete**, **Pogled izvan mete** and **Premalo podataka**. Missing data is not a measured miss. The advice directs the helper to positioning, profile calibration or the button trial. **Prikaži mjerenja** reveals data coverage, error and spread, with explanations. **Prekini i prikaži rezultat** keeps completed parts in an interrupted report; **Podesi položaj** returns to positioning and **Ponovi preciznost** starts a new dated attempt.

## Button trial

**Probaj izbor dugmeta** tries three sizes of controls with the current selection pause, dwell time and eye policy. Look at **Pogledaj**, beside two **Drugo** buttons, until the progress bar fills. No click goes to another program. **Pogled je na drugom dugmetu** means gaze is there; **Odabrano je pogrešno dugme** confirms a selection. Progress is green on the intended button and amber on another. A permitted short eye loss freezes progress with a pause mark; other ineligible or missing gaze cancels pending selection. Already completed selections cannot repeat without looking away.

Results count correct selections, wrong selections and interrupted pending selections; the **Probni izbor** result tab also shows departures. A timed-out target with insufficient gaze coverage directs the helper to restore tracking. A few isolated samples do not justify asking for a longer stare. Follow the advice to restore tracking, check calibration, retry or try the speech keyboard. **Ponovi probu dugmadi** retains precision results. Individual application controls still need checking in actual use.

## Eye check

**Provjeri oči** measures each eye for 30 seconds while the gaze user looks at the screen as usual. It shows the share of time the device reported the left eye, the right eye and both eyes at once, so one lost eye still shows the other eye's value. This is tracking availability reported by the device, not a Tobii confidence score. **Isto mjesto** shows how often the left-eye and right-eye gaze points were within 36 logical pixels of each other, and their median distance, while both eyes were valid. The Tobii 4C through Stream Engine sends one combined gaze point, so there it shows as unavailable instead of an estimate. The advice names an eye that is often lost, both eyes lost or eyes that often disagree. These values do not establish the cause; if both eyes stay tracked and agree while letters still cannot be hit, use **Provjeri preciznost**, which measures calibration and position. **Prekini test** shows a partial result, **Ponovi provjeru očiju** starts a new run for comparison, and **Nazad na položaj** returns to positioning. The result is not added to saved gaze-check results.

## Free check and measurement limits

**Slobodna provjera** shows nine targets and a green ring for fresh gaze allowed by the selected policy, without timing or a score. Missing or off-screen gaze hides the ring. **Vrati na položaj** returns to positioning. This follows the visual feedback idea in Tobii Core's [Test and recalibrate](https://help.tobii.com/hc/en-us/articles/213891645-Test-and-recalibrate); use the timed test when a measured result is needed.

The [architecture guide](../ARCHITECTURE.md#gaze-check-measurements) defines the measurement rules and thresholds. They are application heuristics, not Tobii-certified or clinical assessments. A short loss may be a blink; the app does not diagnose tears, lighting or illness. Recognized positions and the both-eye continuity indicator do not change the selected input policy. Connection loss, minimizing an active test or resizing interrupts it. Simulator results are labeled and are not Tobii measurements.

## Saved gaze-check results

Results have three tabs: **Preciznost**, **Probni izbor** and **Postavke i uređaj**. A precision result is created as soon as its five targets finish; the optional button trial is not required. Repeating a trial keeps separate dated attempts under the same precision result. **Prekini i prikaži rezultat** keeps completed parts, marks the attempt **Prekinuto** and leaves unfinished targets **Nije izmjereno**. Missing gaze data is shown as **Premalo podataka**, without claiming a measured miss. Closing, repeating, resizing, minimizing or disconnecting also retains completed parts with the reason for interruption.

If **Uključi zapisivanje** was enabled when the check opened, completed and interrupted reports are automatically saved in the background. Otherwise, new results remain in memory until the application closes. This choice is copied with the check's other settings. **Sačuvani rezultati** lists disk and current-session results by date, eye policy and state; selecting a result opens a read-only view of its measurements and the settings used. Viewing an older result never applies its settings. A failed disk read or unsupported report is shown explicitly. **Pokušaj ponovo** retries a failed automatic save; the result remains available in memory.

**Izvezi ZIP** is available independently of logging and opens Windows Save As. The ZIP contains `rezultat.json` for analysis and `izvjestaj.txt`, a readable Bosnian report of the same measurements, settings and available environment information. Unknown device/build values stay unavailable. It includes no raw gaze stream, typed messages, saved speech or credentials.

Export status is separate from automatic-save status. Up to 100 automatic reports and 10 MiB are retained; after a successful save, the oldest supported reports are removed when needed. Manually exported ZIPs are never automatically removed. [Persistent storage](../ARCHITECTURE.md#persistent-data-and-logs) owns the file locations. The broader diagnostic-log bundle remains separate; see [Diagnostic log collection](../USER_GUIDE.md#diagnostic-log-collection).

## Calibration handoff

**Otvori Tobii postavke** opens the installed Tobii settings and minimizes the check. In Tobii Core, select the user's profile, then **Test and recalibrate > Recalibrate** if needed. This action does not use `TOBII_CALIBRATION_COMMAND` or Ctrl+Shift+F10. Tobii documents that shortcut as [Guest calibration](https://help.tobii.com/hc/en-us/articles/209530409-Create-a-new-user-profile), which uses a temporary profile and does not recalibrate the saved one. The existing installation **Pokreni kalibraciju** and Settings **Pokreni Tobii kalibraciju** actions retain that Guest flow.

Check [Display setup](https://help.tobii.com/hc/en-us/articles/209529969-Display-setup) too: Tobii must use Windows' primary display with correct tracker alignment. If settings cannot open, use the Tobii tray icon beside the clock. Return via the Windows taskbar or **Postavke**, then run a new check. Opening Tobii settings does not confirm calibration completed or change saved app settings. Keep the installed Core or Experience software; this feature requires no switch.
