"""Measure synthetic personal learning and indexed-profile query cost offline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import statistics
import sys
import time
from collections import Counter
from itertools import islice
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pogled_assist.suggestions.learning import LearningStore
from pogled_assist.suggestions.model import (
    ISLAMIC_MODEL_PATH,
    MODEL_METADATA_PATH,
    MODEL_PATH,
    WordModel,
    load_model,
    load_model_from_paths,
)

SCENARIOS = Path(__file__).resolve().parents[2] / "language" / "bs" / "evaluation" / "learning.tsv"


def rank(candidates: list[str], target: str) -> int | None:
    return candidates.index(target) + 1 if target in candidates else None


def evaluate_learning(model: WordModel, scenarios: Path) -> list[dict]:
    return [_evaluate_case(model, case) for case in _load_scenarios(scenarios)]


def _load_scenarios(path: Path) -> list[dict]:
    columns = ["id", "learn", "query", "target", "control", "control_target"]
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if reader.fieldnames != columns:
            raise ValueError("Unexpected learning scenario columns")
        cases = list(reader)
    if not cases:
        raise ValueError("Learning scenarios must not be empty")
    identifiers: set[str] = set()
    for case in cases:
        if not _valid_scenario(case, identifiers):
            raise ValueError(f"Invalid learning scenario: {case!r}")
        identifiers.add(case["id"])
    return cases


def _valid_scenario(case: dict, identifiers: set[str]) -> bool:
    if None in case or any(value is None for value in case.values()):
        return False
    required = ("id", "learn", "target", "control_target")
    return all(case[key].strip() for key in required) and case["id"] not in identifiers


def _evaluate_case(model: WordModel, case: dict) -> dict:
    store = LearningStore()
    checkpoints = []
    baseline = model.predict(case["control"])
    for uses in range(11):
        if uses in (0, 1, 3, 10):
            profile = WordModel(store.snapshot())
            checkpoints.append({"uses": uses, **_checkpoint(model, case, profile, baseline)})
        if uses < 10:
            store.learn_text(case["learn"])
    return {"id": case["id"], "checkpoints": checkpoints}


def _checkpoint(model: WordModel, case: dict, profile: WordModel, baseline: list[str]) -> dict:
    candidates = model.predict(case["query"], profile)
    control = model.predict(case["control"], profile)
    target = case["control_target"].upper()
    return {
        "candidates": candidates,
        "target_rank": rank(candidates, case["target"].upper()),
        "control_candidates": control,
        "control_rank": rank(control, target),
        "control_lost_hit": target in baseline and target not in control,
    }


def assess_learning(results: list[dict]) -> dict:
    """Apply the shared usefulness checks to every synthetic scenario."""

    def checkpoint(case: dict, uses: int) -> dict:
        return next(item for item in case["checkpoints"] if item["uses"] == uses)

    missing_after_one = [
        case["id"] for case in results if checkpoint(case, 1)["target_rank"] is None
    ]
    not_first_after_three = [
        case["id"] for case in results if checkpoint(case, 3)["target_rank"] != 1
    ]
    control_losses = [
        case["id"]
        for case in results
        if any(item["control_lost_hit"] for item in case["checkpoints"])
    ]
    return {
        "criteria": {
            "target_visible_after_one_use": not missing_after_one,
            "target_first_after_three_uses": not not_first_after_three,
            "unrelated_top_five_hit_preserved": not control_losses,
        },
        "failures": {
            "not_visible_after_one_use": missing_after_one,
            "not_first_after_three_uses": not_first_after_three,
            "control_hit_lost": control_losses,
        },
        "passed": not (missing_after_one or not_first_after_three or control_losses),
    }


def stress_profile(model: WordModel, size: int) -> dict:
    counts = Counter(islice(_profile_keys(model), max(0, size)))
    if len(counts) != size:
        raise ValueError(f"Requested {size} entries but the base only supplies {len(counts)}")
    started = time.perf_counter()
    profile = WordModel(counts)
    indexing_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    model.predict("TREBA MI ", profile)
    first_query_ms = (time.perf_counter() - started) * 1000
    durations = []
    for _ in range(20):
        for text in ("TREBA MI ", "ŽELIM ", "S", "V"):
            started = time.perf_counter()
            model.predict(text, profile)
            durations.append((time.perf_counter() - started) * 1000)
    return {
        "entries": size,
        "words": len(profile.vocabulary),
        "indexing_ms": round(indexing_ms, 2),
        "first_query_ms": round(first_query_ms, 2),
        "mean_ms": round(statistics.mean(durations), 2),
        "p95_ms": round(sorted(durations)[int(0.95 * (len(durations) - 1))], 2),
    }


def _profile_keys(model: WordModel):
    for context, row in sorted(model.contexts.items(), key=lambda item: (len(item[0]), item[0])):
        for word in sorted(row):
            yield (*context, word)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=MODEL_PATH)
    parser.add_argument("--metadata", type=Path, default=MODEL_METADATA_PATH)
    parser.add_argument("--scenarios", type=Path, default=SCENARIOS)
    parser.add_argument("--stress-sizes", type=int, nargs="*", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if any(size < 0 for size in args.stress_sizes):
        parser.error("Profile sizes must not be negative")
    bundled = args.model == MODEL_PATH and args.metadata == MODEL_METADATA_PATH
    model = load_model() if bundled else load_model_from_paths(args.model, args.metadata)
    scenarios = evaluate_learning(model, args.scenarios)
    result = {
        "model_sha256": hashlib.sha256(args.model.read_bytes()).hexdigest(),
        "islamic_model_sha256": (
            hashlib.sha256(ISLAMIC_MODEL_PATH.read_bytes()).hexdigest() if bundled else None
        ),
        "scenarios_sha256": hashlib.sha256(args.scenarios.read_bytes()).hexdigest(),
        "implementation_sha256": hashlib.sha256(
            (MODEL_PATH.parents[1] / "suggestions" / "model.py").read_bytes()
        ).hexdigest(),
        "ranking": {
            "context_discount": model.context_discount,
            "personal_context_discount": model.personal_context_discount,
            "personal_context_blend": model.personal_context_blend,
        },
        "environment": {"platform": platform.platform(), "python": platform.python_version()},
        "scope": "Synthetic development scenarios, not blind validation or Windows UI latency. Each use is a separate submitted message.",
        "quality": assess_learning(scenarios),
        "scenarios": scenarios,
        "stress": [stress_profile(model, size) for size in args.stress_sizes],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2))
    if not result["quality"]["passed"]:
        raise SystemExit("Personal-learning quality checks failed")


if __name__ == "__main__":
    main()
