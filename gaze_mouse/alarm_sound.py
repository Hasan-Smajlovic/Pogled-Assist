from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)

ALARM_FREQUENCY_HZ = 740
ALARM_TONE_DURATION_MS = 500
ALARM_REPEAT_INTERVAL_MS = 1300
ALARM_UNAVAILABLE_MESSAGE = (
    "Zvučni alarm nije dostupan. Provjerite Windows zvuk i pokušajte ponovo."
)


class AlarmSound(QObject):
    """Repeat the blocking Windows beep without holding up the Qt event loop."""

    failed = Signal(str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        beep: Callable[[int, int], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._beep = beep or _windows_beep
        self._available = beep is not None or sys.platform == "win32"
        self._lock = threading.Lock()
        self._stop_event: threading.Event | None = None
        self._thread: threading.Thread | None = None
        self._last_error: str | None = None

    @property
    def is_playing(self) -> bool:
        with self._lock:
            thread = self._thread
            stop_event = self._stop_event
        return bool(thread and thread.is_alive() and stop_event and not stop_event.is_set())

    @property
    def last_error(self) -> str | None:
        with self._lock:
            return self._last_error

    def start(self) -> bool:
        self.stop()
        if not self._available:
            with self._lock:
                self._last_error = ALARM_UNAVAILABLE_MESSAGE
            logger.error("Alarm sound is unavailable on this platform.")
            return False

        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._play_loop,
            args=(stop_event,),
            name="tobii-alarm-sound",
            daemon=True,
        )
        with self._lock:
            self._last_error = None
            self._stop_event = stop_event
            self._thread = thread
        thread.start()
        logger.info("Alarm sound started.")
        return True

    def stop(self) -> None:
        with self._lock:
            stop_event = self._stop_event
            thread = self._thread
            self._stop_event = None
            self._thread = None

        if stop_event is not None:
            stop_event.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=ALARM_TONE_DURATION_MS / 1000 + 0.5)
            if thread.is_alive():
                logger.warning("Alarm sound thread did not stop before the timeout.")
            else:
                logger.info("Alarm sound stopped.")

    def _play_loop(self, stop_event: threading.Event) -> None:
        pause_seconds = max(0, ALARM_REPEAT_INTERVAL_MS - ALARM_TONE_DURATION_MS) / 1000
        while not stop_event.is_set():
            try:
                self._beep(ALARM_FREQUENCY_HZ, ALARM_TONE_DURATION_MS)
            except Exception:
                logger.exception("Alarm sound playback failed.")
                with self._lock:
                    self._last_error = ALARM_UNAVAILABLE_MESSAGE
                stop_event.set()
                self.failed.emit(ALARM_UNAVAILABLE_MESSAGE)
                return

            if stop_event.wait(pause_seconds):
                return


def _windows_beep(frequency_hz: int, duration_ms: int) -> None:
    import winsound

    winsound.Beep(frequency_hz, duration_ms)
