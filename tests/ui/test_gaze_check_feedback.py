from __future__ import annotations

import pytest

from pogled_assist.tracking.gaze_check import FixationResult
from pogled_assist.ui.gaze_check_feedback import result_advice


@pytest.mark.parametrize(
    "precision,selected,tracked,losses,wrong,expected",
    [
        ([], [], set(), 0, 0, "Kad se prate oba oka"),
        ([True, None, False], [True] * 3, {0, 1, 2}, 0, 0, "Kad se prate oba oka"),
        ([False] * 5, [False] * 3, set(), 2, 1, "ponovite kalibraciju"),
        ([True] * 5, [], set(), 0, 0, "Još provjerite izbor"),
        ([True] * 5, [True, False], set(), 2, 1, "Još provjerite izbor"),
        ([True] * 5, [True, False, True], {0, 2}, 2, 1, "dovoljno podataka"),
        ([True] * 5, [True, False, True], {0, 1, 2}, 2, 1, "Prekidi praćenja"),
        ([True] * 5, [True, False, True], {0, 1, 2}, 0, 1, "pogrešna dugmad"),
        ([True] * 5, [True] * 3, set(), 2, 1, "pogrešna dugmad"),
        ([True] * 5, [False] * 3, {0, 1, 2}, 0, 0, "nisu odabrana na vrijeme"),
        ([True] * 5, [True] * 3, set(), 0, 0, "govornu tastaturu"),
        ([True] * 5, [True] * 3, set(), 2, 0, "Ako se izbor često poništava"),
    ],
)
def test_result_advice_prioritizes_observed_problems(
    precision, selected, tracked, losses, wrong, expected
):
    results = [
        FixationResult(str(index), 90, 0.9, 12, 8, near) for index, near in enumerate(precision)
    ]
    assert expected in result_advice(
        results,
        trial_results=selected,
        tracked_targets=tracked,
        losses=losses,
        wrong_selections=wrong,
    )
