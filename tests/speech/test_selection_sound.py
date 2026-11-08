from __future__ import annotations

import logging
import math
import struct
import wave

import pytest
from PySide6.QtCore import QObject, QUrl

from pogled_assist.speech import selection_sound
from pogled_assist.speech.selection_sound import SELECTION_SOUND_FILE, SelectionSound

# Bound at import, before the autouse fixture silences the Windows player.
from pogled_assist.speech.selection_sound import _create_windows_effect as create_real_effect


class RecordingEffect:
    def __init__(self, *, fail_play=False):
        self.volumes = []
        self.plays = 0
        self.fail_play = fail_play

    def setVolume(self, volume):
        self.volumes.append(volume)

    def play(self):
        if self.fail_play:
            raise RuntimeError("audio device lost")
        self.plays += 1


def _sound(effect=None, *, fail_load=False):
    created = []

    def create(parent):
        created.append(parent)
        if fail_load:
            raise RuntimeError("no audio")
        return effect

    return SelectionSound(create_effect=create), created


@pytest.mark.parametrize(("level", "volume"), [("quiet", 0.35), ("medium", 0.6), ("loud", 1.0)])
def test_each_level_plays_one_tick_at_its_volume(qapp, level, volume):
    effect = RecordingEffect()
    sound, _created = _sound(effect)
    sound.play(level)
    assert effect.plays == 1
    assert effect.volumes == [volume]


@pytest.mark.parametrize("level", ["off", "", "Tih"])
def test_off_and_unknown_levels_stay_silent(qapp, level):
    effect = RecordingEffect()
    sound, _created = _sound(effect)
    sound.play(level)
    assert effect.plays == 0


def test_tick_loads_once_before_the_first_selection(qtbot):
    effect = RecordingEffect()
    sound, created = _sound(effect)
    assert created == []
    qtbot.waitUntil(lambda: created == [sound])
    sound.play("quiet")
    sound.play("quiet")
    assert created == [sound]
    assert effect.plays == 2


def test_failed_load_is_logged_once_and_selections_continue(qapp, caplog):
    sound, created = _sound(fail_load=True)
    with caplog.at_level(logging.ERROR, logger=selection_sound.__name__):
        for _ in range(3):
            sound.play("quiet")
    assert len(created) == 1
    assert [record.message for record in caplog.records] == ["Selection sound could not be loaded."]


def test_failed_playback_is_logged_once_and_not_retried(qapp, caplog):
    effect = RecordingEffect(fail_play=True)
    sound, created = _sound(effect)
    with caplog.at_level(logging.ERROR, logger=selection_sound.__name__):
        for _ in range(3):
            sound.play("loud")
    assert effect.volumes == [1.0]
    assert len(created) == 1
    assert [record.message for record in caplog.records] == ["Selection sound playback failed."]


def test_without_windows_the_tick_is_silent(qtbot, monkeypatch):
    monkeypatch.setattr(selection_sound.sys, "platform", "linux")
    monkeypatch.setattr(
        selection_sound,
        "_create_windows_effect",
        lambda _parent: pytest.fail("No player outside Windows"),
    )
    sound = SelectionSound()
    qtbot.wait(1)
    sound.play("loud")


def test_windows_player_uses_the_bundled_tick(qapp):
    parent = QObject()
    effect = create_real_effect(parent)
    assert effect.parent() is parent
    assert effect.source() == QUrl.fromLocalFile(str(SELECTION_SOUND_FILE))


def test_windows_player_loads_the_bundled_tick(qtbot):
    from PySide6.QtMultimedia import QMediaDevices, QSoundEffect

    if QMediaDevices.defaultAudioOutput().isNull():
        pytest.skip("Native selection sound loading needs an available audio output")
    parent = QObject()
    effect = create_real_effect(parent)
    qtbot.waitUntil(lambda: effect.status() != QSoundEffect.Status.Loading)
    assert effect.status() == QSoundEffect.Status.Ready


def test_bundled_tick_is_short_mono_and_fades_out():
    with wave.open(str(SELECTION_SOUND_FILE), "rb") as audio:
        assert (audio.getnchannels(), audio.getsampwidth()) == (1, 2)
        rate = audio.getframerate()
        frames = audio.readframes(audio.getnframes())
    samples = struct.unpack(f"<{len(frames) // 2}h", frames)
    # A tick longer than 100 ms would blur into the next selection.
    assert len(samples) / rate <= 0.1
    peak_dbfs = 20 * math.log10(max(abs(sample) for sample in samples) / 32767)
    # Levels are gains on this peak; Glasan must not exceed the file's -3 dBFS.
    assert -3.5 <= peak_dbfs <= -2.5
    assert max(abs(sample) for sample in samples[-48:]) < 0.01 * 32767
