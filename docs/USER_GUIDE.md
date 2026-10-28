# User guide

- [Installation readiness](#installation-readiness) and [before starting](#before-starting)
- [Tracking notifications](#tracking-notifications-in-speech), [gaze check](#gaze-check) and [saved results](#saved-gaze-check-results)
- [Hotbar controls](#hotbar-controls) and [quick actions](#quick-actions)
- [Speech](#speech), [Keyboard](#keyboard), and [Controller](#controller)
- [Settings](#settings) and [updates](#update)
- [Troubleshooting](#troubleshooting), [diagnostic recording](#diagnostic-log-collection) and [exit](#exit)

## Installation readiness

After installation, **Provjera instalacije** shows whether the speech tools and Tobii bridge are ready, whether Tobii software was found, and whether Windows recognizes a connected Tobii device. It does not verify gaze accuracy or finish personal calibration. Detection errors appear as **Nije provjereno**.

The person setting up the computer can use **Preuzmi Tobii softver** to open the official download page, **Pokreni kalibraciju** to request calibration through installed Tobii software, and **Ponovi provjeru** after making changes. Nothing is downloaded or calibrated automatically. Use mouse or keyboard in this setup window; gaze tracking starts in the main application.

You can close the summary and reopen it with `PogledAssist.exe --installation-check`. Standard speech is available offline; the natural voice still requires internet.

Pogled Assist places a toolbar at the top of the primary Windows display. It can move the pointer from gaze, select its own controls by dwell, and perform a click after you hold your gaze on a stable target.

## Before starting

Opening the app again keeps the existing instance and its current focus. It does not start another tracker, keyboard, or copy of the saved data.

Connect and calibrate the Tobii Eye Tracker 4C with the matching Tobii software. The app tries these tracking backends in order:

1. Tobii Pro SDK through `tobii-research`.
2. A directly loadable Tobii Stream Engine DLL.
3. The optional 32-bit Python bridge for 32-bit Stream Engine installations.

The top-right status uses an icon, color, and visible text. **Praćenje spremno** requires a connected tracker, both eyes and fresh gaze. With the experimental one-eye policy, **Odabir jednim okom** identifies usable application selection with one eye; direct desktop input still needs both. **Odabir na čekanju** identifies a selection attempt whose progress is still retained during a short interruption. When an unfinished initial pause is discarded at the full-progress deadline, the status changes to **Praćenje pauzirano**; an already completed pause can remain on hold until 500 ms total from the loss. **Praćenje pauzirano** keeps both labeled eye indicators visible: a check means valid data and a dash means no valid data. These indicate SDK validity, not physical eye closure or calibration accuracy. **Čekam podatke** reports missing or stale data, **Povezivanje…** reports discovery, and **Uređaj nije povezan** reports automatic retry. Source simulation keeps the **Simulacija mišem** label; its [shortcuts](UI_DEVELOPMENT.md#mouse-gaze-simulation) use synthetic input. Application selection follows the [chosen policy](#eye-tracking-policy).

Missing eye-status delivery pauses input. A prolonged interruption in the x86 bridge or a closed bridge starts automatic reconnection; normal invalid-eye samples do not restart the connection. A direct native connection stays paused until fresh data returns. After a gaze-delivery gap of at least 500 ms, pending selection restarts from zero; time spent waiting cannot confirm the target.

The action overlay uses a steady cyan progress ring with a transparent center on application controls. It freezes with a pause mark during a hold and shows a full ring for 220 ms after confirmation. This changes feedback, not selection timing or eye eligibility.

The blue gaze marker follows fresh gaze allowed by the selected policy and expires after 500 ms without a new point. Restored eye indicators alone do not make an old marker position visible again.

## Tracking notifications in Speech

**Postavke > Pogled i odabir > Odabir pogledom > Obavijesti o praćenju pogleda** is on by default, including when loading older settings. Turning it off hides Speech notifications without changing the selected eye-tracking policy or desktop input eligibility.

The message header normally has no notification or reserved empty row. Deletion dialogs keep a 32-pixel notification row below the title and recording indicator, so a tracking change does not move their buttons. A tracking problem lasting about 0.8 seconds shows a notice in the message header, including during letter selection, or deletion confirmation. It distinguishes missing eye data, missing fresh gaze and a disconnected device. Three eye-tracking interruptions of at least 0.35 seconds within 10 seconds can also show **Praćenje često prekida · provjerite položaj uređaja**. These presentation thresholds filter short interruptions; they do not delay cancellation of gaze selection or identify a medical cause.

After eligible eyes and fresh gaze return, **Praćenje se vraća** appears while stability is checked. About half a second of continuous valid tracking changes it to green **Možete nastaviti** for two seconds, then it slides away. Another interruption updates the same notice. Green confirms returned tracking data, not calibration accuracy, and adds no delay to selection. During repeated interruptions, a warning can coexist with usable tracking; **odabir je zaustavljen** appears only while selection lacks eligible data.

The notice takes no focus and requires no acknowledgement. Buttons stay in place and the message field retains its full width; its original height returns when the notice disappears. Rest, Gaze check, Settings and hidden or minimized Speech do not produce these notifications. The existing hotbar status remains independent of this option.

## Gaze check

Open **Postavke > Pogled i odabir > Pokazivač i provjera > Provjera pogleda**. A helper uses mouse or keyboard while the gaze user follows the targets. Normal gaze input stays paused until the check closes. The [gaze-check guide](features/gaze-check.md) covers positioning, precision, button trials and calibration.

### Saved gaze-check results

The [results guide](features/gaze-check.md#saved-gaze-check-results) explains automatic saving, history, interrupted attempts and local ZIP export. Export works independently of ordinary logging.

### Calibration handoff

[Calibration handoff](features/gaze-check.md#calibration-handoff) distinguishes named-profile recalibration through **Otvori Tobii postavke** from the existing Guest calibration action.

## Hotbar controls

The left side of the hotbar contains:

1. Hide
2. Settings
3. Quick actions
4. Left click
5. Right click
6. Double click
7. Speech
8. Keyboard
9. Controller

Hide removes the AppBar reservation and the entire hotbar, including its tracking status. It leaves a floating Show button near the top-left corner. Show restores the hotbar and its current status. The status is passive and has no dwell action, blinking animation, or sound during eye loss. Left, Right, and Double click arm one action. Keep your gaze on the target until the progress overlay completes. The mode resets after the click to reduce accidental repeats.

Every gaze selection starts with a configurable pause without a progress ring. The default pause is 250 ms and can be adjusted between 100 and 2000 ms. The ring then fills for the configured stare time, which defaults to 850 ms; together the defaults take 1100 ms. Existing saved timing values stay unchanged. After a control activates, look away from it before returning to select it again. A mouse click remains immediate and cancels any pending gaze selection.

The top edge directly above each hotbar button also selects that button. Gaps between buttons remain neutral. A brief movement near a button edge freezes selection for the configured [edge duration](#selection-stability-near-edges); it cannot fire an action outside the target or unlock a completed action for a repeat.

A gaze-driven right click arms one direct left click for selecting a context-menu item. That follow-up click skips precision zoom so the menu stays open.

## Quick actions

Quick actions is a toggle. With precision zoom enabled, holding gaze on a target first opens a magnified square. Choose the exact point inside the square, then use the radial menu:

- Top: left click
- Right: right click
- Bottom: double click
- Left: cancel

With precision zoom disabled, the radial menu opens directly at the stable gaze point. Gaze does not move the real pointer while the zoom or menu is open.

## Speech

The first three bottom controls share the letter area; **Arapski / Latinica** aligns with the system controls on the right. Dividers separate typing, keyboard changes and system actions. Dense keyboards show at most twelve keys per page, with **Prethodna** and **Sljedeća** for the remaining keys. Categories, answers and phrases show four entries per page. Selecting a letter returns to the same keyboard page; changing script or switching letters/symbols starts on page one. Selecting a group replaces the groups with individual letters in the keyboard area. The message, suggestions and other controls stay available. **Nazad na grupe** or Escape returns without entering a letter. Diagnostic recording stays above the system controls.

For **Standardni**, **Prirodni**, and **Efendija**, **Izgovori** becomes **Zaustavi** in the same position while preparing or speaking. A thin activity bar appears inside its lower edge, keeping the button aligned with **Fraze** and its text centered. The bar shows activity rather than a percentage and lets clicks reach the button. Select it again, or press Enter, to stop without submitting a second request. The message remains available. The stop action stays available while adding a phrase or answer; it does not speak the unfinished saved entry. Completion, failure and stopping remove the bar and restore **Izgovori**. Playback status alone does not verify audible sound.

If a library file cannot be read, **Kategorije** and **Fraze** show **Biblioteka nije učitana** and **Učitaj ponovo**. Available entries still work for composing a message, but adding, deleting, and saving usage counts are blocked to protect the original files. Retry after restoring access to the file; a successful reload restores the library without changing your message. A damaged file must be repaired or restored from a backup before retrying.

Speech opens a full-screen Bosnian keyboard. Select a letter group, then a letter. The message field is ready for typing when Speech opens, after its controls or dialogs are used, and when returning to Speech with Alt+Tab. Returning focus preserves the caret and any selected text. While adding a category, answer, or phrase, typing belongs to that new entry. Modal dialogs and **Odmor** block typing into the message until closed; Settings and other Windows applications keep their focus until you return to Speech. Launch still opens the hotbar. Space and Backspace stay on the bottom row. `Izgovori` sends the current text to the selected speech engine without clearing it. `Kategorije` contains saved groups of answers, while `Fraze` contains standalone reusable text. Both lists support adding and deleting entries with the same grouped keyboard. The conversation message and all category, answer, and phrase content appear and are entered in uppercase. Text typed or pasted with lowercase letters is converted immediately. Settings can show 1 to 12 letters per group. A group of 12 letters uses four columns in the same keyboard area, or five columns while editing a saved entry to leave room for Save and Cancel. **Nazad na grupe** is the last choice. All choices fit at 1920×1080 with Windows scaling set to 150%. Selecting a letter returns to the groups. After a group changes into letters, look away and return before selecting a new target.

On Speech controls, a brief gaze movement just beyond a button edge freezes the pause or ring instead of clearing it. Returning before the configured [edge duration](#selection-stability-near-edges) expires resumes that progress. The button cannot activate while gaze is outside it. Moving farther away or staying outside longer starts a new selection. This applies to letter groups, letters, word suggestions, and `Izgovori`, as well as the other Speech controls. A brief edge movement does not unlock a button for repeat selection. Returning after the edge tolerance expires permits a repeat with a full new pause and dwell, even if no further gaze sample arrived while outside. Mouse actions, changed views, and window resizing cancel pending progress. Eye loss follows the [selected policy](#eye-tracking-policy) and cannot extend an already running edge deadline. A changed word suggestion requires looking away before selecting it.

The suggestion row shows up to five uppercase Bosnian words. It completes the word at the end of the input or adds a next word followed by one space. The suggestions work without internet access, preserve the rest of the message, and never speak automatically. They are inactive while text is selected, the cursor is away from the end, or a category name is being entered.

`Poništi riječ` restores the exact text from before the most recent suggestion. It remains available until the text is otherwise edited, even after `Izgovori`. If `.`, `,`, `?`, or `!` is entered immediately after a suggestion, the keyboard removes only the space it added and places the punctuation after the word. A period or question mark then adds one space automatically, so the next sentence can begin without selecting `Razmak`.

The offline dictionary also includes reviewed Bosnian Islamic terminology and common phrases for worship, Qur'an and hadith, Ramadan and Bajram, mosque and community life, Islamic scholarship, and the user's experience as an imam. For example, typing `KUR` offers `KUR'AN`, while phrases such as `POMOZI MI DA UZMEM` can offer `ABDEST`. Personal learning continues to adapt these results locally.

The same suggestions are available while adding a phrase or category answer. That editor has its own undo state and cannot replace the saved conversation message. A phrase or answer contributes to personal learning only after it is successfully saved. Category names are never learned.

The controls on the right remain available while browsing or adding entries:

- `Alarm` stops speech, repeats a distinct local emergency sound, and opens a dialog. Select `Zaustavi alarm` to silence it and return to the same Speech state.
- `Odmor` stops speech and blacks out the display. Select `Nastavi` by gaze or mouse to restore the message, current list and page, and any unfinished entry.
- `Izlaz` offers three choices. `Odustani` returns to the same state, `Izađi` closes only Speech mode while preserving the conversation message, and `Ugasi aplikaciju` closes the whole application through its normal shutdown path.

Saved categories, answers, and phrases use UTF-8 text. Selecting an answer or phrase appends it to the message, and saved phrases remain ordered by usage count. The full library is stored in `data\speech_library.json`. The app also maintains `data\speech_phrases.json` so older releases can read standalone phrases during rollback. Personal word and short-context counts are stored locally in `data\speech_learning.json`; message transcripts are not stored.

Standardni uses eSpeak NG with the Bosnian `bs` voice. Prirodni uses `edge-playback` with `bs-BA-GoranNeural` and requires internet access. Efendija uses the ElevenLabs voice selected in Settings.

### Efendija voice and ElevenLabs setup

Choose **Efendija > Podesi ElevenLabs** in **Postavke > Govor i tastatura**. Follow the [ElevenLabs guide](features/elevenlabs.md) to save a key, select a voice/model, test playback and manage credits or saved audio. New Efendija speech needs internet and credits; a whole saved phrase or answer with cached audio can play offline.

Efendija sends text to ElevenLabs. Preparation failure can fall back to Prirodni (Microsoft), then Standardni (offline). Read the [text-transfer and fallback rules](features/elevenlabs.md#text-transfer-and-fallback) before using it.

### Arabic keyboard

Choose **Arapski** under **Govor i tastatura > Pismo tastature**, or select `Arapski` on Speech, Keyboard, or the Controller keyboard. The choice applies to all three keyboards and is saved immediately. Select `Latinica` to return. Switching preserves the message, an unfinished phrase or answer, saved entries, and the existing Bosnian voice and gaze settings. Controls remain in Bosnian and keep their established order; this does not translate text or the interface.

Arabic uses the same group-then-letter selection. Letters and the message read right to left, with normal Unicode shaping. `Brojevi i znakovi` in Speech and the Numbers and Symbols tabs in the side panels include both `0123456789` and Arabic-Indic digits, Arabic punctuation, vowel and tanwin marks, shadda, sukun, dagger alif, extended marks, and combining Quranic signs. Symbols in Arabic Speech are grouped, and long group lists in side panels use `Prethodna` and `Sljedeća` to keep gaze targets large. A dotted circle makes standalone marks visible on buttons; only the actual mark is entered. `Obriši slovo` removes the last entered character, so a mark can be corrected without removing its letter. Mixed Arabic and Latin text is preserved.

Both Latin and Arabic side-panel keyboards show at most eight groups per page, including when **Broj slova u grupi** is set to one or two. Selecting a character returns to the same page. Changing the script or keyboard tab returns to page one.

Arabic has no word suggestions or new personal learning in this release. Returning to Latin restores the existing Bosnian suggestions and learned data.

Arabic Speech uses the natural male **Hamed** voice (`ar-SA-HamedNeural`) through the already included `edge-playback` tool. It requires internet and sends the spoken text to Microsoft's speech service, like the existing natural Bosnian voice. No Windows Arabic keyboard layout, new model download, or additional speech installation is required. The standard/natural Bosnian choice is retained for returning to Latin. Arabic does not silently use a Bosnian or offline voice if the natural voice is unavailable: Speech reports that the selected voice is unavailable and preserves the message for retry.

Automated checks verify Unicode entry, switching, layout, and voice commands. They do not establish audible playback, pronunciation, online service availability, external application text direction, or physical Tobii accuracy. Review those on the target Windows machine at 1920 × 1080 and 150% scaling using the [UI development checklist](UI_DEVELOPMENT.md#ui-review).

## Keyboard

Keyboard opens a right-side panel with Letters, Numpad, and Symbols tabs. The panel sends normal Windows keyboard input to the last external foreground window. It reserves the right work area while the hotbar is visible and expands to the full screen height while the hotbar is hidden. Its controls use the same brief edge tolerance as [Speech](#speech). Changing groups, hiding or resizing cancels pending selection. Eye loss follows the [selected policy](#eye-tracking-policy).

## Controller

Controller opens a right-side panel with General, Keyboard, Speech, and Settings tabs. General provides left, right, and double-click actions, Enter, and scrolling. The embedded Keyboard tab contains the same letters, numpad, and symbols controls. Only Keyboard or Controller can reserve the right work area at one time.

## Settings

The four navigation choices are **Aplikacija**, **Pogled i odabir**, **Govor i tastatura** and **Podrška**. Notification and action-progress switches share a separated row below the timing controls. Each switch sits next to its label.

Changes apply immediately. If saving fails, **Postavke \*** on the hotbar and a persistent notice in Settings indicate that the current values are only active until the app closes. **Pokušaj sačuvati** retries saving the latest values. Changing tabs or reopening Settings keeps the notice until saving succeeds. This also applies to settings changed from the sidebars or Speech.

Windows startup queries and changes run in the background, so other settings remain usable. The startup checkbox follows the latest requested choice while a change is pending. Closing Settings keeps requested Windows changes running while the application remains open. Reopening Settings reads the state after those changes finish. A launcher-window choice made during the initial query also applies to an existing enabled startup task.

**Aplikacija** controls startup, updates, and whether the PowerShell launcher window stays visible. **Podrška** contains ordinary logging, diagnostic recording and the gaze check. The active Settings page can be scrolled with the mouse wheel or scrollbar. Scrolling cancels an unfinished gaze selection; clipped controls cannot be selected through the surrounding window. Start with Windows creates a per-user Scheduled Task that runs the launcher with administrator privileges.

Gaze settings uses these values:

| Setting | Default | Range |
| --- | --- | --- |
| Pause before gaze selection | 250 ms | 100 to 2000 ms |
| Progress-ring fill time after the pause | 850 ms | 150 to 5000 ms |
| Full-progress retention during a short eye-tracking interruption | 150 ms | 50 to 500 ms, step 50 ms |
| Edge selection hold | 120 ms | 0 to 300 ms, step 20 ms; 0 disables it |
| Stable target radius | 48 px | 10 to 160 px |
| Delay between actions | 350 ms | 100 to 5000 ms |
| Pointer smoothing | 1.00 | 0.05 to 1.00 |

**Pogled i odabir** has three tabs. **Odabir pogledom** contains the eye-tracking policy, interruption duration, pause, dwell, cooldown, notifications and action-overlay visibility. **Pokazivač i provjera** contains radius, smoothing, pointer movement, the gaze bubble, precision zoom, calibration and the gaze check. **Stabilnost uz rub** contains the shared edge duration. Existing saved timing values remain unchanged when installing a version with new defaults.

The edge duration applies when gaze moves just beyond a button. The short eye-tracking interruption applies when one eye loses valid tracking in **Oba oka uz kratke prekide**. They are separate settings; neither fills progress or permits activation while paused. Neither corrects calibration or establishes which setting is best for a person.

### Selection stability near edges

Use **Postavke > Pogled i odabir > Stabilnost uz rub > Čuvanje odabira uz rub** to adjust brief edge departures on Speech, the standalone Keyboard and the hotbar. The range is listed above; **Isključeno** means zero retention. The spatial tolerance stays unchanged. Settings controls, Controller controls and direct desktop actions retain their existing rules. The gaze check's local button trial copies this setting when opened.

While gaze is briefly outside A but still near its edge, the pause or ring freezes. Only returning inside the same unchanged A before expiry can resume it; outside time, including the interval up to the first returning point, earns no progress. If gaze stays on a nearby B until expiry, A is discarded and B starts its full pause and dwell from the first eligible sample after expiry. B earns no time while A is frozen. Moving farther away switches immediately. Changing the duration cancels an unfinished selection; completed buttons still require departure before repetition. A tracking interruption cannot extend an already running edge deadline.

Longer retention can preserve progress through longer small departures, but it also delays deliberate moves to a neighbor. The adjustment range is for trials, not a proven optimum or a calibration correction. Compare unintended selections and switching delay on the tracker before choosing a value for daily use.

### Eye-tracking policy

Choose **Režim praćenja očiju** in **Postavke > Pogled i odabir > Odabir pogledom**:

| Choice | Behavior |
| --- | --- |
| **Oba oka** | Default, including older settings files. Losing either eye cancels progress. |
| **Oba oka uz kratke prekide** | Starts with both eyes. Losing one eye freezes all progress for the selected duration, then retains only an already completed initial pause until 500 ms total from the loss. Both eyes and fresh gaze inside the same unchanged target are required to resume. |
| **Jedno oko je dovoljno (probno)** | Allows starting and completing an application selection with at least one valid eye and fresh valid gaze coordinates. Without coordinates it waits. Availability on Tobii 4C needs checking on the device. |

**Trajanje kratkog prekida** keeps its saved value in every mode and is adjustable only in the second mode. It sets full-progress retention H, not an extra delay after a fixed hold. The default remains 150 ms; installing the update does not change saved values.

| Time from the original single-eye loss | Retained selection |
| --- | --- |
| Less than H | All credited pause and fill progress stays frozen. |
| From H until 500 ms total | Only an initial pause completed before the loss survives. Fill is cleared; an unfinished initial pause is discarded. |
| At least 500 ms | The attempt is discarded. |

At H = 500 ms there is no second window. The full-progress hold keeps the filled arc and pause mark; the completed-pause hold shows an empty arc with the pause mark. Neither state can advance or activate. Turning off progress hides both displays. The first returning sample restores state without earning the missing interval or activating.

For example, with an 850 ms initial pause, 650 ms fill and H = 300 ms, returning after 350 ms to the same unchanged target preserves a completed pause and requires the full 650 ms fill again. It does not repeat the 850 ms pause. This is a synthetic reference example, not a recommended optimum for every user.

Both-eye loss, switching the sole tracked eye without fresh both-eye gaze between, a changed target/content/geometry, lost connection, suspended input or relevant timing/policy changes discard retained progress. Existing stale-data and delivery-gap checks take precedence and can discard it before 500 ms. Repeated eye reports do not restart either deadline, and tracking retention cannot extend an edge-hold deadline. Completed controls still require looking away before repetition.

The policy applies to all application gaze controls, including keyboards, dialogs, Settings and Controller click buttons. Direct desktop pointer movement, direct desktop clicks, Quick actions and precision zoom require both eyes in every mode. Controller click buttons keep their existing external pointer target. The gaze check's precision, free view and button trial use the selected policy and display its name; eye indicators and both-eye availability remain actual measurements. The hold contributes no measurement samples. Tracking notices use the chosen eligibility rule and do not report stopped selection solely because one eye is invalid in the experimental mode.

### Speech settings

Speech settings controls eSpeak speed (155 words per minute by default, 80 to 320), letters per group (5 by default, 1 to 12), and the voice preset. `Pismo tastature` accepts `Latinica` (the default for existing installations) or `Arapski`. The voice choices appear directly below it. The selected voice button stays selected when pressed again. Arabic replaces the Bosnian choices with Hamed while retaining the Bosnian preference. The speed control appears only for Standardni and applies to eSpeak. `Naučene riječi` opens the personal vocabulary. Select one word and then `Zaboravi riječ` to remove its personal ranking contribution without changing messages, phrases, answers, or the bundled dictionary. If learning cannot be read or saved, the page preserves the last file, reports the problem, and offers `Pokušaj ponovo` while normal typing and speech remain usable. Other settings are saved immediately to `data\app_settings.json`.

## Update

In the installed Windows application, open **Postavke > Aplikacija**. The current version is always shown separately from **Verzija za instalaciju**. Settings checks the official stable release list when opened; **Provjeri verzije** refreshes it. A notice identifies a newer stable version. A failed check does not mean your installed version is the latest.

Choose an older or newer version in the dropdown, then select **Instaliraj i ponovo pokreni**. With gaze, dwelling on the dropdown cycles through its values. Selection alone does not install anything. Internet access is required for the list and package download. The app stays open while the package is downloaded and verified. If a message or entry is unfinished, choose **Odustani** to keep it or **Odbaci unos i ponovo pokreni** to continue. Unsaved drafts are not restored after restart. Closing Settings cancels a pending installation.

Saved phrases, categories, answers, usage counts, settings, learned words and logs are preserved, including a return from an older version. The installer also keeps pre-install data snapshots as described in the [persistent-data contract](ARCHITECTURE.md#persistent-data-and-logs). The selected version remains active after restarts. Updates are never installed automatically. Older releases may not have this selector or version notices; returning from them can require their updater or a manual verified installation. There is no device selector, offline version list or separate recovery launcher.

If the application cannot open, use the manual update procedure:

Close Pogled Assist, open PowerShell in `C:\PogledAssist`, and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\update_windows.ps1
```

The updater requests Administrator access, compares the installed `VERSION` with the latest stable GitHub Release, verifies the downloaded ZIP against its published SHA-256 file, and tests the new application before replacing the old one. Settings, saved phrases, logs, and installation metadata are preserved. If the download, checksum, staging, or installed smoke test fails, the previous installation remains available. Rerun the same command after an interrupted update so the installer can recover the saved transaction.

For source installations with the old updater, install a verified current stable package manually to migrate to the packaged channel. Its installer keeps user data and local runtime components. Later updates never install a repository branch, draft, or prerelease.

## Troubleshooting

If no tracker is found, confirm that Tobii software sees the device and that it is calibrated. The runtime log should eventually include `Tracking with`, `Stream Engine backend started`, or `x86 bridge started`.

If the log contains `[WinError 193] %1 is not a valid Win32 application`, the Tobii DLL is probably 32-bit. Rerun source setup or configure a 32-bit Python 3.10 path:

```powershell
$env:POGLED_ASSIST_X86_PYTHON = "C:\Path\To\Python310-32\python.exe"
```

An existing `TOBII_GAZE_MOUSE_X86_PYTHON` setting from the previous app is also accepted when it points to a valid 32-bit Python 3.10. The new setting takes priority if both are present.

If Stream Engine is installed outside a common location:

```powershell
$env:TOBII_STREAM_ENGINE_DLL = "C:\Path\To\tobii_stream_engine.dll"
```

If calibration needs a product-specific command, set `TOBII_CALIBRATION_COMMAND` before launching the app. This override belongs to the existing Guest calibration action, which still sends Ctrl+Shift+F10 after requesting the command. It is not used by **Otvori Tobii postavke**.

Runtime diagnostics are written to `logs\latest.txt` when logging is enabled. The launcher writes `start_gaze_mouse.log` even when its window is hidden. Updater diagnostics are appended to `update_windows.log` in the installation folder.

### Diagnostic log collection

Use a [gaze-check result](#saved-gaze-check-results) to compare measured targets and button trials. Use a diagnostic recording to investigate what happened during application use. The two exports are separate; a support ZIP includes a gaze-check result only when you explicitly choose one.

#### Record a problem

1. Open **Postavke > Podrška > Dijagnostičko snimanje**, or use the same shortcut in **Provjera pogleda** when no precision/button measurement is active. A caregiver operates this screen by mouse or keyboard; normal gaze input is paused while it is open.
2. Choose **1, 2, 5 or 10 min** (default 2), then **Pokreni snimanje**. Explicit recording works even with **Uključi zapisivanje** off and never changes that setting. It also works after an ordinary log session reaches its size cap.
3. Return to the application, reproduce the problem and note the approximate time and intended control. Closing the recording window keeps recording active. Returning to a gaze check preserves its result and keeps normal input paused until the check closes; no measurement continues hidden behind diagnostics.
4. Wait for the duration or 32 MiB limit, or reopen the screen and choose **Zaustavi snimanje**. Wait for saving to finish before exporting or starting another recording.

#### Understand the indicator

A steady **Snimanje dijagnostike · MM:SS** indicator shows remaining time in Speech's Controls column and letter/delete/exit/alarm dialogs, Settings, Keyboard, Controller, gaze check and diagnostics. The hotbar Settings button uses a compact countdown. Space stays reserved while hidden, so countdowns and state changes do not move targets or replace tracking/speech notices. Rest keeps its black screen.

| Message | Meaning |
| --- | --- |
| **Završavam snimak…** | The writer is finishing; another recording cannot start until it acknowledges completion. |
| **Snimak je sačuvan** | Confirmed successful saving; shown for five seconds across open windows. |
| **Snimak nije potpun** | A recording was retained with an interruption or missing data; review its details. |
| **Greška čuvanja snimka** | Saving failed; review the recording's available data and error state. |

Incomplete/error messages stay visible until a new recording starts. Opening another window does not restart the shared confirmation timer. A recording is technical gaze/event data, not microphone or screen capture.

#### Review and export

**Sačuvani snimci** lists recordings available after restart. Review the reason, final-record presence, omitted-event count, write errors and truncated-data count. Time expiry or a manual stop can be complete; a size cap, shutdown, write error, missing final record or reported loss is incomplete. A force-killed application can leave a useful partial stream. An unreadable recording cannot be exported. Failed reading offers **Osvježi listu**. The newest five recordings, up to 200 MiB, are kept after a successful new save; manually exported ZIPs are preserved. [Persistent storage](ARCHITECTURE.md#persistent-data-and-logs) owns file locations and retention details.

Choose **Izvezi ZIP** and a destination in Windows Save As. The package includes the selected detailed JSONL, `kontekst.json`, a Bosnian `sazetak.txt`, and `manifest.json` with version, recording identity/state, byte sizes and SHA-256 hashes. **Dodaj rezultat Provjere pogleda** optionally includes one saved or current-memory report, including an interrupted report. Its own date, policy, simulation flag and state remain separate; no report is selected automatically. Export is local and sends nothing. Failure leaves the recording and any earlier destination intact, allowing retry.

The package includes detailed gaze coordinates and control geometry, selected gaze settings, display/backend/device information and build identity. A full revision with **Lokalne izmjene izvora: Da** describes a modified build; unknown values remain unavailable. It excludes complete settings/log folders, API keys, composed or spoken messages, library contents, audio, screenshots and device serial numbers. Coordinates and geometry may reveal activity; review the package before sharing it through your agreed support channel.

#### Ordinary logs and launch-time trace

Normal logging collects summaries and selection interruption reasons. The explicit recording controls above are the normal way to capture a short problem. The older launch-time trace remains available from PowerShell:

```powershell
$env:POGLED_ASSIST_GAZE_DIAGNOSTICS = 'trace'
& 'C:\PogledAssist\PogledAssist.exe'
Remove-Item Env:\POGLED_ASSIST_GAZE_DIAGNOSTICS
```

Close any already-running copy first. This older launch-time trace requires **Uključi zapisivanje**, lasts at most ten minutes or 32 MiB, then returns to basic logging; disabling normal logging ends that trace. The explicit recording controls above work independently. Ordinary structured sessions remain capped at 64 MiB and use process-cumulative writer health; do not treat those counts as losses from a new manual recording. Archive filenames reflect rotation time, which can differ from session start. A crash can omit the last batch or closing record.

## Exit

Use `Izlaz` on the Speech screen to return to the hotbar or close the whole application. **Postavke > Aplikacija > Isključi aplikaciju** closes the whole application. `Ctrl+Q` works while the hotbar has focus, and `Alt+F4` closes the active application window.
