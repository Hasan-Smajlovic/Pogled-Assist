"""Settings page for reviewing learned words and forgetting one at a time."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QWidget

from ..suggestions.service import SuggestionService
from .settings_controls import SettingsControls, content_layout, global_rect, styled_label

WORDS_PER_PAGE = 6


class LearnedWordsPage(QFrame):
    """Page through learned words so one can be chosen and forgotten."""

    back_requested = Signal()
    status_changed = Signal(str)

    def __init__(
        self, controls: SettingsControls, suggestions: SuggestionService, parent: QWidget
    ) -> None:
        super().__init__(parent)
        self._controls = controls
        self._suggestions = suggestions
        self._word_page = 0
        self._chosen_word: str | None = None
        self._visible_words: list[str] = []
        self._busy = False
        self._last_gaze_point: QPoint | None = None
        self._held_button: QWidget | None = None
        self._build()
        suggestions.storage_finished.connect(self._saving_finished)

    def show_first_page(self) -> None:
        self._word_page = 0
        self._chosen_word = None
        self.refresh()

    def blocks_gaze_at(self, point: QPoint) -> bool:
        """Keep a word that changed under the gaze from firing until the gaze leaves it."""

        self._last_gaze_point = QPoint(point)
        if self._held_button is not None and global_rect(self._held_button).contains(point):
            return True
        self._held_button = None
        return False

    def refresh(self) -> None:
        self._hold_button_under_gaze()
        self._controls.interrupt_gaze()
        learned = self._suggestions.store.learned_words()
        pages = max(1, (len(learned) + WORDS_PER_PAGE - 1) // WORDS_PER_PAGE)
        self._word_page = min(self._word_page, pages - 1)
        start = self._word_page * WORDS_PER_PAGE
        self._visible_words = learned[start : start + WORDS_PER_PAGE]
        if self._chosen_word not in self._visible_words:
            self._chosen_word = None
        self._refresh_word_buttons()
        self._previous_button.setEnabled(self._word_page > 0 and not self._busy)
        self._next_button.setEnabled(self._word_page + 1 < pages and not self._busy)
        self._page_label.setText(f"{self._word_page + 1} / {pages}")
        self._forget_button.setEnabled(self._chosen_word is not None and not self._busy)
        self._retry_button.setEnabled(bool(self._suggestions.store.error) and not self._busy)
        self._selection_label.setText(self._selection_text(learned))
        self._status_label.setText(
            "Spremam promjenu…"
            if self._busy
            else self._suggestions.store.error or "Učenje je sačuvano."
        )

    def _build(self) -> None:
        layout = content_layout(self)
        header = QHBoxLayout()
        header.addWidget(styled_label("Naučene riječi", "sectionTitle", self), 1)
        header.addWidget(self._controls.button("Nazad", self.back_requested.emit, QSize(170, 58)))
        layout.addLayout(header)
        hint = QLabel(
            "Odaberite riječ, zatim Zaboravi riječ. Riječ iz osnovnog rječnika i dalje se može pojaviti u prijedlozima.",
            self,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        grid = QGridLayout()
        grid.setSpacing(12)
        self._word_buttons: list[QWidget] = []
        for index in range(WORDS_PER_PAGE):
            button = self._controls.tile_button(
                "·", lambda index=index: self._choose_word(index), QSize(170, 68)
            )
            grid.addWidget(button, index // 2, index % 2)
            self._word_buttons.append(button)
        layout.addLayout(grid, 1)
        self._selection_label = QLabel("Odaberite riječ.", self)
        self._selection_label.setWordWrap(True)
        layout.addWidget(self._selection_label)
        actions = QHBoxLayout()
        self._previous_button = self._controls.button(
            "Prethodna", lambda: self._change_page(-1), QSize(160, 58)
        )
        self._next_button = self._controls.button(
            "Sljedeća", lambda: self._change_page(1), QSize(160, 58)
        )
        self._page_label = QLabel("1 / 1", self)
        self._forget_button = self._controls.button(
            "Zaboravi riječ", self._forget_word, QSize(180, 58)
        )
        for widget in (
            self._previous_button,
            self._page_label,
            self._next_button,
            self._forget_button,
        ):
            actions.addWidget(widget)
        layout.addLayout(actions)
        self._status_label = QLabel("", self)
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)
        self._retry_button = self._controls.button(
            "Pokušaj ponovo", self._retry_saving, QSize(200, 58)
        )
        layout.addWidget(self._retry_button)
        self.refresh()

    def _hold_button_under_gaze(self) -> None:
        if self._last_gaze_point is None:
            return
        for button in self._word_buttons:
            if button.isVisible() and global_rect(button).contains(self._last_gaze_point):
                self._held_button = button
                return

    def _refresh_word_buttons(self) -> None:
        for index, button in enumerate(self._word_buttons):
            word = self._visible_words[index] if index < len(self._visible_words) else ""
            button.setText(word.upper() if word else "·")
            button.setAccessibleName(word.upper() if word else "Nema naučene riječi")
            button.setChecked(bool(word) and word == self._chosen_word)
            button.setEnabled(bool(word) and not self._busy)
            self._controls.rename(button, word.upper())

    def _selection_text(self, learned: list[str]) -> str:
        if self._chosen_word:
            return f"Odabrano: {self._chosen_word.upper()}"
        if learned:
            return "Odaberite riječ."
        if self._suggestions.store.error:
            return "Naučene riječi nisu učitane."
        return "Nema naučenih riječi."

    def _choose_word(self, index: int) -> None:
        if not self._busy and 0 <= index < len(self._visible_words):
            self._chosen_word = self._visible_words[index]
            self.refresh()

    def _change_page(self, delta: int) -> None:
        self._word_page = max(0, self._word_page + delta)
        self._chosen_word = None
        self.refresh()

    def _forget_word(self) -> None:
        if self._chosen_word is None or self._busy:
            return
        word = self._chosen_word
        self._busy = True
        self.refresh()
        self._suggestions.forget(word)

    def _retry_saving(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.refresh()
        self._suggestions.retry()

    def _saving_finished(self, successful: bool) -> None:
        was_busy = self._busy
        self._busy = False
        self.refresh()
        if was_busy:
            self.status_changed.emit(
                "Promjena je sačuvana."
                if successful
                else "Promjena nije sačuvana. Pokušajte ponovo."
            )
