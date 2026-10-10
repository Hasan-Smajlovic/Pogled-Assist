"""Result advice independent of Qt, with missing measurements taking priority."""

from __future__ import annotations

from collections.abc import Sequence, Set

from ..tracking.gaze_check import FixationResult


def result_advice(
    results: Sequence[FixationResult],
    *,
    trial_results: Sequence[bool],
    tracked_targets: Set[int],
    losses: int,
    wrong_selections: int,
) -> str:
    if not results or any(result.near is None for result in results):
        return "Odaberite „Podesi položaj“. Kad se prate oba oka, ponovite provjeru."
    if any(result.near is False for result in results):
        return (
            "Odaberite „Podesi položaj“. Ako pogled i dalje promašuje, "
            "otvorite Tobii postavke i ponovite kalibraciju korisnikovog profila."
        )
    if len(trial_results) != 3:
        return "Još provjerite izbor dugmeta pogledom."
    if any(
        not selected and index not in tracked_targets
        for index, selected in enumerate(trial_results)
    ):
        return (
            "Tokom dijela probe nije bilo dovoljno podataka o pogledu. Podesite položaj "
            "dok se prate oba oka, pa ponovite probu."
        )
    if losses and not all(trial_results):
        return (
            "Prekidi praćenja poništavali su izbor. Podesite ekran dok uređaj "
            "ne vidi oba oka, pa ponovite probu."
        )
    if wrong_selections:
        return "Odabrana su i pogrešna dugmad. Provjerite položaj i kalibraciju, pa ponovite probu."
    if not all(trial_results):
        return (
            "Neka dugmad nisu odabrana na vrijeme. Ponovite probu; zadržite "
            "pogled na „Pogledaj“ dok se traka ne popuni."
        )
    advice = "Zatvorite provjeru i probajte govornu tastaturu."
    if losses:
        advice += " Ako se izbor često poništava, ponovo podesite položaj."
    return advice
