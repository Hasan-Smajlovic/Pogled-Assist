"""Shared visual feedback for gaze-targeted controls."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget


def set_gaze_feedback(widget: QWidget, active: bool) -> None:
    """Toggle a pulsing gaze-target style on a widget."""

    timer = _feedback_timer(widget)
    if active:
        widget.setProperty("gazeTarget", True)
        widget.setProperty("gazePulse", "0")
        _refresh_style(widget)
        if not timer.isActive():
            timer.start()
        return

    timer.stop()
    widget.setProperty("gazeTarget", False)
    widget.setProperty("gazePulse", "")
    _refresh_style(widget)


def _feedback_timer(widget: QWidget) -> QTimer:
    timer = getattr(widget, "_gaze_feedback_timer", None)
    if timer is not None:
        return timer

    timer = QTimer(widget)
    timer.setInterval(180)
    timer.timeout.connect(lambda target=widget: _toggle_pulse(target))
    widget._gaze_feedback_timer = timer
    return timer


def _toggle_pulse(widget: QWidget) -> None:
    if not widget.property("gazeTarget"):
        return

    current = str(widget.property("gazePulse") or "0")
    widget.setProperty("gazePulse", "1" if current == "0" else "0")
    _refresh_style(widget)


def _refresh_style(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
