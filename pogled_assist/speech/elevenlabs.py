"""ElevenLabs speech and account data without automatic billable retries."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from threading import Event
from urllib.parse import quote, urlencode

from ..settings_limits import ELEVENLABS_SIMILARITY_DEFAULT, ELEVENLABS_STABILITY_DEFAULT

from .eleven_transport import MAX_AUDIO_BYTES as MAX_AUDIO_BYTES, BoundedCall as BoundedCall, Budget, Request, request_data
from .voice_state import VoiceError

DEFAULT_MODEL = "eleven_v4"
OUTPUT_FORMAT = "mp3_44100_128"
TEXT_NORMALIZATION_VERSION = 1
ENV_OVERRIDES = ("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "ELEVENLABS_MODEL_ID")


def env_override(name: str) -> str:
    return os.environ.get(name, "").strip()


def valid_identifier(value: object) -> str:
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) else ""


def prepare_eleven_text(text: str) -> str:
    text = text.replace("[", "(").replace("]", ")").lower()
    return re.sub(r"(^|[.!?]\s*)([^\W\d_])", lambda match: match[1] + match[2].upper(), text)


@dataclass(frozen=True)
class ElevenConfig:
    key: str = field(repr=False)
    voice: str = ""
    model: str = DEFAULT_MODEL
    stability: int = ELEVENLABS_STABILITY_DEFAULT
    similarity: int = ELEVENLABS_SIMILARITY_DEFAULT

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(f"{self.key}\0{self.audio_identity}".encode()).hexdigest()

    @property
    def parameters(self) -> dict:
        return {
            "model_id": self.model,
            "language_code": "bs",
            "apply_text_normalization": "auto",
            "voice_settings": {"stability": self.stability / 100, "similarity_boost": self.similarity / 100},
        }

    @property
    def audio_identity(self) -> str:
        return json.dumps([TEXT_NORMALIZATION_VERSION, self.voice, OUTPUT_FORMAT, self.parameters], sort_keys=True, separators=(",", ":"))

    def validate(self) -> None:
        _validate_key(self.key)
        if not all(valid_identifier(value) for value in (self.voice, self.model)):
            raise VoiceError("configuration")


def _validate_key(key) -> None:
    if not key:
        raise VoiceError("missing_key")
    if not key.isascii() or any(char.isspace() for char in key):
        raise VoiceError("invalid_key")


def configuration(settings, saved_key: str) -> ElevenConfig:
    return ElevenConfig(
        env_override(ENV_OVERRIDES[0]) or saved_key,
        env_override(ENV_OVERRIDES[1]) or settings.elevenlabs_voice_id,
        env_override(ENV_OVERRIDES[2]) or settings.elevenlabs_model_id,
        settings.elevenlabs_stability,
        settings.elevenlabs_similarity,
    )


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
            self.resets_at is not None and previous.resets_at is not None
            and self.resets_at > previous.resets_at
        )


@dataclass(frozen=True)
class AccountOptions:
    voices: tuple[tuple[str, str], ...]
    models: tuple[tuple[str, str], ...]
    subscription: Subscription | None = None


class ElevenClient:
    def synthesize(self, config: ElevenConfig, text: str, cancel: Event, deadline: float) -> bytes:
        config.validate()
        path = f"/v1/text-to-speech/{quote(config.voice, safe='')}?output_format={OUTPUT_FORMAT}"
        return self._request(Request(config.key, "POST", path, {"text": prepare_eleven_text(text), **config.parameters}, True), Budget(cancel, deadline))

    def subscription(self, key: str, cancel: Event, deadline: float) -> Subscription:
        return _parse_subscription(self._request(Request(key, "GET", "/v1/user/subscription"), Budget(cancel, deadline)))

    def options(self, key: str, cancel: Event, deadline: float) -> AccountOptions:
        _validate_key(key)
        budget = Budget(cancel, deadline)
        return AccountOptions(self._saved_voices(key, budget), self._bosnian_models(key, budget))

    def _catalog(self, key, path, budget, permission):
        try:
            return self._request(Request(key, "GET", path), budget)
        except VoiceError as error:
            if error.reason == "permission":
                raise VoiceError(permission) from None
            raise

    def _saved_voices(self, key, budget):
        voices, seen, token = [], set(), ""
        for _page in range(20):
            query = {"page_size": 100, "voice_type": "saved", "include_total_count": "false"}
            if token:
                query["next_page_token"] = token
            payload = self._catalog(key, "/v2/voices?" + urlencode(query), budget, "voices_permission")
            voices.extend(_choices(payload.get("voices", []), "voice_id"))
            if not payload.get("has_more"):
                return tuple(voices)
            token = _next_token(payload, seen)
        raise VoiceError("offline")

    def _bosnian_models(self, key, budget):
        models = self._catalog(key, "/v1/models", budget, "models_permission")
        return tuple(_choices([model for model in models if _supports_bosnian(model)], "model_id"))

    def _request(self, request: Request, budget: Budget):
        return request_data(request, budget)


def _next_token(payload, seen):
    token = payload.get("next_page_token")
    if not isinstance(token, str):
        raise VoiceError("offline")
    if not token or token in seen:
        raise VoiceError("offline")
    seen.add(token)
    return token


def _supports_bosnian(model) -> bool:
    if not isinstance(model, dict) or not model.get("can_do_text_to_speech"):
        return False
    return any(isinstance(language, dict) and language.get("language_id") == "bs" for language in model.get("languages", []))


def _non_negative_int(value):
    if type(value) is not int or value < 0:
        raise ValueError
    return value


def _parse_subscription(payload):
    try:
        used, limit = (_non_negative_int(payload[name]) for name in ("character_count", "character_limit"))
        reset = payload.get("next_character_count_reset_unix")
        return Subscription(used, limit, None if reset is None else _non_negative_int(reset))
    except (KeyError, TypeError, ValueError, AttributeError):
        raise VoiceError("offline") from None


def _choices(items: list, field_name: str) -> list[tuple[str, str]]:
    return [(item[field_name], _choice_name(item, field_name)) for item in items if isinstance(item, dict) and valid_identifier(item.get(field_name))]


def _choice_name(item, field_name):
    name = item.get("name")
    return (name if isinstance(name, str) else item[field_name])[:120]
