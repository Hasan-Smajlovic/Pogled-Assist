"""Build the reviewed Bosnian Islamic terminology layer for word suggestions."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pogled_assist.suggestions.text import words

MODEL_VERSION = 1
DOMAIN_BOOST = 5
SOURCE_REFERENCES = (
    {
        "title": "Islam.ba - platforma Islamske zajednice u Bosni i Hercegovini",
        "url": "https://www.islam.ba/platforma",
    },
    {
        "title": "Islam.ba - kratki rječnik islamskih termina",
        "url": "https://www.islam.ba/teme/tekst/kratki-rjecnik-pojmovnik-islamskih-termina",
    },
)


def load_rows(path: Path) -> tuple[list[tuple[str, int, str]], dict]:
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if reader.fieldnames != ["category", "weight", "text"]:
            raise ValueError("Islamic supplement needs category, weight, and text columns")
        rows = []
        seen = set()
        categories: Counter[str] = Counter()
        weighted_rows: Counter[str] = Counter()
        for line_number, row in enumerate(reader, 2):
            category = (row.get("category") or "").strip()
            text = (row.get("text") or "").strip()
            try:
                weight = int(row.get("weight") or "")
            except ValueError as error:
                raise ValueError(
                    f"Invalid weight on Islamic supplement line {line_number}"
                ) from error
            normalized = " ".join(token.text for token in words(text))
            if (
                None in row
                or not category
                or not text
                or not 1 <= weight <= 10
                or not normalized
                or normalized in seen
            ):
                raise ValueError(f"Invalid or duplicate Islamic supplement line {line_number}")
            seen.add(normalized)
            rows.append((text, weight, category))
            categories[category] += 1
            weighted_rows[category] += weight
    if not rows:
        raise ValueError("Islamic supplement is empty")
    return rows, {
        "rows": len(rows),
        "categories": dict(sorted(categories.items())),
        "weighted_rows": dict(sorted(weighted_rows.items())),
    }


def metadata_path(model_path: Path) -> Path:
    suffix = ".json.gz"
    if not model_path.name.endswith(suffix):
        raise ValueError("Model output must end in .json.gz")
    return model_path.with_name(model_path.name[: -len(suffix)] + ".meta.json")


def build(source: Path, destination: Path) -> dict:
    rows, row_metadata = load_rows(source)
    counts: Counter[tuple[str, ...]] = Counter()
    vocabulary = set()
    for text, weight, _category in rows:
        for token in words(text):
            vocabulary.add(token.text)
            # One-word contexts often contain ordinary words and can distort
            # general suggestions. Two-word contexts keep the domain signal specific.
            counts.update({key: weight * DOMAIN_BOOST for key in token.keys if len(key) != 2})

    payload = {
        "version": MODEL_VERSION,
        "counts": [[" ".join(key), count] for key, count in sorted(counts.items())],
    }
    encoded = gzip.compress(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), mtime=0
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(encoded)
    digest = hashlib.sha256(encoded).hexdigest()
    metadata = {
        "version": MODEL_VERSION,
        "model_id": f"bs-islamic-reviewed-1-{digest[:12]}",
        "source": "Reviewed synthetic Bosnian Islamic terminology and conversation phrases",
        "text_origin": "Project-authored examples; reference pages were used for terminology only",
        "source_references": list(SOURCE_REFERENCES),
        "supplement_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "tokenizer_sha256": hashlib.sha256(
            (
                Path(__file__).resolve().parents[2] / "pogled_assist" / "suggestions" / "text.py"
            ).read_bytes()
        ).hexdigest(),
        "preparation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "model_sha256": digest,
        "supplement": row_metadata,
        "configuration": {"domain_boost": DOMAIN_BOOST},
        "counts": {
            "words": len(vocabulary),
            "bigrams": sum(len(key) == 2 for key in counts),
            "trigrams": sum(len(key) == 3 for key in counts),
        },
        "compressed_bytes": len(encoded),
    }
    metadata_path(destination).write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("language/bs/model/domains/islamic.tsv"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("pogled_assist/assets/bosnian-islamic-model.json.gz"),
    )
    args = parser.parse_args()
    print(
        json.dumps(
            build(args.source, args.output),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
