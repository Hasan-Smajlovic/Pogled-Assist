"""Tobii Stream Engine fallback for consumer Tobii trackers."""

from __future__ import annotations

import contextlib
import ctypes
import logging
import math
import os
import threading
import time
from pathlib import Path
from typing import Callable


logger = logging.getLogger(__name__)

TOBII_ERROR_NO_ERROR = 0
TOBII_VALIDITY_VALID = 1
CALLBACK_POLL_INTERVAL_SECONDS = 1 / 120

DLL_NAMES = (
    "tobii_stream_engine.dll",
    "StreamEngineClient.dll",
)

DLL_ENV = "TOBII_STREAM_ENGINE_DLL"
DEVICE_CREATE_ARG_ENV = "TOBII_STREAM_ENGINE_DEVICE_CREATE_ARGS"
FIELD_OF_USE_INTERACTIVE = 0

GazeCallback = Callable[[float, float, int], None]
EyeStatusCallback = Callable[[bool, bool, int], None]

_DLL_DIRECTORY_HANDLES: list[object] = []


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

    @property
    def label(self) -> str:
        return self._device_label

    @property
    def dll_path(self) -> str:
        return self._dll_path

    def start(self) -> None:
        try:
            self._lib, self._dll_path = _load_stream_engine_library()
            self._configure_signatures()
            self._log_version()
            self._create_api()
            self._device_url = self._find_device_url()
            self._create_device()
            self._device_label = self._read_device_label()
            self._subscribe()
            self._start_pump_thread()
            logger.info(
                "Tobii Stream Engine backend started with %s via %s.",
                self._device_label,
                self._dll_path,
            )
        except Exception:
            self._destroy_resources()
            raise

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            if self._thread.is_alive():
                logger.warning("Tobii Stream Engine pump thread did not stop cleanly.")
                return
            self._thread = None

        self._destroy_resources()
        logger.info("Tobii Stream Engine backend stopped.")

    def _destroy_resources(self) -> None:
        if self._lib is None:
            return

        if self._device:
            with contextlib.suppress(Exception):
                self._lib.tobii_eye_position_normalized_unsubscribe(self._device)

            with contextlib.suppress(Exception):
                self._lib.tobii_gaze_origin_unsubscribe(self._device)

            with contextlib.suppress(Exception):
                self._lib.tobii_gaze_point_unsubscribe(self._device)

            try:
                self._lib.tobii_device_destroy(self._device)
            except Exception:
                logger.exception("Tobii Stream Engine device destroy failed.")
            self._device = ctypes.c_void_p()

        if self._api:
            try:
                self._lib.tobii_api_destroy(self._api)
            except Exception:
                logger.exception("Tobii Stream Engine API destroy failed.")
            self._api = ctypes.c_void_p()

    def _configure_signatures(self) -> None:
        assert self._lib is not None

        self._lib.tobii_error_message.argtypes = [ctypes.c_uint32]
        self._lib.tobii_error_message.restype = ctypes.c_char_p

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

        # Stream Engine versions differ here. Some expose:
        #   tobii_device_create(api, url, device)
        # and consumer builds commonly expose:
        #   tobii_device_create(api, url, field_of_use, device)
        # Keep argtypes unset and choose call shapes in _create_device.
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
        status = self._lib.tobii_get_api_version(ctypes.byref(version))
        if status == TOBII_ERROR_NO_ERROR:
            logger.info(
                "Tobii Stream Engine API version: %s.%s.%s.%s",
                version.major,
                version.minor,
                version.revision,
                version.build,
            )
        else:
            logger.warning("Could not read Tobii Stream Engine API version: %s", self._error(status))

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
            raise TobiiStreamEngineError("No Stream Engine compatible Tobii device URLs were found.")

        return urls[0]

    def _create_device(self) -> None:
        assert self._lib is not None

        url = self._device_url.encode("utf-8")
        errors: list[str] = []

        for arg_count in _device_create_arg_counts():
            device = ctypes.c_void_p()
            logger.info("Trying tobii_device_create with %s arguments.", arg_count)
            if arg_count == "4":
                status = self._lib.tobii_device_create(
                    self._api,
                    ctypes.c_char_p(url),
                    ctypes.c_uint32(FIELD_OF_USE_INTERACTIVE),
                    ctypes.byref(device),
                )
            else:
                status = self._lib.tobii_device_create(
                    self._api,
                    ctypes.c_char_p(url),
                    ctypes.byref(device),
                )

            if status == TOBII_ERROR_NO_ERROR and device:
                self._device = device
                return

            errors.append(f"{arg_count} args: {self._error(status)}")
            logger.warning("tobii_device_create with %s arguments failed: %s", arg_count, self._error(status))

        raise TobiiStreamEngineError(f"tobii_device_create failed: {'; '.join(errors)}")

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
            if gaze_point.validity != TOBII_VALIDITY_VALID:
                return

            x = float(gaze_point.position_xy[0])
            y = float(gaze_point.position_xy[1])
            if not math.isfinite(x) or not math.isfinite(y):
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
            raise TobiiStreamEngineError(f"tobii_gaze_point_subscribe failed: {self._error(status)}")

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
            status = self._lib.tobii_device_process_callbacks(self._device)
            if status != TOBII_ERROR_NO_ERROR:
                logger.warning("Stream Engine callback processing failed: %s", self._error(status))
                time.sleep(0.25)
            else:
                time.sleep(CALLBACK_POLL_INTERVAL_SECONDS)

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


def _load_stream_engine_library() -> tuple[ctypes.CDLL, str]:
    errors: list[str] = []
    for candidate in _stream_engine_candidates():
        try:
            logger.info("Trying Tobii Stream Engine DLL: %s", candidate)
            return _load_candidate_dll(candidate), str(candidate)
        except OSError as exc:
            errors.append(f"{candidate}: {exc}")

    for dll_name in DLL_NAMES:
        try:
            logger.info("Trying Tobii Stream Engine DLL from loader path: %s", dll_name)
            return ctypes.CDLL(dll_name), dll_name
        except OSError as exc:
            errors.append(f"{dll_name}: {exc}")

    logger.warning("Tobii Stream Engine DLL load attempts failed: %s", errors)
    raise TobiiStreamEngineError(
        "tobii_stream_engine.dll could not be loaded by this Python process. "
        "If the log includes WinError 193, the installed Tobii DLL is 32-bit and "
        "the x86 bridge runtime is required. Rerun setup_windows.ps1."
    )


def _stream_engine_candidates() -> list[Path]:
    candidates: list[Path] = []

    configured = os.environ.get(DLL_ENV, "").strip()
    if configured:
        configured_path = Path(configured)
        if configured_path.is_dir():
            candidates.extend(configured_path / dll_name for dll_name in DLL_NAMES)
        else:
            candidates.append(configured_path)

    app_root = Path(__file__).resolve().parents[1]
    search_roots = [
        app_root,
        app_root / "tools",
        app_root / "tools" / "tobii",
        app_root / "tools" / "tobii-stream-engine",
    ]

    for env_name in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData", "ProgramData"):
        value = os.environ.get(env_name, "").strip()
        if value:
            search_roots.append(Path(value) / "Tobii")

    for root in search_roots:
        if not root.exists():
            continue

        for dll_name in DLL_NAMES:
            direct = root / dll_name
            if direct.exists():
                candidates.append(direct)

        if root.name.lower() == "tobii" or root.name.lower().startswith("tobii"):
            for dll_name in DLL_NAMES:
                try:
                    candidates.extend(root.rglob(dll_name))
                except OSError:
                    logger.exception("Could not scan Tobii DLL folder: %s", root)

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).lower()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)

    return unique


def _device_create_arg_counts() -> list[str]:
    configured = os.environ.get(DEVICE_CREATE_ARG_ENV, "").strip()
    if configured in ("3", "4"):
        return [configured]

    return ["4", "3"]


def _load_candidate_dll(candidate: Path) -> ctypes.CDLL:
    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is not None and candidate.parent.exists():
        _DLL_DIRECTORY_HANDLES.append(add_dll_directory(str(candidate.parent)))

    return ctypes.CDLL(str(candidate))


def _decode_char_array(value: ctypes.Array) -> str:
    return bytes(value).split(b"\0", 1)[0].decode("utf-8", errors="replace").strip()
