from __future__ import annotations

import ctypes

import pytest

from pogled_assist.tracking import tobii_stream_engine as engine


class FakeFunction:
    def __init__(self, library, name):
        self.library = library
        self.name = name
        self.argtypes = None
        self.restype = None

    def __call__(self, *arguments):
        library = self.library
        library.calls.append(self.name)
        status = library.errors.get(self.name, 0)
        if status:
            return status
        effect = library.effects.get(self.name)
        return effect(*arguments) if effect is not None else 0


class FakeLibrary:
    def __init__(self):
        self.calls = []
        self.errors = {}
        self.functions = {}
        self.callbacks = {}
        self.effects = {
            "tobii_api_create": self.create_api,
            "tobii_enumerate_local_device_urls": self.enumerate_urls,
            "tobii_device_create": self.create_device,
            "tobii_eye_position_normalized_subscribe": self.subscribe_eyes,
            "tobii_gaze_origin_subscribe": self.subscribe_origin,
            "tobii_gaze_point_subscribe": self.subscribe_gaze,
            "tobii_error_message": lambda _status: b"synthetic failure",
        }

    def __getattr__(self, name):
        if not name.startswith("tobii_"):
            raise AttributeError(name)
        if name not in self.functions:
            self.functions[name] = FakeFunction(self, name)
        return self.functions[name]

    def create_api(self, output, _allocator, _log):
        ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p)).contents.value = 10
        return 0

    def enumerate_urls(self, _api, receiver, _user_data):
        receiver(b"tobii://synthetic-device", None)
        return 0

    def create_device(self, *arguments):
        ctypes.cast(arguments[-1], ctypes.POINTER(ctypes.c_void_p)).contents.value = 20
        return 0

    def subscribe_eyes(self, _device, receiver, _user_data):
        self.callbacks["eyes"] = receiver
        return 0

    def subscribe_origin(self, _device, receiver, _user_data):
        self.callbacks["origin"] = receiver
        return 0

    def subscribe_gaze(self, _device, receiver, _user_data):
        self.callbacks["gaze"] = receiver
        return 0


@pytest.fixture
def native_backend(monkeypatch):
    library = FakeLibrary()
    gaze, eyes = [], []
    backend = engine.TobiiStreamEngineBackend(
        lambda *sample: gaze.append(sample), lambda *sample: eyes.append(sample)
    )
    monkeypatch.setattr(engine, "_load_stream_engine_library", lambda: (library, "fake.dll"))
    monkeypatch.setattr(engine, "_device_create_arg_counts", lambda: ("4", "3"))
    monkeypatch.setattr(backend, "_start_pump_thread", lambda: library.calls.append("pump"))
    yield backend, library, gaze, eyes
    backend._thread = None
    backend.stop()


def test_native_start_subscribes_eyes_before_gaze_and_stop_releases_resources(native_backend):
    backend, library, _gaze, _eyes = native_backend
    backend.start()
    assert backend._api.value == 10
    assert backend._device.value == 20
    assert library.calls[-3:] == [
        "tobii_eye_position_normalized_subscribe",
        "tobii_gaze_point_subscribe",
        "pump",
    ]

    backend.stop()
    assert library.calls[-5:] == [
        "tobii_eye_position_normalized_unsubscribe",
        "tobii_gaze_origin_unsubscribe",
        "tobii_gaze_point_unsubscribe",
        "tobii_device_destroy",
        "tobii_api_destroy",
    ]
    assert not backend._api
    assert not backend._device
    calls = list(library.calls)
    backend.stop()
    assert library.calls == calls


def test_native_callbacks_deliver_eye_validity_and_reject_invalid_gaze(native_backend):
    backend, library, gaze, eyes = native_backend
    invalid = []
    backend.gaze_invalid_callback = invalid.append
    backend.start()
    eye = engine.TobiiEyePositionNormalized()
    eye.timestamp_us = 41
    eye.left_validity = 1
    eye.right_validity = 0
    library.callbacks["eyes"](ctypes.pointer(eye), None)
    eye.right_validity = 1
    library.callbacks["eyes"](ctypes.pointer(eye), None)

    point = engine.TobiiGazePoint()
    point.timestamp_us = 42
    point.validity = 1
    point.position_xy[:] = (0.25, 0.75)
    library.callbacks["gaze"](ctypes.pointer(point), None)
    point.validity = 0
    library.callbacks["gaze"](ctypes.pointer(point), None)
    point.validity = 1
    point.position_xy[0] = float("nan")
    library.callbacks["gaze"](ctypes.pointer(point), None)

    assert eyes == [(True, False, 41), (True, True, 41)]
    assert gaze == [(0.25, 0.75, 42)]
    assert invalid == [42, 42]


@pytest.mark.e2e
@pytest.mark.parametrize("bridged", [False, True])
def test_invalid_native_gaze_breaks_check_even_when_eyes_stay_valid(
    native_backend, qtbot, monkeypatch, bridged
):
    from pogled_assist.interaction.mouse_controller import GazeSettings
    from pogled_assist.tracking.gaze_provider import TobiiGazeProvider
    from pogled_assist.tracking.tobii_stream_engine_bridge_backend import (
        TobiiStreamEngineBridgeBackend,
    )
    from pogled_assist.ui.gaze_check_window import GazeCheckWindow

    now = [10.0]
    monkeypatch.setattr("pogled_assist.tracking.gaze_provider.time.monotonic", lambda: now[0])
    provider = TobiiGazeProvider()
    gaze, eyes = provider._new_stream_callbacks()
    provider.set_check_active(True)
    backend, library, _gaze, _eyes = native_backend
    observer = TobiiStreamEngineBridgeBackend(gaze, eyes) if bridged else backend
    provider._attach_check_observers(observer)
    if bridged:
        backend._gaze_callback = lambda x, y, t: observer._on_gaze({"x": x, "y": y, "timestamp": t})
        backend._eye_status_callback = lambda left, right, t: observer._on_eyes(
            {"left_open": left, "right_open": right, "timestamp": t}
        )
        backend.eye_position_callback = lambda left, right, t: observer._on_eye_position(
            {"left": left, "right": right, "timestamp": t}
        )
        backend.gaze_invalid_callback = lambda t: observer._on_gaze_invalid({"timestamp": t})
    else:
        backend._gaze_callback = gaze
        backend._eye_status_callback = eyes
    backend.start()
    window = GazeCheckWindow(GazeSettings())
    provider.setParent(window)
    qtbot.addWidget(window)
    window.show_fullscreen_on_primary()
    qtbot.wait(1)
    window._timer.stop()
    provider.diagnostics_updated.connect(window.handle_snapshot)
    provider.eye_status_changed.connect(window.handle_eye_status)
    window._primary_button.click()
    qtbot.wait(1)
    start = window._check.started_at
    _name, x, y = window._check.targets[0]
    eye = engine.TobiiEyePositionNormalized()
    eye.left_validity = eye.right_validity = 1
    eye.left_xyz[:] = (0.4, 0.5, 0.6)
    eye.right_xyz[:] = (0.6, 0.5, 0.6)
    point = engine.TobiiGazePoint()
    point.position_xy[:] = (x, y)
    for sample in range(20):
        now[0] = start + 1 + sample * 0.1
        library.callbacks["eyes"](ctypes.pointer(eye), None)
        point.validity = 0
        library.callbacks["gaze"](ctypes.pointer(point), None)
        point.validity = 1
        library.callbacks["gaze"](ctypes.pointer(point), None)
        provider._emit_latest_gaze_sample()
    snapshot = provider.check_snapshot()
    assert snapshot.left is snapshot.right is True
    assert snapshot.left_position == pytest.approx((0.4, 0.5, 0.6))
    now[0] = start + 3.01
    window._tick()
    result = window._check.results[0]
    assert result.samples == 20
    assert result.coverage == 0
    assert result.near is None
    window._start_trial()
    screen = window.screen().geometry()
    target = window._target.mapToGlobal(window._target.center())
    point.position_xy[:] = (
        (target.x() - screen.left()) / (screen.width() - 1),
        (target.y() - screen.top()) / (screen.height() - 1),
    )
    for sample in range(40):
        now[0] = start + 3.1 + sample * 0.1
        library.callbacks["eyes"](ctypes.pointer(eye), None)
        point.validity = 0
        library.callbacks["gaze"](ctypes.pointer(point), None)
        point.validity = 1
        library.callbacks["gaze"](ctypes.pointer(point), None)
        provider._emit_latest_gaze_sample()
    assert window._trial_results == []
    assert window._target.progress == 0
    backend.stop()
    provider.stop()
    window.close()
    window.deleteLater()
    qtbot.wait(1)


def test_native_positions_are_copied_without_clamping_or_changing_eye_gate(native_backend):
    backend, library, _gaze, eyes = native_backend
    positions = []
    backend.eye_position_callback = lambda *args: positions.append(args)
    backend.start()
    sample = engine.TobiiEyePositionNormalized()
    sample.timestamp_us = 45
    sample.left_validity = sample.right_validity = 1
    sample.left_xyz[:] = (0.2, 0.4, 1.3)
    sample.right_xyz[:] = (float("nan"), 0.4, 0.5)
    library.callbacks["eyes"](ctypes.pointer(sample), None)
    sample.left_xyz[0] = 0.9  # Callback cannot retain mutable SDK memory.
    assert positions[0][0] == pytest.approx((0.2, 0.4, 1.3))
    assert positions[0][1] is None
    assert eyes == [(True, True, 45)]


def test_native_eye_subscription_falls_back_to_gaze_origin(native_backend):
    backend, library, _gaze, eyes = native_backend
    library.errors["tobii_eye_position_normalized_subscribe"] = 7
    positions = []
    backend.eye_position_callback = lambda *args: positions.append(args)
    backend.start()
    assert library.calls[-5:] == [
        "tobii_eye_position_normalized_subscribe",
        "tobii_error_message",
        "tobii_gaze_origin_subscribe",
        "tobii_gaze_point_subscribe",
        "pump",
    ]
    origin = engine.TobiiGazeOrigin()
    origin.timestamp_us = 43
    origin.left_validity = 0
    origin.right_validity = 1
    library.callbacks["origin"](ctypes.pointer(origin), None)
    assert eyes == [(False, True, 43)]
    assert positions == []  # Millimetre origins are not normalized box positions.


@pytest.mark.parametrize("failure", ["eyes", "gaze", "device"])
def test_native_failed_start_releases_created_resources(native_backend, failure):
    backend, library, _gaze, _eyes = native_backend
    failures = {
        "eyes": ["tobii_eye_position_normalized_subscribe", "tobii_gaze_origin_subscribe"],
        "gaze": ["tobii_gaze_point_subscribe"],
        "device": ["tobii_device_create"],
    }
    library.errors.update(dict.fromkeys(failures[failure], 7))

    with pytest.raises(engine.TobiiStreamEngineError):
        backend.start()

    assert "pump" not in library.calls
    assert library.calls[-1] == "tobii_api_destroy"
    assert not backend._api
    assert not backend._device
    if failure != "device":
        assert library.calls[-2] == "tobii_device_destroy"
    if failure == "eyes":
        assert "tobii_gaze_point_subscribe" not in library.calls


def test_native_stop_keeps_resources_while_callback_thread_is_still_running(native_backend):
    backend, library, _gaze, _eyes = native_backend
    backend.start()

    class StuckThread:
        def join(self, timeout):
            assert timeout == 1.5

        def is_alive(self):
            return True

    backend._thread = StuckThread()
    calls = list(library.calls)
    backend.stop()

    assert backend._stop_event.is_set()
    assert backend._api.value == 10
    assert backend._device.value == 20
    assert library.calls == calls
