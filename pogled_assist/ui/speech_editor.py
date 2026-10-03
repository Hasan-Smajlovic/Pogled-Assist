"""Prepare saved speech entries while keeping the conversation intact."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Literal

from ..speech.speech_library import (
    CategoryRecord,
    PhraseRecord,
    SpeechLibrary,
    entry_exists,
    sorted_phrases,
)

EditorKind = Literal["category", "answer", "phrase"]


class EntryError(ValueError):
    """A message safe to show when a new entry cannot be added."""


@dataclass(frozen=True)
class EditorContext:
    kind: EditorKind
    category_index: int | None
    page: int
    message: str

    @property
    def list_mode(self) -> str:
        return {"category": "categories", "answer": "answers", "phrase": "phrases"}[self.kind]

    def prepare_entry(self, library: SpeechLibrary, text: str) -> SpeechLibrary:
        """Return a candidate copy; the caller must save it before replacing the library."""
        if not text:
            raise EntryError("Prvo unesite tekst.")
        candidate = copy.deepcopy(library)
        destination = self._destination(candidate)
        if destination is None:
            raise EntryError("Odredišna lista više nije dostupna.")
        if entry_exists([_entry_text(item) for item in destination], text):
            raise EntryError("Ova stavka već postoji. Unesite drugi tekst ili odaberite Odustani.")
        if self.kind == "category":
            destination.append(CategoryRecord(name=text))
        elif self.kind == "phrase":
            destination.append(PhraseRecord(text=text))
            candidate.phrases = sorted_phrases(candidate.phrases)
        else:
            destination.append(text)
        return candidate

    def _destination(
        self, library: SpeechLibrary
    ) -> list[CategoryRecord] | list[str] | list[PhraseRecord] | None:
        if self.kind == "category":
            return library.categories
        if self.kind == "phrase":
            return library.phrases
        if self.category_index is None:
            return None
        if not 0 <= self.category_index < len(library.categories):
            return None
        return library.categories[self.category_index].answers


def page_for_text(values: list[str], text: str, page_size: int) -> int:
    normalized = text.casefold()
    for index, value in enumerate(values):
        if value.casefold() == normalized:
            return index // page_size
    return 0


def _entry_text(item: CategoryRecord | PhraseRecord | str) -> str:
    if isinstance(item, CategoryRecord):
        return item.name
    if isinstance(item, PhraseRecord):
        return item.text
    return item
