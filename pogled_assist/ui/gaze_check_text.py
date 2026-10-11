"""Position and precision feedback derived from the current check snapshot."""

from __future__ import annotations

import math

from ..tracking.gaze_check import FRESH_SECONDS, CheckSnapshot
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


def position_guidance(snapshot: CheckSnapshot) -> str:
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
    snapshot: CheckSnapshot, remaining: int, now: float
) -> tuple[str, bool | None]:
    missing_eye = _missing_eye_feedback(snapshot)
    if missing_eye is not None:
        return missing_eye, False
    if not _fresh_gaze(snapshot, now):
        return "Čekam pogled s oba oka. Ako se ne vrati, odaberite „Prekini test“.", None
    return f"Zadržite pogled · još {remaining} s.", None


def free_gaze_is_visible(snapshot: CheckSnapshot, now: float) -> bool:
    if not (snapshot.left and snapshot.right):
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
