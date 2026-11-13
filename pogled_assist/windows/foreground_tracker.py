"""Remember the external input window without letting application windows replace it."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from PySide6.QtCore import QObject, QTimer, Signal

from .windows_input import WindowsInputController

logger = logging.getLogger(__name__)


class ForegroundSurface(Protocol):
    def set_external_window(self, hwnd: int) -> None: ...


class ForegroundTracker(QObject):
    status_changed = Signal(str)

    def __init__(
        self,
        parent: QObject,
        surface: ForegroundSurface,
        input_factory: Callable[[], WindowsInputController],
    ) -> None:
        super().__init__(parent)
        self._surface = surface
        self._input_factory = input_factory
        self._input: WindowsInputController | None = None
        self.window: int | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.update)

    @property
    def ready(self) -> bool:
        return self._input is not None

    def prime(self) -> None:
        try:
            self._input = self._input_factory()
            self.update()
            logger.info("Foreground window tracking primed.")
        except Exception:
            logger.exception("Foreground window tracking could not be primed.")

    def start(self) -> None:
        if self._input is None:
            try:
                self._input = self._input_factory()
            except Exception:
                logger.exception("Foreground window tracking failed to start.")
                self.status_changed.emit("Praćenje aktivnog prozora nije dostupno.")
                return
        self.update()
        if not self._timer.isActive():
            self._timer.start()
        logger.info("Foreground window tracking started.")

    def stop(self) -> None:
        self._timer.stop()

    def update(self) -> None:
        if self._input is None:
            return
        try:
            hwnd = self._input.foreground_window()
            if hwnd is not None and not self._input.belongs_to_current_process(hwnd):
                if hwnd != self.window:
                    logger.info("Last external foreground window updated: hwnd=%s.", hwnd)
                self.window = hwnd
                self._surface.set_external_window(hwnd)
        except Exception:
            logger.exception("Foreground window tracking update failed.")
            self._timer.stop()
            self.status_changed.emit("Praćenje aktivnog prozora je zaustavljeno zbog greške.")
