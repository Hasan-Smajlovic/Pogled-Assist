"""Size the scrollable Settings body from its active page."""

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QLayout, QStackedWidget


class SettingsContent(QStackedWidget):
    def __init__(self, parent):
        super().__init__(parent)
        # Hidden pages must not impose their minimum size on the active page.
        self.layout().setSizeConstraint(QLayout.SetNoConstraint)
        self.currentChanged.connect(self.updateGeometry)

    def sizeHint(self) -> QSize:
        page = self.currentWidget()
        return page.sizeHint() if page is not None else QSize()

    def minimumSizeHint(self) -> QSize:
        page = self.currentWidget()
        return page.minimumSizeHint() if page is not None else QSize()
