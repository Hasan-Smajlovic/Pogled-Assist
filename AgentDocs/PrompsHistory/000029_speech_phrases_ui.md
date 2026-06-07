# 000029 - Speech Phrases UI

## Original Prompt

On the Speech window, please remove the black rectanble on the top left side of the screen and the one on the bottom of the screen. They are taking space unnencecarly

Then on the left side of the input add Phrases. In there allow the user to create common phrases. It should be able to create new, and delete them

When in Phrases make sure the is a list of existing ones, there should be button for deleting them on the left side

Under input tab there should be button to create new one. It must use the same keyboard when creating new one

Then when one is selected it must be added to the input automaticlly with space after it.

## Files Changed

- `gaze_mouse/speech_window.py`
- `README.md`

## What Was Done

- Removed the visible Speech title/status UI areas from the full-screen Speech window layout.
- Removed the now-unused `QLabel` import from `gaze_mouse/speech_window.py`.
- Kept the Speech input row as the top visible area, with smaller margins and no separate top-left title block.
- Kept status updates in logs/tooltips through `_set_status()` instead of using a visible bottom status rectangle.
- Added a checkable `Phrases` tool button on the left side of the Speech input row.
- Added phrase action controls under the input row:
  - `New phrase`
  - `Save phrase`
  - `Cancel`
- Added a phrase-list mode:
  - Existing saved phrases are shown as rows.
  - Each row has `Delete` on the left.
  - The phrase button is on the right.
  - Selecting a phrase appends it to the current input and adds a trailing space.
  - Empty phrase storage shows a disabled `No phrases saved` row.
- Added phrase editor mode:
  - `New phrase` saves the current speech input temporarily.
  - The existing Bosnian letter keyboard is reused for entering the new phrase.
  - `Save phrase` normalizes whitespace, saves the phrase, restores the previous speech input, and returns to phrase list mode.
  - `Cancel` restores the previous speech input and returns to phrase list mode.
- Phrase entries are saved as UTF-8 JSON in:

```text
data/speech_phrases.json
```

- Phrase persistence uses the project root resolved by `get_project_root()`, so it follows the same source/network-root logic as runtime logs when the launcher sets the project root environment.
- Phrase loading sanitizes entries:
  - Missing file returns an empty list.
  - Invalid JSON or non-list JSON is logged and ignored.
  - Duplicate or empty phrases are skipped.
- Added phrase documentation to `README.md`.

## Gaze And Mouse Behavior

- All phrase controls are registered through the existing `_register_button()` path.
- Phrase list buttons, delete buttons, `Phrases`, `New phrase`, `Save phrase`, and `Cancel` work with normal mouse clicks.
- Because they are registered in `_action_buttons`, they are also visible to `action_at_global_point()` and work with Tobii gaze dwell selection.
- Gaze feedback continues to use the existing `set_gaze_feedback()` behavior for phrase buttons and phrase action controls.

## What Is Working

- Speech window no longer has the previous visible top-left title block or bottom status block.
- `Phrases` appears left of the input.
- Phrase list mode renders saved phrases with delete buttons on the left.
- Phrase selection appends the phrase plus a trailing space into the input.
- Phrase creation reuses the existing Bosnian keyboard.
- Save/cancel restores the prior speech input.
- Saved phrases persist under `data/speech_phrases.json`.
- The `README.md` explains phrase behavior and storage path.

## Not Fully Verified

- Full PySide6 runtime UI behavior was not launched in this Linux workspace.
- Tobii gaze behavior was not tested with the physical Tobii Eye Tracker 4C in this environment.
- Visual spacing was checked from code structure only; final appearance should be confirmed on the Windows test machine.

## Validation

Ran syntax validation without generating bytecode:

```bash
PYTHONDONTWRITEBYTECODE=1 python - <<'PY'
from pathlib import Path
files = sorted(Path('gaze_mouse').glob('*.py')) + [Path('run_gaze_mouse.py')]
for path in files:
    compile(path.read_text(encoding='utf-8'), str(path), 'exec')
print('python syntax ok')
PY
```

Result:

```text
python syntax ok
```

Checked for generated Python cache artifacts:

```bash
find . \( -name '__pycache__' -o -name '*.pyc' -o -name '*.pyo' \) -print
```

Result: no cache files found.

## Notes For Next Agent

- There is no `.git` repository available in this workspace, so use direct file inspection instead of `git diff`.
- If future work needs phrase scrolling for large phrase lists, consider wrapping the phrase grid in a `QScrollArea`; this prompt did not require that.
- If the user reports visual problems, inspect `gaze_mouse/speech_window.py` around `_build_ui()`, `_show_phrase_level()`, and `_set_phrase_controls_visible()`.
