# 000018 - Speech Keyboard Layout Groups

Date: 2026-06-06

## Original Prompt

```text
When Speach window is open, make sure it it has all of the letters of bosnian alphabet split into button groups by defined value, if there is less in last group make sure that group is shown as well

Alywas put letter button groups on top part, then Space, Backspace on bottom part!

remove the "." button


Make sure that window keyaboard


Then make sure that buttons have same margin on on all sides asl well !

Make sure that "Speech" text on top left position of screen is readable as well!
```

## Changes Made

Updated `gaze_mouse/speech_window.py`.

Speech keyboard layout:

- Reworked the keyboard body into two fixed zones:
  - Top expanding key grid.
  - Bottom utility row.
- First-level Bosnian letter groups are always placed in the top grid.
- `Space` and `Backspace` are always placed in the bottom utility row.
- Letter-level view also keeps letters in the top grid.
- Letter-level view keeps `Groups`, `Space`, and `Backspace` in the bottom utility row.
- Removed the `.` button completely.
- Removed the `period` action handler.

Letter grouping:

- The existing grouping behavior still splits `BOSNIAN_LETTERS` by the configured `letters_per_group`.
- The last group is preserved even when it contains fewer letters than the configured group size.
- Added adaptive grid column selection so all groups are visible for small group sizes, including `letters_per_group = 1`.

Spacing and readability:

- Outer speech-window margins are now equal on all sides.
- Keyboard grid spacing and utility-row spacing are consistent.
- Buttons have consistent padding.
- The `Speech` title in the top-left is larger, darker, bolder, and given a stable minimum height/width so it remains readable.

Updated `README.md`:

- Documents that all groups stay in the top grid.
- Documents that a final shorter group is still shown.
- Documents that Space and Backspace stay in the bottom utility row.

## What Should Work Now

In the Speech window:

- Bosnian letters appear in groups using the configured group size.
- All groups appear, including the final shorter group.
- Group buttons are in the top part of the keyboard.
- Space and Backspace are in the bottom part.
- There is no `.` key.
- Buttons have more consistent spacing.
- The `Speech` title should be readable in the top-left.

## What Is Not Confirmed

The full Qt window could not be rendered in this Linux workspace because PySide6 is not installed here.

Real visual confirmation should be done on the Windows Tobii machine after setup copies the updated files.

## Validation Performed

Python syntax validation passed:

```text
python syntax ok
```

Static Bosnian alphabet grouping validation passed for group sizes `1`, `5`, and `12`:

```text
bosnian group coverage ok
```

Period-key scan found no active `period` action or `.` key in `gaze_mouse/speech_window.py`.

Cache scan was clean:

```text
find . -name '__pycache__' -o -name '*.pyc' -o -name '*.pyo'
```

Result: no output.

## Next Real-Machine Check

On Windows:

1. Rerun `setup_windows.ps1`.
2. Start the app with `start_gaze_mouse.ps1`.
3. Open Speech.
4. Check default groups of five:
   - The six groups should be in the top grid.
   - Space and Backspace should be in the bottom row.
5. Change letters per group in Settings to `1` and reopen Speech:
   - All Bosnian letters should appear as individual top-grid groups.
   - No groups should be hidden behind Space/Backspace.
6. Change letters per group to a value that leaves a shorter final group, such as `12`:
   - The final shorter group should still be visible.
