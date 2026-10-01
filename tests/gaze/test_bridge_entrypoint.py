from __future__ import annotations

import json
import threading

from pogled_assist.tracking import tobii_stream_engine_bridge


def test_bridge_emit_helpers_write_json(capsys):
    tobii_stream_engine_bridge._emit_gaze(0.25, 0.75, 10)
    tobii_stream_engine_bridge._emit_eye_status(True, False, 11)

    lines = capsys.readouterr().out.splitlines()
    assert json.loads(lines[0]) == {"type": "gaze", "x": 0.25, "y": 0.75, "timestamp": 10}
    assert json.loads(lines[1]) == {
        "type": "eyes",
        "left_open": True,
        "right_open": False,
        "timestamp": 11,
    }


def test_bridge_serializes_concurrent_messages_through_flush(monkeypatch):
    # Block the first writer inside stdout while the gaze callback tries to write.
    entered = threading.Event()
    release = threading.Event()
    competing = threading.Event()
    interleaved = threading.Event()
    chunks = []
    owner = [None]

    class SlowOutput:
        def write(self, text):
            current = threading.get_ident()
            if owner[0] is None:
                owner[0] = current
                entered.set()
                assert release.wait(2)
            elif owner[0] != current:
                interleaved.set()
            chunks.append(text)

        def flush(self):
            owner[0] = None

    def gaze():
        competing.set()
        tobii_stream_engine_bridge._emit_gaze(0.25, 0.75, 10)

    monkeypatch.setattr(tobii_stream_engine_bridge.sys, "stdout", SlowOutput())
    startup = threading.Thread(target=lambda: tobii_stream_engine_bridge._emit("started"))
    sample = threading.Thread(target=gaze)
    startup.start()
    try:
        assert entered.wait(2)
        sample.start()
        assert competing.wait(2)
        collided = interleaved.wait(0.1)
    finally:
        release.set()
        startup.join(2)
        sample.join(2)
    assert not startup.is_alive() and not sample.is_alive()
    assert not collided
    messages = [json.loads(line) for line in "".join(chunks).splitlines()]
    assert [message["type"] for message in messages] == ["started", "gaze"]


def test_bridge_main_rejects_64_bit_python(monkeypatch, capsys):
    monkeypatch.setattr(tobii_stream_engine_bridge, "_pointer_size", lambda: 8)

    assert tobii_stream_engine_bridge.main() == 2
    assert json.loads(capsys.readouterr().out) == {
        "type": "error",
        "message": "Tobii bridge must run with 32-bit Python.",
    }


def test_bridge_check_validates_without_starting_tracker(monkeypatch, capsys):
    monkeypatch.setattr(tobii_stream_engine_bridge, "_pointer_size", lambda: 4)
    monkeypatch.setattr(tobii_stream_engine_bridge.sys, "version_info", (3, 10))
    monkeypatch.setattr(tobii_stream_engine_bridge.sys, "argv", ["bridge.py", "--check"])

    def unexpected_tracking(*args):
        raise AssertionError("Verification must not start a tracker")

    monkeypatch.setattr(tobii_stream_engine_bridge, "TobiiStreamEngineBackend", unexpected_tracking)
    assert tobii_stream_engine_bridge.main() == 0
    assert json.loads(capsys.readouterr().out) == {"type": "checked", "python_bits": 32}
