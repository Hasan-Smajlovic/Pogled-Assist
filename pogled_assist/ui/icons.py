"""Font Awesome icons with a Qt standard icon when qtawesome cannot load."""

from __future__ import annotations

import logging

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QStyle

logger = logging.getLogger(__name__)


def themed_icon(
    name: str,
    color: str,
    style: QStyle,
    fallback: QStyle.StandardPixmap = QStyle.StandardPixmap.SP_FileIcon,
) -> QIcon:
    try:
        import qtawesome as qta

        return qta.icon(name, color=color)
    except Exception:
        logger.exception("Could not load qtawesome icon %s; using fallback.", name)
        return style.standardIcon(fallback)
