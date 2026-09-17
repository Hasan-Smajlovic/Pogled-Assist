"""Persistent categories, answers, and phrases for the Speech screen."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

SPEECH_LIBRARY_VERSION = 2
SPEECH_LIBRARY_FILE = "speech_library.json"
LEGACY_PHRASES_FILE = "speech_phrases.json"


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


def speech_library_store(root: Path) -> SpeechLibraryStore:
    return SpeechLibraryStore(
        root / "data" / SPEECH_LIBRARY_FILE,
        legacy_path=root / "data" / LEGACY_PHRASES_FILE,
    )


class SpeechLibraryStore:
    """Keep the full library and the rollback phrase list in sync."""

    def __init__(self, path: Path, *, legacy_path: Path | None = None) -> None:
        if legacy_path == path:
            raise ValueError("The v2 library and legacy phrase paths must differ.")
        self.path = path
        self.legacy_path = legacy_path

    def load(self) -> SpeechLibrary:
        data = _read_json(self.path)
        if data is _MISSING:
            return self._load_legacy_for_migration()
        if data is _INVALID:
            return self._fallback_after_invalid_primary()

        library = _parse_library(data, self.path)
        if library is None:
            return self._fallback_after_invalid_primary()
        self._sync_legacy_file(library)
        return library

    def save(self, library: SpeechLibrary) -> bool:
        payload = _library_payload(library)
        targets: list[tuple[Path, object]] = [(self.path, payload)]
        if self.legacy_path is not None:
            targets.append((self.legacy_path, payload["phrases"]))

        originals: dict[Path, bytes | None] = {}
        temp_paths: list[Path] = []
        try:
            for target, _target_payload in targets:
                target.parent.mkdir(parents=True, exist_ok=True)
                originals[target] = target.read_bytes() if target.exists() else None

            for target, target_payload in targets:
                temp_path = target.with_suffix(target.suffix + ".tmp")
                temp_path.write_text(
                    json.dumps(target_payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                temp_paths.append(temp_path)

            for (target, _target_payload), temp_path in zip(targets, temp_paths, strict=True):
                temp_path.replace(target)
        except Exception:
            logger.exception("Could not save the speech library to %s.", self.path)
            _remove_temp_files(temp_paths)
            _restore_files(originals)
            return False

        logger.info(
            "Saved %s categories and %s phrases to %s.",
            len(library.categories),
            len(library.phrases),
            self.path,
        )
        return True

    def _load_legacy_for_migration(self) -> SpeechLibrary:
        if self.legacy_path is None:
            return SpeechLibrary(categories=default_categories())

        data = _read_json(self.legacy_path)
        if data is _MISSING or data is _INVALID:
            return SpeechLibrary(categories=default_categories())
        library = _parse_library(data, self.legacy_path)
        if library is None:
            return SpeechLibrary(categories=default_categories())

        if not self.save(library):
            logger.warning("Could not migrate the speech library from %s.", self.legacy_path)
        return library

    def _fallback_after_invalid_primary(self) -> SpeechLibrary:
        if self.legacy_path is None:
            return SpeechLibrary(categories=default_categories())

        legacy_data = _read_json(self.legacy_path)
        if not isinstance(legacy_data, list):
            return SpeechLibrary(categories=default_categories())
        return SpeechLibrary(
            categories=default_categories(),
            phrases=_parse_phrases(legacy_data),
        )

    def _sync_legacy_file(self, library: SpeechLibrary) -> None:
        if self.legacy_path is None:
            return

        legacy_data = _read_json(self.legacy_path)
        if isinstance(legacy_data, list):
            legacy_phrases = _parse_phrases(legacy_data)
            if legacy_phrases == library.phrases:
                return
            if self._legacy_is_newer():
                library.phrases = legacy_phrases
        elif isinstance(legacy_data, dict) and self._legacy_is_newer():
            legacy_library = _parse_library(legacy_data, self.legacy_path)
            if legacy_library is not None:
                # A v2 rollback rebuilds categories from defaults after reading the
                # list-only file, so only its phrase changes are safe to import.
                library.phrases = legacy_library.phrases

        if not self.save(library):
            logger.warning("Could not synchronize the rollback-compatible phrase file.")

    def _legacy_is_newer(self) -> bool:
        if self.legacy_path is None:
            return False
        try:
            return self.legacy_path.stat().st_mtime_ns > self.path.stat().st_mtime_ns
        except OSError:
            return False


_MISSING = object()
_INVALID = object()


def _read_json(path: Path) -> object:
    if not path.exists():
        return _MISSING
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Could not load the speech library from %s.", path)
        return _INVALID


def _parse_library(data: object, path: Path) -> SpeechLibrary | None:
    if isinstance(data, list):
        return SpeechLibrary(categories=default_categories(), phrases=_parse_phrases(data))
    if not isinstance(data, dict):
        logger.warning("Speech library did not contain an object or legacy list: %s", path)
        return None

    categories_value = data.get("categories")
    categories = (
        _parse_categories(categories_value)
        if isinstance(categories_value, list)
        else default_categories()
    )
    phrases_value = data.get("phrases", [])
    phrases = _parse_phrases(phrases_value) if isinstance(phrases_value, list) else []
    return SpeechLibrary(categories=categories, phrases=phrases)


def _library_payload(library: SpeechLibrary) -> dict[str, object]:
    return {
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


def _remove_temp_files(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove temporary speech library file %s.", path)


def _restore_files(originals: dict[Path, bytes | None]) -> None:
    # Saving spans two files so rollback must restore both if the second replace fails.
    for path, content in originals.items():
        try:
            if content is None:
                path.unlink(missing_ok=True)
                continue
            restore_path = path.with_suffix(path.suffix + ".restore.tmp")
            restore_path.write_bytes(content)
            restore_path.replace(path)
        except OSError:
            logger.exception("Could not restore speech library file %s.", path)


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
