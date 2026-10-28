from __future__ import annotations

import sys
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from pogled_assist.interaction.gaze_targets import GazeTargets
from pogled_assist.tracking.gaze_connection import _choose_tracker, _tracker_label
from pogled_assist.tracking.gaze_provider import (
    TobiiGazeProvider,
    _normalize_stream_engine_point,
    _valid_gaze_point,
)
from pogled_assist.tracking.status import TrackingState, TrackingStatus


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
    controller = GazeMouseController(
        GazeTargets(
            lambda _: None,
            lambda *_: None,
            lambda _: False,
        ),
    )
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


def test_provider_tries_backends_in_order_without_scheduling_retry(qtbot, monkeypatch):
    from pogled_assist.tracking import gaze_provider

    attempts = []
    monkeypatch.setitem(
        sys.modules,
        "tobii_research",
        SimpleNamespace(
            find_all_eyetrackers=lambda: attempts.append("research") or [],
        ),
    )
    monkeypatch.setattr(
        gaze_provider,
        "TobiiStreamEngineBackend",
        lambda *_: SimpleNamespace(
            start=lambda: attempts.append("native"),
            stop=lambda: None,
            label="fake",
        ),
    )
    provider = TobiiGazeProvider()
    provider.start()
    qtbot.waitUntil(lambda: provider._running)
    assert attempts == ["research", "native"]
    assert not provider._retry_timer.isActive()
    provider.stop()
    qtbot.waitUntil(lambda: provider._connection_session is None)


def test_provider_schedules_retry_when_all_backends_are_unavailable(qtbot, monkeypatch):
    from pogled_assist.tracking import gaze_provider

    monkeypatch.setitem(
        sys.modules, "tobii_research", SimpleNamespace(find_all_eyetrackers=lambda: [])
    )

    def unavailable(*_):
        raise RuntimeError("synthetic unavailable backend")

    monkeypatch.setattr(gaze_provider, "TobiiStreamEngineBackend", unavailable)
    monkeypatch.setattr(gaze_provider, "TobiiStreamEngineBridgeBackend", unavailable)
    provider = TobiiGazeProvider()
    statuses = []
    tracking = []
    provider.tracking_status_changed.connect(tracking.append)
    provider.status_changed.connect(statuses.append)
    provider.start()
    qtbot.waitUntil(provider._retry_timer.isActive)
    assert statuses[-1] == "Tobii uređaj nije pronađen. Pokušavam ponovo."
    assert [status.state for status in tracking] == [
        TrackingState.CONNECTING,
        TrackingState.RETRYING,
    ]
    provider.stop()
    assert tracking[-1] == TrackingStatus(TrackingState.STOPPED)


def test_provider_stop_closes_active_stream_engine_backend(qtbot):
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

    qtbot.waitUntil(lambda: provider._connection_session is None)
    assert backend.stopped is True
    assert provider._stream_engine is None
    assert provider._running is False
    assert provider._start_requested is False
    assert not provider._emit_timer.isActive()
    assert not provider._retry_timer.isActive()


@pytest.mark.parametrize("backend_name", ["research", "native", "bridge"])
@pytest.mark.parametrize("worker_thread", [False, True])
def test_tracking_lifecycle_and_first_invalid_eyes_are_published_by_each_backend(
    qtbot, monkeypatch, backend_name, worker_thread
):
    callbacks = _install_lifecycle_backends(monkeypatch, backend_name)
    provider = TobiiGazeProvider()
    statuses = []
    eyes = []
    provider.tracking_status_changed.connect(statuses.append)
    provider.eye_status_changed.connect(lambda *status: eyes.append(status))
    provider.start()
    qtbot.waitUntil(lambda: provider._running)
    assert [status.state for status in statuses] == [
        TrackingState.CONNECTING,
        TrackingState.CONNECTED,
    ]
    assert statuses[-1].detail == "Synthetic tracker"
    assert eyes == [(False, False)]

    def deliver_invalid():
        if worker_thread:
            worker = threading.Thread(target=callbacks[-1])
            worker.start()
            worker.join(timeout=1)
            assert not worker.is_alive()
            QApplication.processEvents()
        else:
            callbacks[-1]()

    deliver_invalid()
    assert eyes == [(False, False), (False, False)]
    deliver_invalid()
    assert eyes == [(False, False), (False, False)]
    provider.stop()
    assert statuses[-1] == TrackingStatus(TrackingState.STOPPED)
    qtbot.waitUntil(lambda: provider._connection_session is None)
    provider.start()
    qtbot.waitUntil(lambda: provider._running)
    before_first_sample = len(eyes)
    deliver_invalid()
    assert len(eyes) == before_first_sample + 1
    deliver_invalid()
    assert len(eyes) == before_first_sample + 1
    provider.stop()
    qtbot.waitUntil(lambda: provider._connection_session is None)


def _install_lifecycle_backends(monkeypatch, backend_name):
    from pogled_assist.tracking import gaze_provider

    callbacks = []

    def make_backend(_gaze, eyes, *, fail=False):
        callbacks.append(lambda: eyes(False, False, 1))

        def start():
            if fail:
                raise RuntimeError("Synthetic fallback")

        return SimpleNamespace(label="Synthetic tracker", start=start, stop=lambda: None)

    tracker = SimpleNamespace(
        model="Synthetic tracker",
        device_name="",
        serial_number="",
        subscribe_to=lambda _event, callback, **_kwargs: callbacks.append(lambda: callback({})),
        unsubscribe_from=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setitem(
        sys.modules,
        "tobii_research",
        SimpleNamespace(
            find_all_eyetrackers=lambda: [tracker] if backend_name == "research" else [],
            EYETRACKER_GAZE_DATA="gaze",
        ),
    )
    monkeypatch.setattr(
        gaze_provider,
        "TobiiStreamEngineBackend",
        lambda gaze, eyes: make_backend(gaze, eyes, fail=backend_name == "bridge"),
    )
    monkeypatch.setattr(gaze_provider, "TobiiStreamEngineBridgeBackend", make_backend)
    return callbacks


def test_queued_first_invalid_eyes_are_discarded_on_stop_and_old_callbacks_stay_invalid(qapp):
    provider = TobiiGazeProvider()
    events = []
    provider.eye_status_changed.connect(lambda *status: events.append(status))
    _gaze, old_eyes = provider._new_stream_callbacks()
    worker = threading.Thread(target=lambda: old_eyes(False, False, 1))
    worker.start()
    worker.join(timeout=1)
    assert not worker.is_alive()
    provider.stop()
    _gaze, current_eyes = provider._new_stream_callbacks()
    qapp.processEvents()
    old_eyes(False, False, 2)
    assert events == [(False, False)]
    current_eyes(False, False, 3)
    assert events == [(False, False), (False, False)]
    provider.stop()


@pytest.mark.parametrize("use_bridge", [False, True])
def test_callbacks_from_stopped_stream_cannot_reopen_gate(qapp, qtbot, monkeypatch, use_bridge):
    from pogled_assist.tracking import gaze_provider

    callbacks = []

    def make_backend(gaze, eyes):
        callbacks.append((gaze, eyes))

        def stop():
            # A native callback may already be in flight when stop is requested.
            callbacks[0][1](True, True, 99)
            callbacks[0][0](0.9, 0.9, 99)

        return SimpleNamespace(label="fake stream", start=lambda: None, stop=stop)

    monkeypatch.setitem(
        sys.modules, "tobii_research", SimpleNamespace(find_all_eyetrackers=lambda: [])
    )

    def native(*args):
        if use_bridge:
            raise RuntimeError("synthetic native unavailable")
        return make_backend(*args)

    monkeypatch.setattr(gaze_provider, "TobiiStreamEngineBackend", native)
    monkeypatch.setattr(gaze_provider, "TobiiStreamEngineBridgeBackend", make_backend)
    provider = TobiiGazeProvider()
    gaze = []
    eyes = []
    provider.gaze_updated.connect(lambda *args: gaze.append(args))
    provider.eye_status_changed.connect(lambda *args: eyes.append(args))

    def start():
        provider.start()
        qtbot.waitUntil(lambda: provider._running)
        return True

    assert start()
    callbacks[0][1](True, True, 1)
    provider.stop()
    assert eyes[-1] == (False, False)
    assert provider._pending_gaze_sample is None
    qtbot.waitUntil(lambda: provider._connection_session is None)
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
    qtbot.waitUntil(lambda: provider._connection_session is None)


def test_queued_eye_status_cannot_reopen_gate_after_stop(qapp):
    from pogled_assist.interaction.mouse_controller import GazeMouseController

    provider = TobiiGazeProvider()
    controller = GazeMouseController(
        GazeTargets(
            lambda _: None,
            lambda *_: None,
            lambda _: False,
        ),
    )
    provider.eye_status_changed.connect(controller.handle_eye_status)
    _gaze, eyes = provider._new_stream_callbacks()
    worker = threading.Thread(target=lambda: eyes(True, True, 1))
    worker.start()
    worker.join(timeout=1)
    assert not worker.is_alive()
    provider.stop()
    qapp.processEvents()
    assert controller._both_eyes_open is False


def test_research_callbacks_from_previous_subscription_are_ignored(qapp, qtbot, monkeypatch):
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
    controller = GazeMouseController(
        GazeTargets(
            lambda _: None,
            lambda *_: None,
            lambda _: False,
        ),
    )
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
    provider.start()
    qtbot.waitUntil(lambda: provider._running)
    provider.stop()
    callbacks[0](sample)
    provider._emit_latest_gaze_sample()
    assert not controller._both_eyes_open
    assert gaze == []
    qtbot.waitUntil(lambda: provider._connection_session is None)
    assert unsubscribed == [callbacks[0]]
    provider.start()
    qtbot.waitUntil(lambda: provider._running)
    callbacks[0](sample)
    provider._emit_latest_gaze_sample()
    assert gaze == []
    callbacks[1](sample)
    provider._emit_latest_gaze_sample()
    assert len(gaze) == 1
    assert controller._both_eyes_open
    provider.stop()
    qtbot.waitUntil(lambda: provider._connection_session is None)
