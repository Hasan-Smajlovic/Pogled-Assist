"""Settings controls that respond to both mouse clicks and gaze dwell."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .icons import themed_icon

GazeCallback = Callable[[], None]
CONTROL_HEIGHT = 58
ADJUST_BUTTON_WIDTH = 104
VALUE_WIDTH = 216
CHOICE_WIDTH = 260
CONTROL_SPACING = 12


class SettingsControls:
    """Build settings controls and remember the action gaze dwell selects on each one."""

    def __init__(self, parent: QWidget, interrupt_gaze: GazeCallback) -> None:
        self._parent = parent
        self._interrupt_gaze = interrupt_gaze
        self._actions: dict[QWidget, GazeCallback] = {}
        self._names: dict[QWidget, str] = {}

    def interrupt_gaze(self) -> None:
        """Drop the running dwell so the control under the gaze needs a fresh look."""

        self._interrupt_gaze()

    def action_at(self, point: QPoint) -> tuple[QWidget, GazeCallback] | None:
        for widget, action in self._actions.items():
            if widget.isVisible() and widget.isEnabled() and global_rect(widget).contains(point):
                return widget, action
        return None

    def name(self, widget: QWidget) -> str:
        return self._names[widget]

    def rename(self, widget: QWidget, name: str) -> None:
        self._names[widget] = name

    def button(self, text: str, callback: GazeCallback, size: QSize, icon: str = "") -> QToolButton:
        button = self._tool_button(text, callback, icon)
        _configure(button, size)
        return button

    def toggle_button(
        self, text: str, callback: GazeCallback, size: QSize, icon: str = ""
    ) -> QToolButton:
        button = self.button(text, callback, size, icon)
        button.setCheckable(True)
        return button

    def tile_button(self, text: str, callback: GazeCallback, size: QSize) -> QToolButton:
        """Checkable button that grows with its grid cell instead of keeping a fixed height."""

        button = self._tool_button(text, callback)
        button.setMinimumSize(size)
        button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setCheckable(True)
        return button

    def checkbox(self, text: str, callback: GazeCallback, size: QSize) -> QCheckBox:
        checkbox = QCheckBox(text, self._parent)
        _configure(checkbox, size)
        self._connect(checkbox, callback, text)
        return checkbox

    def choice(
        self,
        choices: tuple[tuple[str, str], ...],
        changed: Callable[[int], None],
        cycle: GazeCallback,
        name: str,
    ) -> QComboBox:
        combo = QComboBox(self._parent)
        _configure(combo, QSize(CHOICE_WIDTH, CONTROL_HEIGHT))
        combo.setFixedWidth(CHOICE_WIDTH)
        for value, label in choices:
            combo.addItem(label, value)
        combo.currentIndexChanged.connect(changed)
        self._register(combo, cycle, name)
        return combo

    def adjust_row(
        self, title: str, hint: str, adjust: Callable[[float], None], step: float
    ) -> tuple[QFrame, QLabel]:
        row, layout, _hint = setting_row(self._parent, title, hint)
        minus_button = self._adjust_button("Manje", "fa5s.minus", lambda: adjust(-step))
        plus_button = self._adjust_button("Više", "fa5s.plus", lambda: adjust(step))
        value_label = _value_label(row)

        layout.addWidget(minus_button, 0, 1, 2, 1)
        layout.addWidget(value_label, 0, 2, 2, 1)
        layout.addWidget(plus_button, 0, 3, 2, 1)
        return row, value_label

    def _adjust_button(self, text: str, icon: str, callback: GazeCallback) -> QToolButton:
        button = self.button(text, callback, QSize(ADJUST_BUTTON_WIDTH, CONTROL_HEIGHT), icon)
        button.setObjectName("adjustButton")
        button.setFixedWidth(ADJUST_BUTTON_WIDTH)
        return button

    def _tool_button(self, text: str, callback: GazeCallback, icon: str = "") -> QToolButton:
        button = QToolButton(self._parent)
        button.setText(text)
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setIconSize(QSize(22, 22))
        if icon:
            button.setIcon(themed_icon(icon, "#f8f7f2", self._parent.style()))
        self._connect(button, callback, text)
        return button

    def _connect(self, control: QAbstractButton, callback: GazeCallback, name: str) -> None:
        control.pressed.connect(self.interrupt_gaze)
        control.clicked.connect(lambda _checked=False, item=callback: item())
        self._register(control, callback, name)

    def _register(self, widget: QWidget, callback: GazeCallback, name: str) -> None:
        self._actions[widget] = callback
        self._names[widget] = name
        widget.setProperty("gazeTarget", False)
        widget.setProperty("gazePulse", "")


def content_layout(page: QFrame) -> QVBoxLayout:
    page.setObjectName("contentPanel")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(8)
    return layout


def styled_label(text: str, object_name: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName(object_name)
    return label


def setting_row(parent: QWidget, title: str, hint: str = "") -> tuple[QFrame, QGridLayout, QLabel]:
    row = QFrame(parent)
    row.setObjectName("settingRow")
    row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    layout = QGridLayout(row)
    layout.setContentsMargins(14, 4, 14, 4)
    layout.setHorizontalSpacing(CONTROL_SPACING)
    layout.setVerticalSpacing(2)
    layout.setColumnStretch(0, 1)

    title_label = styled_label(title, "settingTitle", row)
    hint_label = styled_label(hint, "settingHint", row)
    hint_label.setWordWrap(True)
    layout.addWidget(title_label, 0, 0, 1 if hint else 2, 1)
    if hint:
        layout.addWidget(hint_label, 1, 0)
    else:
        hint_label.hide()
    return row, layout, hint_label


def action_grid(widgets: tuple[QWidget, ...]) -> QGridLayout:
    layout = QGridLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setHorizontalSpacing(0)
    layout.setVerticalSpacing(CONTROL_SPACING)
    for column in range(3):
        layout.setColumnStretch(column * 2, 1)
        if column < 2:
            layout.setColumnMinimumWidth(column * 2 + 1, CONTROL_SPACING)
    for index, widget in enumerate(widgets):
        layout.addWidget(widget, index // 3, (index % 3) * 2)
    return layout


def global_rect(widget: QWidget) -> QRect:
    return QRect(widget.mapToGlobal(QPoint(0, 0)), widget.size())


def _configure(widget: QWidget, size: QSize) -> None:
    widget.setMinimumSize(size)
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    widget.setFixedHeight(size.height())
    widget.setCursor(Qt.CursorShape.PointingHandCursor)


def _value_label(parent: QWidget) -> QLabel:
    label = QLabel(parent)
    label.setObjectName("valueLabel")
    label.setAlignment(Qt.AlignCenter)
    label.setFixedSize(VALUE_WIDTH, CONTROL_HEIGHT)
    return label
