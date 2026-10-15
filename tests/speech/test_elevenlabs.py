from __future__ import annotations

import json
import threading
import time

import pytest

from pogled_assist.speech import elevenlabs
from pogled_assist.speech.elevenlabs import (
    BoundedCall,
    ElevenClient,
    ElevenConfig,
    Subscription,
    configuration,
)
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.speech.voice_state import SpeechCancelled, VoiceError


class Response:
    def __init__(self, status, body, content_type):
        self.status, self.body, self.content_type = status, body, content_type

    def read1(self, size):
        result, self.body = self.body[:size], self.body[size:]
        return result

    def getheader(self, name, default):
        return self.content_type if name == "Content-Type" else default


@pytest.fixture
def transport(monkeypatch):
    class Connection:
        response = Response(200, b"synthetic audio", "audio/mpeg")
        calls = []
        closed = 0
        sock = None

        def __init__(self, host, timeout):
            assert host == "api.elevenlabs.io"
            assert 0 < timeout <= 5

        def request(self, method, path, *, body, headers):
            self.calls.append((method, path, body, headers))

        def getresponse(self):
            return self.response

        def close(self):
            type(self).closed += 1

    monkeypatch.setattr(elevenlabs.http.client, "HTTPSConnection", Connection)
    return Connection


def test_convert_preserves_text_pins_generation_and_never_puts_key_in_url(transport):
    client = ElevenClient()
    config = ElevenConfig("synthetic-secret", "voice-1", "eleven_v3")
    text = 'ČĆŽŠĐ. "<private>" $()'
    audio = client.synthesize(config, text, threading.Event(), time.monotonic() + 5)
    method, url, body, headers = transport.calls[0]
    assert audio == b"synthetic audio"
    assert method == "POST"
    assert url == "/v1/text-to-speech/voice-1?output_format=mp3_44100_128"
    assert json.loads(body) == {"text": text, **config.parameters}
    assert headers["xi-api-key"] == "synthetic-secret"
    assert "secret" not in repr(config) and "secret" not in config.audio_identity
    assert len(transport.calls) == transport.closed == 1


@pytest.mark.parametrize(("status", "detail", "reason"), [
    (401, "quota_exceeded", "quota"),
    (401, "invalid_api_key", "invalid_key"),
    (403, "missing_permissions", "permission"),
    (429, "too_many_concurrent_requests", "rate_limit"),
    (404, "voice_not_found", "configuration"),
    (422, "invalid_parameters", "configuration"),
    (503, "unavailable", "offline"),
])
def test_error_is_classified_without_exposing_body_or_retrying(transport, status, detail, reason):
    transport.response = Response(status, json.dumps({
        "detail": {"status": detail, "message": "private text and secret"}
    }).encode(), "application/json")
    with pytest.raises(VoiceError) as error:
        ElevenClient().synthesize(
            ElevenConfig("synthetic-key", "voice", "eleven_v3"), "private text",
            threading.Event(), time.monotonic() + 5,
        )
    assert error.value.reason == reason
    assert "private" not in str(error.value)
    assert len(transport.calls) == transport.closed == 1


@pytest.mark.parametrize("body", [b"", b"<html>not audio</html>"])
def test_empty_or_wrong_content_type_cannot_be_played(transport, body):
    transport.response = Response(200, body, "text/html")
    with pytest.raises(VoiceError, match="audio"):
        ElevenClient().synthesize(
            ElevenConfig("key", "voice"), "hello", threading.Event(), time.monotonic() + 5
        )


def test_response_size_is_bounded(transport, monkeypatch):
    monkeypatch.setattr(elevenlabs, "MAX_AUDIO_BYTES", 4)
    with pytest.raises(VoiceError, match="audio"):
        ElevenClient().synthesize(
            ElevenConfig("key", "voice"), "hello", threading.Event(), time.monotonic() + 5
        )
    assert transport.closed == 1


def test_development_environment_overrides_without_changing_persisted_settings(monkeypatch):
    settings = SpeechSettings(elevenlabs_voice_id="stored-voice", elevenlabs_model_id="stored-model")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "development-key")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "development-voice")
    monkeypatch.setenv("ELEVENLABS_MODEL_ID", "development-model")
    config = configuration(settings, "saved-key")
    assert (config.key, config.voice, config.model) == (
        "development-key", "development-voice", "development-model"
    )
    assert settings.elevenlabs_voice_id == "stored-voice"
    assert settings.elevenlabs_model_id == "stored-model"


def test_deadline_abandons_late_result_and_does_not_accumulate_network_threads():
    runner, release = BoundedCall(), threading.Event()
    entered = threading.Event()

    def blocked(cancel, _deadline):
        entered.set()
        release.wait(3)
        assert cancel.is_set()
        return b"late paid result"

    try:
        with pytest.raises(VoiceError, match="timeout"):
            runner.run(blocked, threading.Event(), 0.05)
        assert entered.is_set()
        called = []
        with pytest.raises(VoiceError, match="timeout"):
            runner.run(lambda *_: called.append(True), threading.Event(), 0.05)
        assert called == []
    finally:
        release.set()


def test_cancelled_request_never_starts_network_operation():
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(SpeechCancelled):
        BoundedCall().run(lambda *_: pytest.fail("cancelled operation was started"), cancel, 5)


def test_subscription_detects_top_up_and_monthly_reset_without_assuming_zero_balance():
    before = Subscription(95, 100, 1000)
    assert before.remaining == 5
    assert Subscription(95, 110, 1000).improved_from(before)
    assert Subscription(95, 100, 2000).improved_from(before)
    assert not Subscription(96, 100, 1000).improved_from(before)


def test_account_lists_all_voice_pages_and_only_bosnian_tts_models(monkeypatch):
    paths = []

    def request(_self, _key, method, path, *_args):
        assert method == "GET"
        paths.append(path)
        if path == "/v1/models":
            return [
                {"model_id": "bosnian", "name": "Bosanski", "can_do_text_to_speech": True,
                 "languages": [{"language_id": "bs"}]},
                {"model_id": "english", "can_do_text_to_speech": True,
                 "languages": [{"language_id": "en"}]},
            ]
        if path == "/v1/user/subscription":
            return {"character_count": 10, "character_limit": 100,
                    "next_character_count_reset_unix": 2000}
        if "next_page_token" in path:
            return {"voices": [{"voice_id": "two", "name": "Drugi"}], "has_more": False}
        return {"voices": [{"voice_id": "one", "name": "Prvi"}], "has_more": True,
                "next_page_token": "page 2"}

    monkeypatch.setattr(ElevenClient, "_request", request)
    options = ElevenClient().options("key", threading.Event(), time.monotonic() + 5)
    assert options.voices == (("one", "Prvi"), ("two", "Drugi"))
    assert options.models == (("bosnian", "Bosanski"),)
    assert options.subscription.remaining == 90
    assert "next_page_token=page+2" in paths[1]
