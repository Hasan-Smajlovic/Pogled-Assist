# 000031 - Speech Phrases Pagination

## Original Prompt

When in Speech -> Phrases

THis New Phrase button, text and icon must be in same line. 
That button must be on middle as it is! Make sure text is visable

When there is lot of phrases make sure there are buttons for chaning pages, they should be in the same row as New Phrase button. For scroling left put button on left side, for right on right side. Make sure they are visable only when there is something to be scrolled in that direction

## Files Changed

- `gaze_mouse/speech_window.py`
- `README.md`

## What Was Done

- Added phrase pagination to the Speech -> Phrases view.
- Added `PHRASES_PER_PAGE = 6`.
- Added `_phrase_page` state to `SpeechWindow`.
- Phrase rows now render only the current page instead of all saved phrases at once.
- Phrase selection and delete actions still use the real phrase index, so they continue to work across pages.
- Added `Previous` and `Next` phrase page buttons.
- Registered page buttons through the same `_make_tool_button()` / `_register_button()` path as other Speech controls, so they work with both gaze dwell and normal mouse clicks.
- Page buttons are visible only when that direction has another page:
  - `Previous` is hidden on the first page.
  - `Next` is hidden on the final page.
- Added equal fixed-width left and right page-button holders so the centered `New phrase` button stays centered even when only one page button is visible.
- Changed `New phrase` from text-under-icon to icon-beside-text using `Qt.ToolButtonTextBesideIcon`.
- Increased `New phrase` width to keep text visible.
- Added the same icon-beside-text style to `Previous` and `Next`.
- Added phrase page helper methods:
  - `_change_phrase_page()`
  - `_visible_phrases()`
  - `_phrase_page_count()`
  - `_clamp_phrase_page()`
  - `_has_previous_phrase_page()`
  - `_has_next_phrase_page()`
- Saving a new phrase moves to the last phrase page so the new phrase is reachable immediately.
- Deleting a phrase clamps the current page so it cannot point past the new end of the list.
- Updated `README.md` to document phrase pagination.

## What Should Work Now

- In Speech -> Phrases, `New phrase` should stay centered below the input.
- The `New phrase` icon and text should be on one line.
- The `New phrase` text should be visible.
- Phrase lists longer than six entries should use pages.
- `Previous` appears on the left side only when there is an earlier phrase page.
- `Next` appears on the right side only when there is a later phrase page.
- Page navigation works with gaze dwell and mouse clicks.
- Existing phrase add/delete/select behavior should still work.

## Not Fully Verified

- The PySide6 UI could not be visually launched in this Linux workspace.
- Final button spacing and readability should be checked on the Windows test machine.

## Validation

Ran syntax validation with bytecode disabled:

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

- Main code areas:
  - `gaze_mouse/speech_window.py` constants near `PHRASES_PER_PAGE`.
  - Phrase action row inside `_build_ui()`.
  - Phrase page rendering inside `_show_phrase_level()`.
  - Page actions inside `_trigger_action()`.
  - Page helpers near `_change_phrase_page()`.
- If six phrases per page is too few or too many after real screen testing, adjust `PHRASES_PER_PAGE`.
