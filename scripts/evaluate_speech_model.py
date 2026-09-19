"""Reproduce the frozen grouped-keyboard comparison without gaze hardware."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gaze_mouse.suggestion_model import (
    MODEL_METADATA_PATH,
    MODEL_PATH,
    WordModel,
    load_model,
    load_model_from_paths,
)
from gaze_mouse.suggestion_text import START, insert_word, words

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "speech_suggestions"


def letters(word: str) -> list[str]:
    result = []
    index = 0
    while index < len(word):
        size = 2 if word[index : index + 2].upper() in {"DŽ", "LJ", "NJ"} else 1
        result.append(word[index : index + size])
        index += size
    return result


def simulate(text: str, model: WordModel | None, *, contextual: bool = True) -> dict:
    text = text.upper()
    composed = ""
    activations = entered = selections = departures = hits = queries = 0
    prediction = dict.fromkeys(
        (
            "sentence_start_queries",
            "sentence_start_top_one_hits",
            "sentence_start_top_five_hits",
            "next_word_queries",
            "next_word_top_one_hits",
            "next_word_top_five_hits",
            "completion_queries",
            "completion_top_one_hits",
            "completion_top_five_hits",
            "completion_selections",
            "prediction_selections",
        ),
        0,
    )
    durations = []
    last_slot = None
    automatic_space = False
    offset = 0

    def separator(value: str) -> None:
        nonlocal composed, activations, automatic_space, last_slot
        if automatic_space:
            if value.startswith(" "):
                value = value[1:]
            elif value and value[0] in ".,?!":
                composed = composed[:-1]
            elif not value:
                composed = composed[:-1]
                activations += 1
            automatic_space = False
        for character in value:
            if character == " ":
                activations += 1
            elif character in ".?":
                activations += 3
            else:
                raise ValueError(f"Unsupported baseline symbol: {character!r}")
            composed += character
            last_slot = None

    for token in words(text):
        separator(text[offset : token.start])
        target = token.text.upper()
        units = letters(target)
        has_space = token.end < len(text) and text[token.end] == " "
        for index in range(len(units) + 1):
            candidates = []
            if model is not None:
                started = time.perf_counter()
                candidates = model.predict(composed, contextual=contextual)
                durations.append((time.perf_counter() - started) * 1000)
                queries += 1
                hits += target in candidates
                kind = (
                    "completion"
                    if index
                    else ("sentence_start" if token.context == (START,) else "next_word")
                )
                prediction[f"{kind}_queries"] += 1
                prediction[f"{kind}_top_one_hits"] += bool(candidates and candidates[0] == target)
                prediction[f"{kind}_top_five_hits"] += target in candidates
            if target in candidates and 2 * (len(units) - index) + int(has_space) > 1:
                slot = candidates.index(target)
                departures += last_slot == slot
                composed = insert_word(composed, target)
                automatic_space = True
                activations += 1
                selections += 1
                prediction["completion_selections" if index else "prediction_selections"] += 1
                last_slot = slot
                break
            if index < len(units):
                composed += units[index]
                activations += 2
                entered += 1
                last_slot = None
        offset = token.end
    separator(text[offset:])
    if composed != text:
        raise AssertionError(f"Simulation did not reproduce its target: {composed!r} != {text!r}")
    return {
        "activations": activations,
        "letters": entered,
        "suggestion_selections": selections,
        "same_slot_departures": departures,
        "top_five_hits": hits,
        "queries": queries,
        "corrections": 0,
        "undo": 0,
        **prediction,
        "durations_ms": durations,
    }


def evaluate(
    dataset: str,
    *,
    model_path: Path = MODEL_PATH,
    metadata_path: Path = MODEL_METADATA_PATH,
    cases_path: Path | None = None,
    expected_sha256: str | None = None,
) -> dict:
    if cases_path is None:
        frozen = json.loads((FIXTURES / "frozen.json").read_text())
        for name, digest in frozen["sha256"].items():
            if hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() != digest:
                raise ValueError(f"Frozen evaluation file changed: {name}")
        cases_path = FIXTURES / f"{dataset}.tsv"
        expected_sha256 = frozen["sha256"][cases_path.name]
    elif not expected_sha256:
        raise ValueError("External messages require their previously frozen SHA-256")
    else:
        dataset = "external"
    digest = hashlib.sha256(cases_path.read_bytes()).hexdigest()
    if digest != expected_sha256:
        raise ValueError("Evaluation messages do not match their frozen SHA-256")
    with cases_path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if reader.fieldnames != ["id", "category", "text"]:
            raise ValueError("Evaluation messages need id, category, and text columns")
        cases = list(reader)
    identifiers = set()
    for case in cases:
        if (
            None in case
            or not all((case.get(key) or "").strip() for key in ("id", "category", "text"))
            or case["id"] in identifiers
            or not words(case["text"])
        ):
            raise ValueError(f"Invalid or duplicate evaluation row: {case!r}")
        identifiers.add(case["id"])
    if not cases:
        raise ValueError("Evaluation messages must not be empty")
    started = time.perf_counter()
    if model_path == MODEL_PATH and metadata_path == MODEL_METADATA_PATH:
        model = load_model()
    else:
        model = load_model_from_paths(model_path, metadata_path)
    loading_ms = (time.perf_counter() - started) * 1000
    results = []
    totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    categories: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    timings: dict[str, list[float]] = defaultdict(list)
    miss_totals: Counter[str] = Counter()
    for case in cases:
        row = {"id": case["id"], "category": case["category"]}
        for name, engine, contextual in (
            ("keyboard", None, False),
            ("frequency", model, False),
            ("contextual", model, True),
        ):
            outcome = simulate(case["text"], engine, contextual=contextual)
            timings[name].extend(outcome.pop("durations_ms"))
            row[name] = outcome
            for key, value in outcome.items():
                totals[name][key] += value
            categories[case["category"]][name] += outcome["activations"]
        row["misses"] = diagnose(model, case["text"])
        miss_totals.update(miss["reason"] for miss in row["misses"])
        results.append(row)
    for name in ("frequency", "contextual"):
        totals[name]["activation_reduction_percent"] = round(
            100 * (1 - totals[name]["activations"] / totals["keyboard"]["activations"]), 2
        )
        for kind in ("sentence_start", "next_word", "completion"):
            count = totals[name][f"{kind}_queries"]
            for top in ("one", "five"):
                totals[name][f"{kind}_top_{top}_percent"] = (
                    round(100 * totals[name][f"{kind}_top_{top}_hits"] / count, 2) if count else 0.0
                )
    for values in categories.values():
        values["contextual_reduction_percent"] = round(
            100 * (1 - values["contextual"] / values["keyboard"]), 2
        )
    return {
        "dataset": dataset,
        "messages": len(cases),
        "dataset_sha256": digest,
        "independence": "Not established by this script; external authorship and a preselected model are required.",
        "model": json.loads(metadata_path.read_text(encoding="utf-8")),
        "environment": {"platform": platform.platform(), "python": platform.python_version()},
        "profile": "empty per message",
        "assumption": "ideal exact beneficial selection; no intentional mistakes",
        "ranking": {
            "method": "adaptive context interpolation",
            "context_discount": model.context_discount,
            "implementation_sha256": hashlib.sha256(
                (MODEL_PATH.parents[1] / "suggestion_model.py").read_bytes()
            ).hexdigest(),
            "tokenizer_sha256": hashlib.sha256(
                (MODEL_PATH.parents[1] / "suggestion_text.py").read_bytes()
            ).hexdigest(),
            "evaluator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "metric_notes": {
            "next_word": "One query before typing each non-sentence-initial word; exact inflection required.",
            "sentence_start": "One query before typing each sentence-initial word, reported separately.",
            "completion": "Queries after typing at least one letter, along the ideal selection path; not independent trials.",
            "heldout": "The original held-out set is now a regression set after repeated reviews; fresh independent validation remains pending.",
        },
        "loading_ms": round(loading_ms, 2),
        "latency": {
            name: {
                "mean_ms": round(statistics.mean(values), 2),
                "p95_ms": round(sorted(values)[int(0.95 * (len(values) - 1))], 2),
                "max_ms": round(max(values), 2),
            }
            for name, values in timings.items()
            if values
        },
        "totals": dict(totals),
        "categories": dict(categories),
        "miss_reasons": dict(miss_totals),
        "cases": results,
    }


def diagnose(model: WordModel, text: str) -> list[dict]:
    """Explain exact-word misses before typing, separately from completion trials."""
    misses = []
    for token in words(text):
        candidates = model.predict(text[: token.start])
        if token.text.upper() in candidates:
            continue
        has_context = any(
            token.text in model.contexts.get(token.context[-size:], {})
            for size in range(1, len(token.context) + 1)
        )
        if token.text not in model.vocabulary:
            reason = "missing_vocabulary"
        elif not has_context:
            reason = "missing_context"
        else:
            reason = "ranked_below_five"
        misses.append(
            {
                "target": token.text.upper(),
                "context": list(token.context),
                "kind": "sentence_start" if token.context == (START,) else "next_word",
                "reason": reason,
                "candidates": candidates,
            }
        )
    return misses


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    dataset = parser.add_mutually_exclusive_group()
    dataset.add_argument("--dataset", choices=("development", "heldout"), default="development")
    dataset.add_argument("--cases", type=Path, help="Separately authored TSV messages")
    parser.add_argument(
        "--expected-sha256", help="Hash frozen before selecting the candidate model"
    )
    parser.add_argument("--model", type=Path, default=MODEL_PATH)
    parser.add_argument("--metadata", type=Path, default=MODEL_METADATA_PATH)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.expected_sha256 and args.cases is None:
        parser.error("--expected-sha256 requires --cases")
    result = evaluate(
        args.dataset,
        model_path=args.model,
        metadata_path=args.metadata,
        cases_path=args.cases,
        expected_sha256=args.expected_sha256,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("dataset", "messages", "loading_ms", "latency", "totals", "categories")
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
