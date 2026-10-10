from __future__ import annotations

import json
import logging
import threading
from types import SimpleNamespace

import pytest
from _ui_fakes import FakeAlarmSound, FakeLibraryStore, FakeSpeech
from PySide6.QtCore import QRect

from pogled_assist import logging_setup
from pogled_assist.interaction.mouse_controller import GazeMouseController, GazeSettings
from pogled_assist.tracking.gaze_provider import TobiiGazeProvider
from pogled_assist.ui.speech_window import SpeechWindow

pytestmark = pytest.mark.e2e


@pytest.fixture(params=["off", "basic", "trace", "blocked"])
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
    latest = logging_setup.set_application_logging_enabled(mode != "off")
    if mode == "blocked":
        assert entered.wait(1)
        for _ in range(2000):
            logging_setup.diagnostic_writer().event("queue_pressure", {})
    yield mode, latest
    release.set()
    logging_setup._restore_standard_streams()
    logging_setup._clear_root_handlers()
    logging.disable(logging.NOTSET)


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
    now = [100.0]
    monkeypatch.setattr("pogled_assist.tracking.gaze_provider.time.monotonic", lambda: now[0])
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
        events = records(latest)
        assert any(
            item["event"] == "selection_state" and item["data"].get("reason") == "eye_gate_closed"
            for item in events
        )
        assert any(
            item["event"] == "ui_action_requested"
            and item["data"]["source"] == "gaze"
            and item["data"]["target_id"] == "confirm:accept"
            for item in events
        )
        assert any(
            item["event"] == "stream_summary"
            and item["data"]["counts"].get("rejected:right_invalid")
            for item in events
        )
        content = latest.read_text() + "".join(
            path.read_text() for path in (latest.parent / "diagnostics").glob("*.jsonl")
        )
        assert "PRIVATE COMPOSED MESSAGE" not in content
        assert (
            "native_gaze" in {item["event"] for item in events}
            if mode == "trace"
            else not any(item["event"] == "native_gaze" for item in events)
        )


def test_pr73_collection_is_identical_with_logging_and_old_callbacks_are_ignored(
    diagnostic_mode, qtbot, monkeypatch
):
    from pogled_assist.ui.gaze_check_window import GazeCheckWindow

    mode, latest = diagnostic_mode
    now = [100.0]
    monkeypatch.setattr("pogled_assist.tracking.gaze_provider.time.monotonic", lambda: now[0])
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
    window._open_letter_dialog(0)
    qtbot.wait(1)
    assert window._dialogs.active is window._dialogs.letter
    expected = len(window._dialogs.actions)
    if mode in {"basic", "trace"}:
        logging_setup.shutdown_application_logging()
        geometry = [
            item
            for item in records(latest)
            if item["event"] == "target_geometry" and item["data"]["kind"] == "letter"
        ]
        if mode == "basic":
            assert geometry == []
        else:
            assert geometry
            assert not any(item["data"].get("_snapshot_truncated") for item in geometry)
            targets = [target for item in geometry for target in item["data"]["targets"]]
            assert len(targets) == expected
            assert all(len(target["target_id"]) == 32 for target in targets)
            assert all(len(target["logical_bounds"]) == 4 for target in targets)
            assert all(target["visible"] and target["enabled"] for target in targets)
