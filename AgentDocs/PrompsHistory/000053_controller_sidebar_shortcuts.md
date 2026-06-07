# 000053 Controller Sidebar Shortcuts

## Original prompt

On the right side of the Keybaord button in htobar add new button called Controler. Add icon or reomve control there.
When it's clicked it should open up right sidebar which ahs to like for the Keybaord. Make sure it behives like Keyboard
If it's there is some rightsdiber already open close it alwyas befor eopening new one!

On this right sidebar we will have some shortcuts.
It must have following tabs:
  * General
  * Keyboard
  * Speech
  * Settings

In general it must have following actions:
  - Left Click
  - Right Click
  - Double Left click
  - ENTER
  - Scroll up
  - Scroll Down

Make sure those actions are applied correcly when selected!

When keyabord is selected it must show the keyabord

When Speech is selected it must open Speec window

When Settings is selected it must have following settings in there:
  - Ability to turn on and off gaze focuse mode (that thing with zoom in and zoom out)
  - Checkbox for rendering gaze cursor

## What changed

- Added `gaze_mouse/controller_window.py`.
  - Implements a gaze-selectable right-side AppBar panel named `Controler`.
  - Uses the same hit-test methods as `KeyboardWindow`: `action_at_global_point`, `action_center_at_global_point`, `contains_global_point`, `handle_gaze_action`, and `cancel_gaze_interaction`.
  - Includes tabs: `General`, `Keyboard`, `Speech`, and `Settings`.
  - `General` actions:
    - Left Click
    - Right Click
    - Double Left Click
    - ENTER
    - Scroll Up
    - Scroll Down
  - `Keyboard` tab requests the normal right-side Keyboard panel.
  - `Speech` tab opens the fullscreen Speech window.
  - `Settings` tab has checkbox-style buttons with `[X]` state text for:
    - Gaze focus mode / precision zoom
    - Transparent gaze cursor bubble
  - Settings changes are emitted through `gaze_settings_changed` so they use the same saved settings path as the fullscreen settings window.

- Updated `gaze_mouse/toolbar.py`.
  - Added the hotbar `Controler` button to the right of `Keyboard`.
  - Uses a gamepad icon through `qtawesome` with a Qt fallback icon.
  - Added controller window routing to toolbar gaze action lookup and action-center lookup.
  - Added controller window containment checks so gaze over the controller does not move the real Windows cursor.
  - Tracks the last known cursor position outside application UI and passes it to Controler so physical mouse activation of click shortcuts does not click the controller panel itself.
  - Added controller lifecycle methods:
    - `_toggle_controller`
    - `_show_controller_sidebar`
    - `_hide_controller_sidebar`
    - `_controller_window_closed`
    - `_open_keyboard_from_controller`
    - `_open_speech_from_controller`
  - Enforces one right-side sidebar at a time:
    - Opening Keyboard closes Controler.
    - Opening Controler closes Keyboard.
  - Controller panel follows hotbar hidden/shown height behavior, same as Keyboard:
    - Hotbar hidden: controller can use full primary-screen height.
    - Hotbar shown: controller returns to available work-area height and reserves the right AppBar.
  - Controller is closed/cancelled during app shutdown and eye-tracking pause handling.
  - Controller receives updated gaze settings when fullscreen Settings changes them.

- Updated `gaze_mouse/mouse_controller.py`.
  - Added `CONTROLLER = "controller"`.
  - Added the `Controler` action label for dwell-progress text.

- Updated `gaze_mouse/windows_input.py`.
  - Added `GetCursorPos` binding.
  - Added `click_current()` for clicking at the current gaze-controlled cursor position.
  - Added mouse-wheel support with `scroll(units)`.
  - Mouse wheel data is masked to a 32-bit Windows payload so negative scroll deltas are sent correctly.

- Updated `README.md`.
  - Documented the Controler hotbar button.
  - Documented the right-side controller tabs and actions.
  - Documented that only one right-side panel is open at a time.

## What is expected to work

- `Controler` appears to the right of `Keyboard` in the top hotbar.
- Looking at or mouse-clicking `Controler` toggles the right-side controller panel.
- If Keyboard is open, opening Controler closes Keyboard first.
- If Controler is open, opening Keyboard closes Controler first.
- Controller buttons are gaze-selectable and show the existing gaze pulse animation.
- Controller buttons also work with normal mouse clicks.
- `General` actions send native Windows input:
  - Left click at current cursor position.
  - Right click at current cursor position.
  - Double left click at current cursor position.
  - ENTER to the last known external foreground window.
  - Scroll up/down using native mouse wheel input.
- When a click shortcut is selected with a physical mouse, it uses the last cursor position seen outside app UI instead of the mouse position over the controller panel.
- If a physical mouse selection happens before any external cursor target has been recorded, the controller reports that no external cursor target is available and does not click the panel.
- `Keyboard` tab opens the existing right-side Keyboard panel.
- `Speech` tab opens the fullscreen Speech window.
- `Settings` tab toggles precision zoom and gaze cursor visibility and saves changes to `data/app_settings.json`.

## Notes and limitations

- The controller's click shortcuts intentionally click the current Windows cursor position during gaze use. While looking at app UI, the mouse controller preserves the real Windows cursor, so this should click the last external gaze target. Physical mouse activation uses the stored non-app cursor position when available and refuses to click if no external target has been recorded yet.
- Hardware-level Tobii behavior and actual Windows input effects were not executed in this Linux workspace.

## Validation

- Parsed changed Python files with `ast.parse`:
  - `gaze_mouse/windows_input.py`
  - `gaze_mouse/mouse_controller.py`
  - `gaze_mouse/controller_window.py`
  - `gaze_mouse/toolbar.py`
- `py_compile` was initially run and succeeded, but it generated `gaze_mouse/__pycache__`. The generated cache directory and `.pyc` files were removed immediately per repository instructions.
- Verified no `__pycache__`, `.pyc`, or `.pyo` files remain in the workspace after cleanup.
