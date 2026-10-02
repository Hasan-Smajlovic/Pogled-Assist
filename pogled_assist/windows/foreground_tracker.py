"""Remember external input targets without letting application controls replace them."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from PySide6.QtCore import QObject, QPoint, QTimer, Signal
from PySide6.QtGui import QCursor

from .windows_input import WindowsInputController

logger = logging.getLogger(__name__)


class ForegroundSurface(Protocol):
    def contains_global_point(self, point: QPoint) -> bool: ...

    def set_external_window(self, hwnd: int) -> None: ...

    def set_external_cursor(self, position: tuple[int, int]) -> None: ...


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
        self.cursor: tuple[int, int] | None = None
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
            self._update_cursor()
        except Exception:
            logger.exception("Foreground window tracking update failed.")
            self._timer.stop()
            self.status_changed.emit("Praćenje aktivnog prozora je zaustavljeno zbog greške.")

    def _update_cursor(self) -> None:
        if self._input is None or self._surface.contains_global_point(QCursor.pos()):
            return
        cursor = self._input.cursor_position()
        if cursor == self.cursor:
            return
        self.cursor = cursor
        self._surface.set_external_cursor(cursor)
