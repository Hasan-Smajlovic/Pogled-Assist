"""Qt owns audio devices and memory buffers; workers only wait on a result."""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass, field
from threading import Event

from PySide6.QtCore import QBuffer, QIODevice, QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer


@dataclass
class PlaybackResult:
    done: Event = field(default_factory=Event)
    started: bool = False
    outcome: str = "failed"


class AudioPlayback(QObject):
    started = Signal(int)

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self._player: QMediaPlayer | None = None
        self._result: PlaybackResult | None = None
        self._request = 0
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._watch_progress)
        self._progress_at = 0.0

    def play(self, request: int, data: bytes, result: PlaybackResult) -> None:
        self.stop()
        self._result, self._request = result, request
        try:
            player = self._player = QMediaPlayer(self)
            output = QAudioOutput(player)
            if output.device().isNull():
                self._finish("failed")
                return
            player.setAudioOutput(output)
            buffer = QBuffer(player)
            buffer.setData(data)
            buffer.open(QIODevice.ReadOnly)
            # Keep Python wrappers alive as long as Qt reads the source device.
            self._output, self._buffer = output, buffer
            player.positionChanged.connect(self._position)
            player.mediaStatusChanged.connect(self._status)
            player.errorOccurred.connect(self._error)
            player.setSourceDevice(buffer, QUrl("memory.mp3"))
            if self._result is not result:
                return
            self._progress_at = time.monotonic()
            self._timer.start()
            player.play()
        except Exception:
            self._finish("failed")

    def stop(self) -> None:
        self._finish("stopped")

    def _position(self, position: int) -> None:
        if self.sender() is not self._player:
            return
        result = self._result
        if position > 0:
            self._progress_at = time.monotonic()
        if result is None or position <= 0:
            return
        if not result.started:
            result.started = True
            self.started.emit(self._request)

    def _watch_progress(self) -> None:
        if time.monotonic() - self._progress_at >= 5:
            self._finish("failed")

    def _status(self, status: QMediaPlayer.MediaStatus) -> None:
        if self.sender() is not self._player:
            return
        if status == QMediaPlayer.EndOfMedia:
            self._finish("finished" if self._result and self._result.started else "failed")
        elif status == QMediaPlayer.InvalidMedia:
            self._finish("failed")

    def _error(self, _error, _message: str) -> None:
        if self.sender() is self._player:
            self._finish("failed")

    def _finish(self, outcome: str) -> None:
        result, player = self._result, self._player
        self._result = self._player = None
        self._timer.stop()
        if result is not None:
            result.outcome = outcome
            result.done.set()
        if player is not None:
            for signal, slot in (
                (player.positionChanged, self._position),
                (player.mediaStatusChanged, self._status),
                (player.errorOccurred, self._error),
            ):
                with contextlib.suppress(RuntimeError, TypeError):
                    signal.disconnect(slot)
            try:
                player.stop()
            finally:
                # FFmpeg can deadlock while synchronously clearing a QBuffer
                # source. Let Qt destroy the player and its source together
                # after the current media callback returns.
                player.deleteLater()
                self._output = self._buffer = None
