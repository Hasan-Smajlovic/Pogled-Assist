from __future__ import annotations

import pytest
from PySide6.QtGui import QImage

from scripts.ui.capture_ui import capture_ui


@pytest.mark.e2e
@pytest.mark.parametrize("size", [(1280, 720), (1440, 900)])
def test_all_ui_preview_surfaces_render(qapp, tmp_path, monkeypatch, size):
    from scripts.ui import capture_ui as preview

    capture_widget = preview._capture_widget

    def capture_with_script_control_check(app, widget, output_dir, name, width, height):
        snapshot = capture_widget(app, widget, output_dir, name, width, height)
        if name in (
            "controller-keyboard",
            "controller-latin-paged",
            "controller-arabic",
            "controller-arabic-symbols",
        ):
            assert widget._script_button.isVisible(), (
                name,
                widget._active_tab,
                widget._script_button.isHidden(),
                widget._script_button.geometry(),
            )
            assert widget._script_button.height() >= 52
            assert widget._script_button.geometry().bottom() < widget._content_host.geometry().top()
            image = QImage(str(snapshot))
            expected = widget._script_button.grab().toImage()
            actual = image.copy(widget._script_button.geometry().adjusted(8, 8, -8, -8))
            expected = expected.copy(expected.rect().adjusted(8, 8, -8, -8))
            assert actual.convertToFormat(QImage.Format.Format_ARGB32) == expected.convertToFormat(
                QImage.Format.Format_ARGB32
            ), name
        return snapshot

    monkeypatch.setattr(preview, "_capture_widget", capture_with_script_control_check)
    snapshots = capture_ui(tmp_path, width=size[0], height=size[1])

    assert len(snapshots) == 35
    assert (tmp_path / "index.html").is_file()
    for snapshot in snapshots:
        image = QImage(str(snapshot))
        assert not image.isNull(), snapshot.name
        assert image.width() >= 380, snapshot.name
        assert image.height() >= 70, snapshot.name
        if snapshot.name.startswith("settings-"):
            assert (image.width(), image.height()) == (1280, 720), snapshot.name
        if snapshot.name in ("keyboard-latin-paged.png", "controller-latin-paged.png"):
            assert (image.width(), image.height()) == (380, 640), snapshot.name
