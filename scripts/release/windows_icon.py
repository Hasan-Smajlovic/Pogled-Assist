"""Render the application icon from its SVG master and write the Windows executable icon with Qt.

Run ``python -m scripts.release.windows_icon`` after editing the master to regenerate ``assets/icon.png``.
"""

from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[2]
MASTER = ROOT / "docs" / "design" / "assets" / "app-icon.svg"
APPLICATION_ICON = ROOT / "assets" / "icon.png"
MASTER_SIZE = 1024

# Explorer, the taskbar and shortcuts choose among these sizes.
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def render_master(source: Path = MASTER, size: int = MASTER_SIZE) -> QImage:
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        raise ValueError(f"Could not read the icon master: {source}")
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return image


def _png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise RuntimeError("Qt could not encode an icon frame as PNG.")
    return bytes(data)


def icon_bytes(source: Path) -> bytes:
    image = QImage(str(source))
    if image.isNull():
        raise ValueError(f"Could not read the application icon: {source}")
    if image.width() != image.height() or image.width() < max(ICON_SIZES):
        raise ValueError(
            f"The application icon must be square and at least {max(ICON_SIZES)} pixels: "
            f"{source} is {image.width()} x {image.height()}."
        )
    # Premultiplied alpha keeps transparent edges from darkening while scaling down.
    image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    frames = [
        _png_bytes(
            image.scaled(
                size,
                size,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        for size in ICON_SIZES
    ]
    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = len(header) + 16 * len(frames)
    entries = b""
    for size, frame in zip(ICON_SIZES, frames, strict=True):
        # A width or height byte of 0 means 256 pixels.
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(frame), offset)
        offset += len(frame)
    return header + entries + b"".join(frames)


def write_icon(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(icon_bytes(source))
    return destination


def main() -> None:
    if not render_master().save(str(APPLICATION_ICON), "PNG"):
        raise RuntimeError(f"Qt could not write {APPLICATION_ICON}.")
    print(APPLICATION_ICON)


if __name__ == "__main__":
    main()
