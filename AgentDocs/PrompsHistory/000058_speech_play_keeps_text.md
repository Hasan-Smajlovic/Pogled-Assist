# 000058 Speech Play Keeps Text

## Original prompt

In The Speech window, dont clear the text after it player.

## What changed

- Updated `gaze_mouse/speech_window.py`.
  - Removed the `_input.clear()` call from `_play()`.
  - Pressing `Play` now sends the input to eSpeak NG but leaves the text visible for replay or editing.

- Updated `README.md`.
  - Documentation now says Play leaves the text in the input instead of clearing it.

## What is expected to work

- Speech input remains unchanged after a successful Play action.
- The `Clear` button still manually clears the input.
- Empty input still shows `Input is empty.`
- eSpeak NG unavailable state still shows `eSpeak NG is not available.`

## Validation

- Parsed `gaze_mouse/speech_window.py` with `ast.parse`.
- Verified no `__pycache__`, `.pyc`, or `.pyo` files remain in the workspace.
