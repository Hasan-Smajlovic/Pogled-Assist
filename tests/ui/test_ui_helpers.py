from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QRect

from pogled_assist.toolbar import _tracker_dot_state
from pogled_assist.ui.interaction_overlay import _compact_label
from pogled_assist.ui.quick_action_menu import CANCEL_QUICK_ACTION, QuickActionRadialMenu
from pogled_assist.ui.quick_action_zoom import _centered_square, _square_around


def test_zoom_squares_stay_inside_screen_bounds():
    bounds = QRect(100, 200, 800, 600)

    assert _square_around(QPoint(100, 200), 180, bounds) == QRect(100, 200, 180, 180)
    assert _square_around(QPoint(899, 799), 180, bounds) == QRect(720, 620, 180, 180)
    assert _centered_square(bounds, 540) == QRect(130, 30, 540, 540)


def test_radial_menu_maps_each_direction_to_an_action(qapp):
    menu = QuickActionRadialMenu()
    menu._center_global = QPoint(500, 500)

    assert menu._action_for_global_point(QPoint(500, 300)) == "left_click"
    assert menu._action_for_global_point(QPoint(700, 500)) == "right_click"
    assert menu._action_for_global_point(QPoint(500, 700)) == "double_left_click"
    assert menu._action_for_global_point(QPoint(300, 500)) == CANCEL_QUICK_ACTION
    assert menu._action_for_global_point(QPoint(500, 500)) is None
    assert menu._action_for_global_point(QPoint(500, 500), allow_center=True) == CANCEL_QUICK_ACTION


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


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("Praćenje je aktivno putem uređaja Tobii Eye Tracker 4C.", "green"),
        ("Pokušavam Stream Engine.", "yellow"),
        ("Uređaj nije pronađen", "red"),
        ("idle", "yellow"),
    ],
)
def test_tracker_dot_state(status, expected):
    assert _tracker_dot_state(status) == expected
