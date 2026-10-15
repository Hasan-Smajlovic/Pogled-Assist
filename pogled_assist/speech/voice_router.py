"""Efendija preparation, recovery and fallback without changing the selected voice."""

from __future__ import annotations

import time
from collections.abc import Callable
from threading import Event, Lock

from .audio_cache import AudioCache, saved_text
from .elevenlabs import BoundedCall, ElevenClient, ElevenConfig, Subscription
from .natural_audio import prepare_natural
from .voice_state import (
    ELEVEN_TIMEOUT,
    NATURAL,
    NATURAL_TIMEOUT,
    STANDARD,
    SpeechCancelled,
    VoiceError,
    VoiceState,
)


class RecoveryGate:
    def __init__(self) -> None:
        self._lock = Lock()
        self.fingerprint = ""
        self.reason = ""
        self.retry_at = 0.0
        self.balance: Subscription | None = None

    def configure(self, fingerprint: str) -> None:
        with self._lock:
            if fingerprint != self.fingerprint:
                self.fingerprint = fingerprint
                self.reason, self.retry_at, self.balance = "", 0.0, None

    def failure(self, config: ElevenConfig, reason: str, balance: Subscription | None) -> None:
        with self._lock:
            if config.fingerprint != self.fingerprint:
                return
            self.reason, self.balance = reason, balance
            delay = 60 if reason == "quota" else 30
            if reason in ("missing_key", "invalid_key", "configuration", "permission"):
                delay = 300
            self.retry_at = time.monotonic() + delay

    def success(self, config: ElevenConfig) -> bool:
        with self._lock:
            if config.fingerprint != self.fingerprint:
                return False
            recovered = bool(self.reason)
            self.reason, self.retry_at, self.balance = "", 0.0, None
            return recovered

    def snapshot(self) -> tuple[str, float, Subscription | None]:
        with self._lock:
            return self.reason, self.retry_at, self.balance

    def checked(self, config: ElevenConfig, balance: Subscription | None) -> None:
        with self._lock:
            if config.fingerprint != self.fingerprint:
                return
            if self.reason != "quota" or (
                balance is not None
                and (self.balance is None or balance.improved_from(self.balance))
            ):
                self.retry_at = 0.0


class VoiceRouter:
    def __init__(self, cache: AudioCache, client: ElevenClient | None = None) -> None:
        self.cache = cache
        self.client = client or ElevenClient()
        self.gate = RecoveryGate()
        self.network = BoundedCall()
        self.natural_network = BoundedCall()
        self.natural = prepare_natural

    def run(
        self, text: str, config: ElevenConfig, cancel: Event,
        play: Callable, publish: Callable, *, test: bool = False,
    ) -> str:
        if cancel.is_set():
            raise SpeechCancelled
        ticket = None if test else self.cache.ticket(text, config.audio_identity)
        cached = self.cache.read(ticket)
        if cached is not None:
            result = play(cached, VoiceState(cached=True))
            if cancel.is_set() or result.outcome == "stopped":
                raise SpeechCancelled
            if result.outcome == "finished":
                return "finished"
            self.cache.discard(ticket)
            if result.started:
                publish(VoiceState(cached=True, partial=True))
                return "failed"

        started_at = time.monotonic()
        reason = "offline"
        quota_balance = None
        try:
            config.validate()
            previous_reason, retry_at, balance = self.gate.snapshot()
            if not test and previous_reason:
                if time.monotonic() < retry_at:
                    raise VoiceError(previous_reason)
                if previous_reason == "quota":
                    try:
                        updated = self.network.run(
                            lambda stop, end: self.client.subscription(config.key, stop, end),
                            cancel, ELEVEN_TIMEOUT,
                        )
                    except VoiceError:
                        self.gate.failure(config, "quota", balance)
                        raise VoiceError("quota") from None
                    if updated.remaining == 0 or (
                        balance is not None and not updated.improved_from(balance)
                    ):
                        self.gate.failure(config, "quota", updated)
                        raise VoiceError("quota")
                    quota_balance = updated
            remaining = ELEVEN_TIMEOUT - (time.monotonic() - started_at)
            audio = self.network.run(
                lambda stop, end: self.client.synthesize(
                    config, saved_text(text) if ticket else text, stop, end
                ), cancel, remaining,
            )
            result = play(audio, VoiceState())
            if cancel.is_set() or result.outcome == "stopped":
                raise SpeechCancelled
            if result.outcome == "finished":
                self.cache.write(ticket, audio)
                recovered = self.gate.success(config)
                publish(VoiceState(recovered=recovered))
                return "finished"
            if result.started:
                publish(VoiceState(partial=True))
                return "failed"
            raise VoiceError("audio")
        except VoiceError as error:
            reason = error.reason
            if cancel.is_set():
                raise SpeechCancelled from None
            previous_reason, retry_at, balance = self.gate.snapshot()
            # Skipping a cooling-down provider must not postpone its next probe.
            if previous_reason != reason or time.monotonic() >= retry_at:
                self.gate.failure(config, reason, quota_balance or balance)
            if test:
                raise VoiceError(reason) from None

        try:
            audio = self.natural_network.run(
                lambda stop, end: self.natural(text, stop, end), cancel, NATURAL_TIMEOUT
            )
            result = play(audio, VoiceState(NATURAL, reason))
            if cancel.is_set() or result.outcome == "stopped":
                raise SpeechCancelled
            if result.outcome == "finished":
                return "finished"
            if result.started:
                publish(VoiceState(NATURAL, reason, partial=True))
                return "failed"
        except VoiceError:
            pass
        if cancel.is_set():
            raise SpeechCancelled
        publish(VoiceState(STANDARD, reason))
        return "standard"
