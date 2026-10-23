from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtGui import QImage

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

    assert len(snapshots) == 69
    assert {path.stem for path in snapshots} == CORE_NAMES
    assert len(encountered) == 146  # Extended states remain available without PNG encoding.
    assert not omitted.exists()
    assert unrelated.read_bytes() == b"leave caller files alone"
    unrelated.unlink()  # Keep the CI artifact limited to actual previews.
    assert (output_dir / "index.html").is_file()
    for snapshot in snapshots:
        image = QImage(str(snapshot))
        assert not image.isNull(), snapshot.name
        assert image.width() >= 380, snapshot.name
        assert image.height() >= 70, snapshot.name
        if snapshot.name.startswith(("settings-", "gaze-check-")):
            assert (image.width(), image.height()) == (1280, 720), snapshot.name
        if snapshot.name in ("keyboard-latin-paged.png", "controller-latin-paged.png"):
            assert (image.width(), image.height()) == (380, 640), snapshot.name


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
