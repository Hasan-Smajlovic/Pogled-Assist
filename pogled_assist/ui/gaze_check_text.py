"""Position and precision feedback derived from the current check snapshot."""

from __future__ import annotations

import math

from ..interaction.eye_tracking_policy import ANY_EYE, BOTH_EYES, eyes_usable
from ..tracking.gaze_check import (
    AGREEMENT_MIN_FRACTION,
    EYE_GAP_FRACTION,
    EYE_LOW_FRACTION,
    FRESH_SECONDS,
    CheckSnapshot,
    EyeTrackingResult,
)
from ..tracking.status import TrackingState


def position_notice(snapshot: CheckSnapshot, tracking_state: TrackingState | None) -> str:
    if tracking_state in (
        TrackingState.RETRYING,
        TrackingState.STOPPED,
        TrackingState.UNAVAILABLE,
    ):
        return "Veza uređaja je prekinuta. Čekam ponovno povezivanje."
    if snapshot.position_supported is False:
        return "Uređaj ne šalje položaje očiju za ovaj prikaz. Koristite Tobii prikaz položaja."
    if snapshot.left_position is None and snapshot.right_position is None:
        return "Čekam svježe podatke o položaju očiju."
    return "Okvir pokazuje položaj očiju, traka ispod udaljenost."


def position_guidance(snapshot: CheckSnapshot, policy: str = BOTH_EYES) -> str:
    if policy == ANY_EYE and eyes_usable(policy, snapshot.left, snapshot.right):
        if snapshot.gaze is None:
            return "Čekam svjež validan pogled za odabir u probnom režimu."
        return "Probni režim dopušta odabir jednim okom. Provjerite preciznost na metama."
    left_visible, right_visible = visible_eyes(snapshot)
    if left_visible is None or right_visible is None:
        return "Čekam svježe podatke. Provjerite vezu uređaja i pogledajte prema ekranu."
    if not (left_visible and right_visible):
        return "Polako podesite položaj i nagib ekrana dok uređaj ponovo vidi oba oka."
    return _tracked_position_guidance(snapshot)


def _tracked_position_guidance(snapshot: CheckSnapshot) -> str:
    position, depth = snapshot.in_box((0, 1)), snapshot.in_box((2,))
    if position is False:
        return "Pomjerajte i nagnite ekran tako da su obje oznake unutar okvira."
    if depth is False:
        return _depth_guidance(snapshot)
    return _gaze_guidance(snapshot, position, depth)


def _gaze_guidance(snapshot: CheckSnapshot, position: bool | None, depth: bool | None) -> str:
    if snapshot.gaze is None:
        return "Oči su prepoznate, ali pogled se još ne prati. Pogledajte prema ekranu."
    if snapshot.stable is False:
        return "Zadržite ekran mirno. Ako se prekidi nastave, provjerite položaj i osvjetljenje."
    if position is None or depth is None:
        return "Uređaj ne šalje položaj za ovaj prikaz. Podesite ekran uz Tobii prikaz položaja."
    return "Zadržite položaj i odaberite „Provjeri preciznost“."


def _depth_guidance(snapshot: CheckSnapshot) -> str:
    depths = [snapshot.left_position[2], snapshot.right_position[2]]
    if max(depths) < 0:
        return "Polako odmaknite ekran od lica."
    if min(depths) > 1:
        return "Polako približite ekran licu."
    return "Podesite udaljenost i nagib ekrana; pratite oznake na traci."


def precision_feedback(
    snapshot: CheckSnapshot, remaining: int, now: float, policy: str = BOTH_EYES
) -> tuple[str, bool | None]:
    missing_eye = _missing_eye_feedback(snapshot)
    if missing_eye is not None and policy != ANY_EYE:
        return missing_eye, False
    if not _fresh_gaze(snapshot, now):
        return "Čekam svjež validan pogled. Ako se ne vrati, odaberite „Prekini test“.", None
    return f"Zadržite pogled · još {remaining} s.", None


def free_gaze_is_visible(snapshot: CheckSnapshot, now: float, policy: str = BOTH_EYES) -> bool:
    if not eyes_usable(policy, snapshot.left, snapshot.right):
        return False
    if not _fresh_gaze(snapshot, now):
        return False
    return _gaze_in_bounds(snapshot.gaze)


def _fresh_gaze(snapshot: CheckSnapshot, now: float) -> bool:
    if snapshot.gaze is None or snapshot.gaze_at is None:
        return False
    return 0 <= now - snapshot.gaze_at < FRESH_SECONDS


def visible_eyes(snapshot: CheckSnapshot) -> tuple[bool | None, bool | None]:
    return (
        snapshot.left_position is not None or snapshot.left,
        snapshot.right_position is not None or snapshot.right,
    )


def _missing_eye_feedback(snapshot: CheckSnapshot) -> str | None:
    if snapshot.left is False and snapshot.right is True:
        return "Uređaj ne vidi lijevo oko. Pogledajte prema ekranu."
    if snapshot.right is False and snapshot.left is True:
        return "Uređaj ne vidi desno oko. Pogledajte prema ekranu."
    return None


def _gaze_in_bounds(gaze: tuple[float, float]) -> bool:
    return all(math.isfinite(value) and 0 <= value <= 1 for value in gaze)


def eye_tracking_status(result: EyeTrackingResult, remaining: int | None) -> str:
    if remaining is not None:
        return f"Mjerim · još {remaining} s. Korisnik neka gleda ekran kao i inače."
    if result.completed:
        return f"Završeno · izmjereno {result.observed_seconds:.0f} s."
    return f"Prekinuto nakon {result.observed_seconds:.0f} s · rezultat je djelimičan."


def eye_agreement_text(result: EyeTrackingResult) -> str:
    if result.agreement_supported is False:
        return "Isto mjesto · nije dostupno: uređaj šalje samo zajedničku tačku pogleda oba oka."
    if not result.agreement_supported:
        return "Isto mjesto · nije dostupno za ovaj uređaj."
    if result.median_separation is None:
        return "Isto mjesto · nije izmjereno: oba oka nisu dovoljno dugo praćena istovremeno."
    return (
        f"Isto mjesto · {result.agreement_fraction:.0%} uzoraka unutar "
        f"{result.threshold:.0f} px · razmak {result.median_separation:.0f} px"
    )


def eye_tracking_advice(result: EyeTrackingResult) -> tuple[str, bool]:
    """Name what was measured; the values do not establish a cause."""
    if max(result.left, result.right) < 0.005:
        return "Uređaj nije javio nijedno oko. Provjerite vezu, položaj i osvjetljenje.", False
    low = min(result.left, result.right)
    if low < EYE_LOW_FRACTION and abs(result.left - result.right) >= EYE_GAP_FRACTION:
        eye = "Lijevo" if result.left < result.right else "Desno"
        return f"{eye} oko se često gubi. Podesite položaj i ponovite provjeru.", False
    if low < EYE_LOW_FRACTION:
        return "Oba oka se često gube. Podesite položaj i ponovite provjeru.", False
    agreement = result.agreement_fraction
    if agreement is not None and agreement < AGREEMENT_MIN_FRACTION:
        return (
            "Lijevo i desno oko često ne gledaju u istu tačku. "
            "Jedno oko možda odlazi ili kalibracija više ne odgovara.",
            False,
        )
    return (
        "Oba oka se uglavnom prate. Ako slova i dalje ne pogađate, "
        "odaberite „Provjeri preciznost“ za kalibraciju i položaj.",
        True,
    )
