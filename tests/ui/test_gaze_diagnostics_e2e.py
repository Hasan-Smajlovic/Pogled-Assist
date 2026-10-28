from __future__ import annotations

import json
import logging
import threading
from types import SimpleNamespace

import pytest
from _clock import freeze_monotonic
from _ui_fakes import FakeAlarmSound, FakeLibraryStore, FakeSpeech
from PySide6.QtCore import QRect

from pogled_assist import logging_setup
from pogled_assist.diagnostic_recording import recording_context
from pogled_assist.interaction.mouse_controller import GazeMouseController, GazeSettings
from pogled_assist.tracking.gaze_provider import TobiiGazeProvider
from pogled_assist.ui.speech_window import SpeechWindow

pytestmark = pytest.mark.e2e


@pytest.fixture(params=["off", "basic", "trace", "blocked", "manual"])
def diagnostic_mode(request, monkeypatch, tmp_path):
    mode = request.param
    release = threading.Event()
    entered = threading.Event()

    class Console:
        def write(self, _text):
            entered.set()
            release.wait(10)

        def flush(self):
            pass

    monkeypatch.setattr(logging_setup, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(logging_setup.sys, "__stdout__", Console() if mode == "blocked" else None)
    monkeypatch.setattr(logging_setup.sys, "__stderr__", None)
    monkeypatch.setenv(
        "POGLED_ASSIST_GAZE_DIAGNOSTICS", "trace" if mode in {"trace", "blocked"} else ""
    )
    latest = logging_setup.set_application_logging_enabled(mode not in {"off", "manual"})
    if mode == "manual":
        logging_setup.recording_writer().start_recording(
            tmp_path / "recordings", 2, recording_context({}, {}, simulated=True)
        )
    if mode == "blocked":
        assert entered.wait(1)
        _fill_log_queue()
    yield mode, latest
    release.set()
    logging_setup._restore_standard_streams()
    logging_setup._clear_root_handlers()
    logging.disable(logging.NOTSET)


def _fill_log_queue():
    for _ in range(2000):
        logging_setup.diagnostic_writer().event("queue_pressure", {})


def records(latest):
    return [
        json.loads(line)
        for path in (latest.parent / "diagnostics").glob("*.jsonl")
        for line in path.read_text().splitlines()
    ]


def test_clear_confirmation_survives_invalid_eyes_gap_and_logging_failure(
    diagnostic_mode, qtbot, monkeypatch
):
    mode, latest = diagnostic_mode
    now = freeze_monotonic(monkeypatch, 100.0)
    window = SpeechWindow(
        FakeSpeech(), library_store=FakeLibraryStore(), alarm_sound=FakeAlarmSound()
    )
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    window._input.setText("PRIVATE COMPOSED MESSAGE")
    window._open_clear_dialog()
    qtbot.wait(1)
    screen = QRect(0, 0, 1280, 720)
    controller = GazeMouseController(window, pointer_movement_enabled=False)
    controller.update_settings(GazeSettings(selection_pause_ms=500, dwell_ms=1600))
    controller._logical_screen_rect = (0, 0, 1280, 720)
    controller._physical_screen_rect = (0, 0, 1920, 1080)
    provider = TobiiGazeProvider()
    gaze, eyes = provider._new_stream_callbacks()
    provider.eye_status_changed.connect(controller.handle_eye_status)
    provider.gaze_updated.connect(controller.handle_gaze)
    controller.toolbar_action_requested.connect(window.handle_gaze_action)
    window.interaction_context_changed.connect(controller.cancel_toolbar_interaction)
    actions = []
    controller.toolbar_action_requested.connect(actions.append)
    target = window.action_bounds(window._action("confirm:accept")).center()
    x, y = target.x() / (screen.width() - 1), target.y() / (screen.height() - 1)

    def feed(valid=True, advance=0.02):
        now[0] += advance
        eyes(True, valid, 1)
        gaze(x, y, 2)
        provider._emit_latest_gaze_sample()

    for _ in range(3):
        for _ in range(70):
            feed()
        feed(False)
    assert actions == []
    assert window._dialogs.active is window._dialogs.confirm
    assert window._input.text() == "PRIVATE COMPOSED MESSAGE"
    # A valid sample after a delivery gap must start the full selection again.
    feed(advance=0.7)
    assert actions == []
    for _ in range(110):
        feed()
    assert actions == [window._action("confirm:accept")]
    assert window._input.text() == ""
    assert window._dialogs.active is None
    provider.stop()
    if mode in {"basic", "trace"}:
        logging_setup.shutdown_application_logging()
        _assert_confirmation_events(mode, latest)


def _assert_confirmation_events(mode, latest):
    events = records(latest)
    assert any(
        data.get("reason") == "eye_gate_closed" for data in _event_data(events, "selection_state")
    )
    assert any(
        data["source"] == "gaze" and data["target_id"] == "confirm:accept"
        for data in _event_data(events, "ui_action_requested")
    )
    assert any(
        data["counts"].get("rejected:right_invalid")
        for data in _event_data(events, "stream_summary")
    )
    _assert_private_text_absent(latest)
    native_events = {item["event"] for item in events}
    assert ("native_gaze" in native_events) == (mode == "trace")


def _event_data(events, event):
    return [item["data"] for item in events if item["event"] == event]


def test_completed_pause_retention_matches_with_logging_off_on_and_blocked(
    diagnostic_mode, qtbot, monkeypatch
):
    mode, latest = diagnostic_mode
    now = freeze_monotonic(monkeypatch, 100.0)
    window = SpeechWindow(
        FakeSpeech(), library_store=FakeLibraryStore(), alarm_sound=FakeAlarmSound()
    )
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    window._input.setText("PRIVATE COMPOSED MESSAGE")
    window._open_clear_dialog()
    qtbot.wait(1)
    controller = GazeMouseController(window, pointer_movement_enabled=False)
    controller.update_settings(
        GazeSettings(
            eye_tracking_policy="hold",
            eye_tracking_hold_ms=300,
            selection_pause_ms=850,
            dwell_ms=650,
        )
    )
    controller._logical_screen_rect = (0, 0, 1280, 720)
    controller._physical_screen_rect = (0, 0, 1920, 1080)
    provider = TobiiGazeProvider()
    gaze, eyes = provider._new_stream_callbacks()
    provider.eye_state_changed.connect(
        lambda state: controller.handle_eye_status(state.left, state.right, state.received_at)
    )
    provider.gaze_updated.connect(
        lambda x, y, timestamp: controller.handle_gaze(x, y, timestamp, provider.gaze_received_at)
    )
    controller.toolbar_action_requested.connect(window.handle_gaze_action)
    window.interaction_context_changed.connect(controller.cancel_toolbar_interaction)
    actions = []
    controller.toolbar_action_requested.connect(actions.append)
    target = window.action_bounds(window._action("confirm:accept")).center()

    def sample(at):
        now[0] = at
        eyes(True, True, 1)
        gaze(target.x() / 1279, target.y() / 719, 1)
        provider._emit_latest_gaze_sample()

    for index in range(11):
        sample(100 + index / 10)
    now[0] = 101.01
    eyes(True, False, 2)
    now[0] = 101.32
    controller._eye_gate._deadline.timeout.emit()
    assert controller._toolbar_selection.diagnostic_snapshot()["credited_ms"] == 850
    sample(101.36)
    assert actions == []
    for index in range(1, 14):
        sample(101.36 + index * 0.05)
    sample(102.011)
    assert actions == [window._action("confirm:accept")]
    assert window._input.text() == ""
    provider.stop()
    if mode in {"basic", "trace"}:
        logging_setup.shutdown_application_logging()
        _assert_private_text_absent(latest)


def _assert_private_text_absent(latest):
    content = latest.read_text() + "".join(
        path.read_text() for path in (latest.parent / "diagnostics").glob("*.jsonl")
    )
    assert "PRIVATE COMPOSED MESSAGE" not in content


def test_pr73_collection_is_identical_with_logging_and_old_callbacks_are_ignored(
    diagnostic_mode, qtbot, monkeypatch
):
    from pogled_assist.ui.gaze_check_window import GazeCheckWindow

    mode, latest = diagnostic_mode
    now = freeze_monotonic(monkeypatch, 100.0)
    provider = TobiiGazeProvider()
    provider.set_check_active(True)
    gaze, eyes = provider._new_stream_callbacks()
    backend = SimpleNamespace(eye_position_supported=True)
    provider._attach_check_observers(backend)
    window = GazeCheckWindow(GazeSettings())
    qtbot.addWidget(window)
    window.setGeometry(QRect(0, 0, 1280, 720))
    window.show()
    qtbot.wait(1)
    window._timer.stop()
    provider.eye_status_changed.connect(window.handle_eye_status)
    provider.diagnostics_updated.connect(window.handle_snapshot)
    window._start_precision()
    qtbot.wait(1)
    for index in range(5):
        _name, x, y = window._check.targets[index]
        start = window._check.started_at
        for sample in range(100):
            now[0] = start + 1 + sample * 0.02
            eyes(True, True, sample)
            gaze(x, y, sample)
            backend.eye_position_callback((0.4, 0.5, 0.6), (0.6, 0.5, 0.6), sample)
            provider._emit_latest_gaze_sample()
        now[0] = start + 3.01
        window._tick()
    assert [result.samples for result in window._check.results] == [100] * 5
    assert [result.near for result in window._check.results] == [True] * 5
    assert [result.coverage for result in window._check.results] == pytest.approx(
        [0.99, 0.98, 0.98, 0.98, 0.98]
    )
    assert window._snapshot.left_position == (0.4, 0.5, 0.6)
    before = list(window._check.results)
    old_positions = backend.eye_position_callback
    old_invalid = backend.gaze_invalid_callback
    provider._invalidate_stream_callbacks()
    old_positions((0.1, 0.1, 0.1), (0.1, 0.1, 0.1), 0)
    old_invalid(0)
    assert provider.check_snapshot().left_position is None
    assert provider.check_snapshot().gaze_interruptions == 0
    assert window._check.results == before
    provider.stop()
    if mode in {"basic", "trace"}:
        logging_setup.shutdown_application_logging()
        results = [item for item in records(latest) if item["event"] == "fixation_result"]
        assert len(results) == (5 if mode == "trace" else 0)


def test_letter_geometry_is_complete_and_uses_opaque_ids(diagnostic_mode, qtbot):
    mode, latest = diagnostic_mode
    window = SpeechWindow(
        FakeSpeech(),
        letters_per_group=5,
        library_store=FakeLibraryStore(),
        alarm_sound=FakeAlarmSound(),
    )
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    window._show_letter_group(0)
    qtbot.wait(1)
    assert window._dialogs.active is None
    expected = {window._diagnostic_context.token(action) for action in window._main_dynamic_actions}
    if mode in {"basic", "trace"}:
        logging_setup.shutdown_application_logging()
        geometry = [
            item
            for item in records(latest)
            if item["event"] == "target_geometry"
            and item["data"].get("context_id") == window._diagnostic_context.id
        ]
        if mode == "basic":
            assert geometry == []
        else:
            _assert_letter_geometry(geometry, expected)


def _assert_letter_geometry(geometry, expected):
    assert geometry
    assert not any(item["data"].get("_snapshot_truncated") for item in geometry)
    targets = [
        target
        for item in geometry
        for target in item["data"]["targets"]
        if target["target_id"] in expected
    ]
    assert {target["target_id"] for target in targets} == expected
    assert len(targets) == len(expected)
    for target in targets:
        _assert_target_geometry(target)


def _assert_target_geometry(target):
    assert len(target["target_id"]) == 32
    assert len(target["logical_bounds"]) == 4
    assert target["visible"]
    assert target["enabled"]
