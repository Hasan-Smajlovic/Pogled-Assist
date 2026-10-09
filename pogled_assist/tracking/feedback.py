"""Passive notification timing; never changes gaze selection or pointer input."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .gaze_provider import GAZE_DELIVERY_GAP_SECONDS
from .status import TrackingState, TrackingStatus

NOTICE_DELAY_SECONDS = 0.8
RECOVERY_SECONDS = 0.5
SUCCESS_SECONDS = 2.0
REPEATED_WINDOW_SECONDS = 10.0
REPEATED_MIN_GAP_SECONDS = 0.35
REPEATED_GAPS = 3


@dataclass(frozen=True)
class TrackingNotice:
    title: str
    detail: str = ""
    tone: str = "warning"
    eyes: tuple[bool, bool] | None = None

    @property
    def text(self) -> str:
        return self.title + (f" · {self.detail}" if self.detail else "")


def _problem(
    status: TrackingStatus,
    eyes: tuple[bool, bool] | None,
    gaze_at: float | None,
    now: float,
) -> TrackingNotice | None:
    if status.state == TrackingState.RETRYING:
        return TrackingNotice("Uređaj nije povezan", "pokušavam ponovo", "error")
    if status.state == TrackingState.CONNECTING:
        return TrackingNotice("Povezivanje s uređajem", "odabir je zaustavljen", "quiet")
    if status.state == TrackingState.WAITING or eyes is None:
        return TrackingNotice("Čekam podatke o pogledu", "odabir je zaustavljen", "quiet")
    if not all(eyes):
        if eyes == (False, False):
            return TrackingNotice(
                "Praćenje oba oka je prekinuto", "pogledajte prema ekranu", eyes=eyes
            )
        eye = "Lijevo" if not eyes[0] else "Desno"
        return TrackingNotice(f"{eye} oko se trenutno ne prati", "odabir je zaustavljen", eyes=eyes)
    if gaze_at is None or now - gaze_at >= GAZE_DELIVERY_GAP_SECONDS:
        # Known eye validity is not evidence that new gaze coordinates are arriving.
        return TrackingNotice("Čekam podatke o pogledu", "odabir je zaustavljen", "quiet", eyes)
    return None


class TrackingFeedbackState:
    """Debounce presentation independently of the immediate both-eye safety gate."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._problem_since: float | None = None
        self._healthy_since: float | None = None
        self._notice_open = False
        self._eye_gap = False
        self._gaps: deque[float] = deque()

    def update(
        self,
        status: TrackingStatus,
        eyes: tuple[bool, bool] | None,
        gaze_at: float | None,
        now: float,
        *,
        active: bool = True,
    ) -> TrackingNotice | None:
        if not active or status.state in (
            TrackingState.STOPPED,
            TrackingState.SIMULATING,
            TrackingState.UNAVAILABLE,
        ):
            self.reset()
            return None
        while self._gaps and now - self._gaps[0] > REPEATED_WINDOW_SECONDS:
            self._gaps.popleft()
        problem = _problem(status, eyes, gaze_at, now)
        if problem is not None:
            self._healthy_since = None
            if self._problem_since is None:
                self._problem_since = now
                self._eye_gap = (
                    status.state == TrackingState.CONNECTED and eyes is not None and not all(eyes)
                )
            if status.state != TrackingState.CONNECTED:
                self._eye_gap = False
                self._gaps.clear()
            if now - self._problem_since >= NOTICE_DELAY_SECONDS:
                self._notice_open = True
            return problem if self._notice_open else None

        if self._problem_since is not None:
            if self._eye_gap and now - self._problem_since >= REPEATED_MIN_GAP_SECONDS:
                self._gaps.append(now)
                if len(self._gaps) >= REPEATED_GAPS:
                    self._notice_open = True
            self._problem_since = None
        if self._healthy_since is None:
            self._healthy_since = now
        if not self._notice_open:
            return None
        elapsed = now - self._healthy_since
        if elapsed < RECOVERY_SECONDS:
            if len(self._gaps) >= REPEATED_GAPS:
                return TrackingNotice(
                    "Praćenje često prekida", "provjerite položaj uređaja", eyes=eyes
                )
            return TrackingNotice("Praćenje se vraća", tone="quiet", eyes=eyes)
        if elapsed < RECOVERY_SECONDS + SUCCESS_SECONDS:
            return TrackingNotice("Možete nastaviti", tone="ready", eyes=eyes)
        self._notice_open = False
        return None
