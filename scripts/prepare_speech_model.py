"""Build a compact Bosnian seed from a verified CLASSLA-web 2.0 download."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gaze_mouse.suggestion_text import START, words

SOURCE_MD5 = "f92e72f4fe08362a1297f311ac20ad33"
SOURCE_URL = "https://www.clarin.si/repository/xmlui/bitstream/handle/11356/2079/CLASSLA-web.bs.2.0.jsonl.gz?isAllowed=y&sequence=11"
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


def build(source: Path, supplement: Path, destination: Path, *, vocabulary: int = 20000) -> dict:
    md5, sha = hashlib.md5(), hashlib.sha256()
    with source.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            md5.update(block)
            sha.update(block)
    if md5.hexdigest() != SOURCE_MD5:
        raise ValueError("CLASSLA download does not match the published MD5")

    counts: Counter[tuple[str, ...]] = Counter()
    domains: Counter[str] = Counter()
    genres: Counter[str] = Counter()
    seen: set[str] = set()
    scanned = accepted = token_count = 0
    with gzip.open(source, "rt", encoding="utf-8") as stream:
        for line in stream:
            scanned += 1
            record = json.loads(line)
            if (
                record.get("lang") != "bs"
                or record.get("script", "Latin") != "Latin"
                or record.get("genre") not in GENRES
            ):
                continue
            identifier = hashlib.sha256(record["id"].encode()).digest()
            # Spread the sample across the complete corpus instead of the first domains.
            if int.from_bytes(identifier[:4], "big") % 40:
                continue
            domain = record["domain"]
            if domains[domain] >= 120:
                continue
            if record["genre"] == "News" and genres["News"] >= 2000:
                continue
            text = record["text"]
            digest = hashlib.sha256(text.encode()).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            used = 0
            for paragraph in text.splitlines():
                tokens = words(paragraph)
                if not 4 <= len(tokens) <= 120 or any(token.text in NOISE for token in tokens):
                    continue
                for token in tokens:
                    if len(token.text) == 1 and token.text not in {"a", "i", "o", "s", "u"}:
                        continue
                    counts.update(token.keys)
                    used += 1
                if used >= 500:
                    break
            if used:
                domains[domain] += 1
                genres[record["genre"]] += 1
                accepted += 1
                token_count += used

    supplement_words = set()
    for line in supplement.read_text(encoding="utf-8").splitlines():
        for token in words(line):
            supplement_words.add(token.text)
            for key in token.keys:
                counts[key] += 200

    starters_path = supplement.with_name("starters.tsv")
    # Web headings and dates are poor defaults for starting a conversation.
    for key in list(counts):
        if len(key) == 2 and key[0] == START:
            del counts[key]
    with starters_path.open(encoding="utf-8") as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            counts[(START, row["word"])] = int(row["weight"]) * 200
            supplement_words.add(row["word"])

    common = sorted(
        ((count, key[0]) for key, count in counts.items() if len(key) == 1 and count >= 5),
        key=lambda item: (-item[0], item[1]),
    )
    allowed = {word for _count, word in common[:vocabulary]} | supplement_words
    retained = {(word,): counts[(word,)] for word in allowed}
    contexts: dict[tuple[str, ...], list[tuple[tuple[str, ...], int]]] = defaultdict(list)
    for key, count in counts.items():
        if len(key) > 1 and count >= 3 and all(word in allowed or word == START for word in key):
            contexts[key[:-1]].append((key, count))
    ngrams = []
    for rows in contexts.values():
        ngrams.extend(sorted(rows, key=lambda item: (-item[1], item[0]))[:24])
    for length in (2, 3):
        retained.update(
            sorted(
                (item for item in ngrams if len(item[0]) == length),
                key=lambda item: (-item[1], item[0]),
            )[:120000]
        )
    payload = {
        "version": 1,
        "counts": [[" ".join(key), count] for key, count in sorted(retained.items())],
    }
    encoded = gzip.compress(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), mtime=0
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(encoded)
    metadata = {
        "version": 1,
        "model_id": "bs-classla-2.0-2026-09-18",
        "source": "CLASSLA-web.bs 2.0",
        "source_url": SOURCE_URL,
        "source_license": "CC0-1.0",
        "source_md5": md5.hexdigest(),
        "source_sha256": sha.hexdigest(),
        "supplement_sha256": hashlib.sha256(supplement.read_bytes()).hexdigest(),
        "starters_sha256": hashlib.sha256(starters_path.read_bytes()).hexdigest(),
        "preparation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "model_sha256": hashlib.sha256(encoded).hexdigest(),
        "sample": {
            "records_scanned": scanned,
            "documents": accepted,
            "tokens": token_count,
            "domains": len(domains),
            "genres": dict(genres),
            "id_hash_modulus": 40,
            "per_domain_limit": 120,
            "news_limit": 2000,
        },
        "configuration": {
            "maximum_vocabulary": vocabulary,
            "minimum_word_count": 5,
            "minimum_ngram_count": 3,
            "per_context_limit": 24,
            "per_ngram_order_limit": 120000,
            "supplement_weight": 200,
        },
        "counts": {
            "words": len(allowed),
            "bigrams": sum(len(key) == 2 for key in retained),
            "trigrams": sum(len(key) == 3 for key in retained),
        },
        "compressed_bytes": len(encoded),
    }
    destination.with_name("bosnian-model.meta.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--supplement", type=Path, default=Path("language/bs/conversation.txt"))
    parser.add_argument(
        "--output", type=Path, default=Path("gaze_mouse/assets/bosnian-model.json.gz")
    )
    parser.add_argument("--vocabulary", type=int, default=20000)
    args = parser.parse_args()
    print(
        json.dumps(
            build(args.source, args.supplement, args.output, vocabulary=args.vocabulary),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
