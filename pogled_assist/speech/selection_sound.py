"""Short confirmation sound for completed gaze selections."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, QUrl

logger = logging.getLogger(__name__)

SELECTION_SOUND_FILE = Path(__file__).resolve().parents[1] / "assets" / "selection_tick.wav"
SELECTION_SOUND_OFF = "off"
SELECTION_SOUND_QUIET = "quiet"
SELECTION_SOUND_LEVELS = (
    (SELECTION_SOUND_OFF, "Isključen"),
    (SELECTION_SOUND_QUIET, "Tih"),
    ("medium", "Srednji"),
    ("loud", "Glasan"),
)
# Linear gain on the -3 dBFS file: peaks of about -12, -7 and -3 dBFS.
SELECTION_SOUND_VOLUMES = {SELECTION_SOUND_QUIET: 0.35, "medium": 0.6, "loud": 1.0}


class SelectionSound(QObject):
    """Play one short sound per completed selection without blocking the Qt event loop.

    The sound mixes with speech and the emergency alarm. ``winsound`` plays one sound per
    process, so using it here would stop the looping alarm.
    """

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        create_effect: Callable[[QObject], Any] | None = None,
    ) -> None:
        super().__init__(parent)
        self._create_effect = create_effect or _create_windows_effect
        self._available = create_effect is not None or sys.platform == "win32"
        self._effect: Any = None
        # Load once the window is open, so the first selection does not wait for Qt Multimedia.
        QTimer.singleShot(0, self, self._load)

    def play(self, level: str) -> None:
        volume = SELECTION_SOUND_VOLUMES.get(level)
        if volume is None:
            return
        effect = self._load()
        if effect is None:
            return
        try:
            effect.setVolume(volume)
            effect.play()
        except Exception:
            self._disable("Selection sound playback failed.")

    def _load(self) -> Any:
        if self._effect is None and self._available:
            try:
                self._effect = self._create_effect(self)
            except Exception:
                self._disable("Selection sound could not be loaded.")
        return self._effect

    def _disable(self, message: str) -> None:
        logger.exception(message)
        # One report is enough; repeating it for every selection would flood the log.
        self._available = False
        self._effect = None


def _create_windows_effect(parent: QObject) -> Any:
    from PySide6.QtMultimedia import QSoundEffect

    effect = QSoundEffect(parent)

    def report_error() -> None:
        if effect.status() == QSoundEffect.Status.Error:
            logger.warning("Selection sound is unavailable; selections continue silently.")

    effect.statusChanged.connect(report_error)
    effect.setSource(QUrl.fromLocalFile(str(SELECTION_SOUND_FILE)))
    return effect
