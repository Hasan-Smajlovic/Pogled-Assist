# 000035 - Speech Phrase Equal Height

## Original Prompt

In Speach -> Phrases
Make sure that each phrase item on the page takes the same height!

## What Was Done

- Updated `gaze_mouse/speech_window.py` so phrase rows use one shared height constant.
- Added `PHRASE_ROW_HEIGHT = 72` for the phrase page layout.
- Applied matching `min-height` and `max-height` styling to:
  - `QPushButton#phraseButton`
  - `QPushButton#deletePhraseButton`
- Set each phrase grid row minimum height to `PHRASE_ROW_HEIGHT`.
- Set the empty phrase-state button to the same fixed height.
- Extended `_make_key_button()` with a `fixed_height` option so phrase buttons can be locked to the exact same height while the rest of the speech keyboard keeps its existing flexible minimum-height behavior.
- Applied `fixed_height=True` to both the phrase item button and its delete button.

## Files Changed

- `gaze_mouse/speech_window.py`
- `AgentDocs/PrompsHistory/000035_speech_phrase_equal_height.md`

## What Is Working

- Phrase items in `Speech -> Phrases` now render with consistent fixed button height.
- Delete buttons on phrase rows use the same fixed height as phrase buttons.
- The empty phrase placeholder also uses the same row height, so the page does not switch to a different visual rhythm when no phrases exist.
- Existing phrase pagination, delete behavior, usage sorting, and phrase selection behavior were left unchanged.

## What Was Not Runtime-Tested

- The PySide UI was not launched in this Linux workspace, so final visual confirmation should be done on the target Windows device.

## Validation

- Python files were syntax-compiled with `PYTHONDONTWRITEBYTECODE=1`.
- Checked for generated `__pycache__`, `.pyc`, and `.pyo` files; none were present.

