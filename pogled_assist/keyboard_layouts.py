"""Script-specific keys; display labels never become Windows input payloads."""

from __future__ import annotations

import unicodedata

LATIN_SCRIPT = "latin"
ARABIC_SCRIPT = "arabic"
KEYBOARD_SCRIPTS = ((LATIN_SCRIPT, "Latinica"), (ARABIC_SCRIPT, "Arapski"))
BOSNIAN_LETTERS = [
    "A",
    "B",
    "C",
    "Č",
    "Ć",
    "D",
    "DŽ",
    "Đ",
    "E",
    "F",
    "G",
    "H",
    "I",
    "J",
    "K",
    "L",
    "LJ",
    "M",
    "N",
    "NJ",
    "O",
    "P",
    "R",
    "S",
    "Š",
    "T",
    "U",
    "V",
    "Z",
    "Ž",
]
ARABIC_LETTERS = list("ابتثجحخدذرزسشصضطظعغفقكلمنهويءآأؤإئةىٱ")
# The ordinary vowel/tanwin/shadda/sukun marks, extended hamza/maddah marks,
# dagger alif, and combining Quranic annotation signs. Store real Unicode,
# never Arabic Presentation Forms or a manually joined/shaped glyph.
ARABIC_MARKS = (
    [chr(code) for code in range(0x064B, 0x0660)]
    + ["ٰ"]
    + [
        chr(code)
        for code in range(0x06D6, 0x06EE)
        if unicodedata.category(chr(code)).startswith("M")
    ]
)
ARABIC_DIGITS = list("٠١٢٣٤٥٦٧٨٩")
ARABIC_SYMBOLS = list("1234567890") + ARABIC_DIGITS + list(".,،؟؛!:%٪-+/=()«»") + ARABIC_MARKS
SIDEBAR_GROUPS_PER_PAGE = 8


def letters_for_script(script: str) -> list[str]:
    return ARABIC_LETTERS if script == ARABIC_SCRIPT else BOSNIAN_LETTERS


def key_label(key: str) -> str:
    """Give a standalone combining mark a visible base without typing that base."""
    return "◌" + key if key and unicodedata.category(key[0]).startswith("M") else key


def group_label(keys: list[str], script: str) -> str:
    labels = [key_label(key) for key in keys]
    if script == ARABIC_SCRIPT:
        return "\n".join(" ".join(labels[index : index + 3]) for index in range(0, len(labels), 3))
    return " ".join(labels)


def switch_label(script: str) -> str:
    return "Latinica" if script == ARABIC_SCRIPT else "Arapski"


def other_script(script: str) -> str:
    return LATIN_SCRIPT if script == ARABIC_SCRIPT else ARABIC_SCRIPT


def symbols_for_script(script: str, latin_symbols: list[str] | tuple[str, ...]) -> list[str]:
    return (
        list(dict.fromkeys([*latin_symbols, *ARABIC_SYMBOLS]))
        if script == ARABIC_SCRIPT
        else list(latin_symbols)
    )


def numpad_for_script(script: str, latin_keys: list[str]) -> list[str]:
    return latin_keys + ARABIC_DIGITS if script == ARABIC_SCRIPT else latin_keys
