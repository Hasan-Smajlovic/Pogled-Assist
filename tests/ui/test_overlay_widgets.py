from __future__ import annotations

from _clock import freeze_monotonic
from PySide6.QtCore import QPoint, QRect

from pogled_assist.ui.gaze_bubble import GazeBubbleWindow
from pogled_assist.ui.interaction_overlay import InteractionOverlayWindow
from pogled_assist.ui.quick_action_menu import LEFT_CLICK, QuickActionMenu
from pogled_assist.ui.quick_action_zoom import QuickActionZoomWindow


def test_gaze_bubble_tracks_points_and_respects_enabled_state(qtbot, monkeypatch):
    monkeypatch.setattr(
        "pogled_assist.ui.gaze_bubble.force_window_topmost", lambda *_args, **_kwargs: True
    )
    monkeypatch.setattr(GazeBubbleWindow, "_apply_windows_click_through", lambda self: None)
    bubble = GazeBubbleWindow()
    qtbot.addWidget(bubble)

    bubble.handle_gaze(QPoint(300, 250))
    assert bubble.isVisible()
    assert bubble.pos() == QPoint(277, 227)

    bubble.set_enabled(False)
    assert bubble.isHidden()
    bubble.handle_gaze(QPoint(400, 350))
    assert bubble.isHidden()

    bubble.set_enabled(True)
    assert bubble.isVisible()
    assert bubble.pos() == QPoint(377, 327)


def test_gaze_bubble_keeps_its_interior_clear_with_a_visible_ring_and_center(qtbot):
    bubble = GazeBubbleWindow()
    qtbot.addWidget(bubble)
    bubble.handle_gaze(QPoint(300, 250))
    image = bubble.grab().toImage()
    scale = image.devicePixelRatio()

    for x, y in ((10, 23), (15, 23), (23, 10), (23, 15)):
        assert image.pixelColor(round(x * scale), round(y * scale)).alpha() == 0
    for x, y in ((23, 3), (23, 23)):
        assert image.pixelColor(round(x * scale), round(y * scale)).alpha() > 200


def test_interaction_overlay_progress_fire_and_clear(qtbot, monkeypatch):
    monkeypatch.setattr(
        "pogled_assist.ui.interaction_overlay.force_window_topmost", lambda *_args, **_kwargs: True
    )
    monkeypatch.setattr(InteractionOverlayWindow, "_apply_windows_click_through", lambda self: None)
    overlay = InteractionOverlayWindow()
    qtbot.addWidget(overlay)

    overlay.show_progress(QPoint(400, 300), 1.5, "Dvostruki lijevi klik")
    assert overlay.isVisible()
    assert overlay._mode == "progress"
    assert overlay._progress == 1.0
    assert overlay._label == "Dvostruki"

    overlay.clear()
    assert overlay.isHidden()
    overlay.show_fired(QPoint(200, 100), "Lijevi klik")
    assert overlay._mode == "fired"
    assert overlay._progress == 1.0
    overlay._fired_started_ms = 0
    freeze_monotonic(monkeypatch, 10.0)
    overlay._tick()
    assert overlay.isHidden()


def test_gaze_bubble_expires_without_fresh_positions(qtbot, monkeypatch):
    now = freeze_monotonic(monkeypatch, 10.0)
    monkeypatch.setattr(
        "pogled_assist.ui.gaze_bubble.force_window_topmost", lambda *_args, **_kwargs: True
    )
    bubble = GazeBubbleWindow()
    qtbot.addWidget(bubble)
    point = QPoint(300, 250)
    bubble.handle_gaze(point)

    now[0] = 10.4
    bubble.handle_gaze(point)
    now[0] = 10.899
    bubble._refresh_windows_topmost()
    assert bubble.isVisible()
    now[0] = 10.9
    bubble._refresh_windows_topmost()
    assert bubble.isHidden()
    assert not bubble._topmost_timer.isActive()

    bubble.set_enabled(False)
    bubble.set_enabled(True)
    assert bubble.isHidden()
    bubble.handle_gaze(QPoint(600, 450))
    assert bubble.isVisible()
    assert bubble.pos() == QPoint(577, 427)


def test_enabling_gaze_bubble_rejects_stale_points_received_while_hidden(qtbot, monkeypatch):
    now = freeze_monotonic(monkeypatch, 10.0)
    bubble = GazeBubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_enabled(False)
    bubble.handle_gaze(QPoint(300, 250))
    now[0] = 11.0
    bubble.set_enabled(True)
    assert bubble.isHidden()


def test_quick_action_menu_selects_stable_tile_by_gaze(qtbot, monkeypatch):
    monkeypatch.setattr(
        "pogled_assist.ui.quick_action_menu.force_window_topmost", lambda *_args, **_kwargs: True
    )
    menu = QuickActionMenu()
    qtbot.addWidget(menu)
    selected = []
    menu.action_selected.connect(selected.append)
    menu.set_selection_settings(pause_ms=250, dwell_ms=150, radius_px=48)
    menu.show_at(QPoint(400, 300))
    now = freeze_monotonic(monkeypatch, 1.0)

    tile = menu.tile_rect(LEFT_CLICK)
    for at, point in (
        (1.0, tile.center()),
        (1.249, tile.topLeft()),
        (1.25, tile.center()),
        (1.4, tile.bottomRight()),
    ):
        now[0] = at
        menu.handle_gaze(point)

    assert selected == [LEFT_CLICK]
    assert menu._selection_emitted is True


def test_quick_action_zoom_maps_and_selects_stable_gaze_target(qtbot, monkeypatch):
    zoom = QuickActionZoomWindow()
    qtbot.addWidget(zoom)
    zoom.set_selection_settings(pause_ms=250, dwell_ms=150, radius_px=48)
    zoom._screen_geometry = QRect(0, 0, 1000, 800)
    zoom._source_rect = QRect(100, 200, 180, 180)
    zoom._display_rect = QRect(230, 130, 540, 540)
    zoom.show()
    selected = []
    zoom.target_selected.connect(lambda point: selected.append(QPoint(point)))
    now = freeze_monotonic(monkeypatch, 1.0)

    for at in (1.0, 1.249, 1.25, 1.4):
        now[0] = at
        zoom.handle_gaze(QPoint(500, 400))

    assert selected == [QPoint(190, 290)]
    assert zoom._selection_emitted is True
