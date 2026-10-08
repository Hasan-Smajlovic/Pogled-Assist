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
