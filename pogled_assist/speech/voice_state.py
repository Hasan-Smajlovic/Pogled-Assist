"""Public speech state and safe messages shared by the service and its views."""

from __future__ import annotations

from dataclasses import dataclass

EFENDIJA = "efendija"
NATURAL = "human_like"
STANDARD = "default"
VOICE_TEST_TEXT = "SELAM. DOBRO MI DOŠLI."
RECOVERY_NOTICE_MS = 5000
ELEVEN_TIMEOUT = 5.0
NATURAL_TIMEOUT = 3.0

REASONS = {
    "quota": "Nema dovoljno ElevenLabs kredita.",
    "offline": "ElevenLabs trenutno nije dostupan.",
    "timeout": "Efendijin glas se predugo priprema.",
    "invalid_key": "Provjerite ElevenLabs ključ u Postavkama.",
    "missing_key": "Dodajte ElevenLabs ključ u Postavkama.",
    "configuration": "Provjerite ElevenLabs glas i model u Postavkama.",
    "permission": "ElevenLabs ključ nema potrebne dozvole.",
    "rate_limit": "ElevenLabs je trenutno zauzet.",
    "audio": "Efendijin glas se nije mogao reproducirati.",
}


class VoiceError(Exception):
    """Only a fixed reason crosses HTTP, audio, logging and UI boundaries."""

    def __init__(self, reason: str) -> None:
        self.reason = reason if reason in REASONS else "offline"
        super().__init__(self.reason)


class SpeechCancelled(Exception):
    pass


@dataclass(frozen=True)
class VoiceState:
    voice: str = EFENDIJA
    reason: str = ""
    cached: bool = False
    recovered: bool = False
    partial: bool = False

    @property
    def label(self) -> str:
        return {EFENDIJA: "Efendija", NATURAL: "Prirodni", STANDARD: "Standardni"}[self.voice]

    @property
    def notice(self) -> tuple[str, str, str] | None:
        if self.partial:
            return "error", "Izgovor nije završen.", "Za ponavljanje odaberite Izgovori."
        if self.cached:
            return (
                "ready",
                "Koristi se sačuvani Efendijin glas.",
                "Ovaj snimak ne troši nove kredite.",
            )
        if self.recovered:
            return (
                "ready",
                "Efendijin glas je ponovo dostupan.",
                "Naredne poruke koriste Efendiju.",
            )
        if self.reason:
            title = REASONS.get(self.reason, REASONS["offline"])
            if self.voice == STANDARD and self.reason in ("offline", "timeout", "rate_limit"):
                title = "Online glasovi trenutno nisu dostupni."
            return "warning", title, f"Koristi se {self.label} glas."
        return None
