# Prompt 000043 - Freeze And Crash Stability

## Original Prompt

there's a lot of freezes happening, program randomly can crash and freez up and gaze cursor is not moving at all! that is kind of a problem! It must work perfecly without crashes and freezes even on low end PCs! There must be no freezes!

## Log Findings

- `logs/latest.txt` showed the app using the Tobii Stream Engine x86 bridge successfully and receiving long-running gaze samples.
- `start_gaze_mouse.log` showed previous hard exits with code `-805306369`, including one at `2026-06-07 15:07:54`, without a Python traceback in the runtime log. That points toward native/UI/event-loop pressure rather than a normal handled Python exception.
- Older logs showed repeated `Mouse move failed: [WinError 0] The operation completed successfully` errors from `SetCursorPos`. These repeated errors happened rapidly enough to spam the UI status/log pipeline and appeared close to one prior crash sequence.
- The old gaze pipeline emitted every raw Tobii sample directly into the Qt/UI layer. The same emitted gaze point then moved the cursor, updated toolbar dwell, updated the gaze bubble, updated the interaction overlay, and fed quick-action windows. On weaker PCs this can flood the event loop.

## Changes Made

- Added bounded gaze sample coalescing in `gaze_mouse/gaze_provider.py`.
  - Raw Tobii samples are still accepted immediately.
  - Only the latest gaze sample is emitted to the UI/mouse controller every 20 ms.
  - Pending gaze samples are cleared when either eye is not valid/open so stale movement is not emitted after tracking pauses.
  - Coalesced sample counts are logged occasionally instead of flooding logs.

- Reduced expensive overlay work.
  - `gaze_mouse/gaze_bubble.py` now skips tiny/too-frequent topmost window moves.
  - `gaze_mouse/interaction_overlay.py` now skips redundant progress overlay moves/repaints when point/progress/label did not meaningfully change.

- Reduced Tobii callback pump CPU pressure.
  - `gaze_mouse/tobii_stream_engine.py` callback polling changed from 240 Hz to 120 Hz. Tobii gaze samples in logs were effectively around 60 Hz, so this preserves responsiveness while reducing background churn.

- Hardened the x86 Stream Engine bridge lifecycle.
  - `gaze_mouse/tobii_stream_engine_bridge_backend.py` now joins stdout/stderr reader threads on stop.
  - Startup failures now clean up bridge reader threads/process state instead of leaving dangling workers.

- Reduced per-frame mouse controller overhead.
  - `gaze_mouse/mouse_controller.py` now caches logical and physical screen geometry instead of reading primary screen geometry every gaze frame.
  - Cursor movement now skips duplicate same-pixel moves.
  - Mouse movement errors are rate-limited so one bad Windows input state cannot flood logs and UI status.

- Fixed a noisy Windows input edge case.
  - `gaze_mouse/windows_input.py` now clears last error before `SetCursorPos`.
  - If `SetCursorPos` returns false but Windows reports error code 0, it is treated as a dropped non-fatal move and logged only at debug level.

## What Should Work Now

- Gaze cursor updates should remain responsive under load because the UI only handles the newest gaze sample instead of processing a backlog of stale raw samples.
- Bubble and interaction overlay animations should remain visible while doing less topmost-window movement/repaint work.
- Repeated ambiguous `SetCursorPos` results should no longer spam user-facing status messages or exceptions.
- Bridge shutdown/startup failure paths should be less likely to leave orphaned reader threads.

## What Was Not Fully Verified

- Real Tobii hardware behavior was not runtime-tested from this Linux workspace.
- The Windows native crash code `-805306369` cannot be proven fixed without running the updated app on the Windows/Tobii machine for a longer session.
- If freezes continue, the next logs to inspect are:
  - `logs/latest.txt`
  - `start_gaze_mouse.log`
  - any new `Coalesced ... raw gaze samples` messages, which would show how much raw input pressure the app is absorbing.

## Validation Performed

- Syntax-checked changed Python files with `compile(...)` under `PYTHONDONTWRITEBYTECODE=1` and `python -B`.
- Confirmed no `__pycache__`, `.pyc`, or `.pyo` files were created.

