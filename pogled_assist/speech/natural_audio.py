"""Prepare the existing Prirodni voice completely before choosing to play it."""

from __future__ import annotations

import asyncio
import time
from threading import Event

import edge_tts

from .elevenlabs import MAX_AUDIO_BYTES
from .voice_state import NATURAL_PITCH, NATURAL_RATE, NATURAL_VOICE, VoiceError


def prepare_natural(text: str, cancel: Event, deadline: float) -> bytes:
    async def bounded() -> bytes:
        return await asyncio.wait_for(_collect_audio(text, cancel), max(0.001, deadline - time.monotonic()))

    return asyncio.run(bounded())


async def _collect_audio(text, cancel) -> bytes:
    audio = bytearray()
    stream = edge_tts.Communicate(text, voice=NATURAL_VOICE, rate=NATURAL_RATE, pitch=NATURAL_PITCH)
    async for chunk in stream.stream():
        if cancel.is_set():
            raise VoiceError("timeout")
        _append_audio(audio, chunk)
    if not audio:
        raise VoiceError("audio")
    return bytes(audio)



def _append_audio(audio, chunk):
    if chunk["type"] != "audio":
        return
    audio.extend(chunk["data"])
    if len(audio) > MAX_AUDIO_BYTES:
        raise VoiceError("audio")
