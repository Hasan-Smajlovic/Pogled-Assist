"""Hotbar buttons, layout, and restore control."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QStyle, QToolButton, QWidget

from ..interaction.mouse_controller import (
    CLICK_ACTIONS,
    CONTROLLER,
    DOUBLE_LEFT_CLICK,
    HIDE_HOTBAR,
    KEYBOARD,
    LEFT_CLICK,
    QUICK_ACTIONS,
    RIGHT_CLICK,
    SETTINGS,
    SHOW_HOTBAR,
    SPEECH,
)
from .tracking_status import TrackingStatusWidget

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Button:
    action: str
    label: str
    icon: str
    width: int = 104
    icon_size: int = 22
    object_name: str = ""
    checkable: bool = False


CLICK_BUTTONS = (
    _Button(LEFT_CLICK, "Lijevi klik", "fa5s.mouse-pointer", checkable=True),
    _Button(RIGHT_CLICK, "Desni klik", "fa5s.mouse", checkable=True),
    _Button(DOUBLE_LEFT_CLICK, "Dvostruki klik", "fa5s.hand-pointer", checkable=True),
)
SECONDARY_BUTTONS = (
    _Button(SPEECH, "Govor", "fa5s.microphone"),
    _Button(KEYBOARD, "Tastatura", "fa5s.keyboard", checkable=True),
    _Button(CONTROLLER, "Upravljač", "fa5s.gamepad", checkable=True),
)


class HotbarControls:
    """Build controls on the hotbar and a separate restore button."""

    def __init__(self, window: QWidget, run_action, cancel_mouse_gaze) -> None:
        self.window = window
        self.run_action = run_action
        self.cancel_mouse_gaze = cancel_mouse_gaze
        self.buttons: dict[str, QToolButton] = {}

    def build(self) -> None:
        self.window.setStyleSheet(
            """
            QWidget {
                background: #111318;
                color: #f6f7fb;
                font-family: Segoe UI, Arial, sans-serif;
                font-size: 12px;
            }
            QToolButton {
                background: #1c2029;
                border: 1px solid #303747;
                border-radius: 8px;
                color: #eef2f8;
                padding: 5px;
            }
            QToolButton:hover {
                background: #262c38;
                border-color: #4c5970;
            }
            QToolButton:checked {
                background: #245f9f;
                border-color: #67b7dc;
                color: #ffffff;
            }
            QToolButton#hideButton {
                background: #2b1f27;
                border-color: #684354;
                font-weight: 650;
            }
            QToolButton#hideButton:hover {
                background: #3a2933;
                border-color: #9d647c;
            }
            QToolButton[gazeTarget="true"][gazePulse="0"] {
                background: #f0c84a;
                border: 3px solid #ffe58a;
                color: #111318;
            }
            QToolButton[gazeTarget="true"][gazePulse="1"] {
                background: #16a34a;
                border: 3px solid #bbf7d0;
                color: #ffffff;
            }
            """
        )

        layout = QGridLayout(self.window)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setHorizontalSpacing(8)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 0)
        self.hide_button = self._make_button(
            _Button(HIDE_HOTBAR, "Sakrij", "fa5s.chevron-up", 58, 18, "hideButton"),
            self.window,
        )
        self.settings_button = self._make_button(
            _Button(SETTINGS, "Postavke", "fa5s.cog"), self.window
        )
        self.quick_actions_button = self._make_button(
            _Button(QUICK_ACTIONS, "Brze radnje", "fa5s.bolt", 112, checkable=True),
            self.window,
        )
        left_controls = self._build_left_controls()
        self.tracking_status = TrackingStatusWidget(self.window)
        layout.addWidget(left_controls, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.tracking_status, 0, 1, Qt.AlignRight | Qt.AlignVCenter)

    def _build_left_controls(self) -> QWidget:
        controls = QWidget(self.window)
        controls.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(controls)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.hide_button)
        layout.addSpacing(16)
        layout.addWidget(self.settings_button)
        layout.addSpacing(18)
        layout.addWidget(self.quick_actions_button)
        layout.addSpacing(8)
        for definition in CLICK_BUTTONS:
            layout.addWidget(self._make_button(definition, controls))
        layout.addSpacing(26)
        for definition in SECONDARY_BUTTONS:
            layout.addWidget(self._make_button(definition, controls))
        return controls

    def _make_button(self, definition: _Button, parent: QWidget) -> QToolButton:
        button = QToolButton(parent)
        if definition.object_name:
            button.setObjectName(definition.object_name)
        button.setText(definition.label)
        button.setIcon(self._icon(definition.icon, definition.action))
        button.setIconSize(QSize(definition.icon_size, definition.icon_size))
        button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        button.setFixedSize(definition.width, 58)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setCheckable(definition.checkable)
        button.setProperty("gazeTarget", False)
        button.setProperty("gazePulse", "")
        button.pressed.connect(self.cancel_mouse_gaze)
        button.clicked.connect(
            lambda checked=False: self.run_action(
                definition.action, checked=checked, source="mouse"
            )
        )
        self.buttons[definition.action] = button
        return button

    def build_restore_button(self) -> QToolButton:
        button = QToolButton()
        button.setObjectName("restoreHotbarButton")
        button.setWindowTitle("Prikaži Pogled Assist")
        button.setWindowFlags(no_focus_tool_window_flags())
        button.setAttribute(Qt.WA_ShowWithoutActivating, True)
        button.setFocusPolicy(Qt.NoFocus)
        button.setText("Prikaži")
        button.setIcon(self._icon("fa5s.chevron-down", SHOW_HOTBAR))
        button.setIconSize(QSize(26, 26))
        button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        button.setFixedSize(86, 76)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setProperty("gazeTarget", False)
        button.setProperty("gazePulse", "")
        button.pressed.connect(self.cancel_mouse_gaze)
        button.setStyleSheet(
            """
            QToolButton#restoreHotbarButton {
                background: #111318;
                border: 2px solid #67b7dc;
                border-radius: 8px;
                color: #eef2f8;
                font-family: Segoe UI, Arial, sans-serif;
                font-size: 13px;
                font-weight: 700;
                padding: 7px;
            }
            QToolButton#restoreHotbarButton:hover {
                background: #1c2029;
                border-color: #a6e7ff;
            }
            QToolButton#restoreHotbarButton[gazeTarget="true"][gazePulse="0"] {
                background: #f0c84a;
                border: 4px solid #ffe58a;
                color: #111318;
            }
            QToolButton#restoreHotbarButton[gazeTarget="true"][gazePulse="1"] {
                background: #16a34a;
                border: 4px solid #bbf7d0;
                color: #ffffff;
            }
            """
        )
        button.clicked.connect(
            lambda checked=False: self.run_action(
                SHOW_HOTBAR,
                checked=checked,
                source="mouse",
            )
        )
        self.buttons[SHOW_HOTBAR] = button
        button.hide()
        return button

    def _icon(self, icon_name: str, action: str) -> QIcon:
        try:
            import qtawesome as qta

            color = "#ffffff" if action in CLICK_ACTIONS else "#dce6f3"
            return qta.icon(icon_name, color=color)
        except Exception:
            logger.exception("Could not load qtawesome icon %s; using fallback.", icon_name)
            fallback = {
                LEFT_CLICK: QStyle.StandardPixmap.SP_ArrowForward,
                RIGHT_CLICK: QStyle.StandardPixmap.SP_DialogApplyButton,
                DOUBLE_LEFT_CLICK: QStyle.StandardPixmap.SP_BrowserReload,
                QUICK_ACTIONS: QStyle.StandardPixmap.SP_ComputerIcon,
                SPEECH: QStyle.StandardPixmap.SP_MediaVolume,
                KEYBOARD: QStyle.StandardPixmap.SP_FileDialogDetailedView,
                CONTROLLER: QStyle.StandardPixmap.SP_DesktopIcon,
                SETTINGS: QStyle.StandardPixmap.SP_FileDialogInfoView,
                HIDE_HOTBAR: QStyle.StandardPixmap.SP_TitleBarMinButton,
                SHOW_HOTBAR: QStyle.StandardPixmap.SP_TitleBarNormalButton,
            }.get(action, QStyle.StandardPixmap.SP_FileIcon)
            return self.window.style().standardIcon(fallback)


def no_focus_tool_window_flags() -> Qt.WindowFlags:
    flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
    no_focus = getattr(Qt, "WindowDoesNotAcceptFocus", None)
    if no_focus is None:
        no_focus = getattr(Qt.WindowType, "WindowDoesNotAcceptFocus", None)
    if no_focus is not None:
        flags |= no_focus
    return flags
