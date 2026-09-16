"""Fullscreen gaze-selectable settings UI."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .gaze_feedback import set_gaze_feedback
from .gaze_selection import GazeSelectionTimer
from .logging_setup import set_application_logging_enabled
from .mouse_controller import GazeSettings
from .speech_service import VOICE_PRESET_DEFAULT, VOICE_PRESETS, SpeechSettings
from .windows_startup import is_windows_startup_enabled, set_windows_startup_enabled

logger = logging.getLogger(__name__)

GazeCallback = Callable[[], None]


class SettingsWindow(QWidget):
    """Fullscreen settings surface that can be operated by gaze dwell."""

    closed = Signal()
    gaze_settings_changed = Signal(object)
    speech_settings_changed = Signal(object)
    calibration_requested = Signal()
    speech_test_requested = Signal()
    quit_requested = Signal()
    interaction_progress_changed = Signal(QPoint, float, str)
    interaction_finished = Signal(QPoint, str)
    interaction_cancelled = Signal()

    def __init__(
        self,
        gaze_settings: GazeSettings,
        speech_settings: SpeechSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Window)
        self.setObjectName("settingsRoot")

        self._gaze_settings = replace(gaze_settings)
        self._speech_settings = replace(speech_settings)
        self._gaze_actions: dict[QWidget, GazeCallback] = {}
        self._gaze_names: dict[QWidget, str] = {}
        self._gaze_target: QWidget | None = None
        self._gaze_selection = GazeSelectionTimer()
        self._last_gaze_action_ms = 0.0
        self._interaction_active = False

        self._sync_startup_setting_from_windows()
        self._build_ui()
        self._install_shortcuts()
        self._refresh_values()
        logger.info("Settings window initialized.")

    def show_fullscreen_on_primary(self) -> None:
        screen = QGuiApplication.primaryScreen()
        geometry = screen.geometry()
        logger.info(
            "Showing settings fullscreen on primary screen: left=%s top=%s width=%s height=%s.",
            geometry.left(),
            geometry.top(),
            geometry.width(),
            geometry.height(),
        )
        self.setGeometry(geometry)
        self.showFullScreen()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QCloseEvent) -> None:
        logger.info("Settings window closed.")
        self.cancel_gaze_interaction()
        self.closed.emit()
        super().closeEvent(event)

    def handle_gaze(self, point: QPoint) -> None:
        if not self.isVisible():
            self.cancel_gaze_interaction()
            return

        target = self._gaze_action_at(point)
        now_ms = time.monotonic() * 1000
        if target is None:
            self.cancel_gaze_interaction()
            return

        widget, action = target
        update = self._gaze_selection.update(
            widget,
            now_ms,
            self._gaze_settings.dwell_ms,
        )
        if update.progress is None:
            self._set_gaze_target(None)
            self._cancel_interaction()
            return

        if widget is not self._gaze_target:
            self._set_gaze_target(widget)
            self._set_status(f"Target: {self._gaze_names.get(widget, 'control')}")
        self._emit_interaction_progress(widget, update.progress)

        cooled = now_ms - self._last_gaze_action_ms >= self._gaze_settings.click_cooldown_ms
        if update.ready and cooled:
            name = self._gaze_names.get(widget, "control")
            logger.info("Settings gaze action fired: %s", name)
            self._last_gaze_action_ms = now_ms
            self._gaze_selection.complete()
            self._finish_interaction(widget)
            self._set_gaze_target(None)
            action()

    def cancel_gaze_interaction(self, *, require_leave: bool = False) -> None:
        self._gaze_selection.cancel(require_leave=require_leave)
        self._set_gaze_target(None)
        self._cancel_interaction()

    def set_status(self, text: str) -> None:
        self._set_status(text)

    def _build_ui(self) -> None:
        self.setStyleSheet(
            """
            QWidget#settingsRoot {
                background: #151515;
                color: #f4f1ea;
                font-family: Segoe UI, Arial, sans-serif;
                font-size: 15px;
            }
            QLabel#titleLabel {
                color: #ffffff;
                font-size: 25px;
                font-weight: 650;
            }
            QLabel#statusLabel {
                color: #b8c5c0;
                font-size: 14px;
            }
            QLabel#sectionTitle {
                color: #ffffff;
                font-size: 22px;
                font-weight: 650;
            }
            QLabel#settingTitle {
                color: #ffffff;
                font-size: 17px;
                font-weight: 600;
            }
            QLabel#settingHint {
                color: #b9b2a5;
                font-size: 13px;
            }
            QLabel#valueLabel {
                background: #101010;
                border: 1px solid #3a3d3b;
                border-radius: 8px;
                color: #ffffff;
                font-size: 24px;
                font-weight: 650;
                padding: 12px 18px;
            }
            QFrame#settingsPanel {
                background: #1e1f1e;
                border: 1px solid #343a36;
                border-radius: 8px;
            }
            QFrame#settingRow {
                background: #242624;
                border: 1px solid #3a403c;
                border-radius: 8px;
            }
            QToolButton {
                background: #2b2d2b;
                border: 1px solid #494f4b;
                border-radius: 8px;
                color: #f5f3ef;
                font-size: 15px;
                font-weight: 600;
                padding: 10px 14px;
            }
            QToolButton:hover {
                background: #363936;
                border-color: #69736d;
            }
            QToolButton:checked {
                background: #1d6f68;
                border-color: #74d3c6;
                color: #ffffff;
            }
            QToolButton[gazeTarget="true"] {
                background: #3a3420;
                border: 3px solid #f0c84a;
                color: #ffffff;
            }
            QToolButton[gazeTarget="true"][gazePulse="0"] {
                background: #f0c84a;
                border: 4px solid #ffe58a;
                color: #14140f;
            }
            QToolButton[gazeTarget="true"][gazePulse="1"] {
                background: #16a34a;
                border: 4px solid #bbf7d0;
                color: #ffffff;
            }
            QToolButton#dangerButton {
                background: #4b2224;
                border-color: #7d383e;
            }
            QToolButton#dangerButton[gazeTarget="true"] {
                background: #5d3422;
                border: 3px solid #f0c84a;
            }
            QToolButton#dangerButton[gazeTarget="true"][gazePulse="0"] {
                background: #f0c84a;
                border: 4px solid #ffe58a;
                color: #14140f;
            }
            QToolButton#dangerButton[gazeTarget="true"][gazePulse="1"] {
                background: #dc2626;
                border: 4px solid #fecaca;
                color: #ffffff;
            }
            QCheckBox {
                background: #242624;
                border: 1px solid #3a403c;
                border-radius: 8px;
                color: #f5f3ef;
                font-size: 16px;
                font-weight: 600;
                padding: 14px 18px;
                spacing: 14px;
            }
            QCheckBox:hover {
                background: #303330;
                border-color: #69736d;
            }
            QCheckBox::indicator {
                width: 28px;
                height: 28px;
                border: 2px solid #8b938d;
                border-radius: 6px;
                background: #101010;
            }
            QCheckBox::indicator:checked {
                background: #1d6f68;
                border-color: #74d3c6;
                image: url("__CHECKBOX_X_IMAGE__");
            }
            QCheckBox[gazeTarget="true"] {
                background: #3a3420;
                border: 3px solid #f0c84a;
                color: #ffffff;
            }
            QCheckBox[gazeTarget="true"][gazePulse="0"] {
                background: #f0c84a;
                border: 4px solid #ffe58a;
                color: #14140f;
            }
            QCheckBox[gazeTarget="true"][gazePulse="1"] {
                background: #16a34a;
                border: 4px solid #bbf7d0;
                color: #ffffff;
            }
            QComboBox {
                background: #101010;
                border: 1px solid #4c534e;
                border-radius: 8px;
                color: #ffffff;
                font-size: 20px;
                font-weight: 650;
                min-height: 46px;
                padding: 10px 14px;
            }
            QComboBox:hover {
                background: #181a18;
                border-color: #69736d;
            }
            QComboBox::drop-down {
                border: 0;
                width: 42px;
            }
            QComboBox QAbstractItemView {
                background: #1e1f1e;
                border: 1px solid #4c534e;
                color: #ffffff;
                selection-background-color: #1d6f68;
                selection-color: #ffffff;
            }
            QComboBox[gazeTarget="true"] {
                background: #3a3420;
                border: 3px solid #f0c84a;
                color: #ffffff;
            }
            QComboBox[gazeTarget="true"][gazePulse="0"] {
                background: #f0c84a;
                border: 4px solid #ffe58a;
                color: #14140f;
            }
            QComboBox[gazeTarget="true"][gazePulse="1"] {
                background: #16a34a;
                border: 4px solid #bbf7d0;
                color: #ffffff;
            }
            """.replace("__CHECKBOX_X_IMAGE__", _checkbox_x_image_url())
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 22)
        root.setSpacing(16)

        top_bar = QHBoxLayout()
        top_bar.setSpacing(14)
        self._exit_button = self._make_button(
            "Exit",
            self.close,
            icon_name="fa5s.times",
            object_name="dangerButton",
            minimum_size=QSize(128, 58),
        )
        top_bar.addWidget(self._exit_button, 0, Qt.AlignLeft)

        title = QLabel("Settings", self)
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        top_bar.addWidget(title, 1)

        self._status_label = QLabel("Ready", self)
        self._status_label.setObjectName("statusLabel")
        self._status_label.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
        self._status_label.setMinimumWidth(360)
        top_bar.addWidget(self._status_label, 0)
        root.addLayout(top_bar)

        body = QHBoxLayout()
        body.setSpacing(16)
        root.addLayout(body, 1)

        nav_panel = QFrame(self)
        nav_panel.setObjectName("settingsPanel")
        nav_panel.setFixedWidth(250)
        nav_layout = QVBoxLayout(nav_panel)
        nav_layout.setContentsMargins(12, 12, 12, 12)
        nav_layout.setSpacing(10)

        self._general_tab_button = self._make_button(
            "General settings",
            lambda: self._select_tab(0),
            icon_name="fa5s.sliders-h",
            checkable=True,
            minimum_size=QSize(216, 74),
        )
        self._gaze_tab_button = self._make_button(
            "Gaze settings",
            lambda: self._select_tab(1),
            icon_name="fa5s.eye",
            checkable=True,
            minimum_size=QSize(216, 74),
        )
        self._speech_tab_button = self._make_button(
            "Speech settings",
            lambda: self._select_tab(2),
            icon_name="fa5s.volume-up",
            checkable=True,
            minimum_size=QSize(216, 74),
        )
        nav_layout.addWidget(self._general_tab_button)
        nav_layout.addWidget(self._gaze_tab_button)
        nav_layout.addWidget(self._speech_tab_button)
        nav_layout.addStretch(1)

        body.addWidget(nav_panel, 0)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._build_general_page())
        self._stack.addWidget(self._build_gaze_page())
        self._stack.addWidget(self._build_speech_page())
        body.addWidget(self._stack, 1)

        self._select_tab(0)

    def _build_general_page(self) -> QWidget:
        page = QFrame(self)
        page.setObjectName("settingsPanel")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)
        title = QLabel("General settings", page)
        title.setObjectName("sectionTitle")
        header.addWidget(title, 1, Qt.AlignVCenter | Qt.AlignLeft)
        self._quit_button = self._make_button(
            "Quit app",
            self._request_quit,
            icon_name="fa5s.power-off",
            object_name="dangerButton",
            minimum_size=QSize(154, 58),
        )
        header.addWidget(self._quit_button, 0, Qt.AlignVCenter | Qt.AlignRight)
        layout.addLayout(header)

        actions = QGridLayout()
        actions.setHorizontalSpacing(12)
        actions.setVerticalSpacing(12)
        self._startup_checkbox = self._make_checkbox(
            "Start with Windows as Administrator",
            self._toggle_start_with_windows,
            minimum_size=QSize(520, 66),
        )
        self._logging_checkbox = self._make_checkbox(
            "Enable logging",
            self._toggle_logging_enabled,
            minimum_size=QSize(520, 66),
        )
        self._launcher_window_checkbox = self._make_checkbox(
            "Show PowerShell launcher window",
            self._toggle_show_launcher_window,
            minimum_size=QSize(520, 66),
        )
        actions.addWidget(self._startup_checkbox, 0, 0)
        actions.addWidget(self._logging_checkbox, 1, 0)
        actions.addWidget(self._launcher_window_checkbox, 2, 0)
        actions.setColumnStretch(1, 1)
        layout.addLayout(actions)
        layout.addStretch(1)

        return page

    def _build_gaze_page(self) -> QWidget:
        page = QFrame(self)
        page.setObjectName("settingsPanel")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("Gaze settings", page)
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        self._dwell_value = self._make_value_label(page)
        layout.addWidget(
            self._make_adjust_row(
                "Stare time",
                "Progress-ring fill time after the fixed 500 ms gaze pause.",
                self._dwell_value,
                lambda: self._adjust_dwell_ms(-50),
                lambda: self._adjust_dwell_ms(50),
            )
        )

        self._radius_value = self._make_value_label(page)
        layout.addWidget(
            self._make_adjust_row(
                "Stable target radius",
                "How still the gaze point must stay before a target action fires.",
                self._radius_value,
                lambda: self._adjust_dwell_radius(-2),
                lambda: self._adjust_dwell_radius(2),
            )
        )

        self._cooldown_value = self._make_value_label(page)
        layout.addWidget(
            self._make_adjust_row(
                "Repeat delay",
                "Delay after one gaze action before another can fire.",
                self._cooldown_value,
                lambda: self._adjust_click_cooldown(-50),
                lambda: self._adjust_click_cooldown(50),
            )
        )

        self._smoothing_value = self._make_value_label(page)
        layout.addWidget(
            self._make_adjust_row(
                "Pointer smoothing",
                "Lower values feel steadier. Higher values follow gaze faster.",
                self._smoothing_value,
                lambda: self._adjust_smoothing(-0.05),
                lambda: self._adjust_smoothing(0.05),
            )
        )

        actions = QGridLayout()
        actions.setHorizontalSpacing(12)
        actions.setVerticalSpacing(12)
        self._move_pointer_button = self._make_button(
            "Move pointer from gaze",
            self._toggle_move_pointer,
            icon_name="fa5s.mouse-pointer",
            checkable=True,
            minimum_size=QSize(230, 64),
        )
        self._gaze_bubble_button = self._make_button(
            "Show gaze bubble",
            self._toggle_gaze_bubble,
            icon_name="fa5s.bullseye",
            checkable=True,
            minimum_size=QSize(220, 64),
        )
        self._interaction_overlay_button = self._make_button(
            "Show action overlay",
            self._toggle_interaction_overlay,
            icon_name="fa5s.circle-notch",
            checkable=True,
            minimum_size=QSize(220, 64),
        )
        self._precision_zoom_checkbox = self._make_checkbox(
            "Use precision zoom",
            self._toggle_precision_zoom,
            minimum_size=QSize(230, 64),
        )
        self._calibration_button = self._make_button(
            "Start Tobii calibration",
            self._request_calibration,
            icon_name="fa5s.crosshairs",
            minimum_size=QSize(230, 64),
        )
        actions.addWidget(self._move_pointer_button, 0, 0)
        actions.addWidget(self._gaze_bubble_button, 0, 1)
        actions.addWidget(self._calibration_button, 1, 0)
        actions.addWidget(self._interaction_overlay_button, 1, 1)
        actions.addWidget(self._precision_zoom_checkbox, 2, 0)
        actions.setColumnStretch(2, 1)
        layout.addLayout(actions)
        layout.addStretch(1)

        return page

    def _build_speech_page(self) -> QWidget:
        page = QFrame(self)
        page.setObjectName("settingsPanel")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("Speech settings", page)
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        self._speed_value = self._make_value_label(page)
        layout.addWidget(
            self._make_adjust_row(
                "Speech speed",
                "Words per minute used by eSpeak NG.",
                self._speed_value,
                lambda: self._adjust_speech_speed(-5),
                lambda: self._adjust_speech_speed(5),
            )
        )

        self._letters_group_value = self._make_value_label(page)
        layout.addWidget(
            self._make_adjust_row(
                "Letters per group",
                "Letter chunk size for speech and keyboard grouping.",
                self._letters_group_value,
                lambda: self._adjust_letters_per_group(-1),
                lambda: self._adjust_letters_per_group(1),
            )
        )

        voice_row = QFrame(page)
        voice_row.setObjectName("settingRow")
        voice_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        voice_layout = QGridLayout(voice_row)
        voice_layout.setContentsMargins(16, 14, 16, 14)
        voice_layout.setHorizontalSpacing(16)
        voice_layout.setVerticalSpacing(6)
        voice_layout.setColumnStretch(0, 1)

        voice_title = QLabel("Voice", voice_row)
        voice_title.setObjectName("settingTitle")
        voice_hint = QLabel(
            "Default uses eSpeak NG. Human like uses Microsoft Edge neural voice bs-BA-GoranNeural.",
            voice_row,
        )
        voice_hint.setObjectName("settingHint")
        voice_hint.setWordWrap(True)

        self._voice_combo = QComboBox(voice_row)
        self._voice_combo.setMinimumSize(QSize(260, 64))
        self._voice_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        for value, label in VOICE_PRESETS:
            self._voice_combo.addItem(label, value)
        self._voice_combo.currentIndexChanged.connect(self._voice_combo_changed)
        self._register_gaze(self._voice_combo, self._cycle_voice_preset, "Voice")

        voice_layout.addWidget(voice_title, 0, 0)
        voice_layout.addWidget(voice_hint, 1, 0)
        voice_layout.addWidget(self._voice_combo, 0, 1, 2, 1)
        layout.addWidget(voice_row)

        actions = QHBoxLayout()
        actions.setSpacing(12)
        self._test_speech_button = self._make_button(
            "Test speech",
            self._request_speech_test,
            icon_name="fa5s.play",
            minimum_size=QSize(190, 64),
        )
        actions.addWidget(self._test_speech_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addStretch(1)

        return page

    def _make_adjust_row(
        self,
        title: str,
        hint: str,
        value_label: QLabel,
        decrease: GazeCallback,
        increase: GazeCallback,
    ) -> QFrame:
        row = QFrame(self)
        row.setObjectName("settingRow")
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QGridLayout(row)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(5)
        layout.setColumnStretch(0, 1)

        title_label = QLabel(title, row)
        title_label.setObjectName("settingTitle")
        hint_label = QLabel(hint, row)
        hint_label.setObjectName("settingHint")
        hint_label.setWordWrap(True)

        minus_button = self._make_button(
            "Less",
            decrease,
            icon_name="fa5s.minus",
            minimum_size=QSize(112, 58),
        )
        plus_button = self._make_button(
            "More",
            increase,
            icon_name="fa5s.plus",
            minimum_size=QSize(112, 58),
        )

        layout.addWidget(title_label, 0, 0)
        layout.addWidget(hint_label, 1, 0)
        layout.addWidget(value_label, 0, 1, 2, 1)
        layout.addWidget(minus_button, 0, 2, 2, 1)
        layout.addWidget(plus_button, 0, 3, 2, 1)

        return row

    def _make_value_label(self, parent: QWidget) -> QLabel:
        label = QLabel(parent)
        label.setObjectName("valueLabel")
        label.setAlignment(Qt.AlignCenter)
        label.setMinimumWidth(150)
        return label

    def _make_button(
        self,
        text: str,
        callback: GazeCallback,
        icon_name: str = "",
        object_name: str = "",
        checkable: bool = False,
        minimum_size: QSize | None = None,
    ) -> QToolButton:
        button = QToolButton(self)
        button.setText(text)
        button.setMinimumSize(minimum_size or QSize(150, 58))
        button.setCheckable(checkable)
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setIconSize(QSize(22, 22))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if object_name:
            button.setObjectName(object_name)
        if icon_name:
            button.setIcon(self._icon(icon_name))
        button.pressed.connect(lambda: self.cancel_gaze_interaction(require_leave=True))
        button.clicked.connect(lambda _checked=False, item=callback: item())
        self._register_gaze(button, callback, text)
        return button

    def _make_checkbox(
        self,
        text: str,
        callback: GazeCallback,
        minimum_size: QSize | None = None,
    ) -> QCheckBox:
        checkbox = QCheckBox(text, self)
        checkbox.setMinimumSize(minimum_size or QSize(250, 58))
        checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        checkbox.pressed.connect(lambda: self.cancel_gaze_interaction(require_leave=True))
        checkbox.clicked.connect(lambda _checked=False, item=callback: item())
        self._register_gaze(checkbox, callback, text)
        return checkbox

    def _register_gaze(self, widget: QWidget, callback: GazeCallback, name: str) -> None:
        self._gaze_actions[widget] = callback
        self._gaze_names[widget] = name
        widget.setProperty("gazeTarget", False)
        widget.setProperty("gazePulse", "")

    def _gaze_action_at(self, point: QPoint) -> tuple[QWidget, GazeCallback] | None:
        for widget, action in self._gaze_actions.items():
            if not widget.isVisible() or not widget.isEnabled():
                continue

            top_left = widget.mapToGlobal(QPoint(0, 0))
            rect = QRect(top_left, widget.size())
            if rect.contains(point):
                return widget, action

        return None

    def _set_gaze_target(self, widget: QWidget | None) -> None:
        if widget is self._gaze_target:
            return

        if self._gaze_target is not None:
            self._set_target_property(self._gaze_target, False)

        self._gaze_target = widget

        if self._gaze_target is not None:
            self._set_target_property(self._gaze_target, True)

    def _set_target_property(self, widget: QWidget, active: bool) -> None:
        set_gaze_feedback(widget, active)

    def _emit_interaction_progress(self, widget: QWidget, progress: float) -> None:
        self._interaction_active = True
        self.interaction_progress_changed.emit(
            self._widget_global_center(widget),
            progress,
            self._gaze_names.get(widget, "Select"),
        )

    def _finish_interaction(self, widget: QWidget) -> None:
        self._interaction_active = False
        self.interaction_finished.emit(
            self._widget_global_center(widget),
            self._gaze_names.get(widget, "Select"),
        )

    def _cancel_interaction(self) -> None:
        if not self._interaction_active:
            return

        self._interaction_active = False
        self.interaction_cancelled.emit()

    def _widget_global_center(self, widget: QWidget) -> QPoint:
        top_left = widget.mapToGlobal(QPoint(0, 0))
        return QRect(top_left, widget.size()).center()

    def _select_tab(self, index: int) -> None:
        self.cancel_gaze_interaction(require_leave=True)
        self._stack.setCurrentIndex(index)
        self._general_tab_button.setChecked(index == 0)
        self._gaze_tab_button.setChecked(index == 1)
        self._speech_tab_button.setChecked(index == 2)
        if index == 0:
            self._set_status("General settings")
        elif index == 1:
            self._set_status("Gaze settings")
        elif index == 2:
            self._set_status("Speech settings")

    def _toggle_move_pointer(self) -> None:
        checked = not self._gaze_settings.move_mouse
        self._gaze_settings = replace(self._gaze_settings, move_mouse=checked)
        self._emit_gaze_settings("Pointer movement updated.")

    def _toggle_gaze_bubble(self) -> None:
        checked = not self._gaze_settings.show_gaze_bubble
        self._gaze_settings = replace(self._gaze_settings, show_gaze_bubble=checked)
        self._emit_gaze_settings("Gaze bubble updated.")

    def _toggle_interaction_overlay(self) -> None:
        checked = not self._gaze_settings.show_interaction_overlay
        self._gaze_settings = replace(self._gaze_settings, show_interaction_overlay=checked)
        self._emit_gaze_settings("Action overlay updated.")

    def _toggle_precision_zoom(self) -> None:
        checked = not self._gaze_settings.use_precision_zoom
        self._gaze_settings = replace(self._gaze_settings, use_precision_zoom=checked)
        status = "Precision zoom enabled." if checked else "Precision zoom disabled."
        self._emit_gaze_settings(status)

    def _toggle_start_with_windows(self) -> None:
        desired = not self._gaze_settings.start_with_windows
        self._set_status("Enabling Windows startup." if desired else "Disabling Windows startup.")
        result = set_windows_startup_enabled(
            desired,
            show_launcher_window=self._gaze_settings.show_launcher_window,
        )
        self._gaze_settings = replace(self._gaze_settings, start_with_windows=result.enabled)
        self._emit_gaze_settings(result.message)

    def _toggle_logging_enabled(self) -> None:
        desired = not self._gaze_settings.logging_enabled
        status = "Logging enabled." if desired else "Logging disabled."
        try:
            self._gaze_settings = replace(self._gaze_settings, logging_enabled=desired)
            set_application_logging_enabled(desired)
        except Exception as exc:
            logger.exception("Could not update application logging state.")
            self._gaze_settings = replace(self._gaze_settings, logging_enabled=not desired)
            status = f"Logging update failed: {exc}"
        self._emit_gaze_settings(status)

    def _toggle_show_launcher_window(self) -> None:
        desired = not self._gaze_settings.show_launcher_window
        status = (
            "PowerShell launcher window will be shown."
            if desired
            else "PowerShell launcher will run silently in background."
        )
        self._gaze_settings = replace(self._gaze_settings, show_launcher_window=desired)

        if self._gaze_settings.start_with_windows:
            result = set_windows_startup_enabled(True, show_launcher_window=desired)
            self._gaze_settings = replace(self._gaze_settings, start_with_windows=result.enabled)
            if not result.success:
                status = result.message

        self._emit_gaze_settings(status)

    def _adjust_dwell_ms(self, delta: int) -> None:
        value = _clamp_int(self._gaze_settings.dwell_ms + delta, 150, 5000)
        self._gaze_settings = replace(self._gaze_settings, dwell_ms=value)
        self._emit_gaze_settings("Stare time updated.")

    def _adjust_dwell_radius(self, delta: int) -> None:
        value = _clamp_int(self._gaze_settings.dwell_radius_px + delta, 10, 160)
        self._gaze_settings = replace(self._gaze_settings, dwell_radius_px=value)
        self._emit_gaze_settings("Stable target radius updated.")

    def _adjust_click_cooldown(self, delta: int) -> None:
        value = _clamp_int(self._gaze_settings.click_cooldown_ms + delta, 100, 5000)
        self._gaze_settings = replace(self._gaze_settings, click_cooldown_ms=value)
        self._emit_gaze_settings("Repeat delay updated.")

    def _adjust_smoothing(self, delta: float) -> None:
        value = round(_clamp_float(self._gaze_settings.smoothing + delta, 0.05, 1.0), 2)
        self._gaze_settings = replace(self._gaze_settings, smoothing=value)
        self._emit_gaze_settings("Pointer smoothing updated.")

    def _adjust_speech_speed(self, delta: int) -> None:
        value = _clamp_int(self._speech_settings.speed + delta, 80, 320)
        self._speech_settings = replace(self._speech_settings, speed=value)
        self._emit_speech_settings("Speech speed updated.")

    def _adjust_letters_per_group(self, delta: int) -> None:
        value = _clamp_int(self._speech_settings.letters_per_group + delta, 1, 12)
        self._speech_settings = replace(self._speech_settings, letters_per_group=value)
        self._emit_speech_settings("Letters per group updated.")

    def _voice_combo_changed(self, index: int) -> None:
        value = self._voice_combo.itemData(index)
        if not isinstance(value, str) or not value:
            value = VOICE_PRESET_DEFAULT

        if value == self._speech_settings.voice_preset:
            return

        self._speech_settings = replace(self._speech_settings, voice_preset=value)
        self._emit_speech_settings("Voice updated.")

    def _cycle_voice_preset(self) -> None:
        count = self._voice_combo.count()
        if count <= 0:
            return

        next_index = (self._voice_combo.currentIndex() + 1) % count
        self._voice_combo.setCurrentIndex(next_index)

    def _emit_gaze_settings(self, status: str) -> None:
        self._refresh_values()
        self.gaze_settings_changed.emit(replace(self._gaze_settings))
        self._set_status(status)

    def _emit_speech_settings(self, status: str) -> None:
        self._refresh_values()
        self.speech_settings_changed.emit(replace(self._speech_settings))
        self._set_status(status)

    def _request_calibration(self) -> None:
        self._set_status("Starting Tobii calibration.")
        self.calibration_requested.emit()

    def _request_speech_test(self) -> None:
        self._set_status("Testing speech.")
        self.speech_test_requested.emit()

    def _request_quit(self) -> None:
        self._set_status("Quitting application.")
        self.quit_requested.emit()

    def _refresh_values(self) -> None:
        self._dwell_value.setText(f"{self._gaze_settings.dwell_ms} ms")
        self._radius_value.setText(f"{self._gaze_settings.dwell_radius_px} px")
        self._cooldown_value.setText(f"{self._gaze_settings.click_cooldown_ms} ms")
        self._smoothing_value.setText(f"{self._gaze_settings.smoothing:.2f}")
        self._speed_value.setText(f"{self._speech_settings.speed} wpm")
        self._letters_group_value.setText(str(self._speech_settings.letters_per_group))
        self._move_pointer_button.setChecked(self._gaze_settings.move_mouse)
        self._gaze_bubble_button.setChecked(self._gaze_settings.show_gaze_bubble)
        self._interaction_overlay_button.setChecked(self._gaze_settings.show_interaction_overlay)
        self._precision_zoom_checkbox.setChecked(self._gaze_settings.use_precision_zoom)
        self._startup_checkbox.setChecked(self._gaze_settings.start_with_windows)
        self._logging_checkbox.setChecked(self._gaze_settings.logging_enabled)
        self._launcher_window_checkbox.setChecked(self._gaze_settings.show_launcher_window)
        self._sync_voice_combo()

    def _sync_voice_combo(self) -> None:
        desired = self._speech_settings.voice_preset or VOICE_PRESET_DEFAULT
        index = self._voice_combo.findData(desired)
        if index < 0:
            index = self._voice_combo.findData(VOICE_PRESET_DEFAULT)
        if index < 0 or index == self._voice_combo.currentIndex():
            return

        previous = self._voice_combo.blockSignals(True)
        try:
            self._voice_combo.setCurrentIndex(index)
        finally:
            self._voice_combo.blockSignals(previous)

    def _set_status(self, text: str) -> None:
        logger.info("Settings status: %s", text)
        self._status_label.setText(text)

    def _install_shortcuts(self) -> None:
        self._escape_shortcut = QShortcut(QKeySequence("Esc"), self)
        self._escape_shortcut.activated.connect(self.close)

    def _icon(self, icon_name: str) -> QIcon:
        try:
            import qtawesome as qta

            return qta.icon(icon_name, color="#f8f7f2")
        except Exception:
            logger.exception("Could not load qtawesome icon %s; using fallback.", icon_name)
            return self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)

    def _sync_startup_setting_from_windows(self) -> None:
        try:
            self._gaze_settings = replace(
                self._gaze_settings,
                start_with_windows=is_windows_startup_enabled(),
            )
        except Exception:
            logger.exception("Could not sync Windows startup state.")


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return min(maximum, max(minimum, value))


def _clamp_float(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


def _checkbox_x_image_url() -> str:
    return Path(__file__).with_name("assets").joinpath("checkbox_x.svg").resolve().as_posix()
