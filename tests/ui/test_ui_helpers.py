from __future__ import annotations

import sys

import pytest
from PySide6.QtCore import QPoint, QRect

from pogled_assist.interaction.mouse_controller import (
    DOUBLE_LEFT_CLICK,
    LEFT_CLICK,
    PRESS_ENTER,
    RIGHT_CLICK,
    SCROLL_DOWN,
    SCROLL_UP,
    TYPE_HERE,
)
from pogled_assist.ui import quick_action_menu as menu_module
from pogled_assist.ui.interaction_overlay import _compact_label
from pogled_assist.ui.quick_action_menu import (
    CANCEL_QUICK_ACTION,
    QuickActionMenu,
    grid_rect_around,
)
from pogled_assist.ui.quick_action_zoom import _centered_square, _square_around


def test_zoom_squares_stay_inside_screen_bounds():
    bounds = QRect(100, 200, 800, 600)

    assert _square_around(QPoint(100, 200), 180, bounds) == QRect(100, 200, 180, 180)
    assert _square_around(QPoint(899, 799), 180, bounds) == QRect(720, 620, 180, 180)
    assert _centered_square(bounds, 540) == QRect(130, 30, 540, 540)


def test_quick_menu_grid_maps_each_tile_and_leaves_the_centre_empty(qapp):
    menu = QuickActionMenu()
    menu._center_global = QPoint(640, 360)
    menu._grid_global = grid_rect_around(QPoint(640, 360), QRect(0, 0, 1280, 720))
    # Three columns of 150 px and three rows of 190 px with 12 px gaps, centred on the point.
    assert menu._grid_global == QRect(403, 63, 474, 594)
    layout = {
        (0, 0): TYPE_HERE,
        (0, 1): LEFT_CLICK,
        (0, 2): SCROLL_UP,
        (1, 0): CANCEL_QUICK_ACTION,
        (1, 2): RIGHT_CLICK,
        (2, 0): PRESS_ENTER,
        (2, 1): DOUBLE_LEFT_CLICK,
        (2, 2): SCROLL_DOWN,
    }
    for (row, column), action in layout.items():
        rect = menu.tile_rect(action)
        assert (rect.width(), rect.height()) == (150, 190)
        assert rect.topLeft() == QPoint(403 + column * 162, 63 + row * 202)
        assert menu._action_for_global_point(rect.center()) == action
    assert menu._action_for_global_point(QPoint(640, 360)) is None
    # Each half of a gap belongs to the tile beside it; the half next to the centre stays empty.
    assert menu._action_for_global_point(QPoint(558, 100)) == TYPE_HERE
    assert menu._action_for_global_point(QPoint(559, 100)) == LEFT_CLICK
    assert menu._action_for_global_point(QPoint(640, 258)) == LEFT_CLICK
    assert menu._action_for_global_point(QPoint(640, 260)) is None
    assert menu._action_for_global_point(QPoint(10, 10)) is None


def test_quick_menu_grid_shifts_inside_the_screen_near_edges():
    bounds = QRect(0, 0, 1280, 720)

    assert grid_rect_around(QPoint(0, 0), bounds) == QRect(8, 8, 474, 594)
    assert grid_rect_around(QPoint(1279, 719), bounds) == QRect(798, 118, 474, 594)


def test_quick_menu_labels_are_20_px_bold_and_fit_on_one_line(qapp):
    from PySide6.QtGui import QFontInfo, QFontMetrics

    font = menu_module._label_font()
    # Windows CI measures the shipped Segoe UI; other platforms measure a fallback font.
    if sys.platform == "win32":
        assert QFontInfo(font).family() == "Segoe UI"
    assert font.bold()
    assert font.pixelSize() >= 20
    metrics = QFontMetrics(font)
    grid = grid_rect_around(QPoint(640, 360), QRect(0, 0, 1280, 720))
    for tile in menu_module.TILES:
        label = menu_module._menu_label(tile.action)
        cell = menu_module._cell_rect(grid, tile.row, tile.column)
        assert metrics.horizontalAdvance(label) <= menu_module._label_rect(cell).width(), label


def test_quick_menu_requires_leaving_the_tile_under_the_point_at_an_edge(qtbot, monkeypatch):
    monkeypatch.setattr(
        "pogled_assist.ui.quick_action_menu.force_window_topmost", lambda *_args, **_kwargs: True
    )
    menu = QuickActionMenu()
    qtbot.addWidget(menu)
    menu.set_selection_settings(pause_ms=150, dwell_ms=150, radius_px=48)
    corner = menu.screen().geometry().topLeft() + QPoint(20, 20)
    menu.show_at(corner)
    assert menu._action_for_global_point(corner) == TYPE_HERE

    menu.handle_gaze(corner)
    assert menu._candidate_action is None
    menu.handle_gaze(menu.tile_rect(LEFT_CLICK).center())
    menu.handle_gaze(corner)
    assert menu._candidate_action == TYPE_HERE


@pytest.mark.parametrize("release", ["centre", "tile"])
def test_quick_menu_edge_gaze_outside_the_grid_keeps_the_point_tile_blocked(
    qtbot, monkeypatch, release
):
    from _clock import freeze_monotonic

    monkeypatch.setattr(
        "pogled_assist.ui.quick_action_menu.force_window_topmost", lambda *_args, **_kwargs: True
    )
    menu = QuickActionMenu()
    qtbot.addWidget(menu)
    menu.set_selection_settings(pause_ms=150, dwell_ms=150, radius_px=48)
    selected = []
    menu.action_selected.connect(selected.append)
    screen = menu.screen().geometry()
    # Bottom-left corner, where the Start button is: the point lies on Potvrdi (Enter).
    point = QPoint(screen.left() + 20, screen.bottom() - 20)
    menu.show_at(point)
    assert menu._action_for_global_point(point) == PRESS_ENTER
    now = freeze_monotonic(monkeypatch, 1.0)

    def hold(target, seconds):
        for _ in range(round(seconds / 0.05)):
            now[0] += 0.05
            menu.handle_gaze(target)

    # Gaze clamped to the screen edge lands in the margin outside the grid.
    hold(QPoint(screen.left(), point.y()), 0.05)
    hold(point, 1.0)
    assert selected == []

    elsewhere = (
        menu.tile_rect(LEFT_CLICK).center()
        if release == "tile"
        else menu_module._cell_rect(menu._grid_global, 1, 1).center()
    )
    hold(elsewhere, 0.05)
    hold(point, 1.0)
    assert selected == [PRESS_ENTER]


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Dvostruki klik", "Dvostruki"),
        ("Dvostruki lijevi klik", "Dvostruki"),
        ("Brza radnja", "Brza radnja"),
        ("Cilj uvećanja", "Cilj uvećanja"),
        ("Postavke", "Postavke"),
    ],
)
def test_interaction_labels_are_compact(label, expected):
    assert _compact_label(label) == expected
