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
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gaze_mouse.suggestion_learning import LearningStore
from gaze_mouse.suggestion_model import (
    MODEL_METADATA_PATH,
    MODEL_PATH,
    WordModel,
    load_model_from_paths,
)

SCENARIOS = Path(__file__).resolve().parents[1] / "language" / "bs" / "learning.tsv"


def rank(candidates: list[str], target: str) -> int | None:
    return candidates.index(target) + 1 if target in candidates else None


def evaluate_learning(model: WordModel, scenarios: Path) -> list[dict]:
    with scenarios.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if reader.fieldnames != ["id", "learn", "query", "target", "control", "control_target"]:
            raise ValueError("Unexpected learning scenario columns")
        cases = list(reader)
    if not cases:
        raise ValueError("Learning scenarios must not be empty")
    results = []
    identifiers = set()
    for case in cases:
        if (
            None in case
            or any(case.get(key) is None for key in reader.fieldnames)
            or not all(case[key].strip() for key in ("id", "learn", "target", "control_target"))
            or case["id"] in identifiers
        ):
            raise ValueError(f"Invalid learning scenario: {case!r}")
        identifiers.add(case["id"])
        store = LearningStore()
        checkpoints = []
        baseline = model.predict(case["control"])
        for uses in range(11):
            if uses in (0, 1, 3, 10):
                profile = WordModel(store.snapshot())
                candidates = model.predict(case["query"], profile)
                control = model.predict(case["control"], profile)
                checkpoints.append(
                    {
                        "uses": uses,
                        "candidates": candidates,
                        "target_rank": rank(candidates, case["target"].upper()),
                        "control_candidates": control,
                        "control_rank": rank(control, case["control_target"].upper()),
                        "control_lost_hit": case["control_target"].upper() in baseline
                        and case["control_target"].upper() not in control,
                    }
                )
            if uses < 10:
                store.learn_text(case["learn"])
        results.append({"id": case["id"], "checkpoints": checkpoints})
    return results


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
    counts = Counter()
    for context, row in sorted(model.contexts.items(), key=lambda item: (len(item[0]), item[0])):
        for word in sorted(row):
            if len(counts) >= size:
                break
            counts[(*context, word)] = 1
        if len(counts) >= size:
            break
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
    model = load_model_from_paths(args.model, args.metadata)
    scenarios = evaluate_learning(model, args.scenarios)
    result = {
        "model_sha256": hashlib.sha256(args.model.read_bytes()).hexdigest(),
        "scenarios_sha256": hashlib.sha256(args.scenarios.read_bytes()).hexdigest(),
        "implementation_sha256": hashlib.sha256(
            (MODEL_PATH.parents[1] / "suggestion_model.py").read_bytes()
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
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["quality"]["passed"]:
        raise SystemExit("Personal-learning quality checks failed")


if __name__ == "__main__":
    main()
