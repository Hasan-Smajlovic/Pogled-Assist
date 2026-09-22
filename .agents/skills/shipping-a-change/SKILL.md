---
name: shipping-a-change
description: Step-by-step registration chains for the changes Pogled Assist gets most often - a visible UI surface, a setting, a bundled runtime file, and Bosnian model data. Use before implementing one of them and again before opening a pull request.
---

# Shipping a change

`AGENTS.md` owns the maintenance matrix and the `## Done means` list. This
skill adds the order of the steps, which the matrix does not show.

## Change or add a visible UI surface

1. Update `docs/design/speech-keyboard-reference.html` and review it at the
   target display size before touching Qt code.
2. Implement the change in the matching `gaze_mouse/*_window.py` or overlay
   module.
3. For a new window, tab, dialog, or view, render it in `capture_ui()` in
   `scripts/capture_ui.py`.
4. Update the snapshot count in `tests/test_ui_rendering.py` and the surface
   count and list in `docs/DEVELOPMENT.md`.
5. Cover the flow in `tests/test_ui_e2e.py` with its existing fakes.
6. Run `.\dev.ps1 test-ui`, then `.\dev.ps1 ui -Open`, and review the gallery
   for clipping, overlap, spacing, and gaze-sized targets.

## Add a setting

1. Add the field and its default to `GazeSettings` in
   `gaze_mouse/mouse_controller.py` or `SpeechSettings` in
   `gaze_mouse/speech_service.py`. Settings files written by older releases
   lack the field and must load with the default.
2. Clamp or coerce it in `_coerce_gaze_settings` or `_coerce_speech_settings`
   in `gaze_mouse/settings_store.py`.
3. Add the control to `gaze_mouse/settings_window.py` with the same range.
4. Update the Settings section of `docs/design/speech-keyboard-reference.html`
   and `docs/USER_GUIDE.md`.
5. Test missing, malformed, and out-of-range values in
   `tests/test_settings_store.py`.

## Bundle a new runtime file

1. Put the file under `gaze_mouse/assets/`.
2. Add it to `datas` in `packaging/windows/PogledAssist.spec`.
3. Add its `_internal\...` path to `$requiredFiles` in
   `scripts/build_windows_package.ps1`.
4. Mark binary files with `binary` in `.gitattributes`.
5. Run `.\dev.ps1 package`.

## Change Bosnian model data

1. Edit the TSV under `language/bs/model/`, the tokenizer in
   `gaze_mouse/suggestion_text.py`, or a `scripts/prepare_*_model.py` script.
2. Rebuild the affected model with the commands in `docs/DEVELOPMENT.md`. The
   Islamic layer rebuilds offline. The general model needs the local CLASSLA
   archive, so say so in the pull request if it was not available.
3. Regenerate the evaluation and benchmark reports under `language/bs/` with
   the same guide. Tune only against the development set.
4. Run `tests/test_suggestion_text.py`, which checks the recorded input and
   model checksums.
