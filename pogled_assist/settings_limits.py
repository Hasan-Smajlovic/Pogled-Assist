"""Numeric limits shared by persisted settings and their controls."""

from __future__ import annotations

from typing import TypeVar

SMOOTHING_RANGE = (0.05, 1.0)
DWELL_MS_RANGE = (150, 5000)
EYE_TRACKING_HOLD_MS_RANGE = (50, 500)
EYE_TRACKING_HOLD_MS_STEP = 50
DWELL_RADIUS_RANGE = (10, 160)
CLICK_COOLDOWN_MS_RANGE = (100, 5000)
SPEECH_SPEED_RANGE = (80, 320)
SPEECH_PITCH_RANGE = (0, 99)
SPEECH_AMPLITUDE_RANGE = (0, 200)
LETTERS_PER_GROUP_RANGE = (1, 12)
ELEVENLABS_PERCENT_RANGE = (0, 100)
ELEVENLABS_STABILITY_STEPS = (0, 50, 100)
ELEVENLABS_STABILITY_DEFAULT = 50
ELEVENLABS_SIMILARITY_DEFAULT = 80

Number = TypeVar("Number", int, float)


def clamp(value: Number, limits: tuple[Number, Number]) -> Number:
    minimum, maximum = limits
    return min(maximum, max(minimum, value))
