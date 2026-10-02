from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from pogled_assist.interaction.gaze_targets import GazeTargets
from pogled_assist.tracking.gaze_provider import TobiiGazeProvider
from pogled_assist.tracking.status import TrackingState, TrackingStatus


@pytest.fixture
def active_stream(qapp, monkeypatch):
    now = [10.0]
    monkeypatch.setattr("pogled_assist.tracking.gaze_provider.time.monotonic", lambda: now[0])
    stopped = []
    provider = TobiiGazeProvider()
    provider._stream_engine = SimpleNamespace(
        stop=lambda: stopped.append(True), connection_error=None
    )
    provider._running = True
    provider._start_requested = True
    provider._backend_name = "stream-engine-x86-bridge"
    provider._set_tracking_status(TrackingState.CONNECTED, "Fake tracker")
    provider._stream_started_at = now[0]
    provider._on_stream_engine_eye_status(True, True, 1)
    yield provider, now, stopped
    provider.stop()


def test_stream_stale_eye_data_cancels_dwell_and_requires_fresh_eyes(active_stream):
    from PySide6.QtCore import QPoint

    from pogled_assist.interaction.mouse_controller import GazeMouseController

    provider, now, stopped = active_stream
    statuses = []
    tracking = []
    provider.tracking_status_changed.connect(tracking.append)
    provider.status_changed.connect(statuses.append)
    controller = GazeMouseController(
        GazeTargets(
            lambda _point: "speech",
            lambda *_args: QPoint(10, 10),
            lambda _point: True,
        ),
        pointer_movement_enabled=False,
    )
    controller._logical_screen_rect = (0, 0, 1280, 720)
    controller._physical_screen_rect = (0, 0, 1920, 1080)
    controller.handle_eye_status(True, True)
    provider.eye_status_changed.connect(controller.handle_eye_status)
    provider.gaze_updated.connect(controller.handle_gaze)
    actions = []
    controller.toolbar_action_requested.connect(actions.append)
    provider._on_stream_engine_gaze(0.5, 0.5, 2)
    provider._emit_latest_gaze_sample()
    assert controller._toolbar_selection.target == "speech"
    now[0] = 10.6
    provider._on_stream_engine_gaze(0.5, 0.5, 3)
    provider._emit_latest_gaze_sample()
    assert controller._both_eyes_open is False
    assert controller._toolbar_selection.target is None
    assert stopped == []
    assert tracking[-1] == TrackingStatus(TrackingState.WAITING, "Fake tracker")
    now[0] = 10.7
    provider._on_stream_engine_gaze(0.5, 0.5, 4)
    provider._emit_latest_gaze_sample()
    assert controller._toolbar_selection.target is None
    provider._on_stream_engine_eye_status(True, True, 5)
    provider._on_stream_engine_gaze(0.5, 0.5, 6)
    provider._emit_latest_gaze_sample()
    assert statuses[-1] == "Praćenje je aktivno. Podaci o očima ponovo stižu."
    assert tracking[-1] == TrackingStatus(TrackingState.CONNECTED, "Fake tracker")
    assert not provider._stream_stale
    now[0] = 11.1
    provider._on_stream_engine_eye_status(True, True, 7)
    provider._on_stream_engine_gaze(0.5, 0.5, 8)
    provider._emit_latest_gaze_sample()
    assert actions == []
    assert controller._toolbar_selection.target == "speech"


@pytest.mark.parametrize("failure", [False, True])
def test_stream_outage_stops_backend_and_schedules_retry(active_stream, failure):
    provider, now, stopped = active_stream
    if failure:
        provider._stream_engine.connection_error = "stdout closed"
    else:
        now[0] += 3.1
    provider._on_stream_engine_gaze(0.5, 0.5, 2)
    provider._emit_latest_gaze_sample()
    assert stopped == [True]
    assert provider._running is False
    assert provider._start_requested is True
    assert provider._retry_timer.isActive()
    assert provider._pending_gaze_sample is None
    assert provider._stream_eye_status_known is False


def test_live_invalid_eyes_do_not_restart_backend(active_stream):
    provider, now, stopped = active_stream
    tracking = []
    provider.tracking_status_changed.connect(tracking.append)
    for _index in range(20):
        now[0] += 0.2
        provider._on_stream_engine_eye_status(False, False, 1)
        provider._emit_latest_gaze_sample()
    assert stopped == []
    assert provider._running is True
    assert not provider._retry_timer.isActive()
    assert tracking == []


def test_watchdog_does_not_restart_after_shutdown(active_stream):
    provider, now, stopped = active_stream
    provider.stop()
    now[0] += 5
    provider._emit_latest_gaze_sample()
    assert stopped == [True]
    assert not provider._retry_timer.isActive()


@pytest.mark.parametrize("eyes_keep_arriving", [False, True])
def test_resumed_gaze_cannot_complete_dwell_from_before_delivery_gap(
    active_stream, eyes_keep_arriving
):
    from PySide6.QtCore import QPoint

    from pogled_assist.interaction.mouse_controller import GazeMouseController

    provider, now, _stopped = active_stream
    controller = GazeMouseController(
        GazeTargets(
            lambda _point: "speech",
            lambda *_args: QPoint(10, 10),
            lambda _point: True,
        ),
        pointer_movement_enabled=False,
    )
    controller._logical_screen_rect = (0, 0, 1280, 720)
    controller._physical_screen_rect = (0, 0, 1920, 1080)
    controller.handle_eye_status(True, True)
    provider.eye_status_changed.connect(controller.handle_eye_status)
    provider.gaze_updated.connect(controller.handle_gaze)
    actions = []
    controller.toolbar_action_requested.connect(actions.append)
    provider._on_stream_engine_gaze(0.5, 0.5, 1)
    provider._emit_latest_gaze_sample()
    for _ in range(6):
        now[0] += 0.2
        if eyes_keep_arriving:
            provider._on_stream_engine_eye_status(True, True, 2)
        # The GUI can also have been blocked/suspended, with no watchdog ticks.
    provider._on_stream_engine_eye_status(True, True, 3)
    provider._on_stream_engine_gaze(0.5, 0.5, 3)
    provider._emit_latest_gaze_sample()
    assert actions == []
    # The fresh stream must still be usable after starting a full new dwell.
    for _ in range(6):
        now[0] += 0.2
        provider._on_stream_engine_eye_status(True, True, 4)
        provider._on_stream_engine_gaze(0.5, 0.5, 4)
        provider._emit_latest_gaze_sample()
    assert actions == ["speech"]


def test_direct_native_outage_pauses_without_spawning_replacement(active_stream):
    provider, now, stopped = active_stream
    provider._backend_name = "stream-engine"
    now[0] += 4
    provider._emit_latest_gaze_sample()
    assert provider._last_eye_status == (False, False)
    assert stopped == []
    assert not provider._retry_timer.isActive()


def test_delivery_gap_preserves_completed_target_repeat_lock(active_stream):
    from PySide6.QtCore import QPoint

    from pogled_assist.interaction.mouse_controller import GazeMouseController

    provider, now, _stopped = active_stream
    controller = GazeMouseController(
        GazeTargets(
            lambda _point: "speech",
            lambda *_args: QPoint(10, 10),
            lambda _point: True,
        ),
        pointer_movement_enabled=False,
    )
    controller._logical_screen_rect = (0, 0, 1280, 720)
    controller._physical_screen_rect = (0, 0, 1920, 1080)
    controller.handle_eye_status(True, True)
    provider.eye_status_changed.connect(controller.handle_eye_status)
    provider.gaze_updated.connect(controller.handle_gaze)
    actions = []
    controller.toolbar_action_requested.connect(actions.append)
    for _ in range(8):
        now[0] += 0.2
        provider._on_stream_engine_eye_status(True, True, 1)
        provider._on_stream_engine_gaze(0.5, 0.5, 1)
        provider._emit_latest_gaze_sample()
    assert actions == ["speech"]
    now[0] += 2
    for _ in range(8):
        now[0] += 0.2
        provider._on_stream_engine_eye_status(True, True, 2)
        provider._on_stream_engine_gaze(0.5, 0.5, 2)
        provider._emit_latest_gaze_sample()
    assert actions == ["speech"]
    assert controller._toolbar_selection.is_blocked


def test_worker_eye_loss_is_delivered_before_next_gaze(active_stream):
    from PySide6.QtCore import QPoint

    from pogled_assist.interaction.mouse_controller import GazeMouseController

    provider, now, _stopped = active_stream
    controller = GazeMouseController(
        GazeTargets(
            lambda _point: "speech",
            lambda *_args: QPoint(10, 10),
            lambda _point: True,
        ),
        pointer_movement_enabled=False,
    )
    controller._logical_screen_rect = (0, 0, 1280, 720)
    controller._physical_screen_rect = (0, 0, 1920, 1080)
    controller.handle_eye_status(True, True)
    provider.eye_status_changed.connect(controller.handle_eye_status)
    provider.gaze_updated.connect(controller.handle_gaze)
    actions = []
    controller.toolbar_action_requested.connect(actions.append)
    for offset in (0, 0.2, 0.4, 0.6, 0.8):
        now[0] = 10 + offset
        provider._on_stream_engine_eye_status(True, True, 1)
        provider._on_stream_engine_gaze(0.5, 0.5, 1)
        provider._emit_latest_gaze_sample()

    def blink():
        provider._on_stream_engine_eye_status(False, True, 2)
        provider._on_stream_engine_eye_status(True, True, 3)
        provider._on_stream_engine_gaze(0.5, 0.5, 3)

    now[0] = 11.01
    worker = threading.Thread(target=blink)
    worker.start()
    worker.join(timeout=1)
    assert not worker.is_alive()
    # A due Qt timer can run before queued eye notifications from the reader.
    provider._emit_latest_gaze_sample()
    assert actions == []
    assert controller._toolbar_selection._started_ms == pytest.approx(11010)


def test_fresh_eyes_do_not_make_old_pending_gaze_fresh(active_stream):
    provider, now, _stopped = active_stream
    gaze = []
    provider.gaze_updated.connect(lambda *args: gaze.append(args))
    provider._on_stream_engine_gaze(0.9, 0.1, 1)
    now[0] += 0.6
    provider._on_stream_engine_eye_status(True, True, 2)
    provider._emit_latest_gaze_sample()
    assert gaze == []
    provider._on_stream_engine_gaze(0.25, 0.75, 3)
    provider._emit_latest_gaze_sample()
    assert gaze == [(0.25, 0.75, 3)]


def test_queued_stream_resumption_cannot_override_retry_status(active_stream, qapp):
    from PySide6.QtWidgets import QLabel

    provider, now, _stopped = active_stream
    tracking = []
    provider.tracking_status_changed.connect(tracking.append)
    label = QLabel()
    provider.status_changed.connect(label.setText)
    now[0] += 0.6
    provider._emit_latest_gaze_sample()
    worker = threading.Thread(target=lambda: provider._on_stream_engine_eye_status(True, True, 2))
    worker.start()
    worker.join(timeout=1)
    assert not worker.is_alive()
    provider._stream_engine.connection_error = "stdout closed"
    provider._emit_latest_gaze_sample()
    qapp.processEvents()
    assert label.text() == "Veza s Tobii uređajem je prekinuta. Pokušavam ponovo."
    assert tracking[-1].state == TrackingState.RETRYING
    label.deleteLater()
