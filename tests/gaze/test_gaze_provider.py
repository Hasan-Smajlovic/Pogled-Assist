from __future__ import annotations

import sys
import threading
from types import SimpleNamespace

import pytest

from pogled_assist.tracking.gaze_provider import (
    TobiiGazeProvider,
    _choose_tracker,
    _normalize_stream_engine_point,
    _tracker_label,
    _valid_gaze_point,
)


def test_valid_gaze_point_requires_valid_finite_coordinates():
    data = {
        "left_gaze_point_validity": 1,
        "left_gaze_point_on_display_area": (0.25, 0.75),
    }
    assert _valid_gaze_point(data, "left") == (0.25, 0.75)

    for point in ((float("nan"), 0.5), (0.5, float("inf")), None, (0.5,)):
        data["left_gaze_point_on_display_area"] = point
        assert _valid_gaze_point(data, "left") is None

    data["left_gaze_point_validity"] = 0
    data["left_gaze_point_on_display_area"] = (0.25, 0.75)
    assert _valid_gaze_point(data, "left") is None


def test_tracker_choice_prefers_4c_and_builds_readable_labels():
    generic = SimpleNamespace(model="Tobii Pro", device_name="", serial_number="123")
    tracker_4c = SimpleNamespace(model="", device_name="Eye Tracker 4C", serial_number="ABC")

    assert _choose_tracker((generic, tracker_4c)) is tracker_4c
    assert _tracker_label(tracker_4c) == "Eye Tracker 4C ABC"
    assert _tracker_label(SimpleNamespace()) == "Tobii uređaj za praćenje pogleda"


@pytest.mark.parametrize(
    ("point", "expected"),
    [
        ((0.2, 0.8), (0.2, 0.8)),
        ((-0.2, 1.2), (0.0, 1.0)),
        ((0.2399, 1.6603), (0.2399, 1.0)),
        ((-0.6, 0.7), (0.0, 0.7)),
        ((1.6, 0.7), (1.0, 0.7)),
        ((500.0, -50.0), (1.0, 0.0)),
    ],
)
def test_stream_engine_coordinates_are_normalized_and_clamped(point, expected):
    assert _normalize_stream_engine_point(*point) == pytest.approx(expected)


def test_stream_engine_offscreen_point_maps_to_same_edge_at_150_percent(qapp):
    from PySide6.QtCore import QPoint

    from pogled_assist.interaction.mouse_controller import GazeMouseController

    provider = TobiiGazeProvider()
    controller = GazeMouseController(lambda _: None, lambda *_: None, lambda _: False)
    controller._logical_screen_rect = (0, 0, 1280, 720)
    controller._physical_screen_rect = (0, 0, 1920, 1080)
    mapped = []
    provider.gaze_updated.connect(lambda x, y, _t: mapped.append(controller._map_to_screen(x, y)))
    provider._on_stream_engine_eye_status(True, True, 1)
    provider._on_stream_engine_gaze(0.2399, 1.6603, 2)
    provider._emit_latest_gaze_sample()
    assert mapped[0].logical == QPoint(307, 719)
    assert mapped[0].physical == QPoint(460, 1079)


@pytest.mark.parametrize("point", [(float("nan"), 0.5), (0.5, float("inf"))])
def test_stream_engine_rejects_nonfinite_samples(qapp, point):
    provider = TobiiGazeProvider()
    gaze = []
    provider.gaze_updated.connect(lambda *sample: gaze.append(sample))
    provider._on_stream_engine_eye_status(True, True, 1)
    provider._on_stream_engine_gaze(*point, 2)
    provider._emit_latest_gaze_sample()
    assert gaze == []


def test_provider_averages_two_valid_eyes_and_coalesces_samples(qapp):
    provider = TobiiGazeProvider()
    gaze = []
    eyes = []
    provider.gaze_updated.connect(lambda x, y, timestamp: gaze.append((x, y, timestamp)))
    provider.eye_status_changed.connect(lambda left, right: eyes.append((left, right)))

    provider._on_gaze_data(
        {
            "left_gaze_point_validity": 1,
            "left_gaze_point_on_display_area": (0.2, 0.4),
            "right_gaze_point_validity": 1,
            "right_gaze_point_on_display_area": (0.6, 0.8),
            "system_time_stamp": 42,
        }
    )
    provider._emit_latest_gaze_sample()

    assert eyes == [(True, True)]
    assert gaze[0][:2] == pytest.approx((0.4, 0.6))
    assert gaze[0][2] == 42

    provider._queue_gaze_sample("test", 0.1, 0.9, 42)
    provider._queue_gaze_sample("test", 0.9, 0.1, 43)
    provider._emit_latest_gaze_sample()

    assert gaze[-1] == (0.9, 0.1, 43)
    assert provider._dropped_sample_count == 1


def test_provider_stops_emitting_when_either_eye_is_invalid(qapp):
    provider = TobiiGazeProvider()
    gaze = []
    eyes = []
    provider.gaze_updated.connect(lambda *sample: gaze.append(sample))
    provider.eye_status_changed.connect(lambda left, right: eyes.append((left, right)))
    provider._queue_gaze_sample("test", 0.5, 0.5, 1)

    provider._on_gaze_data(
        {
            "left_gaze_point_validity": 1,
            "left_gaze_point_on_display_area": (0.2, 0.4),
            "right_gaze_point_validity": 0,
        }
    )
    provider._emit_latest_gaze_sample()

    assert eyes == [(True, False)]
    assert gaze == []


def test_provider_tries_backends_in_order_without_scheduling_retry(qapp, monkeypatch):
    provider = TobiiGazeProvider()
    provider._start_requested = True
    attempts = []
    monkeypatch.setattr(
        provider,
        "_start_with_tobii_research",
        lambda: attempts.append("tobii-research") or False,
    )
    monkeypatch.setattr(
        provider,
        "_start_with_stream_engine",
        lambda: attempts.append("stream-engine") or True,
    )

    provider._attempt_start()

    assert attempts == ["tobii-research", "stream-engine"]
    assert not provider._retry_timer.isActive()


def test_provider_schedules_retry_when_all_backends_are_unavailable(qapp, monkeypatch):
    provider = TobiiGazeProvider()
    provider._start_requested = True
    statuses = []
    provider.status_changed.connect(statuses.append)
    monkeypatch.setattr(provider, "_start_with_tobii_research", lambda: False)
    monkeypatch.setattr(provider, "_start_with_stream_engine", lambda: False)

    provider._attempt_start()

    assert provider._retry_timer.isActive()
    assert statuses[-1] == "Tobii uređaj nije pronađen. Pokušavam ponovo."
    provider.stop()


def test_provider_stop_closes_active_stream_engine_backend(qapp):
    class FakeBackend:
        stopped = False

        def stop(self):
            self.stopped = True

    provider = TobiiGazeProvider()
    backend = FakeBackend()
    provider._stream_engine = backend
    provider._running = True
    provider._start_requested = True
    provider._emit_timer.start()
    provider._retry_timer.start(1000)

    provider.stop()

    assert backend.stopped is True
    assert provider._stream_engine is None
    assert provider._running is False
    assert provider._start_requested is False
    assert not provider._emit_timer.isActive()
    assert not provider._retry_timer.isActive()


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
    provider._stream_started_at = now[0]
    provider._on_stream_engine_eye_status(True, True, 1)
    yield provider, now, stopped
    provider.stop()


def test_stream_stale_eye_data_cancels_dwell_and_requires_fresh_eyes(active_stream):
    from PySide6.QtCore import QPoint

    from pogled_assist.interaction.mouse_controller import GazeMouseController

    provider, now, stopped = active_stream
    statuses = []
    provider.status_changed.connect(statuses.append)
    controller = GazeMouseController(
        lambda _point: "speech",
        lambda *_args: QPoint(10, 10),
        lambda _point: True,
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
    now[0] = 10.7
    provider._on_stream_engine_gaze(0.5, 0.5, 4)
    provider._emit_latest_gaze_sample()
    assert controller._toolbar_selection.target is None
    provider._on_stream_engine_eye_status(True, True, 5)
    provider._on_stream_engine_gaze(0.5, 0.5, 6)
    provider._emit_latest_gaze_sample()
    assert statuses[-1] == "Praćenje je aktivno. Podaci o očima ponovo stižu."
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
    for _index in range(20):
        now[0] += 0.2
        provider._on_stream_engine_eye_status(False, False, 1)
        provider._emit_latest_gaze_sample()
    assert stopped == []
    assert provider._running is True
    assert not provider._retry_timer.isActive()


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
        lambda _point: "speech",
        lambda *_args: QPoint(10, 10),
        lambda _point: True,
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


@pytest.mark.parametrize("use_bridge", [False, True])
def test_callbacks_from_stopped_stream_cannot_reopen_gate(qapp, monkeypatch, use_bridge):
    from pogled_assist.tracking import gaze_provider

    callbacks = []

    class Backend:
        label = "fake stream"

        def __init__(self, gaze, eyes):
            callbacks.append((gaze, eyes))

        def start(self):
            pass

        def stop(self):
            # A native callback may already be in flight when stop is requested.
            callbacks[0][1](True, True, 99)
            callbacks[0][0](0.9, 0.9, 99)

    monkeypatch.setattr(gaze_provider, "TobiiStreamEngineBackend", Backend)
    monkeypatch.setattr(gaze_provider, "TobiiStreamEngineBridgeBackend", Backend)
    provider = TobiiGazeProvider()
    gaze = []
    eyes = []
    provider.gaze_updated.connect(lambda *args: gaze.append(args))
    provider.eye_status_changed.connect(lambda *args: eyes.append(args))

    def start():
        if use_bridge:
            return provider._start_with_stream_engine_bridge(RuntimeError("fake direct failure"))
        return provider._start_with_stream_engine()

    assert start()
    callbacks[0][1](True, True, 1)
    provider.stop()
    assert eyes[-1] == (False, False)
    assert provider._pending_gaze_sample is None
    assert start()
    callbacks[0][1](True, True, 99)
    callbacks[0][0](0.9, 0.9, 99)
    provider._emit_latest_gaze_sample()
    assert gaze == []
    callbacks[1][1](True, True, 2)
    callbacks[1][0](0.25, 0.75, 2)
    provider._emit_latest_gaze_sample()
    assert gaze == [(0.25, 0.75, 2)]
    provider.stop()


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
        lambda _point: "speech",
        lambda *_args: QPoint(10, 10),
        lambda _point: True,
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
        lambda _point: "speech",
        lambda *_args: QPoint(10, 10),
        lambda _point: True,
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


def test_queued_eye_status_cannot_reopen_gate_after_stop(qapp):
    from pogled_assist.interaction.mouse_controller import GazeMouseController

    provider = TobiiGazeProvider()
    controller = GazeMouseController(lambda _: None, lambda *_: None, lambda _: False)
    provider.eye_status_changed.connect(controller.handle_eye_status)
    _gaze, eyes = provider._new_stream_callbacks()
    worker = threading.Thread(target=lambda: eyes(True, True, 1))
    worker.start()
    worker.join(timeout=1)
    assert not worker.is_alive()
    provider.stop()
    qapp.processEvents()
    assert controller._both_eyes_open is False


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


def test_research_callbacks_from_previous_subscription_are_ignored(qapp, monkeypatch):
    from pogled_assist.interaction.mouse_controller import GazeMouseController

    callbacks = []
    unsubscribed = []
    tracker = SimpleNamespace(
        model="fake tracker",
        subscribe_to=lambda _event, callback, **_kwargs: callbacks.append(callback),
        unsubscribe_from=lambda _event, callback: unsubscribed.append(callback),
    )
    monkeypatch.setitem(
        sys.modules,
        "tobii_research",
        SimpleNamespace(find_all_eyetrackers=lambda: [tracker], EYETRACKER_GAZE_DATA="gaze"),
    )
    provider = TobiiGazeProvider()
    controller = GazeMouseController(lambda _: None, lambda *_: None, lambda _: False)
    provider.eye_status_changed.connect(controller.handle_eye_status)
    gaze = []
    provider.gaze_updated.connect(lambda *args: gaze.append(args))
    sample = {
        "left_gaze_point_validity": 1,
        "left_gaze_point_on_display_area": (0.2, 0.4),
        "right_gaze_point_validity": 1,
        "right_gaze_point_on_display_area": (0.6, 0.8),
        "system_time_stamp": 42,
    }
    assert provider._start_with_tobii_research()
    provider.stop()
    callbacks[0](sample)
    provider._emit_latest_gaze_sample()
    assert not controller._both_eyes_open
    assert gaze == []
    assert unsubscribed == [callbacks[0]]
    assert provider._start_with_tobii_research()
    callbacks[0](sample)
    provider._emit_latest_gaze_sample()
    assert gaze == []
    callbacks[1](sample)
    provider._emit_latest_gaze_sample()
    assert len(gaze) == 1
    assert controller._both_eyes_open
    provider.stop()


def test_queued_stream_resumption_cannot_override_retry_status(active_stream, qapp):
    from PySide6.QtWidgets import QLabel

    provider, now, _stopped = active_stream
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
    label.deleteLater()
