# User guide

## Installation readiness

After installation, **Provjera instalacije** shows whether the speech tools and
Tobii bridge are ready, whether Tobii software was found, and whether Windows
recognizes a connected Tobii device. It does not verify gaze accuracy or finish
personal calibration. Detection errors appear as **Nije provjereno**.

The person setting up the computer can use **Preuzmi Tobii softver** to open the
official download page, **Pokreni kalibraciju** to request calibration through
installed Tobii software, and **Ponovi provjeru** after making changes. Nothing
is downloaded or calibrated automatically. Use mouse or keyboard in this setup
window; gaze tracking starts in the main application.

You can close the summary and reopen it with
`PogledAssist.exe --installation-check`. Standard speech is available offline;
the natural voice still requires internet.

Pogled Assist places a toolbar at the top of the primary Windows display. It
can move the pointer from gaze, select its own controls by dwell, and perform a
click after you hold your gaze on a stable target.

## Before starting

Opening the app again keeps the existing instance and its current focus. It
does not start another tracker, keyboard, or copy of the saved data.

Connect and calibrate the Tobii Eye Tracker 4C with the matching Tobii software.
The app tries these tracking backends in order:

1. Tobii Pro SDK through `tobii-research`.
2. A directly loadable Tobii Stream Engine DLL.
3. The optional 32-bit Python bridge for 32-bit Stream Engine installations.

The top-right status uses an icon, color, and visible text. **Praćenje spremno**
requires a connected tracker, valid data from both eyes, and fresh gaze data.
**Praćenje pauzirano** keeps both labeled eye indicators visible: a check means
valid data and a dash means no valid data. This does not identify whether an eye
is physically open or closed, or confirm calibration accuracy.
**Čekam podatke** reports missing or stale data, **Povezivanje…** reports discovery,
and **Uređaj nije povezan** reports automatic retry. Source simulation instead
shows **Simulacija mišem**, without pretending that Tobii eyes were measured.
Gaze control pauses when either eye becomes invalid.
It also pauses if Stream Engine stops sending eye status. A prolonged interruption
in the x86 bridge or a closed bridge starts automatic reconnection; normal
invalid-eye samples do not restart the connection. A direct native connection
stays paused until fresh data returns. After a gap in gaze delivery, selection
starts again from zero rather than confirming a target using time spent waiting.

## Tracking notifications in Speech

**Postavke > Postavke pogleda > Obavijesti o praćenju pogleda** is on by
default, including when loading settings from an older release. Turn it off to
hide Speech notifications; the both-eye safety rule still applies immediately.

Speech normally has no notification or reserved empty row. A tracking problem
lasting about 0.8 seconds shows a notice in the message header, letter dialog,
or deletion confirmation. It distinguishes missing eye data, missing fresh gaze
and a disconnected device. Three eye-tracking interruptions of at least 0.35 seconds within
10 seconds can also show **Praćenje često prekida · provjerite položaj uređaja**.
These presentation thresholds filter short interruptions; they do not delay
cancellation of gaze selection or identify a medical cause.

After both eyes and fresh gaze return, **Praćenje se vraća** appears while
stability is checked. About half a second of continuous valid tracking changes
it to green **Možete nastaviti** for two seconds, then it slides away. Another
interruption updates the same notice. Green confirms that tracking data has
returned, not calibration accuracy. It adds no waiting time to normal selection.
During repeated interruptions, a warning can coexist with usable tracking;
**odabir je zaustavljen** appears only while selection lacks valid data.

The notice takes no focus and requires no acknowledgement. Buttons stay in
place and the message field retains its full width; its original height returns
when the notice disappears. Rest, Gaze check, Settings and hidden or minimized
Speech do not produce these notifications. The existing hotbar status remains
independent of this option.

## Gaze check

Open **Postavke > Postavke pogleda > Provjera pogleda** to adjust the display
and check gaze. A helper operates this optional screen by mouse or keyboard;
the gaze user looks at the targets. Normal gaze input stays paused while the
check is open, including while minimized. **Zatvori** or Escape returns to
Settings; the speech message is retained.

1. **Položaj i praćenje** shows each eye, gaze delivery and recent tracking
   continuity. Adjust the screen with its attached tracker. When the runtime
   supplies positions, the frame shows the eyes and the bar shows depth from
   **Bliže uređaju** to **Dalje od uređaja**. A checkmark means inside the
   reported tracking area, not verified accuracy; a dash means unavailable or
   stale data. Depth is not measured in centimetres. Position guidance can work
   before valid gaze returns. If positions are unsupported, use the Tobii app's
   positioning display; the target tests remain available.
2. **Provjeri preciznost** presents five automatic targets, about three seconds
   each, at the centre and near the screen corners. Look at each cross; no gaze
   click is required. Results distinguish **Pogled blizu mete**, **Pogled izvan
   mete** and **Premalo podataka**. Missing data is not a measured miss.
   The advice directs the helper to positioning, profile calibration or the
   button trial. **Prikaži mjerenja** reveals data coverage, error and spread,
   with explanations. **Prekini test** returns to positioning; **Podesi položaj**
   or **Ponovi provjeru** clears the results.
3. **Probaj izbor dugmeta** tries three sizes of controls with the current
   selection pause and dwell time. Look at **Pogledaj**, beside two **Drugo**
   buttons, until the progress bar fills. No click goes to another program.
   **Pogled je na drugom dugmetu** means gaze is there; **Odabrano je pogrešno
   dugme** confirms a selection. Progress is green on the intended button and
   amber on another. Eye loss or missing gaze cancels pending progress without
   repeating an already completed selection. Results count correct selections,
   wrong selections and interrupted pending selections; **Prikaži mjerenja**
   also shows departures. A timed-out target with insufficient gaze coverage
   directs the helper to restore tracking. A few isolated samples do not justify
   asking for a longer stare.
   Follow the advice to restore tracking, check calibration, retry
   or try the speech keyboard. **Ponovi probu dugmadi** retains precision
   results. Individual application controls still need checking in actual use.

**Slobodna provjera** shows nine targets and a green ring for fresh gaze from
both eyes, without timing or a score. Missing or off-screen gaze hides the ring.
**Vrati na položaj** returns to positioning. This follows the visual feedback
idea in Tobii Core's [Test and recalibrate](https://help.tobii.com/hc/en-us/articles/213891645-Test-and-recalibrate);
use the timed test when a measured result is needed.

The [architecture guide](ARCHITECTURE.md#gaze-check-measurements) defines the
measurement rules and thresholds. They are application heuristics, not
Tobii-certified or clinical assessments. A short loss may be a blink; the app
does not diagnose tears, lighting or illness. Neither recognizing the eyes nor
the continuity indicator relaxes the both-eye input rule. Connection loss,
minimizing an active test or resizing cancels it. Simulator results are labeled
and are not Tobii measurements. Results stay in memory and are discarded on close.

**Otvori Tobii postavke** opens the installed Tobii settings and minimizes the
check. In Tobii Core, select the user's profile, then **Test and recalibrate >
Recalibrate** if needed. This action does not use `TOBII_CALIBRATION_COMMAND`
or Ctrl+Shift+F10. Tobii documents that shortcut as
[Guest calibration](https://help.tobii.com/hc/en-us/articles/209530409-Create-a-new-user-profile),
which uses a temporary profile and does not recalibrate the saved one.
The existing installation **Pokreni kalibraciju** and Settings
**Pokreni Tobii kalibraciju** actions retain that Guest flow.

Check [Display setup](https://help.tobii.com/hc/en-us/articles/209529969-Display-setup)
too: Tobii must use Windows' primary display with correct tracker alignment.
If settings cannot open, use the Tobii tray icon beside the clock. Return via
the Windows taskbar or **Postavke**, then run a new check. Opening Tobii settings
does not confirm calibration completed or change saved app settings. Keep the
installed Core or Experience software; this feature requires no switch.

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

Hide removes the AppBar reservation and the entire hotbar, including its tracking
status. It leaves a floating Show button near the top-left corner. Show restores
the hotbar and its current status. The status is passive and has no dwell action,
blinking animation, or sound during eye loss. Left, Right, and Double click arm
one action. Keep your gaze on the target until the progress overlay completes.
The mode resets after the click
to reduce accidental repeats.

Every gaze selection starts with a configurable pause without a progress ring.
The default pause is 500 ms and can be adjusted between 100 and 2000 ms. The ring
then fills for the configured stare time, so the two default 500 ms values take
one second in total. After a control activates, look away from it before returning
to select it again. A mouse click remains immediate and cancels any pending gaze
selection.

The top edge directly above each hotbar button also selects that button. Gaps
between buttons remain neutral. A brief movement near a button edge freezes
selection for up to 120 ms, as described under [Speech](#speech); it cannot fire
an action outside the target or unlock a completed action for a repeat.

A gaze-driven right click arms one direct left click for selecting a context-menu
item. That follow-up click skips precision zoom so the menu stays open.

## Quick actions

Quick actions is a toggle. With precision zoom enabled, holding gaze on a target
first opens a magnified square. Choose the exact point inside the square, then use
the radial menu:

- Top: left click
- Right: right click
- Bottom: double click
- Left: cancel

With precision zoom disabled, the radial menu opens directly at the stable gaze
point. Gaze does not move the real pointer while the zoom or menu is open.

## Speech

**Izgovori** reports when speech is starting, running, finished, or failed.
A failure leaves the message available for another attempt. Process completion
does not verify audible playback. Starting a new message stops the previous
speech and its helper processes.

If a library file cannot be read, **Kategorije** and **Fraze** show
**Biblioteka nije učitana** and **Učitaj ponovo**. Available entries still work
for composing a message, but adding, deleting, and saving usage counts are
blocked to protect the original files. Retry after restoring access to the
file; a successful reload restores the library without changing your message.
A damaged file must be repaired or restored from a backup before retrying.

Speech opens a full-screen Bosnian keyboard. Select a letter group, then a letter.
The message field is ready for typing when Speech opens, after its controls or
dialogs are used, and when returning to Speech with Alt+Tab. Returning focus
preserves the caret and any selected text. While adding a category, answer, or
phrase, typing belongs to that new entry. Modal dialogs and **Odmor** block typing
into the message until closed; Settings and other Windows applications keep
their focus until you return to Speech. Launch still opens the hotbar.
Space and Backspace stay on the bottom row. `Izgovori` sends the current text to
the selected speech engine without clearing it. `Kategorije` contains saved groups
of answers, while `Fraze` contains standalone reusable text. Both lists support
adding and deleting entries with the same grouped keyboard. The conversation
message and all category, answer, and phrase content appear and are entered in
uppercase. Text typed or pasted with lowercase letters is converted immediately.
Settings can show 1 to 12 letters per group. When a group contains 12 letters,
the letter dialog uses four columns and a shorter `Nazad` button so all choices
fit at 1920×1080 with Windows scaling set to 150%. Selecting a letter returns
to the groups as before.

On Speech controls, a brief gaze movement just beyond a button edge freezes the
pause or ring instead of clearing it. Returning within 120 ms resumes that
progress. The button cannot activate while gaze is outside it. Moving farther
away or staying outside longer starts a new selection. This applies to letter
groups, letters, word suggestions, and `Izgovori`, as well as the other Speech
controls. A brief edge movement does not unlock a button for repeat selection.
Returning after the edge tolerance expires permits a repeat with a full new
pause and dwell, even if no further gaze sample arrived while outside.
Eye loss, mouse actions, changed views, and window resizing still cancel pending
progress. A changed word suggestion requires looking away before selecting it.

`Brzi izbor` shows up to five uppercase Bosnian suggestions. It completes the
word at the end of the input or adds a next word followed by one space. The
suggestions work without internet access, preserve the rest of the message, and
never speak automatically. They are inactive while text is selected, the cursor
is away from the end, or a category name is being entered.

`Poništi riječ` restores the exact text from before the most recent suggestion.
It remains available until the text is otherwise edited, even after `Izgovori`.
If `.`, `,`, `?`, or `!` is entered immediately after a suggestion, the keyboard
removes only the space it added and places the punctuation after the word. A
period or question mark then adds one space automatically, so the next sentence
can begin without selecting `Razmak`.

The offline dictionary also includes reviewed Bosnian Islamic terminology and
common phrases for worship, Qur'an and hadith, Ramadan and Bajram, mosque and
community life, Islamic scholarship, and the user's experience as an imam. For
example, typing `KUR` offers `KUR'AN`, while phrases such as `POMOZI MI DA UZMEM`
can offer `ABDEST`. Personal learning continues to adapt these results locally.

The same suggestions are available while adding a phrase or category answer.
That editor has its own undo state and cannot replace the saved conversation
message. A phrase or answer contributes to personal learning only after it is
successfully saved. Category names are never learned.

The controls on the right remain available while browsing or adding entries:

- `Alarm` stops speech, repeats a distinct local emergency sound, and opens a dialog. Select
  `Zaustavi alarm` to silence it and return to the same Speech state.
- `Odmor` stops speech and blacks out the display. Select `Nastavi` by gaze or
  mouse to restore the message, current list and page, and any unfinished entry.
- `Izlaz` offers three choices. `Odustani` returns to the same state, `Izađi`
  closes only Speech mode while preserving the conversation message, and
  `Ugasi aplikaciju` closes the whole application through its normal shutdown
  path.

Saved categories, answers, and phrases use UTF-8 text. Selecting an answer or
phrase appends it to the message, and saved phrases remain ordered by usage count.
The full library is stored in `data\speech_library.json`. The app also maintains
`data\speech_phrases.json` so older releases can read standalone phrases during
rollback. Personal word and short-context counts are stored locally in
`data\speech_learning.json`; message transcripts are not stored.

The Default voice uses eSpeak NG with the Bosnian `bs` voice. Human like uses
`edge-playback` with `bs-BA-GoranNeural` and requires internet access.

### Arabic keyboard

Choose **Arapski** under **Postavke govora > Pismo tastature**, or select
`Arapski` on Speech, Keyboard, or the Controller keyboard. The choice applies
to all three keyboards and is saved immediately. Select `Latinica` to return.
Switching preserves the message, an unfinished phrase or answer, saved entries,
and the existing Bosnian voice and gaze settings. Controls remain in Bosnian
and keep their established order; this does not translate text or the interface.

Arabic uses the same group-then-letter selection. Letters and the message read
right to left, with normal Unicode shaping. `Brojevi i znakovi` in Speech and
the Numbers and Symbols tabs in the side panels include both `0123456789`
and Arabic-Indic digits, Arabic punctuation, vowel and tanwin marks, shadda,
sukun, dagger alif, extended marks, and combining Quranic signs. Symbols in
Arabic Speech are grouped, and long group lists in side panels use
`Prethodna` and `Sljedeća` to keep gaze targets large. A dotted circle makes
standalone marks visible on buttons; only the actual mark is entered.
`Obriši slovo` removes the last entered character, so a mark can be corrected
without removing its letter. Mixed Arabic and Latin text is preserved.

Both Latin and Arabic side-panel keyboards show at most eight groups per page,
including when **Broj slova u grupi** is set to one or two. Selecting a character
returns to the same page. Changing the script or keyboard tab returns to page one.

Arabic has no word suggestions or new personal learning in this release.
Returning to Latin restores the existing Bosnian suggestions and learned data.

Arabic Speech uses the natural male **Hamed** voice (`ar-SA-HamedNeural`)
through the already included `edge-playback` tool. It requires internet and
sends the spoken text to Microsoft's speech service, like the existing natural
Bosnian voice. No Windows Arabic keyboard layout, new model download, or
additional speech installation is required. The standard/natural Bosnian choice
is retained for returning to Latin. Arabic does not silently use a Bosnian or
offline voice if the natural voice is unavailable: Speech reports that the
selected voice is unavailable and preserves the message for retry.

Automated checks verify Unicode entry, switching, layout, and voice commands.
They do not establish audible playback, pronunciation, online service
availability, external application text direction, or physical Tobii accuracy.
Review those on the target Windows machine at 1920 × 1080 and 150% scaling
using the [development checklist](DEVELOPMENT.md#ui-review).

## Keyboard

Keyboard opens a right-side panel with Letters, Numpad, and Symbols tabs. The
panel sends normal Windows keyboard input to the last external foreground window.
It reserves the right work area while the hotbar is visible and expands to the
full screen height while the hotbar is hidden.
Its controls use the same brief edge tolerance as [Speech](#speech). Changing
groups, hiding or resizing the panel, or losing either eye cancels pending
selection.

## Controller

Controller opens a right-side panel with General, Keyboard, Speech, and Settings
tabs. General provides left, right, and double-click actions, Enter, and scrolling.
The embedded Keyboard tab contains the same letters, numpad, and symbols controls.
Only Keyboard or Controller can reserve the right work area at one time.

## Settings

Changes apply immediately. If saving fails, **Postavke \*** on the hotbar and
a persistent notice in Settings indicate that the current values are only
active until the app closes. **Pokušaj sačuvati** retries saving the latest
values. Changing tabs or reopening Settings keeps the notice until saving
succeeds. This also applies to settings changed from the sidebars or Speech.

General settings controls startup, logging, and whether the PowerShell launcher
window stays visible. Start with Windows creates a per-user Scheduled Task that
runs the launcher with administrator privileges.

Gaze settings uses these values:

| Setting | Default | Range |
| --- | --- | --- |
| Pause before gaze selection | 500 ms | 100 to 2000 ms |
| Progress-ring fill time after the pause | 500 ms | 150 to 5000 ms |
| Stable target radius | 48 px | 10 to 160 px |
| Delay between actions | 350 ms | 100 to 5000 ms |
| Pointer smoothing | 1.00 | 0.05 to 1.00 |

The same page controls pointer movement from gaze, gaze bubble and action overlay
visibility, precision zoom, and Tobii calibration launch.
These actions use three equal columns. Calibration occupies one cell, and all
action controls keep the same height for selection by gaze.

Speech settings controls eSpeak speed (155 words per minute by default, 80 to
320), letters per group (5 by default, 1 to 12), and the voice preset.
`Pismo tastature` accepts `Latinica` (the default for existing installations)
or `Arapski`. `Glas` appears directly below it. Speed and letters-per-group rows
align their `Manje`, value, and `Više` controls in the same columns.
The voice preset is retained but disabled while Arabic uses Hamed;
the speed setting continues to apply to the standard Bosnian eSpeak voice.
`Naučene riječi` opens the personal vocabulary. Select one word and then
`Zaboravi riječ` to remove its personal ranking contribution without changing
messages, phrases, answers, or the bundled dictionary. If learning cannot be
read or saved, the page preserves the last file, reports the problem, and offers
`Pokušaj ponovo` while normal typing and speech remain usable. Other settings are
saved immediately to `data\app_settings.json`.

## Update

Close Pogled Assist, open PowerShell in `C:\PogledAssist`, and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\update_windows.ps1
```

The updater requests Administrator access, compares the installed `VERSION` with
the latest stable GitHub Release, verifies the downloaded ZIP against its
published SHA-256 file, and tests the new application before replacing the old
one. Settings, saved phrases, logs, and installation metadata are preserved. If
the download, checksum, staging, or installed smoke test fails, the previous
installation remains available. Rerun the same command after an interrupted
update so the installer can recover the saved transaction.

An older source installation has the previous updater, so download and install
the first stable release manually to migrate it to the packaged channel. Its
installer keeps user data and local runtime components. Later updates never
install a repository branch, draft, or prerelease.

## Troubleshooting

If no tracker is found, confirm that Tobii software sees the device and that it is
calibrated. The runtime log should eventually include `Tracking with`,
`Stream Engine backend started`, or `x86 bridge started`.

If the log contains `[WinError 193] %1 is not a valid Win32 application`, the Tobii
DLL is probably 32-bit. Rerun source setup or configure a 32-bit Python 3.10 path:

```powershell
$env:POGLED_ASSIST_X86_PYTHON = "C:\Path\To\Python310-32\python.exe"
```

An existing `TOBII_GAZE_MOUSE_X86_PYTHON` setting from the previous app is also
accepted when it points to a valid 32-bit Python 3.10. The new setting takes
priority if both are present.

If Stream Engine is installed outside a common location:

```powershell
$env:TOBII_STREAM_ENGINE_DLL = "C:\Path\To\tobii_stream_engine.dll"
```

If calibration needs a product-specific command, set
`TOBII_CALIBRATION_COMMAND` before launching the app. This override belongs to
the existing Guest calibration action, which still sends Ctrl+Shift+F10 after
requesting the command. It is not used by **Otvori Tobii postavke**.

Runtime diagnostics are written to `logs\latest.txt` when logging is enabled.
The launcher writes `start_gaze_mouse.log` even when its window is hidden.
Updater diagnostics are appended to `update_windows.log` in the installation
folder.

## Exit

Use `Izlaz` on the Speech screen to return to the hotbar or close the whole
application. Quit app from General settings always closes the application.
`Ctrl+Q` works while the hotbar has focus, and `Alt+F4` closes the active
application window.
