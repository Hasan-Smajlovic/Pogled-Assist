"""Compare context weighting on development messages without reading held-out text."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import statistics
import sys
from collections import Counter
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pogled_assist.suggestions.model import (
    ISLAMIC_MODEL_PATH,
    MODEL_METADATA_PATH,
    MODEL_PATH,
    WordModel,
    load_model,
    load_model_from_paths,
)
from scripts.speech_suggestions.evaluate_speech_model import FIXTURES, fixture_sha256, simulate


class FixedWeightModel(WordModel):
    """Experimental control matching the original context weighting."""

    def _context_weights(self, evidence):
        return [
            (0.12, 0.33, 0.55)[len(context)] for context, _total, _own_total, _distinct in evidence
        ]


def sparse_context_check(model: WordModel) -> dict:
    """Check that weak context backs off and repeated context takes over."""
    counts = {
        ("je",): 100_000,
        ("vode",): 100,
        ("mi", "je"): 1_000,
        ("treba", "mi", "vode"): 3,
    }

    def predict(trigram_count: int) -> str:
        counts[("treba", "mi", "vode")] = trigram_count
        candidate = type(model)(counts)
        candidate.context_discount = model.context_discount
        return candidate.predict("TREBA MI ")[0]

    sparse = predict(3)
    supported = predict(200)
    return {
        "sparse_result": sparse,
        "supported_result": supported,
        "passed": sparse == "JE" and supported == "VODE",
    }


def compare(model_path: Path, metadata_path: Path, discounts: list[float]) -> dict:
    source = FIXTURES / "development.tsv"
    digest = fixture_sha256(source)
    frozen = json.loads((FIXTURES / "frozen.json").read_text())
    if digest != frozen["sha256"][source.name]:
        raise ValueError("Frozen development messages changed")
    with source.open(encoding="utf-8") as stream:
        cases = list(csv.DictReader(stream, delimiter="\t"))
    bundled = model_path == MODEL_PATH and metadata_path == MODEL_METADATA_PATH
    model = load_model() if bundled else load_model_from_paths(model_path, metadata_path)
    control = FixedWeightModel(
        ((*context, word), count)
        for context, rows in model.contexts.items()
        for word, count in rows.items()
    )
    candidates = [("fixed", control, None), *[("adaptive", model, value) for value in discounts]]
    results = []
    for name, candidate, discount in candidates:
        if discount is not None:
            candidate.context_discount = discount
        totals = Counter()
        durations = []
        for case in cases:
            result = simulate(case["text"], candidate)
            durations.extend(result.pop("durations_ms"))
            totals.update(result)
        results.append(
            {
                "ranking": name,
                "context_discount": discount,
                "activations": totals["activations"],
                "next_word_queries": totals["next_word_queries"],
                "next_word_top_one_hits": totals["next_word_top_one_hits"],
                "next_word_top_five_hits": totals["next_word_top_five_hits"],
                "completion_selections": totals["completion_selections"],
                "sparse_context": sparse_context_check(candidate),
                "latency": {
                    "mean_ms": round(statistics.mean(durations), 2),
                    "p95_ms": round(sorted(durations)[int(0.95 * (len(durations) - 1))], 2),
                },
            }
        )
    control_result = results[0]
    eligible = [
        row
        for row in results
        if row["latency"]["p95_ms"] <= 50
        and row["activations"] <= control_result["activations"]
        and row["next_word_top_five_hits"] >= control_result["next_word_top_five_hits"]
        and row["sparse_context"]["passed"]
    ]
    if not eligible:
        raise ValueError("No ranking meets the latency and quality requirements")
    recommended = min(
        eligible,
        key=lambda row: (
            row["activations"],
            -row["next_word_top_five_hits"],
            -row["next_word_top_one_hits"],
            row["ranking"] != "fixed",
            -(row["context_discount"] or 0),
        ),
    )
    return {
        "dataset": "development",
        "dataset_sha256": digest,
        "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "islamic_model_sha256": (
            hashlib.sha256(ISLAMIC_MODEL_PATH.read_bytes()).hexdigest() if bundled else None
        ),
        "implementation_sha256": hashlib.sha256(
            (MODEL_PATH.parents[1] / "suggestions" / "model.py").read_bytes()
        ).hexdigest(),
        "environment": {"platform": platform.platform(), "python": platform.python_version()},
        "selection_rule": (
            "p95 at most 50 ms, no regression from fixed weights in activations or next-word top-five hits, "
            "and sparse context must back off while repeated context takes over; "
            "then fewest activations, most next-word top-five and top-one hits; "
            "ties prefer fixed weights, otherwise the larger discount for more fallback on sparse contexts"
        ),
        "recommended": {key: recommended[key] for key in ("ranking", "context_discount")},
        "candidates": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=MODEL_PATH)
    parser.add_argument("--metadata", type=Path, default=MODEL_METADATA_PATH)
    parser.add_argument("--discounts", type=float, nargs="+", default=[2, 10, 40])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not all(0 < value < float("inf") for value in args.discounts):
        parser.error("Discounts must be finite and positive")
    result = compare(args.model, args.metadata, args.discounts)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
