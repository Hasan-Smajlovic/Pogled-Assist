"""Present only current speech predictions and guard replacements under gaze."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QPoint, Slot
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton

from ..suggestions.service import SuggestionService
from .speech_buttons import button_bounds


@dataclass(frozen=True)
class PredictionControls:
    input: QLineEdit
    label: QLabel
    buttons: list[QPushButton]
    undo: QPushButton


class SpeechPredictions(QObject):
    def __init__(
        self,
        controls: PredictionControls,
        service: SuggestionService,
        allowed: Callable[[], bool],
        context_changed: Callable[[], None],
    ) -> None:
        super().__init__(controls.input)
        self._controls = controls
        self._service = service
        self._allowed = allowed
        self._context_changed = context_changed
        self._owner = object()
        self._revision = 0
        self._text = ""
        self._last_gaze: QPoint | None = None
        self._blocked: QPushButton | None = None
        service.predictions_ready.connect(self._receive)
        service.status_changed.connect(self.show_status)

    def refresh(self, *, can_undo: bool) -> None:
        self._hold_under_gaze()
        self._revision += 1
        for button in self._controls.buttons:
            button.setEnabled(False)
        self._controls.undo.setEnabled(can_undo)
        self._context_changed()
        if self._allowed():
            self._text = self._controls.input.text()
            self._service.request(self._owner, self._revision, self._text)
        else:
            for button in self._controls.buttons:
                button.setText("·")
                button.setAccessibleName("Nema prijedloga")

    def allows_gaze(self, point: QPoint) -> bool:
        self._last_gaze = QPoint(point)
        if self._blocked is not None:
            if button_bounds(self._blocked).contains(point):
                return False
            self._blocked = None
        return True

    def allows_action(self, button: QPushButton | None) -> bool:
        if button is self._blocked:
            return False
        self._blocked = button
        return True

    def candidate(self, index: int) -> str | None:
        if not self._current_input():
            return None
        button = self._controls.buttons[index]
        return button.text() if button.isEnabled() else None

    @Slot(str)
    def show_status(self, message: str) -> None:
        self._controls.label.setText(f"Brzi izbor · {message}" if message else "Brzi izbor")
        self._controls.label.setToolTip(message)

    @Slot(object, int, list)
    def _receive(self, owner: object, revision: int, candidates: list[str]) -> None:
        if owner is not self._owner or revision != self._revision:
            return
        if not self._current_input():
            return
        for index, button in enumerate(self._controls.buttons):
            candidate = candidates[index].upper() if index < len(candidates) else ""
            button.setText(candidate or "·")
            button.setAccessibleName(candidate or "Nema prijedloga")
            button.setEnabled(bool(candidate))

    def _current_input(self) -> bool:
        return self._allowed() and self._controls.input.text() == self._text

    def _hold_under_gaze(self) -> None:
        if self._last_gaze is None:
            return
        for button in self._controls.buttons:
            if button_bounds(button).contains(self._last_gaze):
                self._blocked = button
                return
