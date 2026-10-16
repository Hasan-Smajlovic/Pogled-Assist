"""Efendija preparation and fallback without changing the selected voice."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from threading import Event, Lock

from .audio_cache import AudioCache, saved_text
from .elevenlabs import BoundedCall, ElevenClient, ElevenConfig, Subscription
from .natural_audio import prepare_natural
from .voice_state import ELEVEN_TIMEOUT, NATURAL, NATURAL_TIMEOUT, STANDARD, SpeechCancelled, VoiceError, VoiceState


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
        if reason in ("busy", "too_long"):
            return
        with self._lock:
            if config.fingerprint != self.fingerprint:
                return
            self.reason, self.balance = reason, balance
            delay = {"quota": 60, "missing_key": 300, "invalid_key": 300, "configuration": 300, "permission": 300}.get(reason, 30)
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
            if config.fingerprint == self.fingerprint and self._balance_permits_retry(balance):
                self.retry_at = 0.0

    def _balance_permits_retry(self, balance) -> bool:
        if self.reason != "quota":
            return True
        if balance is None or balance.remaining <= 0:
            return False
        return self.balance is None or balance.improved_from(self.balance)


@dataclass(frozen=True)
class Playback:
    cancel: Event
    play: Callable
    publish: Callable

    def settle(self, result, state) -> str | None:
        if self.cancel.is_set() or result.outcome == "stopped":
            raise SpeechCancelled
        if result.outcome == "finished":
            return "finished"
        if result.started:
            self.publish(replace(state, partial=True))
            return "failed"
        return None


class VoiceRouter:
    def __init__(self, cache: AudioCache, client: ElevenClient | None = None) -> None:
        self.cache = cache
        self.client = client or ElevenClient()
        self.gate = RecoveryGate()
        self.network = BoundedCall()
        self.natural_network = BoundedCall()
        self.natural = prepare_natural

    def run(self, text, config, playback: Playback, *, test=False) -> str:
        if playback.cancel.is_set():
            raise SpeechCancelled
        ticket = None if test else self.cache.ticket(text, config.audio_identity)
        cached = self._play_cached(ticket, playback)
        if cached:
            return cached
        try:
            config.validate()
            self._check_quota_gate(config, test)
            return self._synthesize_and_play(text, config, ticket, playback)
        except VoiceError as error:
            if playback.cancel.is_set():
                raise SpeechCancelled from None
            self._record_failure(config, error.reason)
            return self._failed_request(text, error.reason, playback, test)

    def _failed_request(self, text, reason, playback, test):
        if test:
            raise VoiceError(reason)
        return self._play_fallback(text, reason, playback)

    def _play_cached(self, ticket, playback):
        cached = self.cache.read(ticket)
        if cached is None:
            return None
        result = playback.play(cached, VoiceState(cached=True))
        outcome = playback.settle(result, VoiceState(cached=True))
        if outcome != "finished":
            self.cache.discard(ticket)
        return outcome

    def _check_quota_gate(self, config, test):
        reason, retry_at, _balance = self.gate.snapshot()
        if test:
            return
        if reason and time.monotonic() < retry_at:
            raise VoiceError(reason)
        # Subscription is optional metadata, not a prerequisite for TTS. After
        # cooldown, the next user-requested synthesis establishes recovery.

    def _record_failure(self, config, reason):
        previous, retry_at, balance = self.gate.snapshot()
        if previous != reason or time.monotonic() >= retry_at:
            self.gate.failure(config, reason, balance)

    def _synthesize_and_play(self, text, config, ticket, playback):
        audio = self.network.run(lambda stop, end: self.client.synthesize(config, saved_text(text) if ticket else text, stop, end), playback.cancel, ELEVEN_TIMEOUT)
        state = VoiceState()
        outcome = playback.settle(playback.play(audio, state), state)
        if outcome is None:
            raise VoiceError("audio")
        if outcome == "finished":
            self.cache.write(ticket, audio)
            playback.publish(VoiceState(recovered=self.gate.success(config)))
        return outcome

    def _play_fallback(self, text, reason, playback):
        try:
            audio = self.natural_network.run(lambda stop, end: self.natural(text, stop, end), playback.cancel, NATURAL_TIMEOUT)
            state = VoiceState(NATURAL, reason)
            outcome = playback.settle(playback.play(audio, state), state)
            if outcome:
                return outcome
        except VoiceError:
            pass
        if playback.cancel.is_set():
            raise SpeechCancelled
        playback.publish(VoiceState(STANDARD, reason))
        return "standard"
