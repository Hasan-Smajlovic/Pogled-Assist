"""Prepare the existing Prirodni voice completely before choosing to play it."""

from __future__ import annotations

import asyncio
import time
from threading import Event

import edge_tts

from .elevenlabs import MAX_AUDIO_BYTES
from .voice_state import VoiceError


def prepare_natural(text: str, cancel: Event, deadline: float) -> bytes:
    async def collect() -> bytes:
        audio = bytearray()
        stream = edge_tts.Communicate(
            text, voice="bs-BA-GoranNeural", rate="-10%", pitch="-2Hz"
        )
        async for chunk in stream.stream():
            if cancel.is_set():
                raise VoiceError("timeout")
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
                if len(audio) > MAX_AUDIO_BYTES:
                    raise VoiceError("audio")
        if not audio:
            raise VoiceError("audio")
        return bytes(audio)

    async def bounded() -> bytes:
        return await asyncio.wait_for(collect(), max(0.001, deadline - time.monotonic()))

    return asyncio.run(bounded())
