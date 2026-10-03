from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.speech_suggestions import compare_speech_ranking as ranking
from scripts.speech_suggestions import evaluate_speech_learning as learning


class LearningModel:
    def predict(self, text, profile=None):
        if text == "dobar ":
            return ["DAN"]
        if profile is not None and "pomoć" in profile.vocabulary:
            return ["POMOĆ"]
        return []


def test_learning_checkpoints_measure_before_each_requested_use(tmp_path):
    scenarios = tmp_path / "scenarios.tsv"
    scenarios.write_text(
        "id\tlearn\tquery\ttarget\tcontrol\tcontrol_target\n"
        "one\tželim pomoć\tželim \tpomoć\tdobar \tdan\n",
        encoding="utf-8",
    )

    result = learning.evaluate_learning(LearningModel(), scenarios)
    checkpoints = result[0]["checkpoints"]

    assert result[0]["id"] == "one"
    assert [item["uses"] for item in checkpoints] == [0, 1, 3, 10]
    assert [item["target_rank"] for item in checkpoints] == [None, 1, 1, 1]
    assert [item["control_lost_hit"] for item in checkpoints] == [False] * 4
    assert learning.assess_learning(result)["passed"]


@pytest.mark.parametrize("invalid", ["duplicate", "missing", "extra"])
def test_learning_scenarios_reject_invalid_rows(tmp_path, invalid):
    header = "id\tlearn\tquery\ttarget\tcontrol\tcontrol_target\n"
    row = "one\tželim pomoć\tželim \tpomoć\tdobar \tdan\n"
    contents = {
        "duplicate": row + row,
        "missing": "one\tželim pomoć\n",
        "extra": row.rstrip("\n") + "\textra\n",
    }
    path = tmp_path / "scenarios.tsv"
    path.write_text(header + contents[invalid], encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid learning scenario"):
        learning.evaluate_learning(LearningModel(), path)


def _ranking_result(**changes):
    return {
        "ranking": "fixed",
        "context_discount": None,
        "activations": 100,
        "next_word_top_five_hits": 10,
        "next_word_top_one_hits": 5,
        "latency": {"p95_ms": 40},
        "sparse_context": {"passed": True},
        **changes,
    }


@pytest.mark.parametrize(
    "failure",
    [
        {"latency": {"p95_ms": 51}},
        {"activations": 101},
        {"next_word_top_five_hits": 9},
        {"sparse_context": {"passed": False}},
    ],
)
def test_ranking_rejects_each_quality_or_latency_regression(failure):
    control = _ranking_result()
    candidate = _ranking_result(ranking="adaptive", context_discount=40, activations=90)
    candidate.update(failure)

    assert ranking._recommend([control, candidate]) is control


def test_ranking_ties_prefer_fixed_then_larger_adaptive_discount():
    control = _ranking_result()
    tied = _ranking_result(ranking="adaptive", context_discount=40)
    assert ranking._recommend([control, tied]) is control

    small = _ranking_result(ranking="adaptive", context_discount=2, activations=90)
    large = _ranking_result(ranking="adaptive", context_discount=40, activations=90)
    assert ranking._recommend([control, small, large]) is large


def test_ranking_evaluates_each_message_and_combines_timings(monkeypatch):
    model = SimpleNamespace(context_discount=0)
    seen = []

    def simulate(text, candidate):
        seen.append((text, candidate.context_discount))
        return {"activations": 2, "next_word_top_five_hits": 1, "durations_ms": [1, 3]}

    monkeypatch.setattr(ranking, "simulate", simulate)
    monkeypatch.setattr(ranking, "sparse_context_check", lambda _model: {"passed": True})
    result = ranking._evaluate_candidate("adaptive", model, 40, [{"text": "a"}, {"text": "b"}])

    assert seen == [("a", 40), ("b", 40)]
    assert result["activations"] == 4
    assert result["next_word_top_five_hits"] == 2
    assert result["latency"] == {"mean_ms": 2, "p95_ms": 3}
