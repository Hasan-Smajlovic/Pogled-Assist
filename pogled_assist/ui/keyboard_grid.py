"""Shared key cells and paging for the two sidebar keyboards."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QToolButton

from ..keyboard_layouts import ARABIC_SCRIPT, KeyboardGroupPage, group_label, key_label


class KeyboardGrid:
    def __init__(
        self,
        layout: QGridLayout,
        make_button: Callable[..., QToolButton],
        action: Callable[[str], str],
    ) -> None:
        self._layout = layout
        self._make_button = make_button
        self._action = action

    def add_groups(
        self,
        page: KeyboardGroupPage,
        script: str,
        action_prefix: str,
        *,
        columns: int,
        start_row: int = 0,
    ) -> None:
        arabic = script == ARABIC_SCRIPT
        for offset, group in enumerate(page.groups):
            button = self._make_button(
                group_label(group, script),
                self._action(f"{action_prefix}:{page.start + offset}"),
                "groupButton",
                dynamic=True,
            )
            button.setLayoutDirection(Qt.RightToLeft if arabic else Qt.LeftToRight)
            column = columns - 1 - offset % columns if arabic else offset % columns
            self._layout.addWidget(button, start_row + offset // columns, column)

    def add_keys(
        self,
        keys: list[str],
        action_prefix: str,
        *,
        columns: int,
        start_row: int = 0,
        reverse_columns: bool = False,
    ) -> None:
        for index, key in enumerate(keys):
            button = self._make_button(
                key_label(key),
                self._action(f"{action_prefix}:{index}"),
                "keyButton",
                dynamic=True,
            )
            column = columns - 1 - index % columns if reverse_columns else index % columns
            self._layout.addWidget(button, start_row + index // columns, column)

    def add_pages(self, page: KeyboardGroupPage, row: int, *, action: str, role: str) -> None:
        for column, (delta, label) in enumerate(((-1, "Prethodna"), (1, "Sljedeća"))):
            button = self._make_button(label, self._action(f"{action}:{delta}"), role, dynamic=True)
            button.setEnabled(0 <= page.index + delta < page.count)
            self._layout.addWidget(button, row, column)
