"""Deterministic Quick actions, precision zoom and gaze marker gallery scenarios."""

from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from pogled_assist.interaction.mouse_controller import LEFT_CLICK
from pogled_assist.ui import quick_action_menu as menu_module
from pogled_assist.ui import quick_action_zoom as zoom_module
from pogled_assist.ui.gaze_bubble import GazeBubbleWindow
from pogled_assist.ui.interaction_overlay import InteractionOverlayWindow
from pogled_assist.ui.quick_action_menu import QuickActionMenu, grid_rect_around
from pogled_assist.ui.quick_action_zoom import QuickActionZoomWindow

# A light third-party window on a dark desktop: the overlays work on any application.
DESKTOP_STYLE = """
QWidget#previewDesktop { background: #1f2a37; }
QFrame#previewDocument { background: #f4f6f8; border: 1px solid #9aa7b4; }
QLabel#previewTitle { background: #dde3ea; color: #1f2933; font-size: 13px; padding: 6px 10px; }
QLabel#previewText { color: #1f2933; font-size: 13px; padding: 0 10px; }
QPushButton#previewButton { color: #1f2933; background: #e4e8ed; border: 1px solid #8a96a3;
  border-radius: 3px; font-size: 12px; min-height: 22px; padding: 0 10px; }
"""
SELECTION_PAUSE_MS = 250
SELECTION_DWELL_MS = 1000
SAMPLE_MS = 50
SHOWN_PROGRESS = 0.6
# Wide enough that the 46-pixel marker on the document's left edge stays inside the image.
MARKER_SCENE_SIZE = (720, 360)


class PreviewDesktop(QWidget):
    """A fixed sample application window with small targets for pointer overlays."""

    def __init__(self, size: tuple[int, int]) -> None:
        super().__init__()
        self.setObjectName("previewDesktop")
        self.setStyleSheet(DESKTOP_STYLE)
        self.setAttribute(Qt.WA_StyledBackground, True)
        width, height = size
        self.resize(width, height)
        document = QFrame(self)
        document.setObjectName("previewDocument")
        document.setGeometry(QRect(width // 2 - 300, height // 2 - 170, 600, 300))
        layout = QVBoxLayout(document)
        layout.setContentsMargins(0, 0, 0, 10)
        layout.setSpacing(8)
        title = QLabel("Pismo.txt - Uređivač teksta", document)
        title.setObjectName("previewTitle")
        layout.addWidget(title)
        for line in (
            "Dragi Amire,",
            "hvala na posjeti. Dogovor za srijedu ostaje isti.",
            "Pozdrav, Lejla",
        ):
            text = QLabel(line, document)
            text.setObjectName("previewText")
            layout.addWidget(text)
        layout.addStretch(1)
        buttons = QWidget(document)
        row = QVBoxLayout(buttons)
        row.setContentsMargins(0, 0, 10, 0)
        self.save_button = QPushButton("Spremi", buttons)
        self.save_button.setObjectName("previewButton")
        row.addWidget(self.save_button, 0, Qt.AlignRight)
        layout.addWidget(buttons)

    def target(self) -> QPoint:
        """Return the small Save button's centre in scene coordinates."""

        button = self.save_button
        return button.mapTo(self, button.rect().center())

    def document_edge(self) -> QPoint:
        """Return a point between the light document text and the dark desktop."""

        document = self.findChild(QFrame, "previewDocument").geometry()
        return QPoint(document.left(), document.top() + 60)


class CapturePointerOverlays:
    def capture_pointer_overlays(self) -> None:
        self._capture_quick_actions_menu()
        self._capture_precision_zoom()
        self._capture_gaze_marker()

    def _pointer_scene(self) -> PreviewDesktop:
        scene = PreviewDesktop(self.size)
        self.widgets.append(scene)
        scene.show()
        self.app.processEvents()
        return scene

    def _shared_ring(self, scene: QWidget, source: QWidget, origin: QPoint | None = None) -> None:
        """Draw the shared selection ring the hotbar shows over every gaze selection.

        ``origin`` converts global points from a source that works in global coordinates.
        """

        ring = InteractionOverlayWindow()
        ring.setParent(scene, Qt.Widget)
        ring._timer.timeout.disconnect(ring._tick)
        if origin is None:
            source.selection_progress_changed.connect(ring.show_progress)
        else:
            source.selection_progress_changed.connect(
                lambda point, progress, label: ring.show_progress(point - origin, progress, label)
            )

    def _capture_quick_actions_menu(self) -> None:
        scene = self._pointer_scene()
        menu = self._quick_actions_grid(scene, scene.target())
        self._shared_ring(scene, menu, scene.mapToGlobal(QPoint(0, 0)))
        # Look at the left click tile until the selection is partly complete.
        _hold_gaze(menu_module, menu.handle_gaze, menu.tile_rect(LEFT_CLICK).center())
        self.capture(scene, "quick-actions-menu", "Quick actions: left click selecting")

        # Near a corner the grid shifts to stay on screen and the point lies on a tile.
        scene = self._pointer_scene()
        self._quick_actions_grid(scene, QPoint(60, 40))
        self.capture(scene, "quick-actions-menu-edge", "Quick actions: near the edge")

    def _quick_actions_grid(self, scene: QWidget, center: QPoint) -> QuickActionMenu:
        # The grid works in global coordinates, like the full-screen menu in the app.
        origin = scene.mapToGlobal(QPoint(0, 0))
        menu = QuickActionMenu()
        menu.setParent(scene, Qt.Widget)
        menu.setGeometry(scene.rect())
        menu._center_global = center + origin
        menu._grid_global = grid_rect_around(center + origin, scene.rect().translated(origin))
        menu.set_selection_settings(
            pause_ms=SELECTION_PAUSE_MS, dwell_ms=SELECTION_DWELL_MS, radius_px=48
        )
        menu.show()
        return menu

    def _capture_precision_zoom(self) -> None:
        scene = self._pointer_scene()
        target = scene.target()
        zoom = QuickActionZoomWindow()
        bounds = scene.rect()
        # Use the preview desktop instead of grabbing the real screen.
        zoom._screen_geometry = QRect(bounds)
        zoom._source_rect = zoom_module._square_around(target, zoom.SOURCE_SIZE, bounds)
        zoom._display_rect = zoom_module._centered_square(bounds, zoom.DISPLAY_SIZE)
        zoom._pixmap = scene.grab(zoom._source_rect)
        zoom.setParent(scene, Qt.Widget)
        zoom.setGeometry(bounds)
        zoom.set_selection_settings(
            pause_ms=SELECTION_PAUSE_MS, dwell_ms=SELECTION_DWELL_MS, radius_px=48
        )
        zoom.show()
        self._shared_ring(scene, zoom)
        _hold_gaze(zoom_module, zoom.handle_gaze, zoom._display_rect.center())
        self.capture(scene, "precision-zoom", "Precision zoom: choosing the exact point")

    def _capture_gaze_marker(self) -> None:
        size = MARKER_SCENE_SIZE
        scene = PreviewDesktop(size)
        self.widgets.append(scene)
        scene.show()
        self.app.processEvents()
        marker = GazeBubbleWindow()
        marker.setParent(scene, Qt.Widget)
        marker._move_center_to(scene.document_edge())
        marker.show()
        self.capture(scene, "gaze-marker", "Gaze marker over light and dark content", size=size)


def _hold_gaze(module, handle_gaze, point: QPoint) -> None:
    """Feed steady samples through the overlay's own selection timer."""

    now = [100.0]
    with patch.object(module, "time", SimpleNamespace(monotonic=lambda: now[0])):
        elapsed = 0
        while elapsed <= SELECTION_PAUSE_MS + SELECTION_DWELL_MS * SHOWN_PROGRESS:
            handle_gaze(QPoint(point))
            elapsed += SAMPLE_MS
            now[0] += SAMPLE_MS / 1000
