"""Build compact Bosnian suggestion models from verified language data."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pogled_assist.suggestions.text import START, spelling, valid_word, words

SOURCE_MD5 = "f92e72f4fe08362a1297f311ac20ad33"
SOURCE_URL = "https://www.clarin.si/repository/xmlui/bitstream/handle/11356/2079/CLASSLA-web.bs.2.0.jsonl.gz?isAllowed=y&sequence=11"
DEFAULT_VOCABULARY = 60_000
DEFAULT_SAMPLE_MODULUS = 20
DEFAULT_PER_DOMAIN_LIMIT = 240
DEFAULT_NEWS_LIMIT = 3_000
DEFAULT_SUPPLEMENT_MULTIPLIER = 40
DEFAULT_STARTER_MULTIPLIER = 200
MINIMUM_WORD_COUNT = 5
MINIMUM_NGRAM_COUNT = 3
PER_CONTEXT_LIMIT = 32
PER_NGRAM_ORDER_LIMIT = 160_000
GENRES = {
    "Forum",
    "Instruction",
    "Opinion/Argumentation",
    "Information/Explanation",
    "Prose/Lyrical",
    "News",
}
NOISE = {
    "www",
    "http",
    "https",
    "com",
    "org",
    "html",
    "cookie",
    "cookies",
    "javascript",
    "facebook",
    "instagram",
    "twitter",
    "copyright",
    "login",
    "newsletter",
    "the",
    "and",
    "with",
    "this",
    "that",
    "your",
    "you",
    "for",
    "from",
    "have",
    "has",
    "are",
    "was",
    "were",
}


@dataclass(frozen=True)
class PreparedCounts:
    counts: Counter[tuple[str, ...]]
    supplement_words: frozenset[str]
    source_md5: str
    source_sha256: str
    supplement_sha256: str
    starters_sha256: str
    sample: dict
    supplement: dict
    protected_ngrams: frozenset[tuple[str, ...]] = field(default_factory=frozenset)
    spelling_sha256: str = ""
    spelling_replacements: int = 0


@dataclass(frozen=True)
class ModelWeights:
    supplement_multiplier: int = DEFAULT_SUPPLEMENT_MULTIPLIER
    starter_multiplier: int = DEFAULT_STARTER_MULTIPLIER


@dataclass(frozen=True)
class PreparationOptions:
    sample_modulus: int = DEFAULT_SAMPLE_MODULUS
    per_domain_limit: int = DEFAULT_PER_DOMAIN_LIMIT
    news_limit: int = DEFAULT_NEWS_LIMIT
    weights: ModelWeights = field(default_factory=ModelWeights)

    def validate(self) -> None:
        if min(self.sample_modulus, self.per_domain_limit, self.news_limit) < 1:
            raise ValueError("Corpus sampling limits must be positive")
        if min(self.weights.supplement_multiplier, self.weights.starter_multiplier) < 1:
            raise ValueError("Conversation and starter multipliers must be positive")


@dataclass(frozen=True)
class BuildOptions:
    vocabulary: int = DEFAULT_VOCABULARY
    preparation: PreparationOptions = field(default_factory=PreparationOptions)


DEFAULT_WEIGHTS = ModelWeights()
DEFAULT_PREPARATION = PreparationOptions()
DEFAULT_BUILD = BuildOptions()


def metadata_path(model_path: Path) -> Path:
    suffix = ".json.gz"
    if not model_path.name.endswith(suffix):
        raise ValueError("Model output must end in .json.gz")
    return model_path.with_name(model_path.name[: -len(suffix)] + ".meta.json")


def load_supplement(path: Path) -> tuple[list[tuple[str, int, str]], dict]:
    """Read reviewed conversation rows and reject ambiguous training input."""
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if reader.fieldnames != ["category", "weight", "text"]:
            raise ValueError("Conversation supplement needs category, weight, and text columns")
        rows = []
        seen = set()
        categories: Counter[str] = Counter()
        weighted_rows: Counter[str] = Counter()
        for line_number, row in enumerate(reader, 2):
            text, weight, category = _supplement_row(row, line_number)
            _check_supplement_text(text, line_number, seen)
            rows.append((text, weight, category))
            categories[category] += 1
            weighted_rows[category] += weight
    if not rows:
        raise ValueError("Conversation supplement is empty")
    return rows, {
        "rows": len(rows),
        "categories": dict(sorted(categories.items())),
        "weighted_rows": dict(sorted(weighted_rows.items())),
    }


def _supplement_row(row: dict, line_number: int) -> tuple[str, int, str]:
    category = row["category"].strip()
    text = row["text"].strip()
    try:
        weight = int(row["weight"])
    except ValueError as error:
        raise ValueError(f"Invalid weight on supplement line {line_number}") from error
    if not _supplement_values_valid(category, text, weight):
        raise ValueError(f"Invalid supplement row on line {line_number}")
    return text, weight, category


def _supplement_values_valid(category: str, text: str, weight: int) -> bool:
    return bool(category and text and 1 <= weight <= 10)


def _check_supplement_text(text: str, line_number: int, seen: set[str]) -> None:
    normalized = " ".join(token.text for token in words(text))
    if not normalized:
        raise ValueError(f"Supplement line {line_number} contains no Bosnian words")
    if normalized in seen:
        raise ValueError(f"Duplicate supplement text on line {line_number}")
    seen.add(normalized)


def load_spelling(path: Path) -> dict[str, str]:
    """Only fold explicitly reviewed web spellings, never arbitrary diacritics."""
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if reader.fieldnames != ["variant", "word"]:
            raise ValueError("Spelling data needs variant and word columns")
        result = {}
        for line_number, row in enumerate(reader, 2):
            variant, word = _spelling_row(row, line_number, result)
            result[variant] = word
    if result.keys() & set(result.values()):
        raise ValueError("Spelling replacements must not form chains or cycles")
    return result


def _spelling_row(row: dict, line_number: int, seen: dict) -> tuple[str, str]:
    variant, word = row.get("variant"), row.get("word")
    if not _spelling_words_valid(row):
        raise ValueError(f"Invalid spelling row on line {line_number}")
    if variant == word or variant in seen:
        raise ValueError(f"Invalid spelling row on line {line_number}")
    return variant, word


def _spelling_words_valid(row: dict) -> bool:
    variant, word = row.get("variant"), row.get("word")
    if not _has_row_values(row, ("variant", "word")):
        return False
    return valid_word(variant) and valid_word(word)


def _has_row_values(row: dict, columns: tuple[str, ...]) -> bool:
    return None not in row and all(row.get(column) for column in columns)


def _source_hashes(source: Path) -> tuple[str, str]:
    md5, sha = hashlib.md5(), hashlib.sha256()
    with source.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            md5.update(block)
            sha.update(block)
    if md5.hexdigest() != SOURCE_MD5:
        raise ValueError("CLASSLA download does not match the published MD5")
    return md5.hexdigest(), sha.hexdigest()


def prepare_counts(
    source: Path,
    supplement: Path,
    *,
    options: PreparationOptions = DEFAULT_PREPARATION,
) -> PreparedCounts:
    options.validate()
    source_md5, source_sha256 = _source_hashes(source)
    conversation_rows, supplement_metadata = load_supplement(supplement)
    spelling_path = supplement.with_name("spelling.tsv")
    replacements = load_spelling(spelling_path)
    sample = _CorpusSample(options, replacements)
    sample.scan(source)
    supplement_words, protected_ngrams = _add_conversation(
        sample.counts, conversation_rows, options.weights.supplement_multiplier
    )
    starters_path = supplement.with_name("starters.tsv")
    starter_rows = _add_starters(
        sample.counts, starters_path, options.weights.starter_multiplier
    )
    supplement_words.update(starter_rows)
    return PreparedCounts(
        counts=sample.counts,
        supplement_words=frozenset(supplement_words),
        source_md5=source_md5,
        source_sha256=source_sha256,
        supplement_sha256=hashlib.sha256(supplement.read_bytes()).hexdigest(),
        starters_sha256=hashlib.sha256(starters_path.read_bytes()).hexdigest(),
        sample=sample.metadata(),
        supplement={**supplement_metadata, "starters": len(starter_rows)},
        protected_ngrams=frozenset(protected_ngrams),
        spelling_sha256=hashlib.sha256(spelling_path.read_bytes()).hexdigest(),
        spelling_replacements=len(replacements),
    )


class _CorpusSample:
    def __init__(self, options: PreparationOptions, replacements: dict[str, str]) -> None:
        self.options = options
        self.replacements = replacements
        self.counts: Counter[tuple[str, ...]] = Counter()
        self.domains: Counter[str] = Counter()
        self.genres: Counter[str] = Counter()
        self.seen: set[str] = set()
        self.scanned = self.accepted = self.token_count = 0

    def scan(self, source: Path) -> None:
        with gzip.open(source, "rt", encoding="utf-8") as stream:
            for line in stream:
                self.scanned += 1
                self._add_record(json.loads(line))

    def _record_selected(self, record: dict) -> bool:
        if not _supported_record(record):
            return False
        identifier = hashlib.sha256(record["id"].encode()).digest()
        # Spread the sample across the complete corpus instead of the first domains.
        if int.from_bytes(identifier[:4], "big") % self.options.sample_modulus:
            return False
        if self.domains[record["domain"]] >= self.options.per_domain_limit:
            return False
        return record["genre"] != "News" or self.genres["News"] < self.options.news_limit

    def _add_record(self, record: dict) -> None:
        if not self._record_selected(record):
            return
        text = record["text"]
        digest = hashlib.sha256(text.encode()).hexdigest()
        if digest in self.seen:
            return
        self.seen.add(digest)
        used = self._count_text(text)
        if used:
            self.domains[record["domain"]] += 1
            self.genres[record["genre"]] += 1
            self.accepted += 1
            self.token_count += used

    def _count_text(self, text: str) -> int:
        used = 0
        for paragraph in text.splitlines():
            tokens = words(paragraph)
            if not _usable_paragraph(tokens):
                continue
            used += self._count_tokens(tokens)
            if used >= 500:
                break
        return used

    def _count_tokens(self, tokens) -> int:
        used = 0
        for token in tokens:
            if len(token.text) == 1 and token.text not in {"a", "i", "o", "s", "u"}:
                continue
            self.counts.update(
                tuple(self.replacements.get(word, word) for word in key) for key in token.keys
            )
            used += 1
        return used

    def metadata(self) -> dict:
        return {
            "records_scanned": self.scanned,
            "documents": self.accepted,
            "tokens": self.token_count,
            "domains": len(self.domains),
            "genres": dict(self.genres),
            "id_hash_modulus": self.options.sample_modulus,
            "per_domain_limit": self.options.per_domain_limit,
            "news_limit": self.options.news_limit,
        }


def _supported_record(record: dict) -> bool:
    return (
        record.get("lang") == "bs"
        and record.get("script", "Latin") == "Latin"
        and record.get("genre") in GENRES
    )


def _usable_paragraph(tokens) -> bool:
    return 4 <= len(tokens) <= 120 and not any(token.text in NOISE for token in tokens)


def _add_conversation(counts: Counter, rows: list, multiplier: int) -> tuple[set, set]:
    supplement_words = set()
    protected_ngrams = set()
    for token, weight in _conversation_tokens(rows):
        supplement_words.add(token.text)
        for key in token.keys:
            counts[key] += weight * multiplier
            if len(key) > 1:
                protected_ngrams.add(key)
    return supplement_words, protected_ngrams


def _conversation_tokens(rows: list):
    for text, weight, _category in rows:
        for token in words(text):
            yield token, weight


def _add_starters(counts: Counter, path: Path, multiplier: int) -> set[str]:
    _clear_web_starters(counts)
    seen = set()
    with path.open(encoding="utf-8") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if reader.fieldnames != ["word", "weight"]:
            raise ValueError("Starters need word and weight columns")
        for row in reader:
            word, weight = _starter_row(row, seen)
            seen.add(word)
            counts[(START, word)] = weight * multiplier
            # A starter may be absent from both the corpus and supplement.
            counts[(word,)] = max(counts[(word,)], MINIMUM_WORD_COUNT)
    if not seen:
        raise ValueError("Starters must not be empty")
    return seen


def _starter_row(row: dict, seen: set[str]) -> tuple[str, int]:
    if not _has_row_values(row, ("word", "weight")):
        raise ValueError(f"Invalid starter row: {row!r}")
    word = spelling(row["word"].strip())
    weight = int(row["weight"])
    if not _starter_values_valid(word, weight):
        raise ValueError(f"Invalid starter row: {row!r}")
    if word in seen:
        raise ValueError(f"Invalid starter row: {row!r}")
    return word, weight


def _starter_values_valid(word: str, weight: int) -> bool:
    tokens = words(word)
    return bool(word and 1 <= weight <= 100 and _is_single_word(tokens, word))


def _clear_web_starters(counts: Counter) -> None:
    # Web headings and dates are poor defaults for starting a conversation.
    for key in list(counts):
        if len(key) == 2 and key[0] == START:
            del counts[key]


def _is_single_word(tokens, word: str) -> bool:
    return len(tokens) == 1 and tokens[0].text == word


def write_model(
    prepared: PreparedCounts,
    destination: Path,
    *,
    vocabulary: int,
    weights: ModelWeights = DEFAULT_WEIGHTS,
) -> dict:
    if vocabulary < 1:
        raise ValueError("Vocabulary size must be positive")
    allowed = _allowed_words(prepared, vocabulary)
    retained = _retained_counts(prepared, allowed)
    payload = {
        "version": 1,
        "counts": [[" ".join(key), count] for key, count in sorted(retained.items())],
    }
    encoded = gzip.compress(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), mtime=0
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(encoded)
    metadata = _model_metadata(prepared, retained, encoded, (vocabulary, weights))
    metadata_path(destination).write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def _allowed_words(prepared: PreparedCounts, vocabulary: int) -> set[str]:
    counts = prepared.counts
    common = sorted(
        (
            (count, key[0])
            for key, count in counts.items()
            if len(key) == 1 and count >= MINIMUM_WORD_COUNT and key[0] not in NOISE
        ),
        key=lambda item: (-item[0], item[1]),
    )
    allowed = set(prepared.supplement_words)
    if len(allowed) > vocabulary:
        raise ValueError("Vocabulary limit is smaller than the reviewed vocabulary")
    for _count, word in common:
        if len(allowed) >= vocabulary:
            break
        allowed.add(word)
    return allowed


def _retained_counts(prepared: PreparedCounts, allowed: set[str]) -> dict:
    counts = prepared.counts
    retained = {(word,): counts[(word,)] for word in allowed}
    contexts = _ngram_contexts(counts, allowed)
    ngrams = _retain_reviewed_contexts(prepared, contexts, retained)
    for length in (2, 3):
        retained.update(
            sorted(
                (item for item in ngrams if len(item[0]) == length),
                key=lambda item: (-item[1], item[0]),
            )[:PER_NGRAM_ORDER_LIMIT]
        )
    return retained


def _ngram_contexts(counts: Counter, allowed: set[str]) -> dict:
    contexts: dict[tuple[str, ...], list[tuple[tuple[str, ...], int]]] = defaultdict(list)
    for key, count in counts.items():
        if _ngram_allowed(key, count, allowed):
            contexts[key[:-1]].append((key, count))
    return contexts


def _ngram_allowed(key: tuple, count: int, allowed: set[str]) -> bool:
    if len(key) <= 1 or count < MINIMUM_NGRAM_COUNT:
        return False
    return all(word in allowed or word == START for word in key)


def _retain_reviewed_contexts(prepared: PreparedCounts, contexts: dict, retained: dict) -> list:
    ngrams = []
    for context, rows in contexts.items():
        # Reviewed combinations must survive web-frequency pruning. The limits
        # apply only to web-only rows, so common web phrases cannot evict them.
        if context == (START,):
            retained.update(rows)
        else:
            retained.update((key, count) for key, count in rows if key in prepared.protected_ngrams)
            web_rows = [item for item in rows if item[0] not in prepared.protected_ngrams]
            ngrams.extend(
                sorted(web_rows, key=lambda item: (-item[1], item[0]))[:PER_CONTEXT_LIMIT]
            )
    return ngrams


def _model_metadata(
    prepared: PreparedCounts,
    retained: dict,
    encoded: bytes,
    configuration: tuple[int, ModelWeights],
) -> dict:
    vocabulary, weights = configuration
    return {
        "version": 1,
        "model_id": f"bs-classla-2.0-conversation-4-v{vocabulary}-{hashlib.sha256(encoded).hexdigest()[:12]}",
        "source": "CLASSLA-web.bs 2.0",
        "source_url": SOURCE_URL,
        "source_license": "CC0-1.0",
        "source_md5": prepared.source_md5,
        "source_sha256": prepared.source_sha256,
        "supplement_sha256": prepared.supplement_sha256,
        "starters_sha256": prepared.starters_sha256,
        "spelling_sha256": prepared.spelling_sha256,
        "tokenizer_sha256": hashlib.sha256(
            (
                Path(__file__).resolve().parents[2] / "pogled_assist" / "suggestions" / "text.py"
            ).read_bytes()
        ).hexdigest(),
        "preparation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "model_sha256": hashlib.sha256(encoded).hexdigest(),
        "sample": prepared.sample,
        "supplement": prepared.supplement,
        "configuration": {
            "maximum_vocabulary": vocabulary,
            "minimum_word_count": MINIMUM_WORD_COUNT,
            "minimum_ngram_count": MINIMUM_NGRAM_COUNT,
            "per_context_limit": PER_CONTEXT_LIMIT,
            "per_ngram_order_limit": PER_NGRAM_ORDER_LIMIT,
            "supplement_multiplier": weights.supplement_multiplier,
            "starter_multiplier": weights.starter_multiplier,
            "protect_reviewed_ngrams": True,
            "spelling_scope": "reviewed replacements in web data only",
            "spelling_replacements": prepared.spelling_replacements,
        },
        "counts": {
            "words": sum(len(key) == 1 for key in retained),
            "bigrams": sum(len(key) == 2 for key in retained),
            "trigrams": sum(len(key) == 3 for key in retained),
            "protected_ngrams": sum(key in retained for key in prepared.protected_ngrams),
        },
        "compressed_bytes": len(encoded),
    }


def build_variants(
    source: Path,
    supplement: Path,
    destinations: dict[int, Path],
    *,
    options: PreparationOptions = DEFAULT_PREPARATION,
) -> dict[int, dict]:
    prepared = prepare_counts(source, supplement, options=options)
    return {
        vocabulary: write_model(
            prepared, destination, vocabulary=vocabulary, weights=options.weights
        )
        for vocabulary, destination in destinations.items()
    }


def build(
    source: Path,
    supplement: Path,
    destination: Path,
    *,
    options: BuildOptions = DEFAULT_BUILD,
) -> dict:
    return build_variants(
        source, supplement, {options.vocabulary: destination}, options=options.preparation
    )[options.vocabulary]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--supplement",
        type=Path,
        default=Path("language/bs/model/core/conversation.tsv"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("pogled_assist/assets/bosnian-model.json.gz")
    )
    parser.add_argument("--vocabulary", type=int, default=DEFAULT_VOCABULARY)
    parser.add_argument("--sample-modulus", type=int, default=DEFAULT_SAMPLE_MODULUS)
    parser.add_argument("--per-domain-limit", type=int, default=DEFAULT_PER_DOMAIN_LIMIT)
    parser.add_argument("--news-limit", type=int, default=DEFAULT_NEWS_LIMIT)
    args = parser.parse_args()
    print(
        json.dumps(
            build(
                args.source,
                args.supplement,
                args.output,
                options=BuildOptions(
                    vocabulary=args.vocabulary,
                    preparation=PreparationOptions(
                        sample_modulus=args.sample_modulus,
                        per_domain_limit=args.per_domain_limit,
                        news_limit=args.news_limit,
                    ),
                ),
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
