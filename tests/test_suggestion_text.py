from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter

import pytest

from gaze_mouse.suggestion_model import (
    ISLAMIC_MODEL_METADATA_PATH,
    ISLAMIC_MODEL_PATH,
    MODEL_METADATA_PATH,
    MODEL_PATH,
    WordModel,
    load_model,
)
from gaze_mouse.suggestion_text import START, insert_word, query, words


@pytest.mark.parametrize(
    ("prefix", "expected", "excluded"),
    [
        ("zel", "ŽELIM", "ŠUMA"),
        ("caj", "ČAJ", "ĆUP"),
        ("ć", "ĆUP", "ČAJ"),
        ("š", "ŠUMA", "SADA"),
        ("d", "ĐAK", "ČAJ"),
        ("dj", "DJECA", "DŽEM"),
        ("dj", "ĐAK", "DŽEM"),
        ("dodj", "DOĐI", "DOLAZI"),
        ("dodi", "DOĐI", "DOLAZI"),
        ("đ", "ĐAK", "DJECA"),
        ("l", "LJETO", "NJIVA"),
        ("lj", "LJETO", "LUK"),
        ("nj", "NJIVA", "NOGA"),
    ],
)
def test_bosnian_prefixes(prefix, expected, excluded):
    model = WordModel({(word.lower(),): 1 for word in {expected, excluded}})
    result = model.predict(prefix)
    assert expected in result
    assert excluded not in result


def test_common_plain_c_keeps_distinct_letters():
    model = WordModel({(word,): 1 for word in ("cesta", "čaj", "ćup")})
    assert set(model.predict("c")) == {"CESTA", "ČAJ", "ĆUP"}


@pytest.mark.parametrize("prefix", ["zel", "ZEL", "ZeL"])
def test_prefix_matching_is_case_insensitive(prefix):
    model = WordModel({("želim",): 1})

    assert model.predict(prefix) == ["ŽELIM"]


@pytest.mark.parametrize(
    ("text", "candidate", "result"),
    [
        ("Želim vo", "vodu", "Želim VODU "),
        ("ŽELIM ", "vodu", "ŽELIM VODU "),
        ("", "selam", "SELAM "),
        ("ŽELIM VODU.", "hvala", "ŽELIM VODU. HVALA "),
        ("ŽELIM VODU.  ", "hvala", "ŽELIM VODU.  HVALA "),
        ("Iznos 12", "voda", "Iznos 12"),
    ],
)
def test_selection_preserves_surrounding_text(text, candidate, result):
    assert insert_word(text, candidate) == result


def test_sentence_context_is_shared_with_learning():
    assert query("Želim vodu.")[1] == (START,)
    assert query("Želim vodu, ")[1] == ("želim", "vodu")
    assert words("Želim vodu. Hvala ti")[2].context == (START,)
    assert words("Želim vodu, molim")[2].context == ("želim", "vodu")


@pytest.mark.parametrize("boundary", [".", "?", "!"])
def test_each_sentence_boundary_resets_prediction_context(boundary):
    assert query(f"Želim vodu{boundary}")[1] == (START,)
    assert words(f"Želim vodu{boundary} Hvala")[2].context == (START,)


def test_decomposed_unicode_matches_without_rewriting_surrounding_text():
    assert query("Želim c\u030caj")[0] == "čaj"
    assert insert_word("Želim c\u030caj", "čaja") == "Želim ČAJA "


def test_quran_apostrophe_is_one_word_and_can_be_completed_without_typing_the_mark():
    model = WordModel({("kur'an",): 10})

    assert words("Čitam Kur\u2019an.")[1].text == "kur'an"
    assert model.predict("kuran") == ["KUR'AN"]
    assert insert_word("Čitam kur", "kur'an") == "Čitam KUR'AN "


def test_longer_context_changes_prediction_and_unknown_prefix_is_empty():
    model = WordModel({("voda",): 100, ("piti",): 1, ("želim", "piti"): 20})
    assert model.predict("želim ")[0] == "PITI"
    assert model.predict("želim ", contextual=False)[0] == "VODA"
    assert model.predict("qwert") == []


def test_next_word_pool_keeps_rare_contextual_and_personal_candidates():
    counts = {(word,): 100 - index for index, word in enumerate("abcdef")}
    counts.update({("rijetka",): 1, ("želim", "rijetka"): 50})
    model = WordModel(counts)

    assert model.predict("želim ")[0] == "RIJETKA"
    personal = Counter({("lična",): 4, ("trebam", "lična"): 4})
    assert model.predict("trebam ", personal)[0] == "LIČNA"


def test_bundled_model_has_verified_metadata_and_useful_offline_results(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    metadata = json.loads(MODEL_METADATA_PATH.read_text(encoding="utf-8"))
    root = MODEL_PATH.parents[2]

    assert metadata["source"] == "CLASSLA-web.bs 2.0"
    assert metadata["source_license"] == "CC0-1.0"
    assert metadata["counts"]["words"] == 60_000
    with (root / "language/bs/model/core/conversation.tsv").open(encoding="utf-8") as stream:
        assert metadata["supplement"]["rows"] == sum(
            1 for _ in csv.DictReader(stream, delimiter="\t")
        )
    assert hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() == metadata["model_sha256"]
    assert (
        hashlib.sha256((root / "scripts" / "prepare_speech_model.py").read_bytes()).hexdigest()
        == metadata["preparation_sha256"]
    )
    assert (
        hashlib.sha256(
            (root / "language" / "bs" / "model" / "core" / "conversation.tsv").read_bytes()
        ).hexdigest()
        == metadata["supplement_sha256"]
    )
    assert (
        hashlib.sha256(
            (root / "language" / "bs" / "model" / "core" / "starters.tsv").read_bytes()
        ).hexdigest()
        == metadata["starters_sha256"]
    )
    assert (
        hashlib.sha256((root / "language/bs/model/core/spelling.tsv").read_bytes()).hexdigest()
        == metadata["spelling_sha256"]
    )
    with (root / "language/bs/model/core/spelling.tsv").open(encoding="utf-8") as stream:
        assert metadata["configuration"]["spelling_replacements"] == sum(
            1 for _ in csv.DictReader(stream, delimiter="\t")
        )
    assert load_model().predict("žel")[0] == "ŽELIM"
    assert load_model().predict("")[:5] == ["SELAM", "JA", "KAKO", "MOŽE", "HVALA"]


def test_bundled_islamic_model_has_verified_inputs_and_domain_predictions():
    metadata = json.loads(ISLAMIC_MODEL_METADATA_PATH.read_text(encoding="utf-8"))
    root = MODEL_PATH.parents[2]

    assert metadata["supplement"]["rows"] >= 150
    assert metadata["counts"]["words"] >= 300
    assert hashlib.sha256(ISLAMIC_MODEL_PATH.read_bytes()).hexdigest() == metadata["model_sha256"]
    assert (
        hashlib.sha256((root / "language/bs/model/domains/islamic.tsv").read_bytes()).hexdigest()
        == metadata["supplement_sha256"]
    )
    assert (
        hashlib.sha256((root / "scripts/prepare_islamic_model.py").read_bytes()).hexdigest()
        == metadata["preparation_sha256"]
    )
    assert (
        hashlib.sha256((root / "gaze_mouse/suggestion_text.py").read_bytes()).hexdigest()
        == metadata["tokenizer_sha256"]
    )

    model = load_model()
    assert "KUR'AN" in model.predict("KUR")
    assert "ABDEST" in model.predict("POMOZI MI DA UZMEM ")
    assert "JASIN" in model.predict("OTVORI SURU ")
    assert "DŽUMA" in model.predict("DANAS JE ")


def test_bundled_model_corrects_reviewed_spellings_without_folding_ambiguous_words():
    vocabulary = load_model().vocabulary
    root = MODEL_PATH.parents[2]
    with (root / "language/bs/model/core/spelling.tsv").open(encoding="utf-8") as stream:
        replacements = list(csv.DictReader(stream, delimiter="\t"))

    assert all(row["variant"] not in vocabulary for row in replacements)
    assert all(row["word"] in vocabulary for row in replacements)
    assert {
        "bas",
        "baš",
        "kuca",
        "kuća",
        "oci",
        "oči",
        "reci",
        "reći",
        "rijeci",
        "riječi",
        "znaci",
        "znači",
        "zvuci",
        "zvuči",
    } <= vocabulary


def test_bundled_model_preserves_starters_and_basic_needs():
    model = load_model()
    root = MODEL_PATH.parents[2]
    with (root / "language/bs/model/core/starters.tsv").open(encoding="utf-8") as stream:
        starters = {row["word"] for row in csv.DictReader(stream, delimiter="\t")}
    assert set(model.contexts[(START,)]) == starters
    assert {"VODE", "POMOĆ"} <= set(model.predict("TREBA MI "))
    assert model.predict("TREBA MI ")[0] != "JE"
    assert {"GLAVA", "STOMAK"} <= set(model.predict("BOLI ME "))
    assert model.predict("POM")[0] == "POMOZI"
    assert model.predict("ZAT")[0] == "ZATVORI"


def test_sparse_context_backs_off_but_supported_context_overrides_common_pair():
    counts = {("je",): 100_000, ("vode",): 100, ("mi", "je"): 1000, ("treba", "mi", "vode"): 3}
    assert WordModel(counts).predict("TREBA MI ")[0] == "JE"
    counts[("treba", "mi", "vode")] = 200
    assert WordModel(counts).predict("TREBA MI ")[0] == "VODE"


def test_evaluation_separates_starters_next_words_and_completions():
    from scripts.evaluate_speech_model import simulate

    class ScriptedModel:
        def predict(self, text, *, contextual=True):
            return {
                "": ["ŽELIM"],
                "ŽELIM ": [],
                "ŽELIM V": ["VODE"],
                "ŽELIM VODE. ": ["HVALA"],
            }.get(text, [])

    result = simulate("Želim vode. Hvala.", ScriptedModel())
    assert result["sentence_start_queries"] == 2
    assert result["sentence_start_top_one_hits"] == 2
    assert result["next_word_queries"] == 1
    assert result["next_word_top_five_hits"] == 0
    assert result["completion_queries"] == 1
    assert result["completion_top_one_hits"] == 1
    assert result["prediction_selections"] == 2
    assert result["completion_selections"] == 1
    assert result["activations"] == 12


def test_frozen_fixture_hash_is_stable_across_windows_line_endings(tmp_path):
    from scripts.evaluate_speech_model import fixture_sha256

    fixture = tmp_path / "cases.tsv"
    fixture.write_bytes(b"id\ttext\r\n1\tmessage\r\n")
    windows_digest = fixture_sha256(fixture)
    fixture.write_bytes(b"id\ttext\n1\tmessage\n")

    assert fixture_sha256(fixture) == windows_digest
