"""Persistent categories, answers, and phrases for the Speech screen."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

SPEECH_LIBRARY_VERSION = 2


@dataclass(eq=True)
class PhraseRecord:
    text: str
    uses: int = 0


@dataclass(eq=True)
class CategoryRecord:
    name: str
    answers: list[str] = field(default_factory=list)


@dataclass(eq=True)
class SpeechLibrary:
    categories: list[CategoryRecord] = field(default_factory=list)
    phrases: list[PhraseRecord] = field(default_factory=list)


DEFAULT_CATEGORIES = (
    (
        "Trebam",
        (
            "Trebam vode",
            "Namjesti mi jastuk",
            "Trebam lijek",
            "Pomozi mi da se okrenem",
            "Hladno mi je",
            "Trebam u toalet",
        ),
    ),
    (
        "Brzi odgovor",
        ("Da", "Ne", "Možda", "Hvala", "Molim te", "Nisam razumio"),
    ),
    (
        "Kako se osjećam",
        ("Dobro sam", "Boli me", "Umoran sam", "Nervozan sam", "Sretan sam", "Neugodno mi je"),
    ),
    (
        "Ljudi",
        (
            "Pozovi Hasana",
            "Želim porodicu",
            "Pozovi medicinsku sestru",
            "Želim razgovarati",
            "Ko je ovdje?",
            "Ostani sa mnom",
        ),
    ),
)


def default_categories() -> list[CategoryRecord]:
    return [
        CategoryRecord(name=name, answers=list(answers)) for name, answers in DEFAULT_CATEGORIES
    ]


class SpeechLibraryStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> SpeechLibrary:
        if not self.path.exists():
            return SpeechLibrary(categories=default_categories())

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Could not load the speech library from %s.", self.path)
            return SpeechLibrary(categories=default_categories())

        if isinstance(data, list):
            return SpeechLibrary(
                categories=default_categories(),
                phrases=_parse_phrases(data),
            )

        if not isinstance(data, dict):
            logger.warning("Speech library did not contain an object or legacy list: %s", self.path)
            return SpeechLibrary(categories=default_categories())

        categories_value = data.get("categories")
        categories = (
            _parse_categories(categories_value)
            if isinstance(categories_value, list)
            else default_categories()
        )
        phrases_value = data.get("phrases", [])
        phrases = _parse_phrases(phrases_value) if isinstance(phrases_value, list) else []
        return SpeechLibrary(categories=categories, phrases=phrases)

    def save(self, library: SpeechLibrary) -> bool:
        payload = {
            "version": SPEECH_LIBRARY_VERSION,
            "categories": [
                {"name": category.name, "answers": list(category.answers)}
                for category in library.categories
            ],
            "phrases": [
                {"text": phrase.text, "uses": max(0, int(phrase.uses))}
                for phrase in sorted_phrases(library.phrases)
            ],
        }
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temp_path.replace(self.path)
        except Exception:
            logger.exception("Could not save the speech library to %s.", self.path)
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove temporary speech library file %s.", temp_path)
            return False

        logger.info(
            "Saved %s categories and %s phrases to %s.",
            len(library.categories),
            len(library.phrases),
            self.path,
        )
        return True


def clean_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def entry_exists(values: list[str], candidate: str) -> bool:
    candidate_key = clean_text(candidate).casefold()
    return any(clean_text(value).casefold() == candidate_key for value in values)


def sorted_phrases(phrases: list[PhraseRecord]) -> list[PhraseRecord]:
    return sorted(phrases, key=lambda phrase: (-phrase.uses, phrase.text.casefold()))


def _parse_categories(values: list[object]) -> list[CategoryRecord]:
    categories: list[CategoryRecord] = []
    category_names: list[str] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        name = clean_text(value.get("name"))
        if not name or entry_exists(category_names, name):
            continue
        answers_value = value.get("answers", value.get("items", []))
        answers = _parse_answers(answers_value) if isinstance(answers_value, list) else []
        categories.append(CategoryRecord(name=name, answers=answers))
        category_names.append(name)
    return categories


def _parse_answers(values: list[object]) -> list[str]:
    answers: list[str] = []
    for value in values:
        text = clean_text(value.get("text")) if isinstance(value, dict) else clean_text(value)
        if text and not entry_exists(answers, text):
            answers.append(text)
    return answers


def _parse_phrases(values: list[object]) -> list[PhraseRecord]:
    phrases_by_text: dict[str, PhraseRecord] = {}
    for value in values:
        phrase, uses = parse_phrase_record(value)
        if not phrase:
            continue
        key = phrase.casefold()
        existing = phrases_by_text.get(key)
        if existing is None:
            phrases_by_text[key] = PhraseRecord(text=phrase, uses=uses)
        else:
            existing.uses = max(existing.uses, uses)
    return sorted_phrases(list(phrases_by_text.values()))


def parse_phrase_record(value: object) -> tuple[str, int]:
    if isinstance(value, dict):
        text = value.get("text", value.get("phrase", ""))
        uses = _safe_int(value.get("uses", value.get("count", 0)))
    else:
        text = value
        uses = 0
    return clean_text(text), max(0, uses)


def _safe_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
