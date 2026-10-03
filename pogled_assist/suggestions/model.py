"""Offline word prediction using a sorted prefix index and short word contexts."""

from __future__ import annotations

import gzip
import hashlib
import json
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from functools import lru_cache
from heapq import nsmallest
from pathlib import Path

from .text import START, index_key, prefix_pattern, query, valid_word

MODEL_VERSION = 1
MODEL_PATH = Path(__file__).resolve().parents[1] / "assets" / "bosnian-model.json.gz"
MODEL_METADATA_PATH = MODEL_PATH.with_name("bosnian-model.meta.json")
ISLAMIC_MODEL_PATH = MODEL_PATH.with_name("bosnian-islamic-model.json.gz")
ISLAMIC_MODEL_METADATA_PATH = MODEL_PATH.with_name("bosnian-islamic-model.meta.json")


class WordModel:
    context_discount = 10.0
    personal_context_discount = 2.5
    personal_context_blend = 2.0

    def __init__(
        self,
        counts: Mapping[tuple[str, ...], int] | Iterable[tuple[tuple[str, ...], int]],
    ) -> None:
        rows = counts.items() if isinstance(counts, Mapping) else counts
        self.contexts: dict[tuple[str, ...], dict[str, int]] = defaultdict(dict)
        for key, count in rows:
            if count <= 0:
                continue
            self.contexts[key[:-1]][key[-1]] = count
        self.vocabulary = self.contexts[()].keys()
        self.index = sorted((index_key(word), word) for word in self.vocabulary)
        self.keys = [item[0] for item in self.index]
        self.totals = {context: sum(values.values()) for context, values in self.contexts.items()}
        self.unigram_ranking = sorted(
            self.vocabulary, key=lambda word: (-self.contexts[()].get(word, 0), word)
        )
        self._fallback_cache: tuple[WordModel, int, list[str]] | None = None

    def matching(self, prefix: str) -> set[str]:
        key = index_key(prefix)
        begin, end = bisect_left(self.keys, key), bisect_right(self.keys, key + "\U0010ffff")
        pattern = prefix_pattern(prefix)
        return {word for _key, word in self.index[begin:end] if pattern.match(word)}

    def _fallback(self, personal: WordModel, limit: int) -> list[str]:
        if not personal.vocabulary:
            return self.unigram_ranking[:limit]
        if self._fallback_cache is not None:
            previous, previous_limit, result = self._fallback_cache
            if previous is personal and previous_limit == limit:
                return result
        base, own = self.contexts[()], personal.contexts[()]
        total, own_total = max(1, self.totals.get((), 0)), personal.totals[()]
        boost = self._personal_weight((), own_total)
        # Context-free candidates need the blended ranking: a word can rank
        # highly in the blend without being in either source's top five.
        result = nsmallest(
            limit,
            base.keys() | own.keys(),
            key=lambda word: (
                -((1 - boost) * base.get(word, 0) / total + boost * own.get(word, 0) / own_total),
                word,
            ),
        )
        self._fallback_cache = personal, limit, result
        return result

    def predict(
        self,
        text: str,
        personal: Counter[tuple[str, ...]] | WordModel | None = None,
        *,
        limit: int = 5,
        contextual: bool = True,
    ) -> list[str]:
        if limit <= 0:
            return []
        request = query(text)
        if request is None:
            return []
        prefix, context, _start = request
        learned = _personal_model(personal)
        contexts = _contexts(context) if contextual else [()]
        if prefix:
            candidates = self.matching(prefix) | learned.matching(prefix)
        else:
            candidates = self._next_word_candidates(contexts, learned, limit)
        if not candidates:
            return []
        weighted_rows = self._weighted_rows(contexts, learned)

        def score(word: str) -> tuple[float, str]:
            value = sum(
                weight
                * ((1 - boost) * base.get(word, 0) / total + boost * own.get(word, 0) / own_total)
                for base, own, total, own_total, boost, weight in weighted_rows
            )
            return -value, word

        return [word.upper() for word in nsmallest(limit, candidates, key=score)]

    def _next_word_candidates(
        self, contexts: list[tuple[str, ...]], learned: WordModel, limit: int
    ) -> set[str]:
        candidates = set(self._fallback(learned, limit))
        for preceding in contexts[1:]:
            candidates.update(self.contexts.get(preceding, {}))
            candidates.update(learned.contexts.get(preceding, {}))
        return candidates

    def _weighted_rows(
        self, contexts: list[tuple[str, ...]], learned: WordModel
    ) -> list[tuple[dict[str, int], dict[str, int], int, int, float, float]]:
        rows = []
        evidence = []
        for preceding in contexts:
            base = self.contexts.get(preceding, {})
            own = learned.contexts.get(preceding, {})
            total = self.totals.get(preceding, 0)
            own_total = learned.totals.get(preceding, 0)
            if not total and not own_total:
                continue
            distinct = len(base) + sum(word not in base for word in own)
            evidence.append((preceding, total, own_total, distinct))
            own_weight = self._personal_weight(preceding, own_total)
            rows.append((base, own, max(1, total), max(1, own_total), own_weight))
        weights = self._context_weights(evidence)
        return [(*row, weight) for row, weight in zip(rows, weights, strict=True)]

    def _personal_weight(self, preceding: tuple[str, ...], own_total: int) -> float:
        if preceding:
            return min(0.8, own_total / (own_total + self.personal_context_blend))
        return min(0.25, own_total / (own_total + 40))

    def _context_weights(
        self, evidence: list[tuple[tuple[str, ...], int, int, int]]
    ) -> list[float]:
        weights: list[float] = []
        for _context, total, own_total, distinct in evidence:
            # Sparse contexts retain support from shorter contexts. Keep a floor
            # for fallback words, while repeated personal phrasing earns trust
            # faster than anonymous corpus text.
            base_confidence = total / (total + self.context_discount * distinct)
            own_confidence = own_total / (own_total + self.personal_context_discount * distinct)
            confidence = min(
                0.9,
                1 - (1 - base_confidence) * (1 - own_confidence),
            )
            if not weights:
                weights.append(1.0)
            else:
                weights = [weight * (1 - confidence) for weight in weights]
                weights.append(confidence)
        return weights


def load_counts_from_paths(model_path: Path, metadata_path: Path) -> Counter[tuple[str, ...]]:
    """Load and validate a prepared model from explicit paths."""
    data = model_path.read_bytes()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if hashlib.sha256(data).hexdigest() != metadata["model_sha256"]:
        raise ValueError("Prediction model checksum mismatch")
    payload = json.loads(gzip.decompress(data))
    if payload.get("version") != MODEL_VERSION:
        raise ValueError("Unsupported prediction model version")
    rows = payload.get("counts")
    if not rows:
        raise ValueError("Empty prediction model")
    return Counter(dict(_validated_counts(rows)))


def load_model_from_paths(model_path: Path, metadata_path: Path) -> WordModel:
    return WordModel(load_counts_from_paths(model_path, metadata_path))


def _contexts(preceding: tuple[str, ...]) -> list[tuple[str, ...]]:
    return [(), *(preceding[-size:] for size in range(1, len(preceding) + 1))]


def _personal_model(personal: Counter[tuple[str, ...]] | WordModel | None) -> WordModel:
    if isinstance(personal, WordModel):
        return personal
    return WordModel(personal or ())


def _validated_counts(rows: Iterable[tuple[str, int]]) -> Iterable[tuple[tuple[str, ...], int]]:
    for key, count in rows:
        parts = tuple(key.split(" "))
        if not _valid_count(count):
            raise ValueError("Invalid prediction count")
        if not _valid_key(parts):
            raise ValueError("Invalid prediction word")
        yield parts, count


def _valid_count(count: object) -> bool:
    return isinstance(count, int) and count > 0


def _valid_key(parts: tuple[str, ...]) -> bool:
    words = parts[1:] if len(parts) > 1 and parts[0] == START else parts
    return 1 <= len(parts) <= 3 and all(valid_word(word) for word in words)


@lru_cache(maxsize=1)
def load_model() -> WordModel:
    counts = load_counts_from_paths(MODEL_PATH, MODEL_METADATA_PATH)
    counts.update(load_counts_from_paths(ISLAMIC_MODEL_PATH, ISLAMIC_MODEL_METADATA_PATH))
    return WordModel(counts)
