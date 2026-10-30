"""Allowlisted recording context and validated persisted metadata."""

import json
import math
import re
from datetime import datetime

from .tracking.gaze_check_report import ENVIRONMENT_KEYS

DURATIONS = (1, 2, 5, 10)

GAZE_KEYS = (
    "eye_tracking_policy",
    "eye_tracking_hold_ms",
    "selection_pause_ms",
    "dwell_ms",
    "edge_hold_ms",
    "dwell_radius_px",
    "click_cooldown_ms",
    "smoothing",
    "move_mouse",
    "use_precision_zoom",
    "screen_margin_px",
    "require_leave_after_click",
    "leave_radius_px",
    "show_interaction_overlay",
    "show_gaze_bubble",
    "show_tracking_notifications",
)


def recording_context(settings: dict, environment: dict, *, simulated: bool) -> dict:
    """Explicit allowlist; never serialize complete settings or device objects."""
    return {
        "gaze_settings": _selected_recording_context(settings, GAZE_KEYS),
        "environment": _selected_recording_context(
            environment, (*ENVIRONMENT_KEYS, "physical_screen", "eye_validity_source")
        ),
        "simulated": bool(simulated),
    }


def _selected_recording_context(source: dict, keys: tuple[str, ...]) -> dict:
    result = {}
    for key in keys:
        value = source.get(key)
        if value is None or type(value) in (bool, int, float):
            result[key] = value
        elif isinstance(value, str):
            result[key] = value[:256]
        elif _is_screen_geometry(key, value):
            result[key] = list(value)
    return result


def _is_screen_geometry(key: str, value) -> bool:
    return (
        key in ("logical_screen", "physical_screen")
        and isinstance(value, (tuple, list))
        and len(value) == 4
        and all(type(coordinate) is int for coordinate in value)
    )


_RECORDING_METADATA_KEYS = {
    "schema_version",
    "id",
    "state",
    "reason",
    "started_at",
    "ended_at",
    "duration_seconds",
    "minutes",
    "bytes",
    "health",
    "session_end_present",
    "complete",
    "context",
}
_RECORDING_STATES = {
    "starting",
    "recording",
    "finishing",
    "completed",
    "interrupted",
    "error",
}
_RECORDING_REASONS = {
    None,
    "manual",
    "time",
    "size",
    "shutdown",
    "writer_error",
    "missing_end",
}


def _validate_recording_state(item: dict) -> None:
    if (
        set(item) - {"segment_count"} != _RECORDING_METADATA_KEYS
        or item["state"] not in _RECORDING_STATES
    ):
        raise ValueError("Unsupported recording metadata")
    _validate_segment_count(item.get("segment_count", 1))
    if item["reason"] not in _RECORDING_REASONS:
        raise ValueError("Invalid end reason")
    _validate_recording_flags(item)
    _validate_recording_measurements(item)
    _validate_recording_timestamps(item)


def _validate_segment_count(count):
    if type(count) is not int or count < 1:
        raise ValueError("Invalid recording segments")


def _validate_recording_flags(item: dict) -> None:
    if item["minutes"] not in DURATIONS:
        raise ValueError("Invalid recording state")
    if type(item["complete"]) is not bool or type(item["session_end_present"]) is not bool:
        raise ValueError("Invalid recording state")


def _validate_recording_measurements(item: dict) -> None:
    for name in ("duration_seconds", "bytes"):
        value = item[name]
        unknown_duration = name == "duration_seconds" and item["reason"] == "missing_end"
        if value is None and unknown_duration:
            continue
        if not _is_valid_recording_measurement(value):
            raise ValueError("Invalid recording measurement")


def _is_valid_recording_measurement(value) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _validate_recording_timestamps(item: dict) -> None:
    for name in ("started_at", "ended_at"):
        if name == "ended_at" and item[name] is None:
            continue
        if datetime.fromisoformat(item[name]).utcoffset() is None:
            raise ValueError("Missing recording timezone")


def _validate_recording_context(context: dict) -> None:
    if not isinstance(context, dict) or set(context) != {
        "gaze_settings",
        "environment",
        "simulated",
        "build",
    }:
        raise ValueError("Invalid recording context")
    safe = recording_context(
        context["gaze_settings"], context["environment"], simulated=context["simulated"]
    )
    if any(safe[key] != context[key] for key in safe):
        raise ValueError("Unexpected recording context")


def _validate_build_identity(build: dict) -> None:
    if set(build) != {"app_version", "build_revision", "build_dirty"} or not isinstance(
        build["app_version"], str
    ):
        raise ValueError("Invalid build identity")
    _validate_build_revision(build["build_revision"])
    if build["build_dirty"] is not None and type(build["build_dirty"]) is not bool:
        raise ValueError("Invalid build state")


def _validate_build_revision(revision: str | None) -> None:
    if revision is not None and not re.fullmatch(r"[0-9a-f]{40,64}", revision):
        raise ValueError("Invalid revision")


def _validate_recording_health(health: dict) -> None:
    if set(health) != {"dropped", "writer_errors", "bounded_snapshots"} or not isinstance(
        health["dropped"], dict
    ):
        raise ValueError("Invalid recording health")
    if any(
        type(count) is not int or count < 0
        for count in (
            *health["dropped"].values(),
            health["writer_errors"],
            health["bounded_snapshots"],
        )
    ):
        raise ValueError("Invalid loss count")


def _validate_metadata(item: dict) -> None:
    _validate_recording_state(item)
    context = item["context"]
    _validate_recording_context(context)
    _validate_build_identity(context["build"])
    _validate_recording_health(item["health"])


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
