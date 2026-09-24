from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)

ALARM_SOUND_FILE = Path(__file__).resolve().parents[1] / "assets" / "emergency_alarm.wav"
ALARM_UNAVAILABLE_MESSAGE = (
    "Zvučni alarm nije dostupan. Provjerite Windows zvuk i pokušajte ponovo."
)


class AlarmSound(QObject):
    """Play a repeating emergency alarm without holding up the Qt event loop."""

    failed = Signal(str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        play_alarm: Callable[[], None] | None = None,
        stop_alarm: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._play_alarm = play_alarm or _play_windows_alarm
        self._stop_alarm = stop_alarm or _stop_windows_alarm
        self._available = play_alarm is not None or sys.platform == "win32"
        self._lock = threading.Lock()
        self._is_playing = False
        self._last_error: str | None = None

    @property
    def is_playing(self) -> bool:
        with self._lock:
            return self._is_playing

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

        try:
            self._play_alarm()
        except Exception:
            logger.exception("Alarm sound playback failed.")
            with self._lock:
                self._last_error = ALARM_UNAVAILABLE_MESSAGE
            self.failed.emit(ALARM_UNAVAILABLE_MESSAGE)
            return False

        with self._lock:
            self._last_error = None
            self._is_playing = True
        logger.info("Alarm sound started.")
        return True

    def stop(self) -> None:
        with self._lock:
            was_playing = self._is_playing
            self._is_playing = False

        if not was_playing:
            return

        try:
            self._stop_alarm()
        except Exception:
            logger.exception("Alarm sound could not be stopped.")
        else:
            logger.info("Alarm sound stopped.")


def _play_windows_alarm() -> None:
    import winsound

    winsound.PlaySound(
        str(ALARM_SOUND_FILE),
        winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP,
    )


def _stop_windows_alarm() -> None:
    import winsound

    winsound.PlaySound(None, 0)
