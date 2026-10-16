"""Public speech state and safe messages shared by the service and its views."""

from __future__ import annotations

from dataclasses import dataclass

EFENDIJA = "efendija"
NATURAL = "human_like"
STANDARD = "default"
NATURAL_VOICE = "bs-BA-GoranNeural"
NATURAL_RATE = "-10%"
NATURAL_PITCH = "-2Hz"
ACTIVE_PLAYBACK_STATES = frozenset({"preparing", "speaking"})
PLAYBACK_LABELS = {"preparing": "Pripremam…", "speaking": "Izgovaram…"}
FALLBACK_NOTE = "Zamjenski glasovi: Prirodni → Standardni."
CREDITS_UNAVAILABLE = "Stanje kredita nije dostupno."
CREDITS_UNAVAILABLE_NOTE = CREDITS_UNAVAILABLE + " Provjerite vezu i dozvolu za čitanje podataka o računu."
VOICE_TEST_TEXT = "SELAM. DOBRO MI DOŠLI."
RECOVERY_NOTICE_MS = 5000
# Non-streaming synthesis includes generation and the full audio download.
ELEVEN_TIMEOUT = 30.0
NATURAL_TIMEOUT = 3.0

REASONS = {
    "busy": "Prethodni ElevenLabs zahtjev se još zaustavlja.",
    "too_long": "Poruka je preduga za Efendijin glas.",
    "quota": "Nema dovoljno ElevenLabs kredita.",
    "offline": "ElevenLabs trenutno nije dostupan.",
    "timeout": "Efendijin glas se predugo priprema.",
    "invalid_key": "Provjerite ElevenLabs ključ u Postavkama.",
    "missing_key": "Dodajte ElevenLabs ključ u Postavkama.",
    "configuration": "Provjerite ElevenLabs glas i model u Postavkama.",
    "permission": "ElevenLabs ključ nema potrebne dozvole.",
    "voices_permission": "Za listu glasova dozvolite čitanje glasova na ElevenLabs ključu.",
    "models_permission": "Za listu modela dozvolite čitanje modela na ElevenLabs ključu.",
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
