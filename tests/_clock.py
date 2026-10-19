from __future__ import annotations

import time


def freeze_monotonic(monkeypatch, start: float) -> list[float]:
    """Freeze ``time.monotonic`` for the whole process at a test-controlled value.

    Gaze tests compare timestamps taken by several modules (provider, controller,
    windows), so the clock is shared on purpose. Qt timers of unrelated widgets
    also read it until teardown, so the fake must never raise or run out.
    """
    now = [start]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    return now
