from __future__ import annotations

import faulthandler
import io
import subprocess
import sys
import wave
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtWidgets import QApplication

from pogled_assist.speech import audio_playback
from pogled_assist.speech.audio_playback import AudioPlayback, PlaybackResult


@pytest.fixture
def player(qapp, monkeypatch):
    media_type = audio_playback.QMediaPlayer
    instances = []

    class Media(QObject):
        positionChanged = Signal(int)
        mediaStatusChanged = Signal(object)
        errorOccurred = Signal(object, str)
        EndOfMedia = media_type.EndOfMedia
        InvalidMedia = media_type.InvalidMedia
        FormatError = media_type.FormatError

        def __init__(self, parent):
            super().__init__(parent)
            self.stopped = False
            self.source = None
            instances.append(self)

        def setAudioOutput(self, output):
            self.output = output

        def setSourceDevice(self, source, *_args):
            self.source = source

        def play(self):
            pass

        def stop(self):
            self.stopped = True

    class Output(QObject):
        def device(self):
            return SimpleNamespace(isNull=lambda: False)

    monkeypatch.setattr(audio_playback, "QMediaPlayer", Media)
    monkeypatch.setattr(audio_playback, "QAudioOutput", Output)
    owner = QObject()
    playback = AudioPlayback(owner)
    yield playback, instances
    playback.stop()


def test_start_means_audio_position_advanced_not_player_construction(player):
    playback, instances = player
    result, starts = PlaybackResult(), []
    playback.started.connect(starts.append)
    playback.play(7, b"private audio", result)
    media = instances[0]
    assert bytes(media.source.data()) == b"private audio"
    assert starts == [] and not result.started
    media.positionChanged.emit(15)
    assert starts == [7] and result.started
    media.mediaStatusChanged.emit(media.EndOfMedia)
    assert result.done.is_set() and result.outcome == "finished"
    # Keep the source alive until deferred Qt destruction. Clearing it while
    # FFmpeg is reading a QBuffer can deadlock the Windows UI thread.
    assert media.stopped and media.source is not None


@pytest.mark.parametrize("started", [False, True])
def test_media_error_retains_whether_any_audio_was_played(player, started):
    playback, instances = player
    result = PlaybackResult()
    playback.play(1, b"audio", result)
    media = instances[0]
    if started:
        media.positionChanged.emit(20)
    media.errorOccurred.emit(1, "private diagnostic content")
    assert result.done.is_set() and result.outcome == "failed"
    assert result.started is started
    assert not result.invalid_audio
    assert media.stopped


def test_missing_output_is_not_treated_as_corrupt_media(player, monkeypatch):
    playback, _instances = player
    monkeypatch.setattr(
        audio_playback,
        "QAudioOutput",
        lambda _parent: SimpleNamespace(device=lambda: SimpleNamespace(isNull=lambda: True)),
    )
    result = PlaybackResult()
    playback.play(1, b"valid audio", result)
    assert result.done.is_set() and result.outcome == "failed"
    assert not result.started and not result.invalid_audio


@pytest.mark.parametrize("kind", ["status", "format"])
def test_decoder_rejection_is_distinct_from_output_failure(player, kind):
    playback, instances = player
    result = PlaybackResult()
    playback.play(1, b"unreadable audio", result)
    media = instances[0]
    if kind == "status":
        media.mediaStatusChanged.emit(media.InvalidMedia)
    else:
        media.errorOccurred.emit(media.FormatError, "private diagnostic content")
    assert result.done.is_set() and result.outcome == "failed"
    assert result.invalid_audio


def test_replacement_stops_old_device_before_creating_new_one_and_ignores_old_signals(player):
    playback, instances = player
    first, second = PlaybackResult(), PlaybackResult()
    playback.play(1, b"first", first)
    playback.play(2, b"second", second)
    assert first.done.is_set() and first.outcome == "stopped"
    assert instances[0].stopped
    instances[0].errorOccurred.emit(1, "late failure")
    instances[0].positionChanged.emit(50)
    assert not second.done.is_set() and not second.started
    playback.stop()
    assert second.done.is_set() and second.outcome == "stopped"


def test_stalled_decoder_fails_without_waiting_forever(player, monkeypatch):
    playback, instances = player
    result = PlaybackResult()
    playback.play(1, b"audio", result)
    instances[0].positionChanged.emit(15)
    stalled_at = playback._progress_at + 6
    monkeypatch.setattr(audio_playback, "time", SimpleNamespace(monotonic=lambda: stalled_at))
    playback._watch_progress()
    assert result.done.is_set() and result.outcome == "failed" and result.started
    assert not result.invalid_audio


def test_stop_settles_worker_before_native_cleanup_and_never_clears_source(player):
    playback, instances = player
    result = PlaybackResult()
    playback.play(1, b"audio", result)
    media = instances[0]
    source = media.source

    def stop():
        assert result.done.is_set() and result.outcome == "stopped"
        media.stopped = True

    def set_source(*_args):
        pytest.fail("Clearing an active QBuffer source can deadlock FFmpeg")

    media.stop = stop
    media.setSourceDevice = set_source
    playback.stop()
    assert media.stopped and media.source is source


def test_already_queued_old_media_signals_cannot_change_replacement(player, qtbot):
    playback, instances = player
    first, second = PlaybackResult(), PlaybackResult()
    playback.play(1, b"first", first)
    media = instances[0]
    for signal, slot in (
        (media.positionChanged, playback._position),
        (media.mediaStatusChanged, playback._status),
        (media.errorOccurred, playback._error),
    ):
        signal.disconnect(slot)
        signal.connect(slot, Qt.QueuedConnection)
    media.positionChanged.emit(50)
    media.mediaStatusChanged.emit(media.EndOfMedia)
    media.errorOccurred.emit(1, "late error")
    playback.play(2, b"second", second)
    qtbot.wait(10)
    assert not second.started and not second.done.is_set()


def test_native_buffer_replacement_and_completion_keep_qt_responsive():
    # Isolate the native decoder: a regression must fail within a bounded time
    # instead of hanging the whole test runner. No API, files or audible sound.
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import runpy, sys; runpy.run_path(sys.argv[1], run_name='__main__')",
            __file__,
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if completed.returncode == 77:
        pytest.skip("Native playback needs an available audio output")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "native playback completed" in completed.stdout


def _native_playback_probe():
    faulthandler.enable()
    faulthandler.dump_traceback_later(12, exit=True)
    app = QApplication([])
    if QMediaDevices.defaultAudioOutput().isNull():
        return 77
    stream = io.BytesIO()
    with wave.open(stream, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(44100)
        output.writeframes(bytes(44100 * 2))
    playback = AudioPlayback(app)
    results = [PlaybackResult() for _ in range(3)]

    def play(index):
        playback.play(index, stream.getvalue(), results[index])
        if playback._player is not None:
            playback._output.setMuted(True)

    def replace():
        play(1)
        assert results[0].done.is_set() and results[0].outcome == "stopped"
        QTimer.singleShot(150, stop)

    def stop():
        playback.stop()
        assert results[1].done.is_set() and results[1].outcome == "stopped"
        play(2)

    def finished():
        if results[2].done.is_set():
            assert results[2].started and results[2].outcome == "finished"
            app.quit()

    timer = QTimer(app)
    timer.timeout.connect(finished)
    timer.start(20)
    play(0)
    QTimer.singleShot(150, replace)
    app.exec()
    faulthandler.cancel_dump_traceback_later()
    print("native playback completed")
    return 0


if __name__ == "__main__":
    sys.exit(_native_playback_probe())
