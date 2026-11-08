from __future__ import annotations

import ctypes

import pytest
from _clock import freeze_monotonic

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
    def __init__(self, *, create_args=4, field_of_use=1, version=(4, 25, 0, 3), missing=()):
        self.calls = []
        self.errors = {}
        self.functions = {}
        self.callbacks = {}
        self.create_args = create_args
        self.field_of_use = field_of_use
        self.version = version
        self.missing = set(missing)
        self.effects = {
            "tobii_get_api_version": self.get_version,
            "tobii_api_create": self.create_api,
            "tobii_enumerate_local_device_urls": self.enumerate_urls,
            "tobii_device_create": self.create_device,
            "tobii_eye_position_normalized_subscribe": self.subscribe_eyes,
            "tobii_gaze_origin_subscribe": self.subscribe_origin,
            "tobii_gaze_point_subscribe": self.subscribe_gaze,
            "tobii_error_message": lambda _status: b"synthetic failure",
        }

    def __getattr__(self, name):
        if not name.startswith("tobii_") or name in self.missing:
            raise AttributeError(name)
        if name not in self.functions:
            self.functions[name] = FakeFunction(self, name)
        return self.functions[name]

    def create_api(self, output, _allocator, _log):
        ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p)).contents.value = 10
        return 0

    def get_version(self, output):
        version = ctypes.cast(output, ctypes.POINTER(engine.TobiiVersion)).contents
        version.major, version.minor, version.revision, version.build = self.version
        return 0

    def enumerate_urls(self, _api, receiver, _user_data):
        receiver(b"tobii://synthetic-device", None)
        return 0

    def create_device(self, *arguments):
        assert len(arguments) == self.create_args, "The native ABI must be chosen before calling"
        if self.create_args == 4:
            assert arguments[2].value == self.field_of_use
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
    monkeypatch.delenv(engine.DEVICE_CREATE_ARG_ENV, raising=False)
    monkeypatch.setattr(engine, "_stream_engine_libraries", lambda: iter([(library, "fake.dll")]))
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

    now = freeze_monotonic(monkeypatch, 10.0)
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


def test_native_stop_keeps_resources_while_callback_thread_is_still_running(native_backend, caplog):
    backend, library, _gaze, _eyes = native_backend
    backend.start()

    class StuckThread:
        alive = True

        def join(self, timeout):
            assert timeout == 1.5

        def is_alive(self):
            return self.alive

    stuck = StuckThread()
    backend._thread = stuck
    calls = list(library.calls)
    # Connection cleanup retries stop() until the native call returns.
    for _retry in range(3):
        assert backend.stop() is False

    assert backend._stop_event.is_set()
    assert backend._api.value == 10
    assert backend._device.value == 20
    assert library.calls == calls
    assert caplog.text.count("pump thread did not stop cleanly") == 1

    stuck.alive = False
    assert backend.stop() is True
    backend._thread = StuckThread()
    assert backend.stop() is False
    assert caplog.text.count("pump thread did not stop cleanly") == 2


@pytest.mark.parametrize(
    "version,arity",
    [((1, 1, 1, 1741), 3), ((2, 2, 2, 3002), 3), ((3, 0, 4, 6031), 3), ((4, 0, 0, 16), 4)],
)
def test_sdk_major_selects_one_exact_legacy_or_modern_abi(native_backend, version, arity):
    backend, library, _gaze, _eyes = native_backend
    library.version = version
    library.create_args = arity
    backend.start()
    assert library.calls.count("tobii_device_create") == 1
    assert len(library.tobii_device_create.argtypes) == arity
    assert library.tobii_device_create.argtypes[-1] == ctypes.POINTER(ctypes.c_void_p)


@pytest.mark.parametrize("version", [(0, 0, 0, 0), (5, 0, 0, 0), (4, -1, 0, 0)])
def test_unknown_or_malformed_sdk_never_calls_device_create(native_backend, version):
    backend, library, _gaze, _eyes = native_backend
    library.version = version
    with pytest.raises(engine.TobiiStreamEngineError, match="Unknown Stream Engine"):
        backend.start()
    assert "tobii_device_create" not in library.calls


@pytest.mark.parametrize("arity", [3, 4])
def test_explicit_abi_override_is_authoritative(native_backend, monkeypatch, arity):
    backend, library, _gaze, _eyes = native_backend
    library.version = (99, 0, 0, 0)
    library.create_args = arity
    monkeypatch.setenv(engine.DEVICE_CREATE_ARG_ENV, str(arity))
    backend.start()
    assert len(library.tobii_device_create.argtypes) == arity


@pytest.mark.parametrize("version,override", [((4, 25, 0, 3), "3"), ((3, 0, 4, 6031), "4")])
def test_abi_override_cannot_contradict_a_known_sdk_major(
    native_backend, monkeypatch, version, override
):
    # One override applies to every runtime candidate. A preserved legacy DLL
    # override must not reach an installed modern DLL with the wrong arity.
    backend, library, _gaze, _eyes = native_backend
    library.version = version
    monkeypatch.setenv(engine.DEVICE_CREATE_ARG_ENV, override)
    with pytest.raises(engine.TobiiStreamEngineError, match="conflicts"):
        backend.start()
    assert "tobii_device_create" not in library.calls


@pytest.mark.parametrize("version,arity", [((4, 25, 0, 3), 4), ((2, 2, 2, 3002), 3)])
def test_matching_abi_override_accepts_a_known_sdk_major(
    native_backend, monkeypatch, version, arity
):
    backend, library, _gaze, _eyes = native_backend
    library.version = version
    library.create_args = arity
    monkeypatch.setenv(engine.DEVICE_CREATE_ARG_ENV, str(arity))
    backend.start()
    assert library.calls.count("tobii_device_create") == 1


@pytest.mark.parametrize("version", [(4, 25, 0, 3), None])
def test_invalid_abi_override_is_ignored(native_backend, monkeypatch, caplog, version):
    backend, library, _gaze, _eyes = native_backend
    monkeypatch.setattr(engine, "_IGNORED_DEVICE_CREATE_ARGS", set())
    monkeypatch.setenv(engine.DEVICE_CREATE_ARG_ENV, "auto")
    if version is None:
        library.missing.add("tobii_get_api_version")
        with pytest.raises(engine.TobiiStreamEngineError, match="Unknown Stream Engine"):
            backend.start()
        assert "tobii_device_create" not in library.calls
    else:
        library.version = version
        backend.start()
        assert len(library.tobii_device_create.argtypes) == 4
    # Retries read the override for every candidate; the warning appears once.
    assert engine._configured_device_create_arg_count() is None
    assert caplog.text.count("Ignoring TOBII_STREAM_ENGINE_DEVICE_CREATE_ARGS='auto'") == 1


@pytest.mark.parametrize("override", [None, "3"])
def test_missing_sdk_version_requires_an_explicit_abi(native_backend, monkeypatch, override):
    backend, library, _gaze, _eyes = native_backend
    library.missing.add("tobii_get_api_version")
    if override:
        library.create_args = 3
        monkeypatch.setenv(engine.DEVICE_CREATE_ARG_ENV, override)
        backend.start()
    else:
        with pytest.raises(engine.TobiiStreamEngineError, match="Unknown Stream Engine"):
            backend.start()
        assert "tobii_device_create" not in library.calls


def test_failed_version_read_and_device_error_do_not_probe_another_abi(native_backend):
    backend, library, _gaze, _eyes = native_backend
    library.errors["tobii_get_api_version"] = 1
    with pytest.raises(engine.TobiiStreamEngineError, match="Unknown Stream Engine"):
        backend.start()
    assert "tobii_device_create" not in library.calls
    library.errors.clear()
    library.errors["tobii_device_create"] = 5
    with pytest.raises(engine.TobiiStreamEngineError):
        backend.start()
    assert library.calls.count("tobii_device_create") == 1


@pytest.mark.parametrize("resource", ["device", "api"])
def test_failed_native_destroy_retains_ownership_until_success(native_backend, resource):
    backend, library, _gaze, _eyes = native_backend
    backend.start()
    library.errors[f"tobii_{resource}_destroy"] = 1
    assert backend.stop() is False
    assert backend._api
    if resource == "device":
        assert backend._device
        assert "tobii_api_destroy" not in library.calls
    library.errors.clear()
    assert backend.stop() is True
    assert not backend._device and not backend._api


def test_pending_cleanup_reports_only_changed_sdk_failures(native_backend, caplog):
    backend, library, _gaze, _eyes = native_backend
    backend.start()
    caplog.clear()
    library.errors["tobii_device_destroy"] = 1
    assert backend.stop() is False
    assert backend.stop() is False
    warnings = [record for record in caplog.records if "cleanup pending" in record.message]
    assert len(warnings) == 1
    library.errors.clear()


@pytest.mark.parametrize("raises", [False, True])
def test_native_pump_reports_terminal_failure_and_invalidates_eyes(native_backend, raises):
    backend, library, _gaze, eyes = native_backend
    backend.start()

    def fail(_device):
        if raises:
            raise OSError("synthetic native failure")
        return 5

    library.effects["tobii_device_process_callbacks"] = fail
    backend._pump_loop()
    assert backend.connection_error
    assert eyes == [(False, False, 0)]
    assert library.calls.count("tobii_device_process_callbacks") == 1


def test_native_pump_timeout_is_not_a_terminal_connection_failure(native_backend):
    backend, library, _gaze, eyes = native_backend
    backend.start()
    statuses = iter([6, 0])

    def process(_device):
        status = next(statuses)
        if status == 0:
            backend.request_stop()
        return status

    library.effects["tobii_device_process_callbacks"] = process
    backend._pump_loop()
    assert backend.connection_error is None
    assert eyes == []
    assert library.calls.count("tobii_device_process_callbacks") == 2


@pytest.mark.parametrize("failure", ["device", "eyes", "exports"])
def test_unusable_preserved_runtime_is_cleaned_before_installed_candidate(
    native_backend, monkeypatch, failure
):
    backend, old, _gaze, _eyes = native_backend
    new = FakeLibrary()
    if failure == "device":
        old.errors["tobii_device_create"] = 5
    elif failure == "eyes":
        old.errors.update(tobii_eye_position_normalized_subscribe=3, tobii_gaze_origin_subscribe=3)
    else:
        old.missing.add("tobii_gaze_point_subscribe")
    started = []

    def candidates():
        yield old, "preserved.dll"
        assert not backend._device and not backend._api
        started.append(True)
        yield new, "installed.dll"

    monkeypatch.setattr(engine, "_stream_engine_libraries", candidates)
    backend.start()
    assert started == [True]
    assert backend.dll_path == "installed.dll"
    assert new.calls.count("tobii_device_create") == 1


def test_candidate_cleanup_failure_blocks_every_later_runtime(native_backend, monkeypatch):
    backend, old, _gaze, _eyes = native_backend
    old.errors.update(tobii_gaze_point_subscribe=3, tobii_device_destroy=1)
    new = FakeLibrary()
    monkeypatch.setattr(
        engine, "_stream_engine_libraries", lambda: iter([(old, "old.dll"), (new, "new.dll")])
    )
    with pytest.raises(engine.TobiiStreamEngineError, match="cleanup is still pending"):
        backend.start()
    assert new.calls == []
    old.errors.clear()


def test_pump_start_failure_releases_partial_device(native_backend, monkeypatch):
    backend, _library, _gaze, _eyes = native_backend

    def fail():
        raise RuntimeError("synthetic thread start failed")

    monkeypatch.setattr(backend, "_start_pump_thread", fail)
    with pytest.raises(engine.TobiiStreamEngineError):
        backend.start()
    assert not backend._device and not backend._api


def test_loader_skips_wrong_bitness_before_yielding_a_usable_dll(monkeypatch, tmp_path):
    old, current = tmp_path / "x86.dll", tmp_path / "x64.dll"
    library = FakeLibrary()
    monkeypatch.setattr(engine, "_stream_engine_candidates", lambda: [old, current])

    def load(path):
        if path == old:
            raise OSError("WinError 193: wrong bitness")
        return library

    monkeypatch.setattr(engine, "_load_candidate_dll", load)
    candidates = engine._stream_engine_libraries()
    assert next(candidates) == (library, str(current))
    candidates.close()


def test_each_dll_folder_joins_the_search_path_once(monkeypatch, tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    added = []
    monkeypatch.setattr(engine, "_DLL_DIRECTORY_HANDLES", {})
    monkeypatch.setattr(engine.os, "add_dll_directory", added.append, raising=False)
    monkeypatch.setattr(engine.ctypes, "CDLL", lambda path: path)
    # Retries while no tracker is attached load the same candidates again.
    for _retry in range(3):
        for candidate in (first / engine.DLL_NAMES[0], second / engine.DLL_NAMES[0]):
            assert engine._load_candidate_dll(candidate) == str(candidate)
    assert added == [str(first), str(second)]
