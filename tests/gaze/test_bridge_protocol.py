from __future__ import annotations

import io
import threading
from types import SimpleNamespace

import pytest
from _clock import freeze_monotonic

from pogled_assist.tracking.tobii_stream_engine_bridge_backend import (
    TobiiStreamEngineBridgeBackend,
)


def test_bridge_invalid_gaze_preserves_event_and_rejects_bad_timestamp():
    backend = TobiiStreamEngineBridgeBackend(lambda *_args: None, lambda *_args: None)
    invalid = []
    backend.gaze_invalid_callback = invalid.append
    backend._handle_message({"type": "gaze_invalid", "timestamp": 42})
    for timestamp in (None, [], "bad", float("nan"), float("inf")):
        backend._handle_message({"type": "gaze_invalid", "timestamp": timestamp})
    assert invalid == [42]
    backend._connection_failed("synthetic disconnect")
    backend._handle_message({"type": "gaze_invalid", "timestamp": 43})
    assert invalid == [42]


def test_bridge_position_capability_requires_boolean():
    backend = TobiiStreamEngineBridgeBackend(lambda *_args: None, lambda *_args: None)
    backend._on_started({"eye_position_supported": False})
    assert backend.eye_position_supported is False
    backend._on_started({"eye_position_supported": "false"})
    assert backend.eye_position_supported is None


def test_bridge_metadata_is_optional_bounded_and_does_not_change_position_capability():
    backend = TobiiStreamEngineBridgeBackend(lambda *_args: None, lambda *_args: None)
    backend._on_started(
        {
            "eye_position_supported": False,
            "diagnostic_metadata": {
                "sdk_version": "x" * 1000,
                "eye_validity_source": "gaze-origin",
                "firmware_version": ["bad"],
                "serial_number": "private identifier",
            },
        }
    )
    assert backend.eye_position_supported is False
    assert backend.diagnostic_metadata == {
        "sdk_version": "x" * 128,
        "eye_validity_source": "gaze-origin",
    }
    backend._on_started({"eye_position_supported": True, "diagnostic_metadata": "bad"})
    assert backend.eye_position_supported is True


def test_bridge_forwards_valid_positions_and_never_converts_bad_payloads_into_green():
    backend = TobiiStreamEngineBridgeBackend(lambda *_args: None, lambda *_args: None)
    positions = []
    backend.eye_position_callback = lambda *args: positions.append(args)
    backend._handle_message(
        {
            "type": "eye_position",
            "left": [0.3, 0.5, 1.2],
            "right": [0.7, 0.5, 1.2],
            "timestamp": 12,
        }
    )
    assert positions == [((0.3, 0.5, 1.2), (0.7, 0.5, 1.2), 12)]
    for malformed in (None, "123", [0.1], [0.1, float("nan"), 0.2], [True, 0.5, 0.5]):
        backend._handle_message({"type": "eye_position", "left": malformed, "right": malformed})
        assert positions[-1] == (None, None, 0)
    count = len(positions)
    backend._connection_failed("synthetic error")
    backend._handle_message({"type": "eye_position", "left": [0.5] * 3, "right": [0.5] * 3})
    assert len(positions) == count


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


@pytest.mark.parametrize("exit_code,state", [(None, "running"), (17, "exited")])
def test_bridge_failure_keeps_pretermination_process_observation(monkeypatch, exit_code, state):
    from pogled_assist import diagnostics

    now = freeze_monotonic(monkeypatch, 10.0)
    events = []
    monkeypatch.setattr(diagnostics, "emit", lambda event, **fields: events.append((event, fields)))
    backend = TobiiStreamEngineBridgeBackend(lambda *_: None, lambda *_: None)
    backend.connection_generation = 7
    process = SimpleNamespace(stdout=io.StringIO(""), poll=lambda: exit_code)
    backend._process = process
    backend._on_eyes({"left_open": False, "right_open": False, "timestamp": 1})
    now[0] += 0.2
    backend._read_stdout()
    observed = backend.failure_observation
    assert observed["stream_generation"] == 7
    assert observed["native_eye_age_ms"] == pytest.approx(200)
    assert observed["process_state"] == state
    assert observed["exit_code"] == exit_code
    assert not observed["shutdown_requested"]
    process.poll = lambda: -15
    backend.stop()
    assert backend.failure_observation == observed
    assert events[0][1]["decision"] == "failure"
    assert events[0][1]["exit_code"] == exit_code
    assert events[-1][1]["decision"] == "shutdown"
    assert events[-1][1]["shutdown_requested"]


def test_app_shutdown_is_observed_before_termination_without_an_unexpected_failure(monkeypatch):
    from pogled_assist import diagnostics

    events = []
    monkeypatch.setattr(diagnostics, "emit", lambda event, **fields: events.append(fields))
    backend = TobiiStreamEngineBridgeBackend(lambda *_: None, lambda *_: None)
    code = [None]
    backend._process = SimpleNamespace(
        poll=lambda: code[0], terminate=lambda: code.__setitem__(0, -15), wait=lambda **_: None
    )
    backend.stop()
    assert backend.failure_observation is None
    assert len(events) == 1
    assert events[0]["decision"] == "shutdown"
    assert events[0]["process_state"] == "running"
    assert events[0]["exit_code"] is None
    assert events[0]["native_eye_age_ms"] is None


@pytest.mark.parametrize("failure", ["timeout", "os-error"])
def test_shutdown_observation_is_not_repeated_when_cleanup_retries(monkeypatch, failure):
    from pogled_assist.tracking import tobii_stream_engine_bridge_backend as module

    events = []
    monkeypatch.setattr(module.diagnostics, "emit", lambda _event, **fields: events.append(fields))
    backend = TobiiStreamEngineBridgeBackend(lambda *_: None, lambda *_: None)
    code = [None]
    killed = []
    retry_error = (
        module.subprocess.TimeoutExpired("synthetic-bridge", 3)
        if failure == "timeout"
        else OSError("synthetic wait failure")
    )
    wait_errors = iter([module.subprocess.TimeoutExpired("synthetic-bridge", 3), retry_error, None])

    def wait(**_kwargs):
        error = next(wait_errors)
        if error is not None:
            raise error
        code[0] = -9

    process = SimpleNamespace(
        poll=lambda: code[0],
        terminate=lambda: None,
        kill=lambda: killed.append(True),
        wait=wait,
    )
    backend._process = process
    backend.request_stop()
    with pytest.raises((module.subprocess.TimeoutExpired, OSError)):
        backend.stop()
    assert backend._process is process
    assert killed == [True]
    assert len(events) == 1
    observed = dict(events[0])
    backend.stop()
    backend.stop()
    assert backend._process is None
    assert backend.failure_observation is None
    assert events == [observed]
    assert observed["decision"] == "shutdown"
    assert observed["reason"] == "app_shutdown"
    assert observed["process_state"] == "running"
    assert observed["exit_code"] is None
    assert observed["shutdown_requested"]


def test_cancel_during_python_discovery_never_launches_bridge(monkeypatch):
    from pogled_assist.tracking import tobii_stream_engine_bridge_backend as module

    entered = threading.Event()
    release = threading.Event()
    spawned = []
    errors = []

    def discover(_stop_event=None):
        entered.set()
        assert release.wait(timeout=2)
        return "synthetic-python"

    monkeypatch.setattr(module, "_find_x86_python", discover)
    monkeypatch.setattr(
        module.subprocess,
        "Popen",
        lambda *_, **__: (
            spawned.append(True) or SimpleNamespace(stdout=None, stderr=None, poll=lambda: 0)
        ),
    )
    backend = TobiiStreamEngineBridgeBackend(lambda *_: None, lambda *_: None)

    def start():
        try:
            backend.start()
        except module.TobiiStreamEngineBridgeError as error:
            errors.append(error)

    worker = threading.Thread(target=start)
    worker.start()
    try:
        assert entered.wait(timeout=1)
        backend.request_stop()
    finally:
        release.set()
        worker.join(timeout=2)
    assert not worker.is_alive()
    assert spawned == []
    assert len(errors) == 1
    assert backend.failure_observation is None


def test_bridge_readiness_timeout_keeps_failure_before_termination(monkeypatch):
    from pogled_assist.tracking import tobii_stream_engine_bridge_backend as module

    backend = TobiiStreamEngineBridgeBackend(lambda *_: None, lambda *_: None)
    code = [None]
    backend._process = SimpleNamespace(
        poll=lambda: code[0], terminate=lambda: code.__setitem__(0, -15), wait=lambda **_: None
    )
    monkeypatch.setattr(module, "START_TIMEOUT_SECONDS", 0)
    with pytest.raises(module.TobiiStreamEngineBridgeError, match="did not report ready"):
        backend._wait_for_start()
    observed = backend.failure_observation
    assert observed is not None
    assert "did not report ready" in observed["reason"]
    assert observed["process_state"] == "running"
    assert observed["exit_code"] is None
    assert not observed["shutdown_requested"]


def test_python_discovery_cancellation_stops_before_the_next_probe(monkeypatch):
    from pogled_assist.tracking import tobii_stream_engine_bridge_backend as module

    stopped = threading.Event()
    probed = []

    def probe(candidate):
        probed.append(candidate)
        stopped.set()
        return False

    monkeypatch.setattr(module, "_py_launcher_candidates", lambda: [])
    monkeypatch.setattr(module, "_common_python_candidates", lambda: ["later-candidate"])
    monkeypatch.setattr(module, "_is_x86_python", probe)
    with pytest.raises(module.TobiiStreamEngineBridgeError, match="cancelled"):
        module._find_x86_python(stopped)
    assert len(probed) == 1


@pytest.mark.parametrize("failure", ["timeout", "exit"])
def test_repeated_cleanup_does_not_report_a_started_bridge_as_not_started(monkeypatch, failure):
    from pogled_assist.tracking import tobii_stream_engine_bridge_backend as module

    events = []
    monkeypatch.setattr(module.diagnostics, "emit", lambda _event, **fields: events.append(fields))
    backend = TobiiStreamEngineBridgeBackend(lambda *_: None, lambda *_: None)
    code = [17 if failure == "exit" else None]
    backend._process = SimpleNamespace(
        poll=lambda: code[0],
        returncode=code[0],
        terminate=lambda: code.__setitem__(0, -15),
        wait=lambda **_: None,
    )
    monkeypatch.setattr(module, "START_TIMEOUT_SECONDS", 0)
    with pytest.raises(module.TobiiStreamEngineBridgeError):
        if failure == "exit":
            backend._raise_if_start_failed()
        else:
            backend._wait_for_start()
    observed = backend.failure_observation
    count = len(events)
    backend.stop()
    backend.stop()
    assert backend.failure_observation == observed
    assert len(events) == count
    assert all(event["process_state"] != "not_started" for event in events)
