"""Device model recognition shared by tracking and Tobii settings routing."""

from __future__ import annotations


def is_eye_tracker_5(model: str) -> bool:
    normalized = "".join(character for character in model.lower() if character.isalnum())
    return normalized in {"is5largeeyetracker5", "tobiieyetracker5", "eyetracker5"}
