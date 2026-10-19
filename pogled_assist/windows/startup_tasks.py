"""Serialize Windows startup work across Settings window lifetimes."""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass

from .windows_startup import StartupTaskResult

logger = logging.getLogger(__name__)
_task_lock = threading.Lock()
_order = threading.Condition()
_turns: deque[object] = deque()


@dataclass(frozen=True)
class StartupRequest:
    revision: int
    enabled: bool | None
    show_launcher: bool
    status: str | None
    update_launcher: bool = False

    @property
    def read_only(self) -> bool:
        return self.enabled is None and not self.update_launcher


class StartupTasks:
    """Own pending writes independently of the Settings widget's lifetime."""

    def __init__(
        self,
        completed: Callable[[int, object, str | None], None],
        *,
        query: Callable[[], bool],
        update: Callable[..., StartupTaskResult],
    ) -> None:
        self._completed = completed
        self._query = query
        self._update = update
        self._lock = threading.Lock()
        self._pending: StartupRequest | None = None
        self._running = False
        self._closed = False

    def submit(self, request: StartupRequest) -> None:
        with self._lock:
            self._pending = request
            if self._running:
                return
            self._running = True
        turn = object()
        with _order:
            _turns.append(turn)
        try:
            threading.Thread(
                target=self._run, args=(turn,), name="pogled-startup-task", daemon=True
            ).start()
        except RuntimeError:
            logger.exception("Could not start Windows startup worker.")
            with self._lock:
                self._running = False
                self._pending = None
            self._release_turn(turn)
            self._finish(request, None)

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def _take(self) -> StartupRequest | None:
        with self._lock:
            request, self._pending = self._pending, None
            if request is None:
                self._running = False
            return request

    def _cancelled(self, request: StartupRequest) -> bool:
        with self._lock:
            return self._closed and request.read_only

    def _run(self, turn: object) -> None:
        acquired = False
        try:
            while (request := self._take()) is not None:
                result = None
                try:
                    if not acquired:
                        acquired = self._wait_for_turn(turn, request)
                    if acquired and not self._cancelled(request):
                        result = self._apply(request)
                except Exception:
                    logger.exception("Could not read or update Windows startup state.")
                self._finish(request, result)
        finally:
            # Drain this window's latest write before a reopened window queries
            # the state. No Qt callback is needed to continue after deletion.
            if acquired:
                _task_lock.release()
            self._release_turn(turn)

    def _wait_for_turn(self, turn: object, request: StartupRequest) -> bool:
        while not self._cancelled(request):
            with _order:
                if _turns[0] is not turn:
                    _order.wait(timeout=0.1)
                    continue
            if _task_lock.acquire(timeout=0.1):
                return True
        return False

    def _apply(self, request: StartupRequest) -> object:
        enabled = self._query() if request.enabled is None else request.enabled
        update = request.enabled is not None or (request.update_launcher and enabled)
        if update:
            return self._update(enabled, show_launcher_window=request.show_launcher)
        return enabled

    @staticmethod
    def _release_turn(turn: object) -> None:
        with _order:
            _turns.remove(turn)
            _order.notify_all()

    def _finish(self, request: StartupRequest, result: object) -> None:
        with suppress(RuntimeError):
            self._completed(request.revision, result, request.status)
