from __future__ import annotations

import gc
import sys
import threading
import weakref
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QThread, QTimer

from pogled_assist.tracking import gaze_provider
from pogled_assist.tracking.gaze_provider import TobiiGazeProvider
from pogled_assist.tracking.status import TrackingState


@pytest.mark.parametrize("phase", ["discovery", "native", "bridge"])
def test_startup_waits_leave_qt_events_responsive(qtbot, monkeypatch, phase):
    release = threading.Event()
    waited = []
    attempts = []

    def delayed():
        waited.append(release.wait(timeout=2))

    def discover():
        attempts.append("research")
        if phase == "discovery":
            delayed()
        return []

    def backend(name):
        def start():
            attempts.append(name)
            if phase == name:
                delayed()
            if name == "native" and phase == "bridge":
                raise RuntimeError("synthetic fallback")

        return SimpleNamespace(start=start, stop=lambda: None, label="synthetic")

    monkeypatch.setitem(
        sys.modules, "tobii_research", SimpleNamespace(find_all_eyetrackers=discover)
    )
    monkeypatch.setattr(gaze_provider, "TobiiStreamEngineBackend", lambda *_: backend("native"))
    monkeypatch.setattr(
        gaze_provider, "TobiiStreamEngineBridgeBackend", lambda *_: backend("bridge")
    )
    provider = TobiiGazeProvider()
    deliveries = []
    provider.tracking_status_changed.connect(
        lambda status: deliveries.append((status.state, QThread.currentThread()))
    )
    QTimer.singleShot(0, release.set)
    try:
        provider.start()
        qtbot.waitUntil(lambda: provider._running)
        assert waited == [True]
        assert all(thread == provider.thread() for _state, thread in deliveries)
        assert deliveries[-1][0] == TrackingState.CONNECTED
        assert attempts == (
            ["research", "native", "bridge"] if phase == "bridge" else ["research", "native"]
        )
    finally:
        release.set()
        provider.stop()
        qtbot.waitUntil(lambda: provider._connection_session is None)


@pytest.mark.parametrize("phase", ["discovery", "subscription", "startup", "cleanup"])
def test_stop_during_blocking_work_discards_late_results_and_callbacks(qtbot, monkeypatch, phase):
    entered = threading.Event()
    release = threading.Event()
    callbacks = []
    stopped = []
    subscriptions = []

    def block(name):
        if name == phase:
            entered.set()
            assert release.wait(timeout=3)

    tracker = _blocking_tracker(block, callbacks, subscriptions, stopped)

    def discover():
        block("discovery")
        return [tracker] if phase == "subscription" else []

    def backend(gaze, eyes):
        callbacks.append(lambda: (eyes(True, True, 1), gaze(0.5, 0.5, 1)))

        def stop():
            block("cleanup")
            stopped.append(True)
            callbacks[-1]()

        return SimpleNamespace(start=lambda: block("startup"), stop=stop, label="fake")

    monkeypatch.setitem(
        sys.modules,
        "tobii_research",
        SimpleNamespace(find_all_eyetrackers=discover, EYETRACKER_GAZE_DATA="gaze"),
    )
    monkeypatch.setattr(gaze_provider, "TobiiStreamEngineBackend", backend)
    provider = TobiiGazeProvider()
    eyes = []
    gaze = []
    statuses = []
    provider.eye_status_changed.connect(lambda *args: eyes.append(args))
    provider.gaze_updated.connect(lambda *args: gaze.append(args))
    provider.tracking_status_changed.connect(lambda status: statuses.append(status.state))
    try:
        provider.start()
        provider.start()
        if phase == "cleanup":
            qtbot.waitUntil(lambda: provider._running)
            provider.stop()
        qtbot.waitUntil(entered.is_set)
        provider.stop()
        QTimer.singleShot(0, release.set)
        qtbot.waitUntil(lambda: provider._connection_session is None)
        for callback in callbacks:
            callback()
        provider._emit_latest_gaze_sample()
        assert eyes[-1] == (False, False)
        assert gaze == []
        assert statuses[-1] == TrackingState.STOPPED
        assert not provider._running
        assert not provider._retry_timer.isActive()
        assert len(subscriptions) <= 1
        assert stopped == ([] if phase == "discovery" else [True])
    finally:
        release.set()
        provider.stop()
        qtbot.waitUntil(lambda: provider._connection_session is None)


def _blocking_tracker(block, callbacks, subscriptions, stopped):
    def subscribe(_event, callback, **_kwargs):
        subscriptions.append(callback)
        callbacks.append(
            lambda: callback(
                {
                    "left_gaze_point_validity": 1,
                    "left_gaze_point_on_display_area": (0.5, 0.5),
                    "right_gaze_point_validity": 1,
                    "right_gaze_point_on_display_area": (0.5, 0.5),
                }
            )
        )
        block("subscription")

    return SimpleNamespace(
        model="fake", subscribe_to=subscribe, unsubscribe_from=lambda *_: stopped.append(True)
    )


def test_native_cleanup_must_finish_before_a_new_subscription(qtbot, monkeypatch):
    released = threading.Event()
    closing = threading.Event()
    started = []
    monkeypatch.setitem(
        sys.modules, "tobii_research", SimpleNamespace(find_all_eyetrackers=lambda: [])
    )

    def backend(*_):
        def stop():
            closing.set()
            return released.is_set()

        return SimpleNamespace(start=lambda: started.append(True), stop=stop, label="native")

    monkeypatch.setattr(gaze_provider, "TobiiStreamEngineBackend", backend)
    provider = TobiiGazeProvider()
    try:
        provider.start()
        qtbot.waitUntil(lambda: provider._running)
        provider.stop()
        provider.start()
        qtbot.waitUntil(closing.is_set)
        provider._attempt_start()
        assert started == [True]
        assert not provider._running
        released.set()
        qtbot.waitUntil(lambda: provider._running)
        assert started == [True, True]
    finally:
        released.set()
        provider.stop()
        qtbot.waitUntil(lambda: provider._connection_session is None)


def test_recovery_cleanup_and_retry_leave_qt_responsive(qtbot, monkeypatch):
    from pogled_assist.tracking.tobii_stream_engine_bridge_backend import (
        TobiiStreamEngineBridgeBackend,
    )

    release = threading.Event()
    attempts = []
    closed = []
    monkeypatch.setitem(
        sys.modules, "tobii_research", SimpleNamespace(find_all_eyetrackers=lambda: [])
    )
    monkeypatch.setattr(
        gaze_provider,
        "TobiiStreamEngineBackend",
        lambda *_: (_ for _ in ()).throw(RuntimeError("unavailable")),
    )

    def backend(*_):
        instance = TobiiStreamEngineBridgeBackend(lambda *_: None, lambda *_: None)
        instance.start = lambda: attempts.append(True)

        def stop():
            closed.append(release.wait(timeout=3))

        instance.stop = stop
        return instance

    monkeypatch.setattr(gaze_provider, "TobiiStreamEngineBridgeBackend", backend)
    provider = TobiiGazeProvider()
    try:
        provider.start()
        qtbot.waitUntil(lambda: provider._running)
        provider._stream_engine._connection_failed("synthetic EOF")
        QTimer.singleShot(0, release.set)
        provider._check_stream_health()
        qtbot.waitUntil(provider._retry_timer.isActive)
        assert closed == [True]
        provider._retry_timer.stop()
        provider._attempt_start()
        qtbot.waitUntil(lambda: provider._running)
        assert attempts == [True, True]
    finally:
        release.set()
        provider.stop()
        qtbot.waitUntil(lambda: provider._connection_session is None)


def test_cancel_pending_real_bridge_readiness_leaves_no_child(qtbot, monkeypatch, tmp_path):
    from pogled_assist.tracking import tobii_stream_engine_bridge_backend as bridge

    script = tmp_path / "delayed_bridge.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    monkeypatch.setitem(
        sys.modules, "tobii_research", SimpleNamespace(find_all_eyetrackers=lambda: [])
    )
    monkeypatch.setattr(
        gaze_provider,
        "TobiiStreamEngineBackend",
        lambda *_: (_ for _ in ()).throw(RuntimeError("unavailable")),
    )
    monkeypatch.setattr(bridge, "_find_x86_python", lambda *_: sys.executable)
    monkeypatch.setattr(bridge, "bridge_script_path", lambda: script)
    backends = []

    def backend(*args):
        instance = bridge.TobiiStreamEngineBridgeBackend(*args)
        backends.append(instance)
        return instance

    monkeypatch.setattr(gaze_provider, "TobiiStreamEngineBridgeBackend", backend)
    provider = TobiiGazeProvider()
    try:
        provider.start()
        qtbot.waitUntil(lambda: bool(backends) and backends[0]._process is not None)
        process = backends[0]._process
        provider.stop()
        provider.wait_for_shutdown()
        assert process.poll() is not None
        qtbot.waitUntil(lambda: provider._connection_session is None)
        assert process.poll() is not None
        assert not provider._running
        assert not provider._retry_timer.isActive()
        assert backends[0].failure_observation is None
    finally:
        provider.stop()
        qtbot.waitUntil(lambda: provider._connection_session is None)


def test_stop_from_connected_notification_cannot_publish_later_success(qtbot, monkeypatch):
    monkeypatch.setitem(
        sys.modules, "tobii_research", SimpleNamespace(find_all_eyetrackers=lambda: [])
    )
    monkeypatch.setattr(
        gaze_provider,
        "TobiiStreamEngineBackend",
        lambda *_: SimpleNamespace(start=lambda: None, stop=lambda: None, label="fake"),
    )
    provider = TobiiGazeProvider()
    trackers = []
    statuses = []
    provider.tracker_changed.connect(trackers.append)
    provider.status_changed.connect(statuses.append)
    provider.tracking_status_changed.connect(
        lambda status: provider.stop() if status.state == TrackingState.CONNECTED else None
    )
    provider.start()
    qtbot.waitUntil(lambda: provider._connection_session is None)
    assert not provider._running
    assert trackers == []
    assert not any("Praćenje je aktivno" in text for text in statuses)


def test_failed_research_subscription_cleans_partial_callback_before_fallback(qtbot, monkeypatch):
    registered = []
    attempts = []

    def subscribe(_event, callback, **_):
        registered.append(callback)
        raise RuntimeError("synthetic failed subscription")

    def unsubscribe(_event, callback):
        attempts.append("unsubscribe")
        if callback in registered:
            registered.remove(callback)
            raise RuntimeError("synthetic interop unsubscribe failure")

    tracker = SimpleNamespace(model="fake", subscribe_to=subscribe, unsubscribe_from=unsubscribe)
    monkeypatch.setitem(
        sys.modules,
        "tobii_research",
        SimpleNamespace(find_all_eyetrackers=lambda: [tracker], EYETRACKER_GAZE_DATA="gaze"),
    )
    monkeypatch.setattr(
        gaze_provider,
        "TobiiStreamEngineBackend",
        lambda *_: SimpleNamespace(
            start=lambda: attempts.append("native"), stop=lambda: None, label="native"
        ),
    )
    provider = TobiiGazeProvider()
    try:
        provider.start()
        qtbot.waitUntil(lambda: provider._running)
        assert attempts == ["unsubscribe", "unsubscribe", "native"]
        assert registered == []
        assert provider._backend_name == "stream-engine"
    finally:
        provider.stop()
        qtbot.waitUntil(lambda: provider._connection_session is None)


def test_finished_session_releases_callbacks_without_cyclic_collection(qtbot, monkeypatch):
    monkeypatch.setitem(
        sys.modules, "tobii_research", SimpleNamespace(find_all_eyetrackers=lambda: [])
    )
    monkeypatch.setattr(
        gaze_provider,
        "TobiiStreamEngineBackend",
        lambda gaze, eyes: SimpleNamespace(
            start=lambda: None, stop=lambda: None, label="fake", gaze=gaze, eyes=eyes
        ),
    )
    provider = TobiiGazeProvider()
    was_enabled = gc.isenabled()
    # Callback cycles could otherwise release Qt owners during a later worker's
    # collection. Require the finished session to release by reference count.
    gc.disable()
    try:
        provider.start()
        qtbot.waitUntil(lambda: provider._running)
        session = weakref.ref(provider._connection_session)
        provider.stop()
        qtbot.waitUntil(lambda: provider._connection_session is None)
        assert session() is None
    finally:
        provider.stop()
        qtbot.waitUntil(lambda: provider._connection_session is None)
        if was_enabled:
            gc.enable()
        gc.collect()


@pytest.mark.parametrize("known_error", [False, True])
def test_backend_fallback_messages_stay_on_qt(qtbot, monkeypatch, known_error):
    from pogled_assist.tracking.tobii_stream_engine import TobiiStreamEngineError

    monkeypatch.setitem(
        sys.modules, "tobii_research", SimpleNamespace(find_all_eyetrackers=lambda: [])
    )
    error = TobiiStreamEngineError if known_error else RuntimeError

    def unavailable(*_):
        raise error("synthetic unavailable backend")

    monkeypatch.setattr(gaze_provider, "TobiiStreamEngineBackend", unavailable)
    monkeypatch.setattr(
        gaze_provider,
        "TobiiStreamEngineBridgeBackend",
        lambda *_: SimpleNamespace(start=lambda: None, stop=lambda: None, label="bridge"),
    )
    provider = TobiiGazeProvider()
    messages = []
    provider.status_changed.connect(
        lambda message: messages.append((message, QThread.currentThread()))
    )
    try:
        provider.start()
        qtbot.waitUntil(lambda: provider._running)
        expected = [
            "Tobii uređaj nije pronađen putem Pro SDK-a. Pokušavam Stream Engine.",
            "Stream Engine nije dostupan. Pokušavam drugi način."
            if known_error
            else "Stream Engine nije uspio. Pokušavam drugi način.",
            "Pokušavam Tobii x86 most za 32-bitni Core Software.",
            "Praćenje je aktivno putem uređaja bridge.",
        ]
        assert [message for message, _thread in messages][-4:] == expected
        assert all(thread == provider.thread() for _message, thread in messages)
    finally:
        provider.stop()
        qtbot.waitUntil(lambda: provider._connection_session is None)


def test_closed_real_backend_cannot_retain_the_qt_provider(qtbot, monkeypatch):
    from pogled_assist.tracking.tobii_stream_engine_bridge_backend import (
        TobiiStreamEngineBridgeBackend,
    )

    monkeypatch.setitem(
        sys.modules, "tobii_research", SimpleNamespace(find_all_eyetrackers=lambda: [])
    )
    monkeypatch.setattr(TobiiStreamEngineBridgeBackend, "start", lambda _: None)
    monkeypatch.setattr(gaze_provider, "TobiiStreamEngineBackend", TobiiStreamEngineBridgeBackend)
    provider = TobiiGazeProvider()
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        provider.start()
        qtbot.waitUntil(lambda: provider._running)
        backend = provider._stream_engine
        assert backend._message_handlers["gaze"].__self__ is backend
        provider.stop()
        qtbot.waitUntil(lambda: provider._connection_session is None)
        owner = weakref.ref(provider)
        provider = None
        assert owner() is None
        backend._gaze_callback(0.5, 0.5, 1)
    finally:
        if provider is not None:
            provider.stop()
            qtbot.waitUntil(lambda: provider._connection_session is None)
        if was_enabled:
            gc.enable()
        gc.collect()
