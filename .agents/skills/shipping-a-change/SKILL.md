---
name: shipping-a-change
description: Apply when changing Pogled Assist UI, settings, bundled runtime assets, or Bosnian model inputs; use the applicable workflow before implementation and when preparing that change for review.
---

# Shipping a change

[AGENTS.md](../../../AGENTS.md) owns the maintenance matrix, verification rules,
done criteria, and human review requirements. Read only the sections that match
the change. This skill adds the workflow order; the linked guides own detailed
references. Use the [development guide](../../../docs/DEVELOPMENT.md#verification-before-a-pull-request)
for final verification and deferred execution; focused checks below do not
establish readiness for review.

## Change or add a visible UI surface

1. Use the [design surface map](../../../docs/UI_DEVELOPMENT.md#application-design-reference-workflow)
   to find the matching page and assets under `docs/design/`. Update and review
   them at the target display size before touching Qt code. The entry point
   `docs/design/speech-keyboard-reference.html` changes only when navigation does.
2. Implement the change in the matching `pogled_assist/ui/` module or
   `pogled_assist/toolbar.py`.
3. For a new window, tab, dialog, or view, render it in `capture_ui()` in
   `scripts/ui/capture_ui.py`.
4. When rendered surfaces change, update the snapshot count in
   `tests/ui/test_ui_rendering.py` and the surface count and list in
   `docs/UI_DEVELOPMENT.md`.
5. Cover the changed flow in the matching test module under `tests/ui/`.
   Reuse the shared fixtures and fakes in the
   [test strategy](../../../docs/DEVELOPMENT.md#test-strategy), rather than
   importing from another test module.
6. Run `.\dev.ps1 test-ui`, then `.\dev.ps1 ui -Open`, and review the gallery
   using the [UI review guide](../../../docs/UI_DEVELOPMENT.md#rendered-ui-gallery).
   Record applicable manual Windows and Tobii results separately.

## Add a setting

1. For a visible control, update `docs/design/settings.html` and its assets and
   review them at the target display size using the design workflow above.
2. Add the field and its default to `GazeSettings` in
   `pogled_assist/interaction/mouse_controller.py` or `SpeechSettings` in
   `pogled_assist/speech/speech_service.py`. Settings files written by older releases
   lack the field and must load with the default.
3. Clamp or coerce it in `_coerce_gaze_settings` or `_coerce_speech_settings`
   in `pogled_assist/settings_store.py`. For a numeric range, define or reuse
   its limits in `pogled_assist/settings_limits.py` for storage and UI controls.
   Selection-pause limits remain owned by `pogled_assist/interaction/gaze_selection.py`.
4. Add the control to `pogled_assist/ui/settings_window.py` with those same limits
   and update `docs/USER_GUIDE.md`.
5. Test missing, malformed, and out-of-range values in
   `tests/app/test_settings_store.py`.

## Bundle a new runtime file

1. Put the file under `pogled_assist/assets/`.
2. Add it to `datas` in `packaging/windows/PogledAssist.spec`.
3. Add its `_internal\...` path to `$requiredFiles` in
   `scripts/release/build_windows_package.ps1`.
4. Mark binary files with `binary` in `.gitattributes`.
5. Run `.\dev.ps1 package`.

## Change Bosnian model data

1. Edit the TSV under `language/bs/model/`, the tokenizer in
   `pogled_assist/suggestions/text.py`, or a `scripts/speech_suggestions/prepare_*_model.py` script.
2. Format before rebuilding, then regenerate the affected model and metadata
   with the [preparation commands](../../../language/bs/README.md#preparation-and-evaluation).
   The Islamic layer rebuilds offline. The general model needs the local CLASSLA
   archive; report a missing archive and any rebuild left Not run. Do not edit
   recorded checksums by hand.
3. Regenerate the evaluation and benchmark reports under `language/bs/` with
   the same guide. Tune only against the development set.
4. Run `.\dev.ps1 test -TestPaths tests/suggestions/test_suggestion_text.py`
   to check the recorded input and model checksums.
