# User guide

- [Installation readiness](#installation-readiness) and [before starting](#before-starting)
- [Tracking notifications](#tracking-notifications-in-speech) and [gaze check](#gaze-check)
- [Hotbar controls](#hotbar-controls) and [quick actions](#quick-actions)
- [Speech](#speech), [Keyboard](#keyboard), and [Controller](#controller)
- [Settings](#settings) and [updates](#update)
- [Troubleshooting](#troubleshooting) and [exit](#exit)

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

The top-right status uses an icon, color, and visible text. **Praćenje spremno** requires a connected tracker, both eyes and fresh gaze. With the experimental one-eye policy, **Odabir jednim okom** identifies usable application selection with one eye; direct desktop input still needs both. **Odabir na čekanju** identifies the short-interruption hold. **Praćenje pauzirano** keeps both labeled eye indicators visible: a check means valid data and a dash means no valid data. These indicate SDK validity, not physical eye closure or calibration accuracy. **Čekam podatke** reports missing or stale data, **Povezivanje…** reports discovery, and **Uređaj nije povezan** reports automatic retry. Source simulation keeps the **Simulacija mišem** label; its [shortcuts](UI_DEVELOPMENT.md#mouse-gaze-simulation) use synthetic input. Application selection follows the [chosen policy](#eye-tracking-policy).

Missing eye-status delivery pauses input. A prolonged interruption in the x86 bridge or a closed bridge starts automatic reconnection; normal invalid-eye samples do not restart the connection. A direct native connection stays paused until fresh data returns. After a gaze-delivery gap of at least 500 ms, pending selection restarts from zero; time spent waiting cannot confirm the target.

The blue gaze marker follows fresh gaze allowed by the selected policy and expires after 500 ms without a new point. Restored eye indicators alone do not make an old marker position visible again.

## Tracking notifications in Speech

**Postavke > Postavke pogleda > Odabir pogledom > Obavijesti o praćenju pogleda** is on by default, including when loading older settings. Turning it off hides Speech notifications without changing the selected eye-tracking policy or desktop input eligibility.

Speech normally has no notification or reserved empty row. A tracking problem lasting about 0.8 seconds shows a notice in the message header, letter dialog, or deletion confirmation. It distinguishes missing eye data, missing fresh gaze and a disconnected device. Three eye-tracking interruptions of at least 0.35 seconds within 10 seconds can also show **Praćenje često prekida · provjerite položaj uređaja**. These presentation thresholds filter short interruptions; they do not delay cancellation of gaze selection or identify a medical cause.

After eligible eyes and fresh gaze return, **Praćenje se vraća** appears while stability is checked. About half a second of continuous valid tracking changes it to green **Možete nastaviti** for two seconds, then it slides away. Another interruption updates the same notice. Green confirms returned tracking data, not calibration accuracy, and adds no delay to selection. During repeated interruptions, a warning can coexist with usable tracking; **odabir je zaustavljen** appears only while selection lacks eligible data.

The notice takes no focus and requires no acknowledgement. Buttons stay in place and the message field retains its full width; its original height returns when the notice disappears. Rest, Gaze check, Settings and hidden or minimized Speech do not produce these notifications. The existing hotbar status remains independent of this option.

## Gaze check

Open **Postavke > Postavke pogleda > Pokazivač i provjera > Provjera pogleda** to adjust the display and check gaze. A helper operates this optional screen by mouse or keyboard; the gaze user looks at the targets. The selected eye policy is labeled throughout the test. Normal gaze input stays paused while the check is open, including while minimized. **Zatvori** or Escape returns to Settings; the speech message is retained.

1. **Položaj i praćenje** shows each eye, gaze delivery and recent tracking continuity. Adjust the screen with its attached tracker. When the runtime supplies positions, the frame shows the eyes and the bar shows depth from **Bliže uređaju** to **Dalje od uređaja**. A checkmark means inside the reported tracking area, not verified accuracy; a dash means unavailable or stale data. Depth is not measured in centimetres. Position guidance can work before valid gaze returns. If positions are unsupported, use the Tobii app's positioning display; the target tests remain available.
2. **Provjeri preciznost** presents five automatic targets, about three seconds each, at the centre and near the screen corners. Look at each cross; no gaze click is required. Results distinguish **Pogled blizu mete**, **Pogled izvan mete** and **Premalo podataka**. Missing data is not a measured miss. The advice directs the helper to positioning, profile calibration or the button trial. **Prikaži mjerenja** reveals data coverage, error and spread, with explanations. **Prekini test** returns to positioning; **Podesi položaj** or **Ponovi provjeru** clears the results.
3. **Probaj izbor dugmeta** tries three sizes of controls with the current selection pause, dwell time and eye policy. Look at **Pogledaj**, beside two **Drugo** buttons, until the progress bar fills. No click goes to another program. **Pogled je na drugom dugmetu** means gaze is there; **Odabrano je pogrešno dugme** confirms a selection. Progress is green on the intended button and amber on another. A permitted short eye loss freezes progress with a pause mark; other ineligible or missing gaze cancels pending selection. Already completed selections cannot repeat without looking away. Results count correct selections, wrong selections and interrupted pending selections; **Prikaži mjerenja** also shows departures. A timed-out target with insufficient gaze coverage directs the helper to restore tracking. A few isolated samples do not justify asking for a longer stare. Follow the advice to restore tracking, check calibration, retry or try the speech keyboard. **Ponovi probu dugmadi** retains precision results. Individual application controls still need checking in actual use.

**Slobodna provjera** shows nine targets and a green ring for fresh gaze allowed by the selected policy, without timing or a score. Missing or off-screen gaze hides the ring. **Vrati na položaj** returns to positioning. This follows the visual feedback idea in Tobii Core's [Test and recalibrate](https://help.tobii.com/hc/en-us/articles/213891645-Test-and-recalibrate); use the timed test when a measured result is needed.

The [architecture guide](ARCHITECTURE.md#gaze-check-measurements) defines the measurement rules and thresholds. They are application heuristics, not Tobii-certified or clinical assessments. A short loss may be a blink; the app does not diagnose tears, lighting or illness. Recognized positions and the both-eye continuity indicator do not change the selected input policy. Connection loss, minimizing an active test or resizing cancels it. Simulator results are labeled and are not Tobii measurements. The screen discards results on close. An explicitly enabled diagnostic trace can save measurement fields; see [Diagnostic log collection](#diagnostic-log-collection).

**Otvori Tobii postavke** opens the installed Tobii settings and minimizes the check. In Tobii Core, select the user's profile, then **Test and recalibrate > Recalibrate** if needed. This action does not use `TOBII_CALIBRATION_COMMAND` or Ctrl+Shift+F10. Tobii documents that shortcut as [Guest calibration](https://help.tobii.com/hc/en-us/articles/209530409-Create-a-new-user-profile), which uses a temporary profile and does not recalibrate the saved one. The existing installation **Pokreni kalibraciju** and Settings **Pokreni Tobii kalibraciju** actions retain that Guest flow.

Check [Display setup](https://help.tobii.com/hc/en-us/articles/209529969-Display-setup) too: Tobii must use Windows' primary display with correct tracker alignment. If settings cannot open, use the Tobii tray icon beside the clock. Return via the Windows taskbar or **Postavke**, then run a new check. Opening Tobii settings does not confirm calibration completed or change saved app settings. Keep the installed Core or Experience software; this feature requires no switch.

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

Every gaze selection starts with a configurable pause without a progress ring. The default pause is 500 ms and can be adjusted between 100 and 2000 ms. The ring then fills for the configured stare time, so the two default 500 ms values take one second in total. After a control activates, look away from it before returning to select it again. A mouse click remains immediate and cancels any pending gaze selection.

The top edge directly above each hotbar button also selects that button. Gaps between buttons remain neutral. A brief movement near a button edge freezes selection for up to 120 ms, as described under [Speech](#speech); it cannot fire an action outside the target or unlock a completed action for a repeat.

A gaze-driven right click arms one direct left click for selecting a context-menu item. That follow-up click skips precision zoom so the menu stays open.

## Quick actions

Quick actions is a toggle. With precision zoom enabled, holding gaze on a target first opens a magnified square. Choose the exact point inside the square, then use the radial menu:

- Top: left click
- Right: right click
- Bottom: double click
- Left: cancel

With precision zoom disabled, the radial menu opens directly at the stable gaze point. Gaze does not move the real pointer while the zoom or menu is open.

## Speech

For **Standardni**, **Prirodni**, and **Efendija**, **Izgovori** becomes **Zaustavi** in the same position while preparing or speaking. Select it again, or press Enter, to stop without submitting a second request. The message remains available. The stop action stays available while adding a phrase or answer; it does not speak the unfinished saved entry. Completion, failure and stopping restore **Izgovori**. Playback status alone does not verify audible sound.

If a library file cannot be read, **Kategorije** and **Fraze** show **Biblioteka nije učitana** and **Učitaj ponovo**. Available entries still work for composing a message, but adding, deleting, and saving usage counts are blocked to protect the original files. Retry after restoring access to the file; a successful reload restores the library without changing your message. A damaged file must be repaired or restored from a backup before retrying.

Speech opens a full-screen Bosnian keyboard. Select a letter group, then a letter. The message field is ready for typing when Speech opens, after its controls or dialogs are used, and when returning to Speech with Alt+Tab. Returning focus preserves the caret and any selected text. While adding a category, answer, or phrase, typing belongs to that new entry. Modal dialogs and **Odmor** block typing into the message until closed; Settings and other Windows applications keep their focus until you return to Speech. Launch still opens the hotbar. Space and Backspace stay on the bottom row. `Izgovori` sends the current text to the selected speech engine without clearing it. `Kategorije` contains saved groups of answers, while `Fraze` contains standalone reusable text. Both lists support adding and deleting entries with the same grouped keyboard. The conversation message and all category, answer, and phrase content appear and are entered in uppercase. Text typed or pasted with lowercase letters is converted immediately. Settings can show 1 to 12 letters per group. When a group contains 12 letters, the letter dialog uses four columns and a shorter `Nazad` button so all choices fit at 1920×1080 with Windows scaling set to 150%. Selecting a letter returns to the groups as before.

On Speech controls, a brief gaze movement just beyond a button edge freezes the pause or ring instead of clearing it. Returning within 120 ms resumes that progress. The button cannot activate while gaze is outside it. Moving farther away or staying outside longer starts a new selection. This applies to letter groups, letters, word suggestions, and `Izgovori`, as well as the other Speech controls. A brief edge movement does not unlock a button for repeat selection. Returning after the edge tolerance expires permits a repeat with a full new pause and dwell, even if no further gaze sample arrived while outside. Eye loss, mouse actions, changed views, and window resizing still cancel pending progress. A changed word suggestion requires looking away before selecting it.

`Brzi izbor` shows up to five uppercase Bosnian suggestions. It completes the word at the end of the input or adds a next word followed by one space. The suggestions work without internet access, preserve the rest of the message, and never speak automatically. They are inactive while text is selected, the cursor is away from the end, or a category name is being entered.

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

Open **Postavke > Postavke govora**, choose **Efendija**, then **Podesi ElevenLabs**. The ElevenLabs account must have access to the intended ef. Fikret voice and a model supporting Bosnian. The app does not create or clone the voice.

1. Create an ElevenLabs API key with **Text to Speech**, **Voices: Read**, and **Models: Read** enabled. Text to Speech alone cannot load the voice/model choices. **User: Read** is optional for reading the credit balance.
2. Enter the key and select **Sačuvaj ključ**. A successful save hides the input and shows **Ključ je sačuvan**, **Zamijeni ključ**, and **Ukloni ključ**. **Zamijeni ključ** opens an empty masked editor. **Odustani** discards the new input and retains the previous key; **Ukloni ključ** deletes it and opens an empty editor. Windows Credential Manager retains the saved key for the current Windows user across application restarts and updates. A failed save keeps the input masked for retry and preserves the previous credential. Save a replacement before checking it or testing speech; both actions use the saved key.
3. Select **Provjeri vezu**, then choose the intended voice from **Moji glasovi** and a Bosnian model. New settings start with `eleven_v4`; existing saved model choices are retained. The list includes only voices saved in the ElevenLabs account, including saved library voices, rather than the default catalog. If a previously selected voice is absent, select a voice from this list before testing; the app does not replace it automatically. An empty collection shows **Nema glasova**. Add the voice on ElevenLabs and check again. Voice/model selections save automatically. The connection check only reads catalogs and optional account information; it neither generates speech nor proves that Text to Speech is permitted or that audio will play.
4. Choose **Kreativno**, **Prirodno**, or **Stabilno** for **Stabilnost** (0%, 50%, or 100%; default **Prirodno**). Existing percentages load as the nearest choice. **Sličnost glasa** defaults to **80%**; use its slider or large **− / +** buttons to change it by five percentage points. Changes save automatically. Efendija preparation/playback stops when its voice, model or tuning changes; these unused settings do not interrupt Standardni or Prirodni speech.
5. Select **Isprobaj Efendiju** to hear **SELAM. DOBRO MI DOŠLI.** This spends ElevenLabs credits. The test succeeds only with Efendija, without cached audio or a fallback. Confirm similarity, pronunciation and clarity by listening.

The credit bar shows the latest account balance as **Preostalo / limit** and a percentage, yellow below 20% and red below 10%. It refreshes without generating speech when ElevenLabs settings open and after Efendija speech finishes. Enable **User: Read** to see it. Missing permission or a failed request shows **Stanje kredita nije dostupno** and does not disable speech. Account credits do not establish an API key's separate quota or the final cost of the next message.

Settings disable the test button during preparation/playback and provide **Zaustavi**. For the shared Speech button and Enter behavior, see [Speech](#speech).

An explicit permission error identifies missing catalog access separately from an invalid key. A failed check retains the saved key and voice choice. Development overrides `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, and `ELEVENLABS_MODEL_ID` take precedence over saved values; overridden controls are disabled.

Efendija sends sentence-case text to ElevenLabs; square brackets become parentheses to prevent audio-tag interpretation. The displayed message stays unchanged. ElevenLabs may retain the submitted text; zero-retention requests are available only to Enterprise customers. If preparation fails, the same message tries Prirodni (Microsoft's online service), then Standardni (offline), while the selected voice remains Efendija. The display names the voice actually used. Preparation waits at most 30 seconds for ElevenLabs generation and the full audio download, and three seconds for Prirodni before falling back. An interrupted playback preserves the message and requires another **Izgovori**; it does not repeat automatically in another voice. Changing the active Efendija voice, model or tuning cancels its preparation/playback. The five-second connection check only reads catalogs; its success does not measure synthesis time.

After a quota failure, uncached messages use fallback for 60 seconds before retrying ElevenLabs. **Provjeri vezu** can permit an earlier retry if a positive balance is newly available or improved; passive balance refresh does not. After the cooldown, a new **Izgovori** can retry even without User: Read. The green **Efendijin glas je ponovo dostupan** notice disappears after five visible seconds. Tracking warnings take priority; the recovery notice receives a fresh five seconds when it becomes visible again. Key-specific quotas may differ from the account balance. Automatic top-ups are controlled on the ElevenLabs account; disable them there if unwanted.

**Sačuvani zvuk** keeps downloaded Efendija audio when the whole message matches one saved phrase or answer, ignoring case and repeated whitespace. Stopping playback or an output failure retains the clip; unreadable audio is discarded. Repetition works offline without new credits. **Zvuk nije sačuvan** warns that storage failed: speech can finish, but repetition may spend credits. Other messages and combinations are not cached. Editing/deleting an entry removes all its clips. Changing voice, model or tuning retains earlier clips for switching back. The 256 MiB limit removes least recently used clips first. A library read failure disables cache access until a successful retry without deleting clips. **Obriši sačuvani zvuk** removes clips, not phrases or answers; removing the API key does not clear clips. Incompatible cache formats or text-preparation versions require regeneration, which can spend credits. See [storage details](ARCHITECTURE.md#persistent-data-and-logs) for file locations and backup behavior.

### Arabic keyboard

Choose **Arapski** under **Postavke govora > Pismo tastature**, or select `Arapski` on Speech, Keyboard, or the Controller keyboard. The choice applies to all three keyboards and is saved immediately. Select `Latinica` to return. Switching preserves the message, an unfinished phrase or answer, saved entries, and the existing Bosnian voice and gaze settings. Controls remain in Bosnian and keep their established order; this does not translate text or the interface.

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

Changes apply immediately. If saving fails, **Postavke \*** on the hotbar and a persistent notice in Settings indicate that the current values are only active until the app closes. **Pokušaj sačuvati** retries saving the latest values. Changing tabs or reopening Settings keeps the notice until saving succeeds. This also applies to settings changed from the sidebars or Speech.

Windows startup queries and changes run in the background, so other settings remain usable. The startup checkbox follows the latest requested choice while a change is pending. Closing Settings keeps requested Windows changes running while the application remains open. Reopening Settings reads the state after those changes finish. A launcher-window choice made during the initial query also applies to an existing enabled startup task.

General settings controls startup, logging, and whether the PowerShell launcher window stays visible. Start with Windows creates a per-user Scheduled Task that runs the launcher with administrator privileges.

Gaze settings uses these values:

| Setting | Default | Range |
| --- | --- | --- |
| Pause before gaze selection | 250 ms | 100 to 2000 ms |
| Progress-ring fill time after the pause | 850 ms | 150 to 5000 ms |
| Short eye-tracking interruption | 150 ms | 50 to 500 ms, step 50 ms |
| Stable target radius | 48 px | 10 to 160 px |
| Delay between actions | 350 ms | 100 to 5000 ms |
| Pointer smoothing | 1.00 | 0.05 to 1.00 |

**Postavke pogleda** has two tabs. **Odabir pogledom** contains the eye-tracking policy, interruption duration, pause, dwell, cooldown, notifications and action-overlay visibility. **Pokazivač i provjera** contains radius, smoothing, pointer movement, the gaze bubble, precision zoom, calibration and the gaze check. Pointer actions use three equal columns with 58-pixel controls. Existing saved timing values remain unchanged when installing a version with new defaults.

### Eye-tracking policy

Choose **Režim praćenja očiju** in **Postavke > Postavke pogleda > Odabir pogledom**:

| Choice | Behavior |
| --- | --- |
| **Oba oka** | Default, including older settings files. Losing either eye cancels progress. |
| **Oba oka uz kratke prekide** | Starts with both eyes. Losing one eye freezes the current attempt for the selected duration. Both eyes and fresh gaze inside the same unchanged target must return before expiry. |
| **Jedno oko je dovoljno (probno)** | Allows starting and completing an application selection with at least one valid eye and fresh valid gaze coordinates. Without coordinates it waits. Availability on Tobii 4C needs checking on the device. |

**Trajanje kratkog prekida** remains visible and retains its saved value in every mode; it is adjustable only in the second mode. During the hold, the filled arc stays still with a pause mark. It cannot fill or activate. The first returning sample adds no progress. Expiry, losing both eyes, changing the sole tracked eye without fresh both-eye gaze between them, changing the target or its content/geometry, losing the connection, or changing the mode or duration discards pending progress. Completed controls still require looking away before selecting them again. Turning off the progress display hides the arc and its pause mark.

The policy applies to all application gaze controls, including keyboards, dialogs, Settings and Controller click buttons. Direct desktop pointer movement, direct desktop clicks, Quick actions and precision zoom require both eyes in every mode. Controller click buttons keep their existing external pointer target. The gaze check's precision, free view and button trial use the selected policy and display its name; eye indicators and both-eye availability remain actual measurements. The hold contributes no measurement samples. Tracking notices use the chosen eligibility rule and do not report stopped selection solely because one eye is invalid in the experimental mode.

Speech settings controls eSpeak speed (155 words per minute by default, 80 to 320), letters per group (5 by default, 1 to 12), and the voice preset. `Pismo tastature` accepts `Latinica` (the default for existing installations) or `Arapski`. The voice choices appear directly below it. Speed and letters-per-group rows align their `Manje`, value, and `Više` controls in the same columns. The selected voice button stays selected when pressed again. Arabic replaces the Bosnian choices with Hamed while retaining the Bosnian preference. The speed control appears only for Standardni and applies to eSpeak. `Naučene riječi` opens the personal vocabulary. Select one word and then `Zaboravi riječ` to remove its personal ranking contribution without changing messages, phrases, answers, or the bundled dictionary. If learning cannot be read or saved, the page preserves the last file, reports the problem, and offers `Pokušaj ponovo` while normal typing and speech remain usable. Other settings are saved immediately to `data\app_settings.json`.

## Update

In the installed Windows application, open **Postavke > Opće postavke**. The current version is always shown separately from **Verzija za instalaciju**. Settings checks the official stable release list when opened; **Provjeri verzije** refreshes it. A notice identifies a newer stable version. A failed check does not mean your installed version is the latest.

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

When reporting a tracking or selection problem, close the application after the reproduction and send the whole `logs` folder through your agreed support channel. It includes the readable log and structured sessions in `logs\diagnostics`. Note the approximate time, the control you tried to select, and whether someone used the mouse or keyboard. Keep a short video when practical. Archive filenames reflect rotation time, which can differ from the start of the recorded session.

Normal logging collects summaries and selection interruption reasons. For a short, more detailed reproduction, a caregiver can launch from PowerShell with:

```powershell
$env:POGLED_ASSIST_GAZE_DIAGNOSTICS = 'trace'
& 'C:\PogledAssist\PogledAssist.exe'
Remove-Item Env:\POGLED_ASSIST_GAZE_DIAGNOSTICS
```

Close any already-running copy first. Trace lasts at most ten minutes or 32 MiB, then continues with normal logging. The existing **Uključi zapisivanje** setting must be enabled; disabling it also disables trace. No new control is added. Structured sessions have a size limit and can omit records when output is slow; their health records show that loss. A crash can omit the last batch or closing record. Detailed coordinates and button geometry may reveal activity even though the application does not add composed text, spoken messages, suggestion text or key labels to these diagnostic records. Review the folder before sharing it.

## Exit

Use `Izlaz` on the Speech screen to return to the hotbar or close the whole application. Quit app from General settings always closes the application. `Ctrl+Q` works while the hotbar has focus, and `Alt+F4` closes the active application window.
