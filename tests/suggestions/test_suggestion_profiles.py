from collections import Counter

from pogled_assist.suggestions.learning import LearningStore
from pogled_assist.suggestions.model import WordModel, load_model
from scripts.speech_suggestions.evaluate_speech_learning import (
    SCENARIOS,
    assess_learning,
    evaluate_learning,
)
from scripts.speech_suggestions.evaluate_speech_model import diagnose


def test_indexed_profile_keeps_a_word_that_only_the_blend_ranks_first():
    base = Counter({(word,): 100 for word in ("voda", "kafa", "sok", "mlijeko", "jogurt")})
    own = Counter({(word,): 100 for word in ("hljeb", "sir", "med", "voće", "supa")})
    base[("čaj",)] = own[("čaj",)] = 90
    model = WordModel(base)
    profile = WordModel(own)

    assert "čaj" not in model.unigram_ranking[:5]
    assert "čaj" not in profile.unigram_ranking[:5]
    assert model.predict("ŽELIM ", profile)[0] == "ČAJ"
    assert model.predict("ŽELIM ", own) == model.predict("ŽELIM ", profile)


def test_context_candidates_are_not_pruned_by_personal_word_popularity():
    model = WordModel({("kafa",): 1000})
    profile = WordModel({("kafa",): 1000, ("zvrković",): 1, ("pozovi", "zvrković"): 10})

    assert model.predict("POZOVI ", profile)[0] == "ZVRKOVIĆ"
    assert model.predict("ZVR", profile) == ["ZVRKOVIĆ"]
    assert model.predict("POZOVI ", profile, limit=0) == []


def test_profile_snapshot_changes_after_forgetting_and_relearning():
    store = LearningStore()
    store.learn_text("Zvrković")
    revision, counts = store.snapshot_if_changed(-1)
    original = WordModel(counts)
    assert store.snapshot_if_changed(revision) is None

    store.forget("Zvrković")
    forgotten_revision, forgotten = store.snapshot_if_changed(revision)
    assert WordModel({}).predict("ZVR", WordModel(forgotten)) == []
    assert WordModel({}).predict("ZVR", original) == ["ZVRKOVIĆ"]

    store.learn_text("Zvrković")
    _revision, learned = store.snapshot_if_changed(forgotten_revision)
    assert WordModel({}).predict("ZVR", WordModel(learned)) == ["ZVRKOVIĆ"]


def test_storage_retry_invalidates_a_previously_indexed_profile(tmp_path):
    path = tmp_path / "learning.json"
    path.write_text("{", encoding="utf-8")
    store = LearningStore(path)
    revision, _counts = store.snapshot_if_changed(-1)
    path.write_text('{"version":1,"counts":[["čaj",3]]}', encoding="utf-8")

    assert store.save(retry=True)
    _revision, counts = store.snapshot_if_changed(revision)
    assert counts[("čaj",)] == 3


def test_diagnostics_distinguish_missing_words_context_and_low_rank():
    counts = Counter(
        {(word,): 10 for word in ("voda", "kafa", "čaj", "hljeb", "sok", "sir", "med")}
    )
    counts.update({("želim", word): 100 for word in ("voda", "kafa", "čaj", "hljeb", "sok")})
    counts[("želim", "sir")] = 1
    model = WordModel(counts)

    assert diagnose(model, "Želim zvrkovića")[-1]["reason"] == "missing_vocabulary"
    assert diagnose(model, "Želim med")[-1]["reason"] == "missing_context"
    assert diagnose(model, "Želim sir")[-1]["reason"] == "ranked_below_five"


def test_learning_scenarios_meet_personalization_contract():
    results = evaluate_learning(load_model(), SCENARIOS)

    assert len(results) >= 12
    assert assess_learning(results)["passed"]
