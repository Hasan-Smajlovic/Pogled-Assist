from __future__ import annotations

from dataclasses import replace

import pytest
from _hotbar_fixtures import hotbar_gaze as hotbar_gaze
from _hotbar_fixtures import use_letter_groups
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QWidget

from pogled_assist.keyboard_layouts import ARABIC_SCRIPT

# Selection-ring rules from docs/UI_DEVELOPMENT.md, checked on the painted overlay
# after real gaze samples reach each control through the hotbar.
MAX_RING_PX = 64
EDGE_CLEARANCE_PX = 8
# Antialiased edge pixels below this alpha are not visible on the dark controls.
VISIBLE_ALPHA = 64
PAUSE_MS = 500
DWELL_MS = 500
SAMPLE_MS = 50


@pytest.mark.e2e
@pytest.mark.parametrize("view", ["letters", "groups", "inline-letters", "library", "arabic"])
def test_speech_selection_rings_stay_inside_their_controls(hotbar_gaze, qtbot, view):
    hotbar, rings = _ring_probe(hotbar_gaze)
    if view in {"groups", "inline-letters"}:
        use_letter_groups(hotbar)
    if view == "arabic":
        hotbar._update_speech_settings(
            replace(hotbar._speech.settings, keyboard_script=ARABIC_SCRIPT)
        )
    hotbar._open_speech()
    window = hotbar._speech_window
    window.showNormal()
    window.setGeometry(*hotbar._mouse._logical_screen_rect)
    qtbot.waitUntil(window.isVisible)
    if view == "inline-letters":
        window._action_buttons[window._action("group:0")].click()
    elif view == "library":
        window._action_buttons[window._action("phrases")].click()
    qtbot.wait(1)

    _check_rings(rings, _sidebar_targets(window))


@pytest.mark.e2e
@pytest.mark.parametrize("script", ["latin", ARABIC_SCRIPT])
def test_keyboard_selection_rings_stay_inside_their_controls(hotbar_gaze, qtbot, script):
    hotbar, rings = _ring_probe(hotbar_gaze)
    hotbar._update_speech_settings(replace(hotbar._speech.settings, keyboard_script=script))
    hotbar._show_keyboard_sidebar()
    window = hotbar._keyboard_window
    qtbot.waitUntil(window.isVisible)
    for show_tab in (window._show_letter_groups, window._show_numpad, window._show_symbols):
        show_tab()
        qtbot.wait(1)
        _check_rings(rings, _sidebar_targets(window))


@pytest.mark.e2e
@pytest.mark.parametrize("tab", range(4), ids=["general", "gaze", "speech", "support"])
def test_settings_selection_rings_stay_inside_their_controls(hotbar_gaze, qtbot, tab):
    hotbar, rings = _ring_probe(hotbar_gaze)
    hotbar._open_settings()
    window = hotbar._settings_window
    window.showNormal()
    window.setGeometry(*hotbar._mouse._logical_screen_rect)
    qtbot.waitUntil(window.isVisible)
    window._select_tab(tab)
    qtbot.wait(1)
    targets = []
    for widget in window._controls._actions:
        if not (widget.isVisible() and widget.isEnabled()):
            continue
        center = widget.mapToGlobal(widget.rect().center())
        found = window._controls.action_at(center)
        # Scrolled-away controls cannot be selected at their centre.
        if found is not None and found[0] is widget:
            targets.append((window._controls.name(widget), widget))

    _check_rings(rings, targets)


@pytest.mark.e2e
def test_hotbar_selection_rings_stay_inside_their_controls(hotbar_gaze):
    hotbar, rings = _ring_probe(hotbar_gaze)

    _check_rings(rings, [(action, button) for action, button in hotbar._buttons.items()])


def _sidebar_targets(window) -> list[tuple[str, QWidget]]:
    return [
        (action, button)
        for action, button in window._action_buttons.items()
        if window.action_bounds(action) is not None
    ]


def _ring_probe(hotbar_gaze):
    hotbar, controller, feed, actions, progress = hotbar_gaze
    assert (controller.settings.selection_pause_ms, controller.settings.dwell_ms) == (
        PAUSE_MS,
        DWELL_MS,
    )
    overlay = hotbar._interaction_overlay
    clock = [0]

    def rings(button: QWidget) -> dict[str, QRect | None]:
        """Look at the control's centre with real gaze; return active and paused ring bounds."""

        center = button.mapToGlobal(button.rect().center())
        overlay.clear()
        progress.clear()
        # Steady 50 ms samples, like the tracker, until the ring is half full.
        for _ in range((PAUSE_MS + DWELL_MS) // SAMPLE_MS):
            clock[0] += SAMPLE_MS
            feed(center, clock[0])
            if progress and progress[-1] >= 0.5:
                break
        assert actions == []
        painted = {}
        for state in ("active", "paused"):
            overlay.set_paused(state == "paused")
            bounds = _painted_bounds(overlay.grab().toImage()) if overlay.isVisible() else None
            painted[state] = bounds.translated(overlay.pos()) if bounds is not None else None
        return painted

    return hotbar, rings


def _check_rings(rings, targets) -> None:
    assert targets
    problems = []
    for name, button in targets:
        control = QRect(button.mapToGlobal(QPoint(0, 0)), button.size())
        allowed = control.adjusted(
            EDGE_CLEARANCE_PX, EDGE_CLEARANCE_PX, -EDGE_CLEARANCE_PX, -EDGE_CLEARANCE_PX
        )
        for state, painted in rings(button).items():
            if painted is None:
                problems.append(f"{name} {control.getRect()} {state}: no ring")
            elif (
                painted.width() > MAX_RING_PX
                or painted.height() > MAX_RING_PX
                or not allowed.contains(painted)
            ):
                problems.append(f"{name} {control.getRect()} {state}: ring {painted.getRect()}")
    assert problems == []


def _painted_bounds(image: QImage) -> QRect | None:
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    width, height = image.width(), image.height()
    alpha = bytes(image.constBits())[3::4]
    rows = [y for y in range(height) if max(alpha[y * width : (y + 1) * width]) >= VISIBLE_ALPHA]
    if not rows:
        return None
    columns = [x for x in range(width) if max(alpha[x::width]) >= VISIBLE_ALPHA]
    scale = image.devicePixelRatio()
    return QRect(
        int(columns[0] / scale),
        int(rows[0] / scale),
        int((columns[-1] - columns[0] + 1) / scale),
        int((rows[-1] - rows[0] + 1) / scale),
    )
