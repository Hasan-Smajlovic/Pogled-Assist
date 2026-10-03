"""Track suggestion undo and learning for one active text input."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher

from .learning import Contribution, Key, LearningStore
from .text import Word, insert_word, words

PUNCTUATION = frozenset(".,?!")
SENTENCE_ENDINGS = frozenset(".?")


@dataclass
class Occurrence:
    word: Word
    credits: dict[Key, Contribution] = field(default_factory=dict)
    submitted: bool = False


@dataclass
class Undo:
    text: str
    occurrences: list[Occurrence]
    selected: Occurrence
    revoked: list[Contribution]
    automatic_space: str | None


class Composition:
    def __init__(self, store: LearningStore, *, learn: bool = True) -> None:
        self.store = store
        self.learn = learn
        self.text = ""
        self.occurrences: list[Occurrence] = []
        self.undo: Undo | None = None
        self.automatic_space: str | None = None

    def edit(self, text: str) -> str:
        if text == self.text:
            return text
        typed = _appended_character(self.text, text)
        if typed.isspace() and self.text.endswith((". ", "? ")):
            return self.text
        if typed in PUNCTUATION and self.automatic_space == self.text:
            text = self.text[:-1] + typed
        if typed in SENTENCE_ENDINGS:
            text += " "
        self.undo = None
        self.automatic_space = None
        self._reconcile(words(text))
        self.text = text
        return text

    def select(self, candidate: str) -> str:
        result = insert_word(self.text, candidate)
        if result == self.text:
            return result
        before = self.text
        previous = list(self.occurrences)
        copies = [replace(item, credits=item.credits.copy()) for item in previous]
        active = [credit for item in copies for credit in item.credits.values() if credit.active]
        automatic_space = self.automatic_space
        self.edit(result)
        selected = self.occurrences[-1]
        occurrences = self._undo_occurrences(previous, copies, selected)
        if self.learn:
            self._credit(selected)
        self.undo = Undo(
            before,
            occurrences,
            selected,
            [credit for credit in active if not credit.active],
            automatic_space,
        )
        self.automatic_space = result
        return result

    def undo_selection(self) -> str:
        undo = self.undo
        if undo is None:
            return self.text
        before_credits = {
            id(credit) for item in undo.occurrences for credit in item.credits.values()
        }
        for credit in undo.selected.credits.values():
            if id(credit) not in before_credits:
                self.store.revoke(credit)
        for credit in undo.revoked:
            self.store.restore(credit)
        self.text = undo.text
        self.occurrences = undo.occurrences
        self.automatic_space = undo.automatic_space
        self.undo = None
        return self.text

    def submit(self) -> None:
        if not self.learn or not self.text.strip():
            return
        for occurrence in self.occurrences:
            self._credit(occurrence)
            occurrence.submitted = True

    def _reconcile(self, tokens: list[Word]) -> None:
        previous = _previous_positions(self.occurrences, tokens)
        retained = set(previous.values())
        for index, occurrence in enumerate(self.occurrences):
            if index not in retained:
                self._revoke_credits(occurrence)
        updated = []
        for index, token in enumerate(tokens):
            occurrence = (
                self.occurrences[previous[index]] if index in previous else Occurrence(token)
            )
            self._revoke_credits(occurrence, keep=token.keys)
            occurrence.word = token
            updated.append(occurrence)
        self.occurrences = updated

    def _revoke_credits(self, occurrence: Occurrence, keep: tuple[Key, ...] = ()) -> None:
        if occurrence.submitted:
            return
        for key in list(occurrence.credits):
            if key not in keep:
                self.store.revoke(occurrence.credits.pop(key))

    def _undo_occurrences(
        self, previous: list[Occurrence], copies: list[Occurrence], selected: Occurrence
    ) -> list[Occurrence]:
        surviving = {id(item) for item in self.occurrences if item is not selected}
        return [
            item if id(item) in surviving else copy
            for item, copy in zip(previous, copies, strict=True)
        ]

    def _credit(self, occurrence: Occurrence) -> None:
        for key in occurrence.word.keys:
            if key not in occurrence.credits:
                occurrence.credits[key] = self.store.credit(key)


def _appended_character(before: str, after: str) -> str:
    if len(after) == len(before) + 1 and after.startswith(before):
        return after[-1]
    return ""


def _previous_positions(occurrences: list[Occurrence], tokens: list[Word]) -> dict[int, int]:
    matching = SequenceMatcher(
        a=[item.word.text for item in occurrences],
        b=[token.text for token in tokens],
        autojunk=False,
    )
    return {
        block.b + offset: block.a + offset
        for block in matching.get_matching_blocks()
        for offset in range(block.size)
    }
