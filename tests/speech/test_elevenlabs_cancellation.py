from __future__ import annotations

import threading

import pytest
from _speech_service_fakes import service as service

from pogled_assist.speech import eleven_transport
from pogled_assist.speech.elevenlabs import ElevenClient


@pytest.fixture
def blocked_transport(monkeypatch):
    entered, released = threading.Event(), threading.Event()
    calls = []

    class Socket:
        def shutdown(self, _how):
            released.set()

        def settimeout(self, _timeout):
            pass

    class Response:
        status = 200
        body = b"synthetic audio"

        def read1(self, size):
            data, self.body = self.body[:size], self.body[size:]
            return data

        def getheader(self, name, default):
            return "audio/mpeg" if name == "Content-Type" else default

    class Connection:
        def __init__(self, _host, timeout):
            self.sock = Socket()
            self.first = not calls

        def connect(self):
            pass

        def request(self, method, path, **_kwargs):
            assert method == "POST"
            calls.append(path)

        def getresponse(self):
            if self.first:
                entered.set()
                assert released.wait(3), "cancellation did not close the active socket"
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(eleven_transport.http.client, "HTTPSConnection", Connection)
    yield entered, released, calls
    released.set()


def test_stop_then_immediate_speak_reaches_elevenlabs_without_false_timeout(
    service, blocked_transport, qtbot
):
    instance, _client, played = service
    entered, _released, calls = blocked_transport
    instance._router.client = ElevenClient()
    instance._router.natural = lambda *_: b"synthetic fallback"
    voices = []
    instance.voice_changed.connect(lambda _request, state: voices.append(state))
    assert instance.speak("PRVA PORUKA")
    qtbot.waitUntil(entered.is_set)
    instance.stop()
    assert instance.speak("DRUGA PORUKA")
    qtbot.waitUntil(lambda: instance.playback_state == "finished")
    assert len(calls) == 2
    assert len(played) == 1
    assert instance._router.gate.snapshot()[0] == ""
    assert not any(state.voice == "human_like" and state.reason == "timeout" for state in voices)
