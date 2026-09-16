from __future__ import annotations

from PySide6.QtCore import QPoint, QRect

from gaze_mouse.gaze_bubble import GazeBubbleWindow
from gaze_mouse.interaction_overlay import InteractionOverlayWindow
from gaze_mouse.quick_action_menu import LEFT_CLICK, QuickActionRadialMenu
from gaze_mouse.quick_action_zoom import QuickActionZoomWindow


def test_gaze_bubble_tracks_points_and_respects_enabled_state(qtbot, monkeypatch):
    monkeypatch.setattr(
        "gaze_mouse.gaze_bubble.force_window_topmost", lambda *_args, **_kwargs: True
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


def test_interaction_overlay_progress_fire_and_clear(qtbot, monkeypatch):
    monkeypatch.setattr(
        "gaze_mouse.interaction_overlay.force_window_topmost", lambda *_args, **_kwargs: True
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
    monkeypatch.setattr("gaze_mouse.interaction_overlay.time.monotonic", lambda: 10.0)
    overlay._tick()
    assert overlay.isHidden()


def test_quick_action_menu_selects_stable_sector_by_gaze(qtbot, monkeypatch):
    monkeypatch.setattr(
        "gaze_mouse.quick_action_menu.force_window_topmost", lambda *_args, **_kwargs: True
    )
    menu = QuickActionRadialMenu()
    qtbot.addWidget(menu)
    selected = []
    menu.action_selected.connect(selected.append)
    menu.set_selection_settings(pause_ms=250, dwell_ms=150, radius_px=48)
    menu.show_at(QPoint(400, 300))
    times = iter((1.0, 1.249, 1.25, 1.4))
    monkeypatch.setattr("gaze_mouse.quick_action_menu.time.monotonic", lambda: next(times))

    menu.handle_gaze(QPoint(400, 200))
    menu.handle_gaze(QPoint(400, 200))
    menu.handle_gaze(QPoint(400, 200))
    menu.handle_gaze(QPoint(400, 200))

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
    times = iter((1.0, 1.249, 1.25, 1.4))
    monkeypatch.setattr("gaze_mouse.quick_action_zoom.time.monotonic", lambda: next(times))

    zoom.handle_gaze(QPoint(500, 400))
    zoom.handle_gaze(QPoint(500, 400))
    zoom.handle_gaze(QPoint(500, 400))
    zoom.handle_gaze(QPoint(500, 400))

    assert selected == [QPoint(190, 290)]
    assert zoom._selection_emitted is True
