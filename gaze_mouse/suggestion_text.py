"""Bosnian word boundaries shared by preparation, prediction, and learning."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

START = "<s>"
LETTERS = frozenset("abcčćdđefghijklmnoprsštuvzž")
BASE_LETTER = r"[^\W\d_]"
COMBINING_MARKS = r"[\u0300-\u036f]*"
WORD_PART = rf"{BASE_LETTER}{COMBINING_MARKS}(?:{BASE_LETTER}{COMBINING_MARKS})*"
WORD = re.compile(rf"{WORD_PART}(?:['\u2019]{WORD_PART})?", re.UNICODE)
BOUNDARY = re.compile(r"[.?!\n]")


@dataclass(frozen=True)
class Word:
    text: str
    start: int
    end: int
    context: tuple[str, ...]

    @property
    def keys(self) -> tuple[tuple[str, ...], ...]:
        return (
            (self.text,),
            *((*self.context[-n:], self.text) for n in range(1, len(self.context) + 1)),
        )


def spelling(value: str) -> str:
    return unicodedata.normalize("NFC", value).lower().replace("\u2019", "'")


def valid_word(value: str) -> bool:
    parts = value.split("'")
    return (
        0 < len(value) <= 32
        and 1 <= len(parts) <= 2
        and all(part and all(letter in LETTERS for letter in part) for part in parts)
    )


def words(text: str) -> list[Word]:
    result = []
    context = (START,)
    end = 0
    for match in WORD.finditer(text):
        gap = text[end : match.start()]
        if BOUNDARY.search(gap) or any(character.isdigit() for character in gap):
            context = (START,)
        value = spelling(match.group())
        end = match.end()
        if not valid_word(value):
            context = (START,)
            continue
        result.append(Word(value, match.start(), end, context))
        context = (*context, value)[-2:]
    return result


def query(text: str) -> tuple[str, tuple[str, ...], int] | None:
    """Return the prefix, preceding context, and replacement start in original text."""
    tokens = words(text)
    if tokens and tokens[-1].end == len(text):
        last = tokens[-1]
        return last.text, last.context, last.start
    tail = text[tokens[-1].end :] if tokens else text
    if tail and not all(character.isspace() or character in ".,?!" for character in tail):
        return None
    if not tokens or BOUNDARY.search(tail):
        return "", (START,), len(text)
    return "", (*tokens[-1].context, tokens[-1].text)[-2:], len(text)


def insert_word(text: str, candidate: str) -> str:
    request = query(text)
    if request is None or not valid_word(spelling(candidate)):
        return text
    prefix, _context, start = request
    before = text[:start]
    if not prefix and before and not before[-1].isspace():
        before += " "
    return before + spelling(candidate).upper() + " "


def index_key(value: str) -> str:
    return (
        spelling(value)
        .replace("'", "")
        .translate(str.maketrans("čćđšž", "ccdsz"))
        .replace("dj", "d")
    )


def prefix_pattern(prefix: str) -> re.Pattern[str]:
    value = spelling(prefix).replace("'", "")
    pattern = []
    index = 0
    while index < len(value):
        if value[index : index + 2] == "dj":
            pattern.append("(?:dj|đ)")
            index += 2
        else:
            pattern.append(
                {"c": "[cčć]", "d": "[dđ]", "s": "[sš]", "z": "[zž]"}.get(
                    value[index], re.escape(value[index])
                )
            )
            index += 1
    return re.compile("^" + "'?".join(pattern))
