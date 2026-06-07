# 000032 - Speech Phrases Usage Sorting

## Original Prompt

In the Speech in Phrases 
The list of Phrases must have maxiumum of 8 5 prases per page, the delete button must be on the right side!
THey must be sorted by most common usage!

## Implementation Notes

- Interpreted `8 5 prases per page` as a request for a maximum of 8 phrases per page.
- Existing saved phrase files are still supported:
  - Old format: `["phrase one", "phrase two"]`
  - New format: `[{"text": "phrase one", "uses": 3}]`

## Files Changed

- `gaze_mouse/speech_window.py`
- `README.md`

## What Was Done

- Changed `PHRASES_PER_PAGE` from 6 to 8.
- Added `PhraseRecord` with:
  - `text`
  - `uses`
- Updated the phrase list layout so:
  - Phrase button is on the left.
  - `Delete` button is on the right.
  - Phrase text column receives the flexible stretch.
  - Delete column stays compact.
- Updated phrase selection behavior:
  - Selecting a phrase appends it to the input with a trailing space.
  - The phrase usage count increments by 1.
  - Phrases are sorted by highest usage count first.
  - Usage counts are saved immediately.
- Updated phrase creation behavior:
  - New phrases are saved as `PhraseRecord(text=..., uses=0)`.
  - The phrase list is sorted after saving.
  - The UI moves to the page containing the newly saved phrase.
- Updated phrase deletion behavior:
  - Deletes the selected phrase record.
  - Clamps the current page after deletion.
  - Logs the deleted phrase text.
- Added persistent JSON storage for usage counts.
- Added backward-compatible loader for old list-of-string phrase files.
- Updated README phrase documentation.

## What Should Work Now

- Speech -> Phrases shows a maximum of 8 phrases per page.
- Delete appears on the right side of each phrase row.
- Phrase rows are sorted by most-used first.
- Selecting a phrase increases its usage count and re-sorts the list.
- Existing `data/speech_phrases.json` files from earlier versions still load.
- New saves write usage counts to `data/speech_phrases.json`.
- Phrase navigation, creation, deletion, and selection still work with gaze dwell and mouse clicks.

## Not Fully Verified

- The PySide6 UI could not be visually launched in this Linux workspace.
- The exact visual fit of 8 phrase rows should be checked on the Windows test machine, especially if the display is lower than 1080p.

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

- If the user meant 5 phrases per page instead of 8, change `PHRASES_PER_PAGE` in `gaze_mouse/speech_window.py`.
- Sorting currently uses `(-uses, text.casefold())`, so ties are alphabetical.
- Usage count is based on selecting a phrase from the Phrases list, not on free-typed text that happens to match a phrase.
