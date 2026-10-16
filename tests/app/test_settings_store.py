from __future__ import annotations

import json

import pytest

from pogled_assist.interaction.mouse_controller import GazeSettings
from pogled_assist.settings_store import load_app_settings, save_app_settings
from pogled_assist.speech.speech_service import SpeechSettings


@pytest.mark.parametrize("setting", [("elevenlabs_stability", 50), ("elevenlabs_similarity", 80)])
@pytest.mark.parametrize(
    "sample",
    [(None, None), ("bad", None), ({}, None), ([], None), (-20, 0), (120, 100), ("42", 42)],
)
def test_elevenlabs_slider_settings_coerce_and_clamp(tmp_path, monkeypatch, setting, sample):
    field, default = setting
    value, expected = sample
    path = point_settings_at(monkeypatch, tmp_path)
    path.parent.mkdir()
    path.write_text(json.dumps({"speech": {field: value}}), encoding="utf-8")
    expected = default if expected is None else expected
    if field == "elevenlabs_stability" and expected == 42:
        expected = 50
    assert getattr(load_app_settings()[1], field) == expected


def test_elevenlabs_slider_defaults_and_round_trip(tmp_path, monkeypatch):
    point_settings_at(monkeypatch, tmp_path)
    speech = load_app_settings()[1]
    assert (speech.elevenlabs_stability, speech.elevenlabs_similarity) == (50, 80)
    speech.elevenlabs_stability, speech.elevenlabs_similarity = 100, 95
    assert save_app_settings(GazeSettings(), speech)
    assert load_app_settings()[1] == speech


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        ("off", False),
        ("true", True),
        (0, False),
        (1, True),
        (None, True),
        ({}, True),
        ([], True),
    ],
)
def test_tracking_notification_setting_coercion(tmp_path, monkeypatch, value, expected):
    path = point_settings_at(monkeypatch, tmp_path)
    path.parent.mkdir()
    path.write_text(json.dumps({"gaze": {"show_tracking_notifications": value}}), encoding="utf-8")
    gaze, _speech = load_app_settings()
    assert gaze.show_tracking_notifications is expected


def test_tracking_notifications_default_on_in_old_settings_and_false_survives_restart(
    tmp_path, monkeypatch
):
    path = point_settings_at(monkeypatch, tmp_path)
    path.parent.mkdir()
    path.write_text('{"gaze": {"dwell_ms": 850}}', encoding="utf-8")
    gaze, speech = load_app_settings()
    assert gaze.show_tracking_notifications is True
    gaze.show_tracking_notifications = False
    assert save_app_settings(gaze, speech)
    assert load_app_settings()[0].show_tracking_notifications is False


@pytest.mark.parametrize("value", [None, "", "unknown", 99, [], {}])
def test_invalid_keyboard_script_loads_as_latin(monkeypatch, tmp_path, value):
    path = point_settings_at(monkeypatch, tmp_path)
    path.parent.mkdir()
    path.write_text(json.dumps({"speech": {"keyboard_script": value}}), encoding="utf-8")
    assert load_app_settings()[1].keyboard_script == "latin"


def test_arabic_script_round_trip_preserves_latin_voice_and_other_settings(monkeypatch, tmp_path):
    point_settings_at(monkeypatch, tmp_path)
    gaze = GazeSettings(dwell_ms=950)
    speech = SpeechSettings(
        keyboard_script="arabic",
        language="bs",
        voice_preset="human_like",
        letters_per_group=7,
        speed=180,
    )
    save_app_settings(gaze, speech)
    assert load_app_settings() == (gaze, speech)


def test_legacy_settings_without_script_keep_latin(monkeypatch, tmp_path):
    path = point_settings_at(monkeypatch, tmp_path)
    path.parent.mkdir()
    path.write_text(
        json.dumps({"speech": {"voice_preset": "human_like", "speed": 180}}), encoding="utf-8"
    )
    speech = load_app_settings()[1]
    assert speech.keyboard_script == "latin"
    assert speech.voice_preset == "human_like"
    assert speech.speed == 180


def point_settings_at(monkeypatch, tmp_path):
    path = tmp_path / "data" / "app_settings.json"
    monkeypatch.setattr("pogled_assist.settings_store._settings_path", lambda: path)
    return path


def test_unknown_settings_survive_saves_and_downgrade_round_trip(monkeypatch, tmp_path):
    path = point_settings_at(monkeypatch, tmp_path)
    path.parent.mkdir()
    original = {
        "version": 1,
        "future": {"enabled": True},
        "speech": {"keyboard_script": "arabic", "future_voice": "keep", "speed": 180},
        "gaze": {"show_tracking_notifications": False},
    }
    path.write_text(json.dumps(original), encoding="utf-8")
    gaze, speech = load_app_settings()
    assert save_app_settings(gaze, speech)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["future"] == original["future"]
    assert saved["speech"]["future_voice"] == "keep"
    history = path.parent / "version-history" / "20261011-checkpoint"
    history.mkdir(parents=True)
    (history / path.name).write_bytes(path.read_bytes())
    path.write_text(
        json.dumps({"version": 1, "speech": {"speed": 210}, "gaze": {"dwell_ms": 950}}),
        encoding="utf-8",
    )
    gaze, speech = load_app_settings()
    assert speech.keyboard_script == "arabic"
    assert speech.speed == 210
    assert gaze.show_tracking_notifications is False
    assert gaze.dwell_ms == 950
    assert save_app_settings(gaze, speech)
    assert json.loads(path.read_text(encoding="utf-8"))["speech"]["future_voice"] == "keep"


@pytest.mark.parametrize("contents", ["invalid json", '{"version":999,"speech":{"speed":220}}'])
def test_unsupported_or_unreadable_settings_are_never_overwritten(monkeypatch, tmp_path, contents):
    path = point_settings_at(monkeypatch, tmp_path)
    path.parent.mkdir()
    path.write_text(contents, encoding="utf-8")
    assert not save_app_settings(GazeSettings(), SpeechSettings())
    assert path.read_text(encoding="utf-8") == contents


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
                    "selection_pause_ms": 5000,
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
    assert gaze.selection_pause_ms == 2000
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
    gaze = GazeSettings(selection_pause_ms=650, dwell_ms=750, move_mouse=False)
    speech = SpeechSettings(language="bs-Latn", letters_per_group=6)

    save_app_settings(gaze, speech)

    assert path.exists()
    assert not path.with_suffix(".json.tmp").exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["gaze"]["selection_pause_ms"] == 650
    assert payload["gaze"]["dwell_ms"] == 750
    assert payload["speech"]["language"] == "bs-Latn"
    assert load_app_settings() == (gaze, speech)


def test_save_failure_does_not_escape(monkeypatch, tmp_path):
    path = point_settings_at(monkeypatch, tmp_path)
    monkeypatch.setattr(
        type(path), "write_text", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("full"))
    )

    assert save_app_settings(GazeSettings(), SpeechSettings()) is False

    assert not path.exists()


def test_failed_replace_preserves_settings_and_retry_saves_latest_values(monkeypatch, tmp_path):
    path = point_settings_at(monkeypatch, tmp_path)
    assert save_app_settings(GazeSettings(dwell_ms=500), SpeechSettings())
    original = path.read_bytes()
    with monkeypatch.context() as patch:

        def fail(*_args):
            raise PermissionError("Synthetic locked file")

        patch.setattr(type(path), "replace", fail)
        assert not save_app_settings(GazeSettings(dwell_ms=800), SpeechSettings(speed=180))
    assert path.read_bytes() == original
    assert save_app_settings(GazeSettings(dwell_ms=800), SpeechSettings(speed=180))
    gaze, speech = load_app_settings()
    assert gaze.dwell_ms == 800 and speech.speed == 180


@pytest.mark.parametrize("value", [None, 123, [], {}, "", "../voice", "bad voice", "x" * 129])
def test_invalid_elevenlabs_identifiers_load_safe_defaults(monkeypatch, tmp_path, value):
    path = point_settings_at(monkeypatch, tmp_path)
    path.parent.mkdir()
    path.write_text(
        json.dumps(
            {
                "speech": {
                    "elevenlabs_voice_id": value,
                    "elevenlabs_model_id": value,
                }
            }
        ),
        encoding="utf-8",
    )
    settings = load_app_settings()[1]
    assert settings.elevenlabs_voice_id == ""
    assert settings.elevenlabs_model_id == "eleven_v4"


def test_elevenlabs_selection_survives_restart_and_older_release_without_storing_key(
    monkeypatch, tmp_path
):
    path = point_settings_at(monkeypatch, tmp_path)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "synthetic-private-key")
    speech = SpeechSettings(
        voice_preset="efendija",
        elevenlabs_voice_id="synthetic-voice",
        elevenlabs_model_id="eleven_v3",
    )
    assert save_app_settings(GazeSettings(), speech)
    assert load_app_settings()[1] == speech
    snapshot = path.parent / "version-history" / "synthetic-snapshot"
    snapshot.mkdir(parents=True)
    (snapshot / path.name).write_bytes(path.read_bytes())
    path.write_text('{"version": 1, "speech": {"speed": 200}}', encoding="utf-8")
    restored = load_app_settings()[1]
    assert restored.voice_preset == "efendija"
    assert restored.elevenlabs_voice_id == "synthetic-voice"
    assert restored.elevenlabs_model_id == "eleven_v3"
    assert restored.speed == 200


@pytest.mark.parametrize("value,expected", [(65, 50), (80, 100), (20, 0), (25, 0), (75, 50)])
def test_stability_uses_nearest_supported_step(tmp_path, monkeypatch, value, expected):
    path = point_settings_at(monkeypatch, tmp_path)
    path.parent.mkdir()
    path.write_text(json.dumps({"speech": {"elevenlabs_stability": value}}), encoding="utf-8")
    assert load_app_settings()[1].elevenlabs_stability == expected


def test_default_model_changes_without_overwriting_saved_model(tmp_path, monkeypatch):
    path = point_settings_at(monkeypatch, tmp_path)
    assert load_app_settings()[1].elevenlabs_model_id == "eleven_v4"
    path.parent.mkdir()
    path.write_text('{"speech": {"elevenlabs_model_id": "eleven_v3"}}', encoding="utf-8")
    assert load_app_settings()[1].elevenlabs_model_id == "eleven_v3"
