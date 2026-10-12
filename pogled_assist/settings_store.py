"""Persistent application settings storage."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, fields, replace
from pathlib import Path
from typing import Any

from .interaction.gaze_selection import MAX_SELECTION_PAUSE_MS, MIN_SELECTION_PAUSE_MS
from .interaction.mouse_controller import GazeSettings
from .keyboard_layouts import KEYBOARD_SCRIPTS, LATIN_SCRIPT
from .logging_setup import get_project_root
from .settings_limits import (
    CLICK_COOLDOWN_MS_RANGE,
    DWELL_MS_RANGE,
    DWELL_RADIUS_RANGE,
    LETTERS_PER_GROUP_RANGE,
    SMOOTHING_RANGE,
    SPEECH_AMPLITUDE_RANGE,
    SPEECH_PITCH_RANGE,
    SPEECH_SPEED_RANGE,
    clamp,
)
from .speech.speech_service import VOICE_PRESET_DEFAULT, VOICE_PRESET_LABELS, SpeechSettings

logger = logging.getLogger(__name__)

SETTINGS_FILE = "app_settings.json"
SETTINGS_VERSION = 1


def load_app_settings() -> tuple[GazeSettings, SpeechSettings]:
    """Load persisted app settings, falling back field-by-field to defaults."""

    path = _settings_path()
    if not path.exists() and not (path.parent / "version-history").exists():
        logger.info("No app settings file found at %s; using defaults.", path)
        return GazeSettings(), SpeechSettings()

    try:
        data = _settings_payload(path)
    except Exception:
        logger.exception("Could not load app settings from %s; using defaults.", path)
        return GazeSettings(), SpeechSettings()

    if not isinstance(data, dict):
        logger.warning("App settings file did not contain an object: %s", path)
        return GazeSettings(), SpeechSettings()

    gaze = _coerce_gaze_settings(data.get("gaze", {}))
    speech = _coerce_speech_settings(data.get("speech", {}))
    logger.info("Loaded app settings from %s: gaze=%s speech=%s", path, gaze, speech)
    return gaze, speech


def save_app_settings(gaze: GazeSettings, speech: SpeechSettings) -> bool:
    """Persist app settings as UTF-8 JSON in the project data folder."""

    path = _settings_path()
    try:
        payload = _settings_payload(path)
        if (
            not isinstance(payload, dict)
            or payload.get("version", SETTINGS_VERSION) != SETTINGS_VERSION
        ):
            raise ValueError("Cannot safely write this settings format")
        for section, settings in (("gaze", gaze), ("speech", speech)):
            previous = payload.get(section, {})
            if not isinstance(previous, dict):
                previous = {}
            payload[section] = {**previous, **asdict(settings)}
        payload["version"] = SETTINGS_VERSION
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)
        logger.info("Saved app settings to %s.", path)
        return True
    except Exception:
        logger.exception("Could not save app settings to %s.", path)
        return False


def _settings_path() -> Path:
    return get_project_root() / "data" / SETTINGS_FILE


def _settings_payload(path: Path) -> Any:
    payload: Any = {}
    history = path.parent / "version-history"
    if history.exists():
        for snapshot in sorted(history.iterdir()):
            saved = snapshot / SETTINGS_FILE
            if saved.is_file():
                previous = json.loads(saved.read_text(encoding="utf-8-sig"))
                if not isinstance(previous, dict):
                    raise ValueError("Invalid settings snapshot")
                payload = _merge_settings(payload, previous)
    if path.exists():
        payload = _merge_settings(payload, json.loads(path.read_text(encoding="utf-8")))
    return payload


def _merge_settings(saved: Any, current: Any) -> Any:
    # Old releases omit unknown fields when saving; their supported edits still win.
    if not isinstance(saved, dict) or not isinstance(current, dict):
        return current
    return {
        key: _merge_settings(saved.get(key), current[key]) if key in current else saved[key]
        for key in saved.keys() | current.keys()
    }


def _coerce_gaze_settings(value: Any) -> GazeSettings:
    settings = _dataclass_from_mapping(GazeSettings(), value)
    return replace(
        settings,
        smoothing=clamp(settings.smoothing, SMOOTHING_RANGE),
        selection_pause_ms=clamp(
            settings.selection_pause_ms,
            (MIN_SELECTION_PAUSE_MS, MAX_SELECTION_PAUSE_MS),
        ),
        dwell_ms=clamp(settings.dwell_ms, DWELL_MS_RANGE),
        dwell_radius_px=clamp(settings.dwell_radius_px, DWELL_RADIUS_RANGE),
        click_cooldown_ms=clamp(settings.click_cooldown_ms, CLICK_COOLDOWN_MS_RANGE),
        move_mouse=bool(settings.move_mouse),
        show_gaze_bubble=bool(settings.show_gaze_bubble),
        show_interaction_overlay=bool(settings.show_interaction_overlay),
        show_tracking_notifications=bool(settings.show_tracking_notifications),
        use_precision_zoom=bool(settings.use_precision_zoom),
        start_with_windows=bool(settings.start_with_windows),
        logging_enabled=bool(settings.logging_enabled),
        show_launcher_window=bool(settings.show_launcher_window),
    )


def _coerce_speech_settings(value: Any) -> SpeechSettings:
    settings = _dataclass_from_mapping(SpeechSettings(), value)
    language = str(settings.language).strip() or SpeechSettings().language
    voice_preset = str(settings.voice_preset).strip() or VOICE_PRESET_DEFAULT
    if voice_preset not in VOICE_PRESET_LABELS:
        voice_preset = VOICE_PRESET_DEFAULT
    return replace(
        settings,
        language=language,
        keyboard_script=(
            settings.keyboard_script
            if settings.keyboard_script in dict(KEYBOARD_SCRIPTS)
            else LATIN_SCRIPT
        ),
        speed=clamp(settings.speed, SPEECH_SPEED_RANGE),
        pitch=clamp(settings.pitch, SPEECH_PITCH_RANGE),
        amplitude=clamp(settings.amplitude, SPEECH_AMPLITUDE_RANGE),
        letters_per_group=clamp(settings.letters_per_group, LETTERS_PER_GROUP_RANGE),
        voice_preset=voice_preset,
    )


def _dataclass_from_mapping(defaults: Any, value: Any) -> Any:
    if not isinstance(value, dict):
        return defaults

    updates: dict[str, Any] = {}
    for field in fields(defaults):
        if field.name not in value:
            continue

        current_value = getattr(defaults, field.name)
        updates[field.name] = _coerce_value(value[field.name], current_value)

    try:
        return replace(defaults, **updates)
    except Exception:
        logger.exception("Could not coerce settings payload; using defaults: %s", value)
        return defaults


def _coerce_value(value: Any, default: Any) -> Any:
    if isinstance(default, bool):
        return _coerce_bool(value, default)
    if isinstance(default, int) and not isinstance(default, bool):
        return _coerce_int(value, default)
    if isinstance(default, float):
        return _coerce_float(value, default)
    if isinstance(default, str):
        return str(value)
    return value


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
