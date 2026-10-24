"""Steady visual feedback for gaze-targeted controls."""

from PySide6.QtWidgets import QWidget


def set_gaze_feedback(widget: QWidget, active: bool) -> None:
    widget.setProperty("gazeTarget", active)
    if not active:
        widget.setProperty("gazePaused", False)
    _refresh_style(widget)


def set_gaze_paused(widget: QWidget, paused: bool) -> None:
    widget.setProperty("gazePaused", paused)
    _refresh_style(widget)


def _refresh_style(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
