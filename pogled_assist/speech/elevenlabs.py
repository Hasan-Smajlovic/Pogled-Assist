"""Bounded ElevenLabs requests with no automatic replay of billable POSTs."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Event, Lock, Thread
from urllib.parse import quote, urlencode

from .voice_state import SpeechCancelled, VoiceError

API_HOST = "api.elevenlabs.io"
MAX_AUDIO_BYTES = 16 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
DEFAULT_MODEL = "eleven_v3"
OUTPUT_FORMAT = "mp3_44100_128"


def valid_identifier(value: object) -> str:
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) else ""


@dataclass(frozen=True)
class ElevenConfig:
    key: str = field(repr=False)
    voice: str = ""
    model: str = DEFAULT_MODEL
    stability: int = 65
    similarity: int = 80

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(f"{self.key}\0{self.audio_identity}".encode()).hexdigest()

    @property
    def parameters(self) -> dict:
        # Pin the generation settings so a saved clip has a stable identity.
        return {
            "model_id": self.model,
            "language_code": "bs",
            "apply_text_normalization": "auto",
            "voice_settings": {
                "stability": self.stability / 100,
                "similarity_boost": self.similarity / 100,
            },
        }

    @property
    def audio_identity(self) -> str:
        return json.dumps(
            [self.voice, OUTPUT_FORMAT, self.parameters], sort_keys=True, separators=(",", ":")
        )

    def validate(self) -> None:
        if not self.key:
            raise VoiceError("missing_key")
        if not self.key.isascii() or any(char.isspace() for char in self.key):
            raise VoiceError("invalid_key")
        if not valid_identifier(self.voice) or not valid_identifier(self.model):
            raise VoiceError("configuration")


def configuration(settings, saved_key: str) -> ElevenConfig:
    return ElevenConfig(
        os.environ.get("ELEVENLABS_API_KEY", "").strip() or saved_key,
        os.environ.get("ELEVENLABS_VOICE_ID", "").strip() or settings.elevenlabs_voice_id,
        os.environ.get("ELEVENLABS_MODEL_ID", "").strip() or settings.elevenlabs_model_id,
        settings.elevenlabs_stability,
        settings.elevenlabs_similarity,
    )


@dataclass(frozen=True)
class _CallStop:
    """Observe caller cancellation immediately without cancelling fallback on timeout."""

    caller: Event
    abandoned: Event

    def is_set(self) -> bool:
        return self.caller.is_set() or self.abandoned.is_set()


class BoundedCall:
    """A blocked DNS/socket call must neither hold speech nor accumulate workers."""

    def __init__(self) -> None:
        self._slot = Lock()

    def run(self, operation: Callable, cancel: Event, timeout: float):
        if cancel.is_set():
            raise SpeechCancelled
        if timeout <= 0 or not self._slot.acquire(blocking=False):
            raise VoiceError("timeout")
        finished, abandoned = Event(), Event()
        stop = _CallStop(cancel, abandoned)
        deadline = time.monotonic() + timeout
        result = []

        def work() -> None:
            try:
                result.append((True, operation(stop, deadline)))
            except VoiceError as error:
                result.append((False, error.reason))
            except Exception:
                result.append((False, "offline"))
            finally:
                self._slot.release()
                finished.set()

        try:
            Thread(target=work, daemon=True, name="speech-network").start()
        except RuntimeError:
            self._slot.release()
            raise VoiceError("offline") from None
        try:
            while not finished.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise VoiceError("timeout")
                if cancel.wait(min(0.02, remaining)):
                    raise SpeechCancelled
            if cancel.is_set():
                raise SpeechCancelled
            if time.monotonic() > deadline:
                raise VoiceError("timeout")
            success, value = result[0]
            if not success:
                raise VoiceError(value)
            return value
        finally:
            abandoned.set()


@dataclass(frozen=True)
class Subscription:
    used: int
    limit: int
    resets_at: int | None = None

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def improved_from(self, previous: Subscription) -> bool:
        return self.remaining > previous.remaining or (
            self.resets_at is not None
            and previous.resets_at is not None
            and self.resets_at > previous.resets_at
        )


@dataclass(frozen=True)
class AccountOptions:
    voices: tuple[tuple[str, str], ...]
    models: tuple[tuple[str, str], ...]
    subscription: Subscription | None


class ElevenClient:
    def synthesize(self, config: ElevenConfig, text: str, cancel: Event, deadline: float) -> bytes:
        config.validate()
        path = f"/v1/text-to-speech/{quote(config.voice, safe='')}?output_format={OUTPUT_FORMAT}"
        return self._request(
            config.key,
            "POST",
            path,
            cancel,
            deadline,
            payload={"text": text, **config.parameters},
            audio=True,
        )

    def subscription(self, key: str, cancel: Event, deadline: float) -> Subscription:
        payload = self._request(key, "GET", "/v1/user/subscription", cancel, deadline)
        try:
            values = [payload[name] for name in ("character_count", "character_limit")]
            if any(type(value) is not int or value < 0 for value in values):
                raise ValueError
            reset = payload.get("next_character_count_reset_unix")
            if reset is not None and (type(reset) is not int or reset < 0):
                raise ValueError
            return Subscription(*values, reset)
        except (KeyError, TypeError, ValueError):
            raise VoiceError("offline") from None

    def options(self, key: str, cancel: Event, deadline: float) -> AccountOptions:
        if not key:
            raise VoiceError("missing_key")
        voices = []
        token = ""
        seen = set()
        for _page in range(20):
            # Match My Voices, including library/default voices explicitly saved there.
            query = {"page_size": 100, "voice_type": "saved"}
            if token:
                query["next_page_token"] = token
            try:
                payload = self._request(
                    key, "GET", "/v2/voices?" + urlencode(query), cancel, deadline
                )
            except VoiceError as error:
                if error.reason == "permission":
                    raise VoiceError("voices_permission") from None
                raise
            voices.extend(_choices(payload.get("voices", []), "voice_id"))
            if not payload.get("has_more"):
                break
            token = payload.get("next_page_token")
            if not isinstance(token, str) or not token or token in seen:
                raise VoiceError("offline")
            seen.add(token)
        else:
            raise VoiceError("offline")
        try:
            models = self._request(key, "GET", "/v1/models", cancel, deadline)
        except VoiceError as error:
            if error.reason == "permission":
                raise VoiceError("models_permission") from None
            raise
        supported = [
            model
            for model in models
            if isinstance(model, dict)
            and model.get("can_do_text_to_speech")
            and any(
                isinstance(language, dict) and language.get("language_id") == "bs"
                for language in model.get("languages", [])
            )
        ]
        # Optional balance has its own worker/budget; it cannot discard catalogs.
        return AccountOptions(tuple(voices), tuple(_choices(supported, "model_id")), None)

    def _request(
        self,
        key: str,
        method: str,
        path: str,
        cancel: Event,
        deadline: float,
        *,
        payload: dict | None = None,
        audio: bool = False,
    ):
        remaining = _remaining(cancel, deadline)
        connection = http.client.HTTPSConnection(API_HOST, timeout=remaining)
        headers = {"xi-api-key": key, "Accept": "audio/mpeg" if audio else "application/json"}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            # DNS/connect can finish after the caller has abandoned this worker.
            # Recheck before sending any authenticated or billable request.
            connection.connect()
            if connection.sock:
                connection.sock.settimeout(_remaining(cancel, deadline))
            _remaining(cancel, deadline)
            connection.request(method, path, body=body, headers=headers)
            _remaining(cancel, deadline)
            if connection.sock:
                connection.sock.settimeout(_remaining(cancel, deadline))
            response = connection.getresponse()
            successful = 200 <= response.status < 300
            limit = MAX_AUDIO_BYTES if audio and successful else MAX_JSON_BYTES
            data = bytearray()
            while True:
                if connection.sock:
                    connection.sock.settimeout(_remaining(cancel, deadline))
                _remaining(cancel, deadline)
                chunk = response.read1(min(65536, limit + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > limit:
                    raise VoiceError("audio" if audio and successful else "offline")
            _remaining(cancel, deadline)
            if not successful:
                raise VoiceError(_error_reason(response.status, bytes(data)))
            declared = response.getheader("Content-Length", "")
            if declared and (not declared.isdigit() or int(declared) != len(data)):
                raise VoiceError("audio" if audio else "offline")
            if audio:
                if not data or "audio/" not in response.getheader("Content-Type", ""):
                    raise VoiceError("audio")
                return bytes(data)
            return json.loads(data)
        except TimeoutError:
            raise VoiceError("timeout") from None
        except (VoiceError, SpeechCancelled):
            raise
        except Exception:
            raise VoiceError("offline") from None
        finally:
            connection.close()


def _remaining(cancel: Event, deadline: float) -> float:
    if cancel.is_set():
        raise SpeechCancelled
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise VoiceError("timeout")
    return remaining


def _error_reason(status: int, body: bytes) -> str:
    try:
        detail = json.loads(body).get("detail", {})
        code = detail.get("status", "") if isinstance(detail, dict) else ""
    except (ValueError, AttributeError):
        code = ""
    if code == "quota_exceeded":
        return "quota"
    if status == 403 or code in ("insufficient_permissions", "missing_permissions"):
        return "permission"
    if code in ("invalid_api_key", "unauthorized") or status == 401:
        return "invalid_key"
    if status == 429:
        return "rate_limit"
    if status in (400, 404, 422):
        return "configuration"
    return "offline"


def _choices(items: list, field_name: str) -> list[tuple[str, str]]:
    result = []
    for item in items:
        if not isinstance(item, dict) or not valid_identifier(item.get(field_name)):
            continue
        name = item.get("name")
        if not isinstance(name, str):
            name = item[field_name]
        result.append((item[field_name], name[:120]))
    return result
