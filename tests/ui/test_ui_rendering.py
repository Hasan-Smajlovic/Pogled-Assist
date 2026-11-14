from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QWidget

from scripts.ui.capture_ui import capture_ui
from scripts.ui.gallery import CORE_NAMES


@pytest.mark.e2e
def test_representative_ui_preview_surfaces_render(qapp, tmp_path, monkeypatch):
    size = (1280, 720)
    from scripts.ui import capture_ui as preview

    capture_widget = preview._capture_widget
    capture_state = preview._CaptureSession.capture
    encountered = set()

    def check_state(session, widget, name, title, **kwargs):
        encountered.add(name)
        if name == "diagnostics-error":
            assert "Razlog: Greška zapisivanja" in widget._detail.text()
            assert "Greške: 1" in widget._detail.text()
        if name == "gaze-check-one-eye-free":
            assert widget._phase == "free"
            assert widget._target.gaze_point is not None
        capture_state(session, widget, name, title, **kwargs)

    def capture_with_script_control_check(app, widget, output_dir, name, size):
        snapshot = capture_widget(app, widget, output_dir, name, size)
        if name == "keyboard-latin-paged":
            assert widget._active_tab == "letters"
            first_group = widget._action_buttons[widget._action("group:0")]
            next_page = widget._action_buttons[widget._action("group-page:1")]
            assert first_group.isVisible()
            assert first_group.text() == "A B"
            assert next_page.isVisible()
            assert next_page.isEnabled()
        return snapshot

    monkeypatch.setattr(preview, "_capture_widget", capture_with_script_control_check)
    monkeypatch.setattr(preview._CaptureSession, "capture", check_state)
    gallery_root = os.environ.get("POGLED_ASSIST_UI_GALLERY")
    output_dir = Path(gallery_root) / f"{size[0]}x{size[1]}" if gallery_root else tmp_path
    output_dir.mkdir(parents=True, exist_ok=True)
    omitted = output_dir / "speech-voice-timeout.png"
    previous = QImage(380, 70, QImage.Format.Format_RGB32)
    previous.fill(0)
    assert previous.save(str(omitted))
    unrelated = output_dir / "review-notes.txt"
    unrelated.write_bytes(b"leave caller files alone")
    snapshots = capture_ui(output_dir, width=size[0], height=size[1])

    assert len(snapshots) == 71
    assert {path.stem for path in snapshots} == CORE_NAMES
    assert len(encountered) == 153  # Extended states remain available without PNG encoding.
    assert not omitted.exists()
    assert unrelated.read_bytes() == b"leave caller files alone"
    unrelated.unlink()  # Keep the CI artifact limited to actual previews.
    assert (output_dir / "index.html").is_file()
    for snapshot in snapshots:
        image = QImage(str(snapshot))
        assert not image.isNull(), snapshot.name
        assert image.width() >= (200 if snapshot.name.startswith("information-") else 380), (
            snapshot.name
        )
        assert image.height() >= 70, snapshot.name
        if snapshot.name.startswith(("settings-", "gaze-check-")):
            assert (image.width(), image.height()) == (1280, 720), snapshot.name
        if snapshot.name == "keyboard-latin-paged.png":
            assert (image.width(), image.height()) == (380, 640), snapshot.name


@pytest.mark.e2e
def test_full_gallery_shows_quick_actions_precision_zoom_and_gaze_marker(qapp, tmp_path):
    from PySide6.QtCore import QPoint, QRect

    from pogled_assist.ui import quick_action_menu as menu_module
    from pogled_assist.ui import quick_action_zoom as zoom_module
    from pogled_assist.ui.gaze_bubble import GazeBubbleWindow
    from pogled_assist.ui.quick_action_zoom import QuickActionZoomWindow
    from scripts.ui.capture_pointer_overlays import MARKER_SCENE_SIZE, PreviewDesktop

    snapshots = {
        path.stem: QImage(str(path))
        for path in capture_ui(tmp_path, profile="full", groups=("tracking",))
    }
    overlays = {"quick-actions-menu", "quick-actions-menu-edge", "precision-zoom", "gaze-marker"}
    assert overlays <= snapshots.keys()
    # CI renders the main Quick actions grid; the other overlays are review states only.
    assert overlays & CORE_NAMES == {"quick-actions-menu"}
    desktop = PreviewDesktop((1280, 720))
    desktop.show()
    qapp.processEvents()
    target = desktop.target()
    document = desktop.findChild(QWidget, "previewDocument").geometry()
    desktop.close()

    # Quick actions opens a 3x3 grid around the gaze target; the centre shows the point.
    menu = snapshots["quick-actions-menu"]
    grid = menu_module.grid_rect_around(target, QRect(0, 0, 1280, 720))

    def tile(row, column):
        return menu_module._cell_rect(grid, row, column)

    assert tile(1, 1).contains(target)
    assert _is_white(menu.pixelColor(target))

    def fill(row, column):
        return menu.pixelColor(tile(row, column).topLeft() + QPoint(16, 16)).name()

    # Only the looked-at left click tile is selected; Odustani keeps its muted red tone.
    assert fill(0, 1) == "#2e6478"
    assert fill(1, 0) == "#2b1f27"
    assert {fill(0, 0), fill(0, 2), fill(1, 2), fill(2, 0), fill(2, 1), fill(2, 2)} == {"#283442"}
    # The shared selection ring surrounds the same icon as the tile's own arc and leaves
    # the label below it clear.
    icon = menu_module._icon_rect(tile(0, 1)).center()
    assert any(_is_shared_ring(menu.pixelColor(icon + QPoint(r, 0))) for r in range(24, 37))
    label_top = tile(0, 1).center().y() + 12
    assert not any(
        _is_shared_ring(menu.pixelColor(QPoint(x, label_top + 6)))
        for x in range(icon.x() - 40, icon.x() + 41)
    )

    # Near a corner the whole grid shifts inside the screen and the point stays marked.
    edge = snapshots["quick-actions-menu-edge"]
    corner_grid = menu_module.grid_rect_around(QPoint(60, 40), QRect(0, 0, 1280, 720))
    assert corner_grid.topLeft() == QPoint(8, 8)
    assert _is_white(edge.pixelColor(QPoint(60, 40)))
    bottom_right = menu_module._cell_rect(corner_grid, 2, 2)
    assert edge.pixelColor(bottom_right.topLeft() + QPoint(16, 16)).name() == "#283442"

    # Precision zoom magnifies the area around the target three times over a dimmed desktop.
    zoom = snapshots["precision-zoom"]
    screen = QRect(0, 0, 1280, 720)
    source = zoom_module._square_around(target, QuickActionZoomWindow.SOURCE_SIZE, screen)
    display = zoom_module._centered_square(screen, QuickActionZoomWindow.DISPLAY_SIZE)
    scale = display.width() / source.width()
    crosshair = display.center()
    assert any(_is_shared_ring(zoom.pixelColor(crosshair + QPoint(r, 0))) for r in range(24, 37))

    def magnified(point):
        return display.topLeft() + (point - source.topLeft()) * scale

    inside = QPoint(document.right() - 40, document.bottom() - 60)
    outside = QPoint(document.right() + 30, document.bottom() + 30)
    assert source.contains(inside) and source.contains(outside)
    assert zoom.pixelColor(magnified(inside)).lightness() > 220  # Undimmed document
    assert zoom.pixelColor(magnified(outside)).lightness() < 60  # Desktop beside it
    edge = magnified(QPoint(document.right(), target.y() - 50))
    assert zoom.pixelColor(edge - QPoint(6, 0)).lightness() > 220  # Edge drawn 3x larger
    assert zoom.pixelColor(edge + QPoint(6, 0)).lightness() < 60
    beside_square = QPoint(display.left() - 20, document.top() + 120)
    assert document.contains(beside_square)
    assert 90 < zoom.pixelColor(beside_square).lightness() < 180  # Dimmed document

    # The 46-pixel marker keeps a clear centre over light text and the dark desktop.
    small = PreviewDesktop(MARKER_SCENE_SIZE)
    marker = snapshots["gaze-marker"]
    center = small.document_edge()
    small.close()
    assert _is_white(marker.pixelColor(center))
    assert marker.pixelColor(center + QPoint(12, 0)).lightness() > 220
    assert marker.pixelColor(center - QPoint(12, 0)).lightness() < 60
    ring = marker.pixelColor(center - QPoint(0, 20))
    assert ring.blue() > ring.red() + 40  # Light-blue ring
    assert center.x() >= GazeBubbleWindow.BUBBLE_SIZE // 2  # The whole marker is in the image.


def _is_white(color) -> bool:
    return min(color.red(), color.green(), color.blue()) > 215


def _is_shared_ring(color) -> bool:
    """Match the filled arc of the shared selection ring (#84c5d9)."""

    return abs(color.red() - 0x84) + abs(color.green() - 0xC5) + abs(color.blue() - 0xD9) < 24


def test_gallery_profiles_filter_before_grabbing_widgets(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QWidget

    from scripts.ui import capture_ui as preview
    from scripts.ui.gallery import select_names

    grabbed = []

    def grab(app, widget, output_dir, name, size):
        grabbed.append(name)
        return output_dir / f"{name}.png"

    monkeypatch.setattr(preview, "_capture_widget", grab)
    widget = QWidget()
    for profile, groups, expected in (
        ("core", (), ["speech"]),
        ("full", (), ["speech", "speech-voice-timeout", "settings-elevenlabs-invalid"]),
        ("full", ("voice",), ["speech-voice-timeout", "settings-elevenlabs-invalid"]),
        ("core", ("voice",), []),
    ):
        grabbed.clear()
        session = preview._CaptureSession(
            qapp, tmp_path, (1280, 720), select_names(profile, groups), groups
        )
        for name in ("speech", "speech-voice-timeout", "settings-elevenlabs-invalid"):
            session.capture(widget, name, name)
        assert grabbed == expected
    dispatched = []
    QTimer.singleShot(0, lambda: dispatched.append(True))
    session.capture(widget, "gaze-check-precision", "Fixation target")
    assert dispatched == [True]  # Omitted states must still finish deferred Qt setup.
    widget.close()


@pytest.mark.e2e
@pytest.mark.parametrize("phase", ["precision", "trial", "free"])
def test_capture_keeps_active_gaze_check_when_native_reshow_delivers_resize(qapp, tmp_path, phase):
    from PySide6.QtGui import QResizeEvent

    from pogled_assist.interaction.mouse_controller import GazeSettings
    from pogled_assist.ui.gaze_check_window import GazeCheckWindow
    from scripts.ui.capture_ui import _capture_widget

    class NativeResizeCheck(GazeCheckWindow):
        def showEvent(self, event):
            super().showEvent(event)
            if self._phase in ("precision", "trial", "free"):
                # Windows can deliver a resize on re-show even at the same size.
                qapp.sendEvent(self, QResizeEvent(self.size(), self.size()))

    window = NativeResizeCheck(GazeSettings())
    window.resize(1280, 720)
    window.show()
    window._timer.timeout.disconnect(window._tick)
    qapp.processEvents()
    getattr(window, f"_start_{phase}")()
    qapp.processEvents()
    check = window._check
    if phase == "precision":
        assert check is not None

    snapshot = _capture_widget(qapp, window, tmp_path, "gaze-check-precision", (1280, 720))

    assert window._phase == phase
    assert window._check is check
    assert not QImage(str(snapshot)).isNull()
