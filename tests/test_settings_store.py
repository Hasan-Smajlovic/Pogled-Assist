from __future__ import annotations

import json

from gaze_mouse.mouse_controller import GazeSettings
from gaze_mouse.settings_store import load_app_settings, save_app_settings
from gaze_mouse.speech_service import SpeechSettings


def point_settings_at(monkeypatch, tmp_path):
    path = tmp_path / "data" / "app_settings.json"
    monkeypatch.setattr("gaze_mouse.settings_store._settings_path", lambda: path)
    return path


def test_load_returns_defaults_when_file_is_missing(monkeypatch, tmp_path):
    point_settings_at(monkeypatch, tmp_path)

    gaze, speech = load_app_settings()

    assert gaze == GazeSettings()
    assert speech == SpeechSettings()


def test_load_returns_defaults_for_invalid_json(monkeypatch, tmp_path):
    path = point_settings_at(monkeypatch, tmp_path)
    path.parent.mkdir()
    path.write_text("not json", encoding="utf-8")

    assert load_app_settings() == (GazeSettings(), SpeechSettings())


def test_load_coerces_and_clamps_each_setting(monkeypatch, tmp_path):
    path = point_settings_at(monkeypatch, tmp_path)
    path.parent.mkdir()
    path.write_text(
        json.dumps(
            {
                "gaze": {
                    "smoothing": "2.5",
                    "dwell_ms": "25",
                    "dwell_radius_px": 999,
                    "click_cooldown_ms": None,
                    "move_mouse": "off",
                    "show_gaze_bubble": "yes",
                    "show_interaction_overlay": 0,
                    "use_precision_zoom": 1,
                    "start_with_windows": "true",
                    "logging_enabled": "false",
                    "show_launcher_window": "on",
                    "future_field": "ignored",
                },
                "speech": {
                    "language": "  ",
                    "speed": 999,
                    "pitch": -10,
                    "amplitude": "175",
                    "letters_per_group": 0,
                    "voice_preset": "unknown",
                },
            }
        ),
        encoding="utf-8",
    )

    gaze, speech = load_app_settings()

    assert gaze.smoothing == 1.0
    assert gaze.dwell_ms == 150
    assert gaze.dwell_radius_px == 160
    assert gaze.click_cooldown_ms == GazeSettings().click_cooldown_ms
    assert gaze.move_mouse is False
    assert gaze.show_gaze_bubble is True
    assert gaze.show_interaction_overlay is False
    assert gaze.use_precision_zoom is True
    assert gaze.start_with_windows is True
    assert gaze.logging_enabled is False
    assert gaze.show_launcher_window is True
    assert speech.language == "bs"
    assert speech.speed == 320
    assert speech.pitch == 0
    assert speech.amplitude == 175
    assert speech.letters_per_group == 1
    assert speech.voice_preset == "default"


def test_save_round_trips_utf8_settings_and_cleans_temp_file(monkeypatch, tmp_path):
    path = point_settings_at(monkeypatch, tmp_path)
    gaze = GazeSettings(dwell_ms=750, move_mouse=False)
    speech = SpeechSettings(language="bs-Latn", letters_per_group=6)

    save_app_settings(gaze, speech)

    assert path.exists()
    assert not path.with_suffix(".json.tmp").exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["gaze"]["dwell_ms"] == 750
    assert payload["speech"]["language"] == "bs-Latn"
    assert load_app_settings() == (gaze, speech)


def test_save_failure_does_not_escape(monkeypatch, tmp_path):
    path = point_settings_at(monkeypatch, tmp_path)
    monkeypatch.setattr(
        type(path), "write_text", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("full"))
    )

    save_app_settings(GazeSettings(), SpeechSettings())

    assert not path.exists()
