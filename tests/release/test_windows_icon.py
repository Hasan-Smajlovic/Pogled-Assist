from __future__ import annotations

import ast
import struct
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter

from scripts.release import windows_icon

ROOT = Path(__file__).resolve().parents[2]


def _frames(data: bytes) -> list[tuple[int, QImage]]:
    reserved, kind, count = struct.unpack_from("<HHH", data)
    assert (reserved, kind) == (0, 1)
    frames = []
    for index in range(count):
        width, height, _colors, _reserved, planes, bits, length, offset = struct.unpack_from(
            "<BBBBHHII", data, 6 + 16 * index
        )
        assert (width, planes, bits) == (height, 1, 32)
        image = QImage.fromData(data[offset : offset + length], "PNG")
        assert not image.isNull()
        frames.append((width or 256, image))
    return frames


def test_windows_icon_keeps_every_shell_size_and_transparency(tmp_path):
    source = QImage(512, 512, QImage.Format.Format_ARGB32)
    source.fill(Qt.GlobalColor.transparent)
    painter = QPainter(source)
    painter.fillRect(128, 128, 256, 256, QColor("#84c5d9"))
    painter.end()
    path = tmp_path / "icon.png"
    assert source.save(str(path))

    frames = _frames(windows_icon.write_icon(path, tmp_path / "out" / "app.ico").read_bytes())

    assert [size for size, _image in frames] == list(windows_icon.ICON_SIZES)
    for size, image in frames:
        assert (image.width(), image.height()) == (size, size)
        assert image.pixelColor(0, 0).alpha() == 0
        assert image.pixelColor(size // 2, size // 2) == QColor("#84c5d9")


@pytest.mark.parametrize("size", [(256, 200), (128, 128)])
def test_windows_icon_rejects_sources_that_would_distort_or_blur(tmp_path, size):
    path = tmp_path / "icon.png"
    assert QImage(*size, QImage.Format.Format_ARGB32).save(str(path))

    with pytest.raises(ValueError, match="square and at least 256 pixels"):
        windows_icon.icon_bytes(path)


def _comparable_pixels(image: QImage) -> bytes:
    image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied).scaled(
        128,
        128,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    return bytes(image.constBits())


def test_application_icon_is_rendered_from_its_svg_master():
    committed = QImage(str(windows_icon.APPLICATION_ICON))
    size = windows_icon.MASTER_SIZE
    committed_pixels = _comparable_pixels(committed)
    rendered_pixels = _comparable_pixels(windows_icon.render_master())

    assert (committed.width(), committed.height()) == (size, size)
    # The tolerance absorbs antialiasing differences between platforms, not design changes.
    difference = max(abs(a - b) for a, b in zip(committed_pixels, rendered_pixels, strict=True))
    assert difference <= 8, "Regenerate assets/icon.png: python -m scripts.release.windows_icon"


def test_application_icon_produces_the_windows_icon():
    frames = _frames(windows_icon.icon_bytes(ROOT / "assets" / "icon.png"))

    assert [size for size, _image in frames] == list(windows_icon.ICON_SIZES)


def test_windows_executable_icon_is_generated_without_pillow():
    spec = ROOT / "packaging" / "windows" / "PogledAssist.spec"
    executable = next(
        node
        for node in ast.walk(ast.parse(spec.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "EXE"
    )
    icon = next(keyword.value for keyword in executable.keywords if keyword.arg == "icon")

    assert "write_icon(" in ast.unparse(icon)
    assert "pillow" not in (ROOT / "requirements-build.txt").read_text(encoding="utf-8").lower()
