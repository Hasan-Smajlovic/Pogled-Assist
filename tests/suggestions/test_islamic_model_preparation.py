from __future__ import annotations

import hashlib
import json

from pogled_assist.suggestions.model import load_model_from_paths
from scripts.speech_suggestions.prepare_islamic_model import build, load_rows, metadata_path


def test_islamic_model_build_is_reproducible_and_keeps_reviewed_contexts(tmp_path):
    source = tmp_path / "islamic.tsv"
    source.write_text(
        "category\tweight\ttext\n"
        "worship\t9\tPomozi mi da uzmem abdest.\n"
        "quran\t10\tDonesi mi Kur'an.\n",
        encoding="utf-8",
    )
    first = tmp_path / "first.json.gz"
    second = tmp_path / "second.json.gz"

    first_metadata = build(source, first)
    second_metadata = build(source, second)
    model = load_model_from_paths(first, metadata_path(first))

    assert first.read_bytes() == second.read_bytes()
    assert first_metadata["model_sha256"] == second_metadata["model_sha256"]
    assert hashlib.sha256(first.read_bytes()).hexdigest() == first_metadata["model_sha256"]
    assert first_metadata["configuration"] == {"domain_boost": 5}
    assert first_metadata["counts"]["bigrams"] == 0
    assert json.loads(metadata_path(first).read_text(encoding="utf-8")) == first_metadata
    assert json.loads(metadata_path(second).read_text(encoding="utf-8")) == second_metadata
    assert first_metadata["supplement"]["categories"] == {"worship": 1, "quran": 1}
    assert first_metadata["source_references"]
    assert "ABDEST" in model.predict("POMOZI MI DA UZMEM ")
    assert "KUR'AN" in model.predict("KUR")

    single_row = tmp_path / "single-row.tsv"
    single_row.write_text("category\tweight\ttext\nvalues\t7\tSabur je važan.\n", encoding="utf-8")
    rows, supplement = load_rows(single_row)
    assert rows == [("Sabur je važan.", 7, "values")]
    assert supplement == {"rows": 1, "categories": {"values": 1}, "weighted_rows": {"values": 7}}
