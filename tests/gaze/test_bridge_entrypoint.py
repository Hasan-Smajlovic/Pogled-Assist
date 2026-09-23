from __future__ import annotations

import json

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


def test_bridge_main_rejects_64_bit_python(monkeypatch, capsys):
    monkeypatch.setattr(tobii_stream_engine_bridge, "_pointer_size", lambda: 8)

    assert tobii_stream_engine_bridge.main() == 2
    assert json.loads(capsys.readouterr().out) == {
        "type": "error",
        "message": "Tobii bridge must run with 32-bit Python.",
    }
