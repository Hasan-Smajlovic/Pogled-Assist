# Tobii Gaze Mouse

Python hotbar for controlling the Windows mouse pointer with a Tobii Eye Tracker 4C.

## What It Does

- Creates a frameless toolbar at the top of the primary screen.
- Registers that toolbar as a Windows AppBar so maximized windows use the area below it instead of covering it.
- Provides a compact left-side hotbar cluster ordered as Hide, Settings, Quick actions, left click, right click, double click, then Speech, Keyboard, and Controler after a small gap; when hidden, a floating Show button appears at the top left of the screen.
- Subscribes to Tobii gaze samples through `tobii-research`.
- Requires valid tracking from both eyes before gaze can move the cursor or trigger dwell actions.
- Maps gaze to Qt logical coordinates for hotbar/window selection and Windows physical coordinates for actual cursor movement/clicks.
- Moves the mouse pointer with Windows `user32` APIs.
- Shows a transparent gaze bubble over the latest gaze point so tracking position is visible while using the app.
- Shows an animated click-through action overlay while a gaze dwell action is charging and briefly flashes when it fires.
- Lets the user arm left click, right click, or double left click from the toolbar.
- Provides a `Quick actions` toggle that can open a magnified precision square over a stable gaze target, then opens an icon-only radial menu at the refined point for left click, right click, double click, or cancel. When Quick actions is active, the separate left, right, and double-click toolbar buttons are hidden.
- Fires the armed click after the gaze stays stable on the target for the dwell time.
- Pulses gaze-targeted buttons between highlight colors while gaze dwell is active, including hotbar buttons, Speech keyboard buttons, and Settings tabs/controls.
- Shows Speech, Keyboard, Controler, and Settings buttons. Speech opens a full-screen Bosnian speech keyboard that sends text to eSpeak NG. Keyboard toggles an in-app right-side keyboard panel with Bosnian letter groups, numpad keys, symbols, Space, and Backspace. Controler toggles a right-side shortcuts panel for common click, keyboard, scroll, speech, and quick settings actions. Settings opens a full-screen gaze-selectable settings surface for gaze timing, Tobii calibration, speech speed, and letter grouping.

## Requirements

- Windows with the Tobii Eye Tracker 4C connected and calibrated.
- Python 3.10 64-bit. The current `tobii-research` wheel is published for CPython 3.10.
- Python 3.10 32-bit for the Tobii Stream Engine bridge when Tobii Eye Tracking Core Software exposes only 32-bit DLLs. The Windows setup script installs and wires this automatically.
- eSpeak NG with the Bosnian `bs` voice. The Windows setup script installs and verifies this automatically.
- `edge-tts`, which provides the `edge-playback` command used by the optional human-like Bosnian neural voice. The Windows setup script installs and verifies this automatically.
- Tobii runtime/software installed so the tracker can be discovered. The app tries `tobii-research` first and then falls back to Tobii Stream Engine for consumer trackers such as the Tobii Eye Tracker 4C.

## Install

The easiest setup path on Windows is:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1
```

The setup script logs each step, writes `setup_windows.log`, installs Python 3.10 automatically when Python 3.10 is missing, installs 32-bit Python 3.10 for the Tobii Core/Stream Engine bridge, installs eSpeak NG with Bosnian voice support, creates `.venv`, installs all Python dependencies from wheels, verifies the packages including `edge-tts` and `edge-playback`, and pauses before closing whether it succeeds or fails.

If setup is launched from a network share such as `\\192.168.0.30\Tobii`, the script automatically copies the app to a local per-user install folder before creating `.venv`. This avoids Windows `Access is denied` failures that can happen when Python tries to create a virtual environment directly on a UNC path.

Default local install folder:

```text
%LocalAppData%\TobiiGazeMouse
```

The setup also creates:

- `run_gaze_mouse.bat`
- `run_gaze_mouse.ps1`
- `start_gaze_mouse.ps1`
- A desktop shortcut named `Tobii Gaze Mouse`, unless `-NoDesktopShortcut` is used

Python installation is attempted in this order:

- `winget install Python.Python.3.10`
- Direct PowerShell download of the official Python.org 64-bit Python 3.10 installer, followed by silent per-user installation

The direct installer fallback defaults to Python `3.10.11` because that Python 3.10 release has an official 64-bit Windows installer. You can pin that explicitly with `.\setup_windows.ps1 -PythonInstallerVersion 3.10.11` if needed.

eSpeak NG installation is attempted in this order:

- `winget install --id eSpeak-NG.eSpeak-NG --exact --version 1.52.0`
- Direct PowerShell download of `espeak-ng.msi` from the eSpeak NG GitHub release, followed by silent MSI installation

After installation, setup verifies that `espeak-ng.exe --voices=bs` reports Bosnian support. The generated launchers set `ESPEAK_NG_EXE` so the Python program can find the exact verified executable.

The human-like voice is installed through the Python `edge-tts` package. Setup verifies that `.venv\Scripts\edge-playback.exe` exists and generated launchers set `EDGE_PLAYBACK_EXE` so the Python program can find it without relying on the system PATH. The configured preset uses:

```powershell
edge-playback --voice bs-BA-GoranNeural --rate=-10% --pitch=-2Hz --text "Dobar dan. Ovo zvuči mnogo prirodnije."
```

The script installs the Python side of the app. The Tobii Eye Tracker 4C still needs to be connected, visible in Tobii software, and calibrated on the Windows machine.

For Tobii Eye Tracker 4C tracking, the runtime log should show either `Tracking with ...` from `tobii-research`, `Tobii Stream Engine backend started ...`, or `Tobii Stream Engine x86 bridge started ...`. If `tobii-research` reports no devices, the app now retries automatically and tries the Stream Engine DLL fallback. Tobii Eye Tracking Core Software 2.x often installs 32-bit DLLs under `Program Files (x86)`, which cannot be loaded by the 64-bit GUI Python process. In that case the launcher sets `TOBII_GAZE_MOUSE_X86_PYTHON`, and the app starts a 32-bit helper process to read gaze samples and send them back to the main app.

If Stream Engine cannot be found, install Tobii Core/Game Hub or place `tobii_stream_engine.dll` under `tools\tobii` in the project before rerunning setup. You can also point directly to the DLL:

```powershell
$env:TOBII_STREAM_ENGINE_DLL = "C:\Path\To\tobii_stream_engine.dll"
.\start_gaze_mouse.ps1
```

If the runtime log shows `[WinError 193] %1 is not a valid Win32 application`, rerun setup so it installs the 32-bit bridge runtime:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1
```

If you do not want the final pause because you are already running inside a terminal:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1 -NoPause
```

To set up and immediately launch the app:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1 -Launch
```

If you want setup to fail instead of trying to install Python automatically:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1 -SkipPythonInstall
```

To force setup to use the current source folder instead of copying to the local install folder:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1 -UseSourceFolder
```

To choose a custom local install folder:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup_windows.ps1 -InstallRoot C:\TobiiGazeMouse
```

Manual setup:

```powershell
winget install --id eSpeak-NG.eSpeak-NG --exact --version 1.52.0 --silent --accept-package-agreements --accept-source-agreements
py -3.10 -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install --no-compile --only-binary=:all: -r requirements.txt
```

## Run

```powershell
.\start_gaze_mouse.ps1
```

`start_gaze_mouse.ps1` is the normal post-install launcher. It finds the installed app under `%LocalAppData%\TobiiGazeMouse`, recreates the `Tobii Gaze Mouse` desktop shortcut if needed, sets `ESPEAK_NG_EXE` when eSpeak NG is installed, points runtime logs back to the original source folder recorded during setup, and starts the app from the local `.venv`.

The application icon is loaded from `assets\icon.png`. Setup copies this asset to the installed app folder, and the PowerShell launchers create `assets\icon.ico` from it when they build the Windows desktop shortcut.

The Speech toolbar button opens a full-screen speech window. By default, the first keyboard level shows Bosnian letters split into groups of five:

```text
A B C Č Ć
D Dž Đ E F
G H I J K
L Lj M N Nj
O P R S Š
T U V Z Ž
```

Select a group to open its letters, then select a letter to append it to the input. The speech keyboard keeps all letter groups in the top grid, including the final shorter group when the configured group size does not divide the Bosnian alphabet evenly. Space and Backspace stay in the bottom utility row. Clear and Play are next to the input at the top. Play sends the input to the selected voice engine and leaves the text in the input so it can be replayed or edited. All speech-window buttons work with normal mouse clicks and with Tobii gaze dwell selection. Speech speed, letters per group, and voice preset can be adjusted from Settings. The hotbar Keyboard button uses the same Bosnian letter grouping setting for its right-side typing panel.

The Speech window also has a `Phrases` button to the left of the input. `Phrases` opens a list of saved common phrases sorted by most-used first. Each phrase row has the phrase button on the left and a `Delete` button on the right. Selecting a phrase appends it to the speech input followed by a space and increases that phrase's usage count. `New phrase` stays centered under the input and opens phrase-creation mode using the same Bosnian letter keyboard; `Save phrase` stores the current phrase, and `Cancel` returns to the phrase list without saving. Phrase pages show up to eight phrases. When there are more saved phrases than fit on one page, `Previous` appears on the left side of the `New phrase` row and `Next` appears on the right side. Each page button is visible only when that direction has another page. Saved phrases and usage counts are stored as UTF-8 JSON under:

```text
data\speech_phrases.json
```

The Keyboard toolbar button is a toggle. When enabled, it opens a right-side panel styled like the hotbar. While the hotbar is visible, the keyboard reserves the right work area as an AppBar. When the hotbar is hidden, the keyboard skips the right AppBar reservation and expands to the full primary-screen height. The panel has tabs for `Letters`, `Numpad`, and `Symbols`. `Letters` uses the same Bosnian letter groups as Speech settings. `Numpad` provides digit/operator keys, and `Symbols` provides common special characters such as `. , @ / ? ! $ % & * ( ) - _ + = : ; ' " # \ | < > [ ] { } ~ \` ^`. Space and Backspace stay available at the bottom. The panel works with gaze dwell and normal mouse clicks. When the hotbar is shown again, the keyboard returns to the available work-area height below the hotbar and reserves the right work area again.

The Controler toolbar button is also a toggle and opens a right-side panel using the same gaze dwell and normal mouse click behavior as the Keyboard panel. Opening Keyboard closes Controler, and opening Controler closes Keyboard, so only one right-side panel reserves screen space at a time. The Controler panel has tabs for `General`, `Keyboard`, `Speech`, and `Settings`. `General` includes icon buttons for Left Click, Right Click, Double Left Click, ENTER, Scroll Up, and Scroll Down. Click shortcuts act at the current gaze-controlled cursor position; if selected with a physical mouse, they use the last known non-app cursor position so the controller panel is not re-clicked. ENTER restores the last external target window before pressing Enter, and scroll uses native Windows mouse-wheel input. The `Keyboard` tab renders Letters, Numpad, and Symbols keyboard controls inside the same Controler sidebar, leaving the main `General`, `Keyboard`, `Speech`, and `Settings` tabs visible. The `Speech` tab opens the full-screen Speech window. The `Settings` tab provides checkbox-style toggles for `Gaze focus mode` precision zoom and the transparent `Gaze cursor`; both update the saved app settings immediately.

The Settings toolbar button opens a full-screen settings window with large gaze-selectable controls:

- `General settings` controls application startup, logging, and launcher visibility. `Start with Windows as Administrator` creates or removes a per-user Windows Scheduled Task named `Tobii Gaze Mouse`. The task starts `start_gaze_mouse.ps1` at logon with highest privileges. The launcher also self-elevates when started manually from the desktop shortcut. `Enable logging` controls whether the Python app writes runtime logs to `logs/latest.txt`; disabling it reduces file and console logging work. `Show PowerShell launcher window` controls whether future launches keep the PowerShell console visible. Checked means the launcher window stays visible and pauses on failures when appropriate; unchecked means the launcher hides its console and runs silently in the background while still writing `start_gaze_mouse.log`.
- `Gaze settings` changes stare time, stable target radius, repeat delay, pointer smoothing, whether gaze moves the mouse pointer, whether the transparent gaze bubble is visible, whether the animated action overlay is visible, and whether precision zoom is used. `Use precision zoom` controls the zoom square used for quick actions. When enabled, quick actions use zoom before the radial action menu and normal armed `Left click`, `Right click`, and `Double click` modes also open zoom before firing the click. When disabled, quick actions open the radial menu directly and normal armed click modes fire directly after dwell. Lower stare time and repeat delay make clicks fire faster; higher pointer smoothing makes cursor movement more delayed.
- `Gaze settings` also has `Start Tobii calibration`. On Windows it hides the fullscreen Settings window, looks for the installed Tobii Start Menu shortcut or Tobii configuration executable, opens the Tobii UI, then sends Tobii's `Ctrl+Shift+F10` calibration shortcut. If the target machine needs a custom command, set `TOBII_CALIBRATION_COMMAND` before starting the app.
- `Speech settings` changes eSpeak NG speech speed and the number of Bosnian letters shown in each speech-keyboard group.
- `Voice settings` selects the speech voice preset. `Default` uses eSpeak NG and is selected by default. `Human like` uses `edge-playback` with the Bosnian neural voice `bs-BA-GoranNeural`, rate `-10%`, and pitch `-2Hz`. The voice dropdown works with normal mouse selection and gaze dwell; gaze dwell cycles to the next voice.
- The `Exit` button is at the top left and closes Settings. The `Quit app` button is on the right side of the `General settings` header row and closes the whole application. Both work with normal mouse clicks and Tobii gaze dwell selection.

General, gaze, and speech settings are saved immediately when changed and loaded again when the app starts. They are stored as UTF-8 JSON under:

```text
data\app_settings.json
```

## Logs

Every program run writes runtime logs to:

```text
logs\latest.txt
```

When setup was launched from a network project folder and copied the app to `%LocalAppData%\TobiiGazeMouse`, `start_gaze_mouse.ps1` reads `install_info.json` and writes runtime logs back to that original source/network folder. The launcher itself also writes:

```text
start_gaze_mouse.log
```

So in the network-share workflow, check these files in the project folder on the share:

```text
start_gaze_mouse.log
logs\latest.txt
```

When the program starts, an existing `logs\latest.txt` is copied to a timestamped archive beside it before the new latest log is opened. Archive names use this format:

```text
logs\YYYYMMDD_HHMMSS_microseconds.txt
```

The app logs startup details, Qt messages, toolbar events, Tobii connection status, mouse actions, errors, uncaught Python exceptions, and stdout/stderr output.

Look at a toolbar button for the dwell time to activate it, or click it normally with a mouse. Buttons pulse between highlight colors while gaze is resting on them, and a click-through action overlay shows dwell progress over the current target. Every gaze-selectable toolbar, speech, and settings button is also a normal clickable Qt button. Mouse clicking a click-mode button arms that mode; clicking the same mode again unarms it. After selecting Left click, Right click, or Double click, look at the target location until the dwell action fires. For desktop targets and icons, the action overlay locks onto the stable gaze point while the armed click is charging. The click mode resets after one click to reduce accidental repeats.

Gaze-selecting controls inside this application does not move the real Windows cursor. This keeps desktop context menus and similar popups open while the user looks back at the hotbar to arm another action.

After a gaze-driven right click, the app automatically arms a direct left click for menu selection and bypasses precision zoom for that one follow-up click. This lets the user open a desktop/app context menu and select an item from it without the menu being closed by the toolbar or zoom overlay.

The left side of the hotbar is ordered as `Hide`, `Settings`, `Quick actions`, `Left click`, `Right click`, `Double click`, then a small gap before `Speech`, `Keyboard`, and `Controler`. Hiding the hotbar unregisters the Windows AppBar reservation so the desktop work area returns to normal. A floating `Show` button appears near the top left of the primary screen and works with both gaze dwell and normal mouse clicks. Runtime status and applied-action details continue to be written to the logs instead of being shown in the hotbar. The right side shows two white eye dots beside the tracker connection dot. The left white dot represents the left eye and the right white dot represents the right eye; a closed or invalid eye is not rendered. The connection dot is green for active tracking, yellow for waiting/retrying/fallback startup, and red when the tracker connection has failed or is unavailable.

Gaze control is active only when both eye dots are visible. If either eye closes or becomes invalid, the app stops emitting gaze positions to the mouse controller, cancels active dwell progress, closes active Quick actions overlays, and leaves the real cursor at its last position until both eyes are valid again. Normal mouse clicks on the application UI still work.

The `Quick actions` toolbar button is a toggle. When it is on and `Use precision zoom` is enabled, looking steadily at a desktop/app target first opens a square zoom view of the selected area. Look steadily inside that zoom square to choose the exact point. The zoom selection maps back to the real desktop/app coordinate, then the icon-only radial menu opens centered on that refined point. When precision zoom is disabled, the radial menu opens directly at the stable target. The four sectors have equal angles:

- Top sector: left click.
- Right sector: right click.
- Bottom sector: double left click.
- Left sector: cancel.

After the menu opens, look steadily in the desired sector direction from the menu center until the normal gaze dwell completes. The selection uses the angle from the refined zoom target point, so the gaze does not need to stay inside the visible circle, but it does need to remain stable inside that sector. While the zoom square or radial menu is open, the real mouse cursor is not moved by gaze; the selected click is applied to the refined real-screen point from the zoom step, not to the later sector gaze point. The zoom square and menu also accept normal mouse clicks.

Press `Ctrl+Q` while the toolbar has focus to close the app. `Alt+F4` also works on Windows.

## Current Limitations

- The AppBar desktop reservation only works on Windows. On other operating systems the toolbar can show, but it cannot push the desktop work area down.
- Multi-monitor support assumes the Tobii-calibrated display is the primary screen.
- Tobii calibration launch depends on Tobii Core/Experience software being installed. The app searches common Tobii install and Start Menu locations, but product-specific Tobii builds may still require `TOBII_CALIBRATION_COMMAND`.
- The executable bundle has not been created yet.

## Later EXE Bundle

When the script behavior is confirmed on the Tobii machine, it can be bundled with PyInstaller:

```powershell
python -m pip install pyinstaller
pyinstaller --noconsole --onefile --name TobiiGazeMouse run_gaze_mouse.py
```
