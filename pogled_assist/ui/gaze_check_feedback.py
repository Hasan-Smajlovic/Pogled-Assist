"""Result advice independent of Qt, with missing measurements taking priority."""

from __future__ import annotations

from collections.abc import Sequence, Set

from ..interaction.eye_tracking_policy import ANY_EYE, BOTH_EYES
from ..tracking.gaze_check import FixationResult


def result_advice(
    results: Sequence[FixationResult],
    *,
    trial_results: Sequence[bool],
    tracked_targets: Set[int],
    losses: int,
    wrong_selections: int,
    policy: str = BOTH_EYES,
    expected: int = 3,
) -> str:
    eyes = "najmanje jedno oko uz svjež pogled" if policy == ANY_EYE else "oba oka"
    tracking = "se prati" if policy == ANY_EYE else "se prate"
    if not results or any(result.near is None for result in results):
        return f"Odaberite „Podesi položaj“. Kad {tracking} {eyes}, ponovite provjeru."
    if any(result.near is False for result in results):
        return (
            "Odaberite „Podesi položaj“. Ako pogled i dalje promašuje, "
            "otvorite Tobii postavke i ponovite kalibraciju korisnikovog profila."
        )
    if len(trial_results) != expected:
        return "Još napišite riječ pogledom."
    if any(
        not selected and index not in tracked_targets
        for index, selected in enumerate(trial_results)
    ):
        return (
            "Tokom dijela testa riječi nije bilo dovoljno podataka o pogledu. Podesite "
            f"položaj dok {tracking} {eyes}, pa ponovite test."
        )
    if losses and not all(trial_results):
        return (
            "Prekidi praćenja poništavali su izbor. Podesite ekran dok uređaj "
            f"ne vidi {eyes}, pa ponovite test."
        )
    if wrong_selections:
        return "Odabrana su i pogrešna slova. Provjerite položaj i kalibraciju, pa ponovite test."
    if not all(trial_results):
        return (
            "Neka slova nisu odabrana na vrijeme. Ponovite test; zadržite "
            "pogled na traženom slovu dok se traka ne popuni."
        )
    advice = "Zatvorite provjeru i probajte govornu tastaturu."
    if losses:
        advice += " Ako se izbor često poništava, ponovo podesite položaj."
    return advice
