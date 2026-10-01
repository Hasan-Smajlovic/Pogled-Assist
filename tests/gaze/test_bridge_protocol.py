from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

from pogled_assist.tracking.tobii_stream_engine_bridge_backend import (
    TobiiStreamEngineBridgeBackend,
)


def test_unexpected_bridge_eof_invalidates_eyes_and_reports_failure():
    eyes = []
    backend = TobiiStreamEngineBridgeBackend(lambda *_args: None, lambda *args: eyes.append(args))
    backend._process = SimpleNamespace(
        stdout=io.StringIO(
            '{"type":"started","label":"test"}\n'
            '{"type":"eyes","left_open":true,"right_open":true,"timestamp":1}\n'
        )
    )
    backend._read_stdout()
    assert backend._started_event.is_set()
    assert backend.connection_error is not None
    assert eyes == [(True, True, 1), (False, False, 0)]


def test_expected_bridge_shutdown_does_not_report_failure():
    backend = TobiiStreamEngineBridgeBackend(lambda *_args: None, lambda *_args: None)
    backend._process = SimpleNamespace(stdout=io.StringIO(""))
    backend._stop_event.set()
    backend._read_stdout()
    assert backend.connection_error is None


@pytest.mark.parametrize(
    "message",
    [
        None,
        [],
        5,
        {"type": "gaze", "x": "nan", "y": 0.5},
        {"type": "gaze", "x": 0.5, "y": float("inf")},
    ],
)
def test_bridge_ignores_malformed_or_nonfinite_gaze(message):
    gaze = []
    backend = TobiiStreamEngineBridgeBackend(lambda *args: gaze.append(args), lambda *_args: None)
    backend._handle_message(message)
    assert gaze == []


@pytest.mark.parametrize("invalid", ["false", 1, None])
def test_bridge_invalid_eye_flags_cannot_enable_gaze(invalid):
    eyes = []
    backend = TobiiStreamEngineBridgeBackend(lambda *_args: None, lambda *args: eyes.append(args))
    backend._handle_message({"type": "eyes", "left_open": True, "right_open": invalid})
    assert eyes == [(False, False, 0)]


def test_bridge_skips_bad_lines_and_delivers_following_normalized_sample():
    gaze = []
    backend = TobiiStreamEngineBridgeBackend(lambda *args: gaze.append(args), lambda *_args: None)
    backend._process = SimpleNamespace(
        stdout=io.StringIO('not-json\n[]\n{"type":"gaze","x":0.2399,"y":1.6603,"timestamp":2}\n')
    )
    backend._read_stdout()
    assert gaze == [(0.2399, 1.6603, 2)]


@pytest.mark.parametrize("terminal", ["error", "stopped"])
def test_bridge_failure_stays_invalid_until_a_new_connection(terminal):
    eyes = []
    gaze = []
    backend = TobiiStreamEngineBridgeBackend(
        lambda *args: gaze.append(args), lambda *args: eyes.append(args)
    )
    backend._handle_message({"type": terminal})
    backend._handle_message({"type": "eyes", "left_open": True, "right_open": True})
    backend._handle_message({"type": "gaze", "x": 0.5, "y": 0.5})
    backend._connection_failed("EOF after terminal message")
    assert backend.connection_error is not None
    assert eyes == [(False, False, 0)]
    assert gaze == []
