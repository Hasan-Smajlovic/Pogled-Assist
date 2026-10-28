"""Own blocking tracker operations for one connection, away from Qt delivery."""

from __future__ import annotations

import logging
import queue
import threading
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .tobii_stream_engine import TobiiStreamEngineError
from .tobii_stream_engine_bridge_backend import TobiiStreamEngineBridgeError

logger = logging.getLogger(__name__)


@dataclass
class GazeConnection:
    name: str
    backend: Any = None
    tracker: Any = None
    research: Any = None
    callback: Callable | None = None
    label: str = ""
    metadata: dict = field(default_factory=dict)
    admitted: threading.Event = field(default_factory=threading.Event)

    def close(self) -> bool:
        self.admitted.clear()
        if self.backend is not None:
            return self.backend.stop() is not False
        if self.tracker is not None:
            self.tracker.unsubscribe_from(self.research.EYETRACKER_GAZE_DATA, self.callback)
        return True


class GazeConnectionSession:
    def __init__(
        self,
        *,
        callbacks: tuple[Callable, ...] = (),
        backend_types: tuple[Callable, ...] = (),
        choose_tracker: Callable | None = None,
        tracker_label: Callable | None = None,
        connection: GazeConnection | None = None,
        generation: int = 0,
    ) -> None:
        self.events: queue.SimpleQueue = queue.SimpleQueue()
        self.done = threading.Event()
        self.cancelled = threading.Event()
        self.connection = connection
        self._generation = generation
        self._pending_backend = None
        self._uses_bridge = connection is not None and connection.name == "stream-engine-x86-bridge"
        self._callbacks = callbacks
        self._backend_types = backend_types
        self._choose_tracker = choose_tracker
        self._tracker_label = tracker_label
        self._thread = threading.Thread(target=self._run, name="TobiiConnection", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def cancel(self) -> None:
        self.cancelled.set()
        request_stop = getattr(self._pending_backend, "request_stop", None)
        if request_stop is not None:
            request_stop()

    def wait_for_bridge_shutdown(self) -> bool:
        """Drain a child process after the application event loop has ended."""
        if self._uses_bridge:
            self._thread.join(timeout=8.0)
        return not self._uses_bridge or not self._thread.is_alive()

    def _run(self) -> None:
        cleanup_only = self.connection is not None
        try:
            if not cleanup_only:
                self.connection = self._connect()
            if self.connection is not None and not cleanup_only and not self.cancelled.is_set():
                self.events.put(("connected", self.connection))
                self.cancelled.wait()
        except Exception:
            logger.exception("Tobii connection attempt failed.")
        finally:
            if self.connection is not None:
                self._close(self.connection)
            self.done.set()

    def _guard(self, callback: Callable, connection: GazeConnection) -> Callable:
        admitted, cancelled = connection.admitted, self.cancelled
        # The session owns callbacks. Backend/ctypes cycles must not retain Qt
        # owners after the session has finished on the UI thread.
        callback_ref = weakref.ref(callback)

        def deliver(*args):
            if admitted.is_set() and not cancelled.is_set():
                callback = callback_ref()
                if callback is not None:
                    callback(*args)

        return deliver

    def _connect(self) -> GazeConnection | None:
        connection = self._research()
        if connection is not None or self.cancelled.is_set():
            return connection
        for name, backend_type in zip(
            ("stream-engine", "stream-engine-x86-bridge"), self._backend_types, strict=True
        ):
            if self.cancelled.is_set():
                break
            if name == "stream-engine-x86-bridge":
                self._uses_bridge = True
                self.events.put(("message", "Pokušavam Tobii x86 most za 32-bitni Core Software."))
            connection = GazeConnection(name)
            gaze, eyes, position, invalid, _research = self._callbacks
            try:
                connection.backend = backend_type(
                    self._guard(gaze, connection), self._guard(eyes, connection)
                )
                self._pending_backend = connection.backend
                connection.backend.connection_generation = self._generation
                if self.cancelled.is_set():
                    self._close(connection)
                    return None
                connection.backend.eye_position_callback = self._guard(position, connection)
                connection.backend.gaze_invalid_callback = self._guard(invalid, connection)
                connection.backend.start()
                connection.label = connection.backend.label
                connection.metadata = getattr(connection.backend, "diagnostic_metadata", {})
                return connection
            except Exception as error:
                logger.exception("Tobii %s startup failed.", name)
                if name == "stream-engine":
                    message = (
                        "Stream Engine nije dostupan. Pokušavam drugi način."
                        if isinstance(error, TobiiStreamEngineError)
                        else "Stream Engine nije uspio. Pokušavam drugi način."
                    )
                else:
                    message = (
                        "Tobii x86 most nije dostupan."
                        if isinstance(error, TobiiStreamEngineBridgeError)
                        else "Tobii x86 most nije uspio."
                    )
                self.events.put(("message", message))
                self._close(connection)
        return None

    def _research(self) -> GazeConnection | None:
        connection = GazeConnection("tobii-research")
        failure_message = "Nedostaje tobii-research. Pokušavam Stream Engine."
        try:
            import tobii_research as tr

            failure_message = "Pretraga Tobii uređaja putem Pro SDK-a nije uspjela."
            trackers = tr.find_all_eyetrackers()
            if self.cancelled.is_set():
                return None
            if not trackers:
                self.events.put(
                    (
                        "message",
                        "Tobii uređaj nije pronađen putem Pro SDK-a. Pokušavam Stream Engine.",
                    )
                )
                return None
            failure_message = "Povezivanje s Tobii uređajem nije uspjelo."
            connection.research = tr
            connection.tracker = self._choose_tracker(trackers)
            connection.callback = self._guard(self._callbacks[4], connection)
            connection.tracker.subscribe_to(
                tr.EYETRACKER_GAZE_DATA, connection.callback, as_dictionary=True
            )
            connection.label = self._tracker_label(connection.tracker)
            connection.metadata = {
                "sdk_version": getattr(tr, "__version__", "unknown"),
                "model": getattr(connection.tracker, "model", "unknown"),
                "firmware_version": getattr(connection.tracker, "firmware_version", "unknown"),
                "eye_validity_source": "pro_sdk_gaze_point_validity",
            }
            return connection
        except Exception:
            logger.exception("Tobii Pro SDK discovery or subscription failed.")
            self.events.put(("message", failure_message))
            self._close(connection)
            return None

    @staticmethod
    def _close(connection: GazeConnection) -> None:
        while True:
            try:
                if connection.close():
                    return
            except Exception:
                logger.exception("Tobii cleanup failed; retaining connection ownership.")
            # An unresponsive native pump still owns its subscription. The session
            # remains busy until cleanup succeeds, including across stop/start.
            threading.Event().wait(0.1)
