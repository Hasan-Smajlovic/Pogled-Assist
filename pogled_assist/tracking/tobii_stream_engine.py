"""Tobii Stream Engine fallback for consumer Tobii trackers."""

from __future__ import annotations

import contextlib
import ctypes
import logging
import math
import os
import sys
import threading
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

TOBII_ERROR_NO_ERROR = 0
TOBII_ERROR_TIMED_OUT = 6
TOBII_VALIDITY_VALID = 1
CALLBACK_POLL_INTERVAL_SECONDS = 1 / 120

DLL_NAMES = (
    "tobii_stream_engine.dll",
    "StreamEngineClient.dll",
)

DLL_ENV = "TOBII_STREAM_ENGINE_DLL"
APP_ROOT_ENV = "POGLED_ASSIST_APP_ROOT"
DEVICE_CREATE_ARG_ENV = "TOBII_STREAM_ENGINE_DEVICE_CREATE_ARGS"
FIELD_OF_USE_INTERACTIVE = 1

GazeCallback = Callable[[float, float, int], None]
EyeStatusCallback = Callable[[bool, bool, int], None]
EyePosition = tuple[float, float, float]
EyePositionCallback = Callable[[EyePosition | None, EyePosition | None, int], None]
GazeInvalidCallback = Callable[[int], None]

# One handle per folder: retries while no tracker is attached must not grow the search path.
_DLL_DIRECTORY_HANDLES: dict[str, object] = {}
_IGNORED_DEVICE_CREATE_ARGS: set[str] = set()


class TobiiStreamEngineError(RuntimeError):
    """Raised when the Tobii Stream Engine backend cannot be started."""


class TobiiVersion(ctypes.Structure):
    _fields_ = [
        ("major", ctypes.c_int),
        ("minor", ctypes.c_int),
        ("revision", ctypes.c_int),
        ("build", ctypes.c_int),
    ]


class TobiiDeviceInfo(ctypes.Structure):
    _fields_ = [
        ("serial_number", ctypes.c_char * 256),
        ("model", ctypes.c_char * 256),
        ("generation", ctypes.c_char * 256),
        ("firmware_version", ctypes.c_char * 256),
        ("integration_id", ctypes.c_char * 128),
        ("hw_calibration_version", ctypes.c_char * 128),
        ("hw_calibration_date", ctypes.c_char * 128),
        ("lot_id", ctypes.c_char * 128),
        ("integration_type", ctypes.c_char * 256),
        ("runtime_build_version", ctypes.c_char * 256),
    ]


class TobiiGazePoint(ctypes.Structure):
    _fields_ = [
        ("timestamp_us", ctypes.c_int64),
        ("validity", ctypes.c_uint32),
        ("position_xy", ctypes.c_float * 2),
    ]


class TobiiEyePositionNormalized(ctypes.Structure):
    _fields_ = [
        ("timestamp_us", ctypes.c_int64),
        ("left_validity", ctypes.c_uint32),
        ("left_xyz", ctypes.c_float * 3),
        ("right_validity", ctypes.c_uint32),
        ("right_xyz", ctypes.c_float * 3),
    ]


class TobiiGazeOrigin(ctypes.Structure):
    _fields_ = [
        ("timestamp_us", ctypes.c_int64),
        ("left_validity", ctypes.c_uint32),
        ("left_xyz", ctypes.c_float * 3),
        ("right_validity", ctypes.c_uint32),
        ("right_xyz", ctypes.c_float * 3),
    ]


DeviceUrlReceiver = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_void_p)
GazePointReceiver = ctypes.CFUNCTYPE(None, ctypes.POINTER(TobiiGazePoint), ctypes.c_void_p)
EyePositionReceiver = ctypes.CFUNCTYPE(
    None,
    ctypes.POINTER(TobiiEyePositionNormalized),
    ctypes.c_void_p,
)
GazeOriginReceiver = ctypes.CFUNCTYPE(None, ctypes.POINTER(TobiiGazeOrigin), ctypes.c_void_p)


class TobiiStreamEngineBackend:
    """Small ctypes wrapper around tobii_stream_engine.dll gaze point streaming."""

    def __init__(
        self,
        gaze_callback: GazeCallback,
        eye_status_callback: EyeStatusCallback,
    ) -> None:
        self._gaze_callback = gaze_callback
        self._eye_status_callback = eye_status_callback
        # Optional diagnostic observer; never participates in the input gate.
        self.eye_position_callback: EyePositionCallback | None = None
        self.gaze_invalid_callback: GazeInvalidCallback | None = None
        self.diagnostic_metadata: dict = {"eye_validity_source": "unknown"}
        self._lib: ctypes.CDLL | None = None
        self._dll_path = ""
        self._api = ctypes.c_void_p()
        self._device = ctypes.c_void_p()
        self._device_url = ""
        self._device_label = "Tobii Stream Engine tracker"
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._url_receiver: DeviceUrlReceiver | None = None
        self._gaze_receiver: GazePointReceiver | None = None
        self._eye_position_receiver: EyePositionReceiver | None = None
        self._gaze_origin_receiver: GazeOriginReceiver | None = None
        self._sample_count = 0
        self._eye_sample_count = 0
        self._eye_position_api_available = False
        self._gaze_origin_api_available = False
        self._api_version: tuple[int, int, int, int] | None = None
        self._connection_error: str | None = None
        self._last_cleanup_failure: tuple[str, int] | None = None
        self._pump_stuck_logged = False

    @property
    def connection_error(self) -> str | None:
        return self._connection_error

    def request_stop(self) -> None:
        self._stop_event.set()

    @property
    def eye_position_supported(self) -> bool:
        return bool(self._device) and self._eye_position_receiver is not None

    @property
    def label(self) -> str:
        return self._device_label

    @property
    def dll_path(self) -> str:
        return self._dll_path

    def start(self) -> None:
        errors = []
        for self._lib, self._dll_path in _stream_engine_libraries():
            if self._stop_event.is_set():
                raise TobiiStreamEngineError("Stream Engine startup cancelled.")
            self._api_version = None
            self._eye_position_api_available = False
            self._gaze_origin_api_available = False
            self.diagnostic_metadata = {"eye_validity_source": "unknown"}
            try:
                self._configure_signatures()
                self._log_version()
                self._create_api()
                self._device_url = self._find_device_url()
                self._create_device()
                self._device_label = self._read_device_label()
                self._subscribe()
                self._start_pump_thread()
            except Exception as exc:
                errors.append(f"{self._dll_path}: {exc}")
                cleaned = self.stop() if self._thread is not None else self._destroy_resources()
                if not cleaned:
                    raise TobiiStreamEngineError(
                        "Stream Engine startup failed and cleanup is still pending."
                    ) from exc
                logger.warning("Tobii runtime candidate failed: %s", errors[-1])
                continue
            logger.info(
                "Tobii Stream Engine backend started with %s via %s.",
                self._device_label,
                self._dll_path,
            )
            return
        raise TobiiStreamEngineError("No usable Stream Engine runtime: " + "; ".join(errors))

    def stop(self) -> bool:
        self._stop_event.set()
        if self._thread is not None:
            if self._thread.is_alive():
                self._thread.join(timeout=1.5)
            if self._thread.is_alive():
                # Cleanup retries every few seconds while a native call is stuck.
                if not self._pump_stuck_logged:
                    logger.warning("Tobii Stream Engine pump thread did not stop cleanly.")
                    self._pump_stuck_logged = True
                return False
            self._thread = None
            self._pump_stuck_logged = False

        if not self._destroy_resources():
            return False
        logger.info("Tobii Stream Engine backend stopped.")
        return True

    def _destroy_resources(self) -> bool:
        if self._lib is None:
            return True
        if self._device and not self._destroy_device():
            return False
        return not self._api or self._destroy_api()

    def _destroy_device(self) -> bool:
        assert self._lib is not None
        with contextlib.suppress(Exception):
            self._lib.tobii_eye_position_normalized_unsubscribe(self._device)

        with contextlib.suppress(Exception):
            self._lib.tobii_gaze_origin_unsubscribe(self._device)

        with contextlib.suppress(Exception):
            self._lib.tobii_gaze_point_unsubscribe(self._device)

        try:
            status = self._lib.tobii_device_destroy(self._device)
            if not self._cleanup_succeeded("device", status):
                return False
        except Exception:
            logger.exception("Tobii Stream Engine device destroy failed.")
            return False
        self._device = ctypes.c_void_p()
        self._eye_position_receiver = None
        self._gaze_origin_receiver = None
        self._gaze_receiver = None
        return True

    def _destroy_api(self) -> bool:
        assert self._lib is not None
        try:
            status = self._lib.tobii_api_destroy(self._api)
            if not self._cleanup_succeeded("API", status):
                return False
        except Exception:
            logger.exception("Tobii Stream Engine API destroy failed.")
            return False
        self._api = ctypes.c_void_p()
        return True

    def _cleanup_succeeded(self, resource: str, status: int) -> bool:
        if status == TOBII_ERROR_NO_ERROR:
            self._last_cleanup_failure = None
            return True
        failure = (resource, status)
        if failure != self._last_cleanup_failure:
            logger.warning("Stream Engine %s cleanup pending: %s", resource, self._error(status))
            self._last_cleanup_failure = failure
        return False

    def _configure_signatures(self) -> None:
        assert self._lib is not None

        self._lib.tobii_error_message.argtypes = [ctypes.c_uint32]
        self._lib.tobii_error_message.restype = ctypes.c_char_p

        with contextlib.suppress(AttributeError):
            self._lib.tobii_get_api_version.argtypes = [ctypes.POINTER(TobiiVersion)]
            self._lib.tobii_get_api_version.restype = ctypes.c_uint32

        self._lib.tobii_api_create.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self._lib.tobii_api_create.restype = ctypes.c_uint32

        self._lib.tobii_api_destroy.argtypes = [ctypes.c_void_p]
        self._lib.tobii_api_destroy.restype = ctypes.c_uint32

        self._lib.tobii_enumerate_local_device_urls.argtypes = [
            ctypes.c_void_p,
            DeviceUrlReceiver,
            ctypes.c_void_p,
        ]
        self._lib.tobii_enumerate_local_device_urls.restype = ctypes.c_uint32

        # The exact device-create signature is selected after reading the API
        # version. A wrong-arity native call can corrupt memory before returning.
        self._lib.tobii_device_create.restype = ctypes.c_uint32

        self._lib.tobii_device_destroy.argtypes = [ctypes.c_void_p]
        self._lib.tobii_device_destroy.restype = ctypes.c_uint32

        self._lib.tobii_get_device_info.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(TobiiDeviceInfo),
        ]
        self._lib.tobii_get_device_info.restype = ctypes.c_uint32

        self._lib.tobii_gaze_point_subscribe.argtypes = [
            ctypes.c_void_p,
            GazePointReceiver,
            ctypes.c_void_p,
        ]
        self._lib.tobii_gaze_point_subscribe.restype = ctypes.c_uint32

        self._lib.tobii_gaze_point_unsubscribe.argtypes = [ctypes.c_void_p]
        self._lib.tobii_gaze_point_unsubscribe.restype = ctypes.c_uint32

        try:
            self._lib.tobii_eye_position_normalized_subscribe.argtypes = [
                ctypes.c_void_p,
                EyePositionReceiver,
                ctypes.c_void_p,
            ]
            self._lib.tobii_eye_position_normalized_subscribe.restype = ctypes.c_uint32
            self._lib.tobii_eye_position_normalized_unsubscribe.argtypes = [ctypes.c_void_p]
            self._lib.tobii_eye_position_normalized_unsubscribe.restype = ctypes.c_uint32
            self._eye_position_api_available = True
        except AttributeError:
            logger.warning("Stream Engine eye-position API is not available in this DLL.")

        try:
            self._lib.tobii_gaze_origin_subscribe.argtypes = [
                ctypes.c_void_p,
                GazeOriginReceiver,
                ctypes.c_void_p,
            ]
            self._lib.tobii_gaze_origin_subscribe.restype = ctypes.c_uint32
            self._lib.tobii_gaze_origin_unsubscribe.argtypes = [ctypes.c_void_p]
            self._lib.tobii_gaze_origin_unsubscribe.restype = ctypes.c_uint32
            self._gaze_origin_api_available = True
        except AttributeError:
            logger.warning("Stream Engine gaze-origin API is not available in this DLL.")

        if not (self._eye_position_api_available or self._gaze_origin_api_available):
            raise TobiiStreamEngineError(
                "Tobii Stream Engine does not expose eye-position or gaze-origin validity; "
                "two-eye safety gating cannot be enabled."
            )

        self._lib.tobii_device_process_callbacks.argtypes = [ctypes.c_void_p]
        self._lib.tobii_device_process_callbacks.restype = ctypes.c_uint32

    def _log_version(self) -> None:
        assert self._lib is not None

        version = TobiiVersion()
        try:
            status = self._lib.tobii_get_api_version(ctypes.byref(version))
        except AttributeError:
            logger.warning("Stream Engine API version is unavailable.")
            return
        if status == TOBII_ERROR_NO_ERROR:
            self._api_version = (version.major, version.minor, version.revision, version.build)
            self.diagnostic_metadata["sdk_version"] = (
                f"{version.major}.{version.minor}.{version.revision}.{version.build}"
            )
            logger.info(
                "Tobii Stream Engine API version: %s.%s.%s.%s",
                version.major,
                version.minor,
                version.revision,
                version.build,
            )
        else:
            logger.warning(
                "Could not read Tobii Stream Engine API version: %s", self._error(status)
            )

    def _create_api(self) -> None:
        assert self._lib is not None

        status = self._lib.tobii_api_create(ctypes.byref(self._api), None, None)
        if status != TOBII_ERROR_NO_ERROR or not self._api:
            raise TobiiStreamEngineError(f"tobii_api_create failed: {self._error(status)}")

    def _find_device_url(self) -> str:
        assert self._lib is not None

        urls: list[str] = []

        def receive_url(url: bytes | None, _user_data: ctypes.c_void_p) -> None:
            if url:
                urls.append(url.decode("utf-8", errors="replace"))

        self._url_receiver = DeviceUrlReceiver(receive_url)
        status = self._lib.tobii_enumerate_local_device_urls(self._api, self._url_receiver, None)
        if status != TOBII_ERROR_NO_ERROR:
            raise TobiiStreamEngineError(
                f"tobii_enumerate_local_device_urls failed: {self._error(status)}"
            )

        logger.info("Tobii Stream Engine device URLs found: %s", urls)
        if not urls:
            raise TobiiStreamEngineError(
                "No Stream Engine compatible Tobii device URLs were found."
            )

        return urls[0]

    def _create_device(self) -> None:
        assert self._lib is not None

        url = self._device_url.encode("utf-8")
        arg_count = _device_create_arg_count(self._api_version)
        arguments = [self._api, ctypes.c_char_p(url)]
        signature = [ctypes.c_void_p, ctypes.c_char_p]
        if arg_count == 4:
            arguments.append(ctypes.c_uint32(FIELD_OF_USE_INTERACTIVE))
            signature.append(ctypes.c_uint32)
        signature.append(ctypes.POINTER(ctypes.c_void_p))
        self._lib.tobii_device_create.argtypes = signature
        status = self._lib.tobii_device_create(*arguments, ctypes.byref(self._device))
        if status != TOBII_ERROR_NO_ERROR or not self._device:
            raise TobiiStreamEngineError(f"tobii_device_create failed: {self._error(status)}")

    def _read_device_label(self) -> str:
        assert self._lib is not None

        info = TobiiDeviceInfo()
        status = self._lib.tobii_get_device_info(self._device, ctypes.byref(info))
        if status != TOBII_ERROR_NO_ERROR:
            logger.warning("Could not read Stream Engine device info: %s", self._error(status))
            return f"Tobii Stream Engine tracker ({self._device_url})"

        parts = [
            _decode_char_array(info.model),
            _decode_char_array(info.generation),
            _decode_char_array(info.serial_number),
        ]
        self.diagnostic_metadata["model"] = _decode_char_array(info.model)
        self.diagnostic_metadata["firmware_version"] = _decode_char_array(info.firmware_version)
        return " ".join(part for part in parts if part) or "Tobii Stream Engine tracker"

    def _subscribe(self) -> None:
        self._subscribe_eye_status()
        self._subscribe_gaze_point()

    def _subscribe_eye_status(self) -> None:
        errors: list[str] = []
        if self._subscribe_eye_position(errors):
            return

        if self._subscribe_gaze_origin(errors):
            return

        detail = "; ".join(errors) or "no eye-validity stream was available"
        raise TobiiStreamEngineError(f"Could not subscribe to an eye-validity stream: {detail}")

    def _subscribe_eye_position(self, errors: list[str]) -> bool:
        assert self._lib is not None
        if not self._eye_position_api_available:
            errors.append("eye-position API missing")
            return False

        def receive_eye_position(eye_position_ptr, _user_data: ctypes.c_void_p) -> None:
            if not eye_position_ptr:
                return

            eye_position = eye_position_ptr.contents
            self._handle_eye_validity_sample(
                "eye-position",
                int(eye_position.left_validity),
                int(eye_position.right_validity),
                int(eye_position.timestamp_us),
            )
            if self.eye_position_callback is not None:
                self.eye_position_callback(
                    finite_eye_position(eye_position.left_xyz, eye_position.left_validity),
                    finite_eye_position(eye_position.right_xyz, eye_position.right_validity),
                    int(eye_position.timestamp_us),
                )

        self._eye_position_receiver = EyePositionReceiver(receive_eye_position)
        status = self._lib.tobii_eye_position_normalized_subscribe(
            self._device,
            self._eye_position_receiver,
            None,
        )
        if status != TOBII_ERROR_NO_ERROR:
            error = f"tobii_eye_position_normalized_subscribe failed: {self._error(status)}"
            logger.warning(error)
            errors.append(error)
            self._eye_position_receiver = None
            return False

        logger.info("Subscribed to Stream Engine normalized eye-position stream.")
        self.diagnostic_metadata["eye_validity_source"] = "eye-position"
        return True

    def _subscribe_gaze_origin(self, errors: list[str]) -> bool:
        assert self._lib is not None
        if not self._gaze_origin_api_available:
            errors.append("gaze-origin API missing")
            return False

        def receive_gaze_origin(gaze_origin_ptr, _user_data: ctypes.c_void_p) -> None:
            if not gaze_origin_ptr:
                return

            gaze_origin = gaze_origin_ptr.contents
            self._handle_eye_validity_sample(
                "gaze-origin",
                int(gaze_origin.left_validity),
                int(gaze_origin.right_validity),
                int(gaze_origin.timestamp_us),
            )

        self._gaze_origin_receiver = GazeOriginReceiver(receive_gaze_origin)
        status = self._lib.tobii_gaze_origin_subscribe(
            self._device,
            self._gaze_origin_receiver,
            None,
        )
        if status != TOBII_ERROR_NO_ERROR:
            error = f"tobii_gaze_origin_subscribe failed: {self._error(status)}"
            logger.warning(error)
            errors.append(error)
            self._gaze_origin_receiver = None
            return False

        logger.info("Subscribed to Stream Engine gaze-origin stream for eye validity.")
        self.diagnostic_metadata["eye_validity_source"] = "gaze-origin"
        return True

    def _handle_eye_validity_sample(
        self,
        source: str,
        left_validity: int,
        right_validity: int,
        timestamp_us: int,
    ) -> None:
        left_open = left_validity == TOBII_VALIDITY_VALID
        right_open = right_validity == TOBII_VALIDITY_VALID

        self._eye_sample_count += 1
        if self._eye_sample_count == 1 or self._eye_sample_count % 300 == 0:
            logger.info(
                "Stream Engine %s eye sample #%s: left_open=%s right_open=%s timestamp_us=%s",
                source,
                self._eye_sample_count,
                left_open,
                right_open,
                timestamp_us,
            )

        self._eye_status_callback(left_open, right_open, timestamp_us)

    def _subscribe_gaze_point(self) -> None:
        assert self._lib is not None

        def receive_gaze(gaze_point_ptr, _user_data: ctypes.c_void_p) -> None:
            if not gaze_point_ptr:
                return

            gaze_point = gaze_point_ptr.contents
            x = float(gaze_point.position_xy[0])
            y = float(gaze_point.position_xy[1])
            if (
                gaze_point.validity != TOBII_VALIDITY_VALID
                or not math.isfinite(x)
                or not math.isfinite(y)
            ):
                if self.gaze_invalid_callback is not None:
                    self.gaze_invalid_callback(int(gaze_point.timestamp_us))
                return

            self._sample_count += 1
            if self._sample_count == 1 or self._sample_count % 300 == 0:
                logger.info(
                    "Stream Engine gaze sample #%s: x=%.4f y=%.4f timestamp_us=%s",
                    self._sample_count,
                    x,
                    y,
                    gaze_point.timestamp_us,
                )

            self._gaze_callback(x, y, int(gaze_point.timestamp_us))

        self._gaze_receiver = GazePointReceiver(receive_gaze)
        status = self._lib.tobii_gaze_point_subscribe(self._device, self._gaze_receiver, None)
        if status != TOBII_ERROR_NO_ERROR:
            raise TobiiStreamEngineError(
                f"tobii_gaze_point_subscribe failed: {self._error(status)}"
            )

    def _start_pump_thread(self) -> None:
        self._thread = threading.Thread(
            target=self._pump_loop,
            name="TobiiStreamEnginePump",
            daemon=True,
        )
        self._thread.start()

    def _pump_loop(self) -> None:
        assert self._lib is not None

        logger.info("Tobii Stream Engine callback pump started.")
        while not self._stop_event.is_set():
            try:
                status = self._lib.tobii_device_process_callbacks(self._device)
            except Exception:
                logger.exception("Stream Engine callback processing raised an exception.")
                self._connection_error = "Stream Engine callback processing failed."
                break
            if status not in (TOBII_ERROR_NO_ERROR, TOBII_ERROR_TIMED_OUT):
                self._connection_error = (
                    f"Stream Engine callback processing failed: {self._error(status)}"
                )
                logger.warning("%s", self._connection_error)
                break
            self._stop_event.wait(CALLBACK_POLL_INTERVAL_SECONDS)

        if self._connection_error is not None and not self._stop_event.is_set():
            self._eye_status_callback(False, False, 0)

        logger.info("Tobii Stream Engine callback pump stopped.")

    def _error(self, status: int) -> str:
        if status == TOBII_ERROR_NO_ERROR:
            return "ok"

        if self._lib is None:
            return f"status {status}"

        try:
            message = self._lib.tobii_error_message(status)
            if message:
                return f"{status}: {message.decode('utf-8', errors='replace')}"
        except Exception:
            logger.exception("Could not get Tobii Stream Engine error message.")

        return f"status {status}"


def finite_eye_position(value: object, validity: object = 1) -> EyePosition | None:
    """Copy a finite XYZ sample, preserving out-of-box values and its units."""
    if validity not in (1, True):
        return None
    if not isinstance(value, (tuple, list, ctypes.Array)):
        return None
    try:
        if len(value) != 3:
            return None
        if any(
            isinstance(component, bool) or not isinstance(component, (int, float))
            for component in value
        ):
            return None
        xyz = tuple(float(component) for component in value)
    except (TypeError, ValueError, OverflowError):
        return None
    return xyz if all(math.isfinite(component) for component in xyz) else None


def _stream_engine_libraries():
    errors: list[str] = []
    for candidate in _stream_engine_candidates():
        try:
            logger.info("Trying Tobii Stream Engine DLL: %s", candidate)
            yield _load_candidate_dll(candidate), str(candidate)
        except OSError as exc:
            errors.append(f"{candidate}: {exc}")

    for dll_name in DLL_NAMES:
        try:
            logger.info("Trying Tobii Stream Engine DLL from loader path: %s", dll_name)
            yield ctypes.CDLL(dll_name), dll_name
        except OSError as exc:
            errors.append(f"{dll_name}: {exc}")

    logger.warning("Tobii Stream Engine DLL load attempts failed: %s", errors)


def app_root() -> Path:
    configured = os.environ.get(APP_ROOT_ENV, "").strip()
    if configured:
        return Path(configured)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _stream_engine_candidates() -> list[Path]:
    candidates = _configured_dll_candidates()
    for root in _dll_search_roots():
        if root.exists():
            candidates.extend(_dlls_in(root))
    return _unique_paths(candidates)


def _configured_dll_candidates() -> list[Path]:
    configured = os.environ.get(DLL_ENV, "").strip()
    if not configured:
        return []
    path = Path(configured)
    if path.is_dir():
        return [path / dll_name for dll_name in DLL_NAMES]
    return [path]


def _dll_search_roots() -> list[Path]:
    root = app_root()
    roots = [root, root / "tools", root / "tools" / "tobii", root / "tools" / "tobii-stream-engine"]
    for env_name in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData", "ProgramData"):
        value = os.environ.get(env_name, "").strip()
        if value:
            roots.append(Path(value) / "Tobii")
    return roots


def _dlls_in(root: Path) -> list[Path]:
    found = [root / dll_name for dll_name in DLL_NAMES if (root / dll_name).exists()]
    if not root.name.lower().startswith("tobii"):
        return found
    for dll_name in DLL_NAMES:
        try:
            found.extend(root.rglob(dll_name))
        except OSError:
            logger.exception("Could not scan Tobii DLL folder: %s", root)
    return found


def _unique_paths(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _device_create_arg_count(version: tuple[int, int, int, int] | None = None) -> int:
    configured = _configured_device_create_arg_count()
    known = _reported_device_create_arg_count(version)
    if known is None:
        if configured is None:
            raise TobiiStreamEngineError(
                "Unknown Stream Engine device-create ABI. Configure "
                f"{DEVICE_CREATE_ARG_ENV}=3 or 4 only from the matching SDK documentation."
            )
        return configured
    # The override applies to every runtime candidate, so it may only fill in
    # an unknown ABI, never contradict the version this DLL reports.
    if configured not in (None, known):
        raise TobiiStreamEngineError(
            f"{DEVICE_CREATE_ARG_ENV}={configured} conflicts with Stream Engine "
            f"API major {version[0]}, which takes {known} device-create arguments."
        )
    return known


def _configured_device_create_arg_count() -> int | None:
    configured = os.environ.get(DEVICE_CREATE_ARG_ENV, "").strip()
    if configured in ("3", "4"):
        return int(configured)
    if configured and configured not in _IGNORED_DEVICE_CREATE_ARGS:
        # A typo must not disable candidates whose version already names the ABI.
        _IGNORED_DEVICE_CREATE_ARGS.add(configured)
        logger.warning("Ignoring %s=%r; only 3 or 4 is valid.", DEVICE_CREATE_ARG_ENV, configured)
    return None


def _reported_device_create_arg_count(version: tuple[int, int, int, int] | None) -> int | None:
    if version is None or any(value < 0 for value in version):
        return None
    # API majors 1-3 create a device with three arguments; API 4 adds a fourth.
    return {1: 3, 2: 3, 3: 3, 4: 4}.get(version[0])


def _load_candidate_dll(candidate: Path) -> ctypes.CDLL:
    add_dll_directory = getattr(os, "add_dll_directory", None)
    folder = candidate.parent
    key = os.path.normcase(str(folder))
    if add_dll_directory is not None and key not in _DLL_DIRECTORY_HANDLES and folder.exists():
        _DLL_DIRECTORY_HANDLES[key] = add_dll_directory(str(folder))

    return ctypes.CDLL(str(candidate))


def _decode_char_array(value: ctypes.Array) -> str:
    return bytes(value).split(b"\0", 1)[0].decode("utf-8", errors="replace").strip()
