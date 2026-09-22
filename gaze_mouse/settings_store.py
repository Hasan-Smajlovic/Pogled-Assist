"""Persistent application settings storage."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, fields, replace
from pathlib import Path
from typing import Any

from .gaze_selection import MAX_SELECTION_PAUSE_MS, MIN_SELECTION_PAUSE_MS
from .logging_setup import get_project_root
from .mouse_controller import GazeSettings
from .speech_service import VOICE_PRESET_DEFAULT, VOICE_PRESET_LABELS, SpeechSettings

logger = logging.getLogger(__name__)

SETTINGS_FILE = "app_settings.json"
SETTINGS_VERSION = 1


def load_app_settings() -> tuple[GazeSettings, SpeechSettings]:
    """Load persisted app settings, falling back field-by-field to defaults."""

    path = _settings_path()
    if not path.exists():
        logger.info("No app settings file found at %s; using defaults.", path)
        return GazeSettings(), SpeechSettings()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
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


def save_app_settings(gaze: GazeSettings, speech: SpeechSettings) -> None:
    """Persist app settings as UTF-8 JSON in the project data folder."""

    path = _settings_path()
    payload = {
        "version": SETTINGS_VERSION,
        "gaze": asdict(gaze),
        "speech": asdict(speech),
    }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)
        logger.info("Saved app settings to %s.", path)
    except Exception:
        logger.exception("Could not save app settings to %s.", path)


def _settings_path() -> Path:
    return get_project_root() / "data" / SETTINGS_FILE


def _coerce_gaze_settings(value: Any) -> GazeSettings:
    settings = _dataclass_from_mapping(GazeSettings(), value)
    return replace(
        settings,
        smoothing=_clamp_float(settings.smoothing, 0.05, 1.0),
        selection_pause_ms=_clamp_int(
            settings.selection_pause_ms,
            MIN_SELECTION_PAUSE_MS,
            MAX_SELECTION_PAUSE_MS,
        ),
        dwell_ms=_clamp_int(settings.dwell_ms, 150, 5000),
        dwell_radius_px=_clamp_int(settings.dwell_radius_px, 10, 160),
        click_cooldown_ms=_clamp_int(settings.click_cooldown_ms, 100, 5000),
        move_mouse=bool(settings.move_mouse),
        show_gaze_bubble=bool(settings.show_gaze_bubble),
        show_interaction_overlay=bool(settings.show_interaction_overlay),
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
        speed=_clamp_int(settings.speed, 80, 320),
        pitch=_clamp_int(settings.pitch, 0, 99),
        amplitude=_clamp_int(settings.amplitude, 0, 200),
        letters_per_group=_clamp_int(settings.letters_per_group, 1, 12),
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


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return min(maximum, max(minimum, value))


def _clamp_float(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))
