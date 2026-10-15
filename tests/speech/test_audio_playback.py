from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal

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
    assert media.stopped and media.source is None


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
    assert media.stopped


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
    monkeypatch.setattr(audio_playback.time, "monotonic", lambda: playback._progress_at + 6)
    playback._watch_progress()
    assert result.done.is_set() and result.outcome == "failed" and result.started
