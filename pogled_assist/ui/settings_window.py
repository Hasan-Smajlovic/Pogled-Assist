"""Fullscreen gaze-selectable settings UI."""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QPoint, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from ..interaction.gaze_selection import (
    MAX_SELECTION_PAUSE_MS,
    MIN_SELECTION_PAUSE_MS,
    GazeSelectionTimer,
)
from ..interaction.mouse_controller import GazeSettings
from ..keyboard_layouts import ARABIC_SCRIPT, KEYBOARD_SCRIPTS, LATIN_SCRIPT
from ..logging_setup import set_application_logging_enabled
from ..release_update import ReleaseUpdateManager
from ..speech.speech_service import VOICE_PRESET_DEFAULT, VOICE_PRESETS, SpeechSettings
from ..suggestions.service import SuggestionService
from ..windows.windows_startup import is_windows_startup_enabled, set_windows_startup_enabled
from .gaze_feedback import set_gaze_feedback
from .learned_words_page import LearnedWordsPage
from .release_update_row import ReleaseUpdateRow
from .settings_controls import (
    GazeCallback,
    SettingsControls,
    action_grid,
    content_layout,
    global_rect,
    setting_row,
    styled_label,
)

logger = logging.getLogger(__name__)

ARABIC_VOICE_ITEM = "arabic_hamed"
BOSNIAN_VOICE_HINT = (
    "Standardni glas koristi eSpeak NG. Prirodni glas koristi Microsoft Edge bs-BA-GoranNeural."
)
ARABIC_VOICE_HINT = (
    "Arapski koristi prirodni muški glas Hamed. Potreban je internet. "
    "Izbor bosanskog glasa ostaje sačuvan."
)

SETTINGS_STYLESHEET = """
            QWidget#settingsRoot {
                background: #111312;
                color: #f4f1ea;
                font-family: Segoe UI, Arial, sans-serif;
                font-size: 15px;
            }
            QWidget#settingsRoot QLabel { color: #f4f1ea; background: transparent; }
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
                font-size: 24px;
                font-weight: 650;
            }
            QLabel#sectionDescription {
                color: #aeb9b3;
                font-size: 14px;
            }
            QLabel#navSectionLabel, QLabel#groupLabel {
                color: #8fa099;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel#navNote {
                color: #8fa099;
                font-size: 13px;
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
            QLabel#updateStatusLabel {
                color: #d8d3c8;
                font-size: 15px;
            }
            QWidget#settingsRoot QLabel#valueLabel {
                background: #0f1110;
                border: 1px solid #3a3d3b;
                border-radius: 10px;
                color: #ffffff;
                font-size: 22px;
                font-weight: 650;
                padding: 4px 12px;
            }
            QFrame#navPanel, QFrame#contentPanel {
                background: #191c1a;
                border: 1px solid #343a36;
                border-radius: 14px;
            }
            QFrame#settingRow {
                background: #222522;
                border: 1px solid #3a403c;
                border-radius: 10px;
            }
            QToolButton, QCheckBox {
                background: #272a28;
                border: 1px solid #414742;
                border-radius: 10px;
                color: #f5f3ef;
                font-size: 15px;
                font-weight: 600;
                padding: 10px 14px;
            }
            QToolButton:hover, QCheckBox:hover {
                background: #323633;
                border-color: #69736d;
            }
            QToolButton:disabled, QCheckBox:disabled {
                background: #242624;
                border-color: #363a37;
                color: #747b76;
            }
            QToolButton:checked, QCheckBox:checked {
                background: #1d6f68;
                border-color: #74d3c6;
                color: #ffffff;
            }
            QToolButton#navButton {
                background: transparent;
                border-color: transparent;
                text-align: left;
            }
            QToolButton#navButton:hover {
                background: #252a27;
                border-color: #3c4540;
            }
            QToolButton#navButton:checked, QToolButton#primaryButton {
                background: #1d6f68;
                border-color: #74d3c6;
                color: #ffffff;
            }
            QToolButton#adjustButton {
                background: #242825;
            }
            QToolButton[gazeTarget="true"], QCheckBox[gazeTarget="true"] {
                background: #3a3420;
                border: 3px solid #f0c84a;
                color: #ffffff;
            }
            QToolButton[gazeTarget="true"][gazePulse="0"],
            QCheckBox[gazeTarget="true"][gazePulse="0"] {
                background: #f0c84a;
                border: 4px solid #ffe58a;
                color: #14140f;
            }
            QToolButton[gazeTarget="true"][gazePulse="1"],
            QCheckBox[gazeTarget="true"][gazePulse="1"] {
                background: #16a34a;
                border: 4px solid #bbf7d0;
                color: #ffffff;
            }
            QToolButton#dangerButton {
                background: #492326;
                border-color: #804047;
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
                spacing: 10px;
            }
            QCheckBox::indicator {
                width: 24px;
                height: 24px;
                border: 2px solid #8b938d;
                border-radius: 6px;
                background: #101010;
            }
            QCheckBox::indicator:checked {
                background: #1d6f68;
                border-color: #74d3c6;
                image: url("__CHECKBOX_X_IMAGE__");
            }
            QComboBox {
                background: #0f1110;
                border: 1px solid #4c534e;
                border-radius: 10px;
                color: #ffffff;
                font-size: 20px;
                font-weight: 650;
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
            """


class SettingsWindow(QWidget):
    """Fullscreen settings surface that can be operated by gaze dwell."""

    closed = Signal()
    gaze_settings_changed = Signal(object)
    speech_settings_changed = Signal(object)
    save_retry_requested = Signal()
    calibration_requested = Signal()
    gaze_check_requested = Signal()
    speech_test_requested = Signal()
    update_requested = Signal()
    quit_requested = Signal()
    interaction_progress_changed = Signal(QPoint, float, str)
    interaction_finished = Signal(QPoint, str)
    interaction_cancelled = Signal()

    def __init__(
        self,
        gaze_settings: GazeSettings,
        speech_settings: SpeechSettings,
        parent: QWidget | None = None,
        *,
        update_manager: ReleaseUpdateManager | None = None,
        suggestions: SuggestionService | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Postavke")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Window)
        self.setObjectName("settingsRoot")

        self._gaze_settings = replace(gaze_settings)
        self._speech_settings = replace(speech_settings)
        self._update_manager = update_manager
        self._suggestions = suggestions or SuggestionService(self)
        self._controls = SettingsControls(
            self, lambda: self.cancel_gaze_interaction(require_leave=True)
        )
        self._gaze_target: QWidget | None = None
        self._gaze_selection = GazeSelectionTimer()
        self._last_gaze_action_ms = 0.0
        self._interaction_active = False

        self._sync_startup_setting_from_windows()
        self._build_ui()
        self._suggestions.status_changed.connect(self._learning_status_changed)
        self._install_shortcuts()
        self._refresh_values()
        self._update_row.start()
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
        if self._learning_page.blocks_gaze_at(point):
            self.cancel_gaze_interaction(require_leave=True)
            return
        if not self.isVisible():
            self.cancel_gaze_interaction()
            return

        target = self._controls.action_at(point)
        now_ms = time.monotonic() * 1000
        if target is None:
            self.cancel_gaze_interaction()
            return

        widget, action = target
        update = self._gaze_selection.update(
            widget,
            now_ms,
            pause_ms=self._gaze_settings.selection_pause_ms,
            dwell_ms=self._gaze_settings.dwell_ms,
        )
        if update.progress is None:
            self._set_gaze_target(None)
            self._cancel_interaction()
            return

        self._show_gaze_progress(widget, update.progress)
        cooled = now_ms - self._last_gaze_action_ms >= self._gaze_settings.click_cooldown_ms
        if update.ready and cooled:
            self._fire_gaze_action(widget, action, now_ms)

    def cancel_gaze_interaction(self, *, require_leave: bool = False) -> None:
        self._gaze_selection.cancel(require_leave=require_leave)
        self._set_gaze_target(None)
        self._cancel_interaction()

    def pause_gaze_interaction(self) -> None:
        self._gaze_selection.pause()
        self._set_gaze_target(None)
        self._cancel_interaction()

    def set_status(self, text: str) -> None:
        self._set_status(text)

    def set_save_error(self, failed: bool) -> None:
        self._save_note.setText(
            "Postavke nisu sačuvane. Važe do zatvaranja aplikacije."
            if failed
            else "Promjene se primjenjuju i čuvaju automatski."
        )
        self._retry_save_button.setVisible(failed)
        self.cancel_gaze_interaction(require_leave=True)

    def update_speech_settings(self, settings: SpeechSettings) -> None:
        self._speech_settings = replace(settings)
        self._refresh_values()

    def show_update_error(self, message: str) -> None:
        self._update_row.show_error(message)

    def _build_ui(self) -> None:
        self.setStyleSheet(
            SETTINGS_STYLESHEET.replace("__CHECKBOX_X_IMAGE__", _checkbox_x_image_url())
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 8, 16, 8)
        root.setSpacing(12)
        root.addLayout(self._build_top_bar())

        body = QHBoxLayout()
        body.setSpacing(14)
        root.addLayout(body, 1)
        body.addWidget(self._build_nav_panel(), 0)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._build_general_page())
        self._stack.addWidget(self._build_gaze_page())
        self._stack.addWidget(self._build_speech_page())
        self._learning_page = LearnedWordsPage(self._controls, self._suggestions, self)
        self._learning_page.back_requested.connect(lambda: self._select_tab(2))
        self._learning_page.status_changed.connect(self._set_status)
        self._stack.addWidget(self._learning_page)
        body.addWidget(self._stack, 1)

        self._select_tab(0)

    def _build_top_bar(self) -> QHBoxLayout:
        top_bar = QHBoxLayout()
        top_bar.setSpacing(16)

        title = styled_label("Postavke", "titleLabel", self)
        title.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        top_bar.addWidget(title, 1)

        self._status_label = styled_label("Spremno", "statusLabel", self)
        self._status_label.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
        self._status_label.setMinimumWidth(360)
        top_bar.addWidget(self._status_label, 0)
        self._exit_button = self._controls.button(
            "Zatvori", self.close, QSize(128, 58), "fa5s.times"
        )
        self._exit_button.setObjectName("dangerButton")
        top_bar.addWidget(self._exit_button, 0, Qt.AlignRight)
        return top_bar

    def _build_nav_panel(self) -> QFrame:
        nav_panel = QFrame(self)
        nav_panel.setObjectName("navPanel")
        nav_panel.setFixedWidth(250)
        nav_layout = QVBoxLayout(nav_panel)
        nav_layout.setContentsMargins(12, 12, 12, 12)
        nav_layout.setSpacing(8)

        nav_label = styled_label("KATEGORIJE", "navSectionLabel", nav_panel)
        nav_label.setContentsMargins(8, 4, 8, 2)
        nav_layout.addWidget(nav_label)

        self._general_tab_button = self._controls.toggle_button(
            "Opće postavke", lambda: self._select_tab(0), QSize(224, 66), "fa5s.sliders-h"
        )
        self._gaze_tab_button = self._controls.toggle_button(
            "Postavke pogleda", lambda: self._select_tab(1), QSize(224, 66), "fa5s.eye"
        )
        self._speech_tab_button = self._controls.toggle_button(
            "Postavke govora", lambda: self._select_tab(2), QSize(224, 66), "fa5s.volume-up"
        )
        self._tab_buttons = (
            self._general_tab_button,
            self._gaze_tab_button,
            self._speech_tab_button,
        )
        for button in self._tab_buttons:
            button.setObjectName("navButton")
            nav_layout.addWidget(button)
        nav_layout.addStretch(1)
        self._save_note = styled_label(
            "Promjene se primjenjuju i čuvaju automatski.", "navNote", nav_panel
        )
        self._save_note.setWordWrap(True)
        self._save_note.setContentsMargins(8, 0, 8, 6)
        nav_layout.addWidget(self._save_note)
        self._retry_save_button = self._controls.button(
            "Pokušaj sačuvati", self.save_retry_requested.emit, QSize(224, 66)
        )
        self._retry_save_button.hide()
        nav_layout.addWidget(self._retry_save_button)
        return nav_panel

    def _build_general_page(self) -> QWidget:
        page = QFrame(self)
        layout = content_layout(page)

        header = QGridLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setHorizontalSpacing(16)
        header.setVerticalSpacing(4)
        header.setColumnStretch(0, 1)
        title = styled_label("Opće postavke", "sectionTitle", page)
        description = styled_label(
            "Pokretanje, zapisivanje i ažuriranje aplikacije.", "sectionDescription", page
        )
        header.addWidget(title, 0, 0, Qt.AlignVCenter | Qt.AlignLeft)
        header.addWidget(description, 1, 0, Qt.AlignVCenter | Qt.AlignLeft)
        self._quit_button = self._controls.button(
            "Isključi aplikaciju", self._request_quit, QSize(154, 58), "fa5s.power-off"
        )
        self._quit_button.setObjectName("dangerButton")
        header.addWidget(self._quit_button, 0, 1, 2, 1, Qt.AlignVCenter | Qt.AlignRight)
        layout.addLayout(header)

        layout.addWidget(styled_label("POKRETANJE I DIJAGNOSTIKA", "groupLabel", page))
        self._startup_checkbox = self._controls.checkbox(
            "Pokreni uz Windows", self._toggle_start_with_windows, QSize(240, 58)
        )
        self._logging_checkbox = self._controls.checkbox(
            "Uključi zapisivanje", self._toggle_logging_enabled, QSize(240, 58)
        )
        self._launcher_window_checkbox = self._controls.checkbox(
            "Prikaži PowerShell", self._toggle_show_launcher_window, QSize(240, 58)
        )
        layout.addLayout(
            action_grid(
                (self._startup_checkbox, self._logging_checkbox, self._launcher_window_checkbox)
            )
        )

        layout.addWidget(styled_label("VERZIJA APLIKACIJE", "groupLabel", page))
        self._update_row = ReleaseUpdateRow(self._controls, self._update_manager, page)
        self._update_row.status_changed.connect(self._set_status)
        self._update_row.update_requested.connect(self.update_requested)
        layout.addWidget(self._update_row)
        layout.addStretch(1)
        return page

    def _build_gaze_page(self) -> QWidget:
        page = QFrame(self)
        layout = content_layout(page)
        layout.addWidget(styled_label("Postavke pogleda", "sectionTitle", page))
        layout.addWidget(
            styled_label(
                "Podesite brzinu, stabilnost i povratnu informaciju pogleda.",
                "sectionDescription",
                page,
            )
        )

        row, self._selection_pause_value = self._controls.adjust_row(
            "Pauza prije odabira",
            "Vrijeme čekanja prije nego što se krug napretka počne puniti.",
            self._adjust_selection_pause,
            50,
        )
        layout.addWidget(row)
        row, self._dwell_value = self._controls.adjust_row(
            "Vrijeme zadržavanja pogleda",
            "Vrijeme punjenja kruga napretka nakon početne pauze.",
            self._adjust_dwell_ms,
            50,
        )
        layout.addWidget(row)
        row, self._radius_value = self._controls.adjust_row(
            "Radijus stabilnog pogleda",
            "Koliko mirno pogled mora ostati prije pokretanja odabrane radnje.",
            self._adjust_dwell_radius,
            2,
        )
        layout.addWidget(row)
        row, self._cooldown_value = self._controls.adjust_row(
            "Pauza između radnji",
            "Vrijeme čekanja nakon jedne radnje prije pokretanja sljedeće.",
            self._adjust_click_cooldown,
            50,
        )
        layout.addWidget(row)
        row, self._smoothing_value = self._controls.adjust_row(
            "Uglađivanje pokazivača",
            "Niže vrijednosti su mirnije, a više brže prate pogled.",
            self._adjust_smoothing,
            0.05,
        )
        layout.addWidget(row)

        layout.addWidget(styled_label("PONAŠANJE I KALIBRACIJA", "groupLabel", page))
        layout.addLayout(self._build_gaze_actions())
        layout.addStretch(1)
        return page

    def _build_gaze_actions(self) -> QGridLayout:
        self._move_pointer_button = self._controls.toggle_button(
            "Pomjeraj pokazivač pogledom",
            self._toggle_move_pointer,
            QSize(220, 58),
            "fa5s.mouse-pointer",
        )
        self._gaze_bubble_button = self._controls.toggle_button(
            "Prikaži oznaku pogleda", self._toggle_gaze_bubble, QSize(210, 58), "fa5s.bullseye"
        )
        self._interaction_overlay_button = self._controls.toggle_button(
            "Prikaži napredak radnje",
            self._toggle_interaction_overlay,
            QSize(210, 58),
            "fa5s.circle-notch",
        )
        self._precision_zoom_checkbox = self._controls.checkbox(
            "Koristi precizno uvećanje", self._toggle_precision_zoom, QSize(220, 58)
        )
        self._calibration_button = self._controls.button(
            "Pokreni Tobii kalibraciju",
            self._request_calibration,
            QSize(220, 58),
            "fa5s.crosshairs",
        )
        self._gaze_check_button = self._controls.button(
            "Provjera pogleda", self._request_gaze_check, QSize(220, 58), "fa5s.eye"
        )
        return action_grid(
            (
                self._move_pointer_button,
                self._gaze_bubble_button,
                self._interaction_overlay_button,
                self._precision_zoom_checkbox,
                self._calibration_button,
                self._gaze_check_button,
            )
        )

    def _request_gaze_check(self) -> None:
        self.cancel_gaze_interaction()
        self.gaze_check_requested.emit()

    def _build_speech_page(self) -> QWidget:
        page = QFrame(self)
        layout = content_layout(page)
        layout.addWidget(styled_label("Postavke govora", "sectionTitle", page))
        layout.addWidget(
            styled_label(
                "Podesite glas i raspored tastature za komunikaciju.", "sectionDescription", page
            )
        )

        self._script_combo = self._controls.choice(
            KEYBOARD_SCRIPTS,
            self._script_combo_changed,
            self._cycle_keyboard_script,
            "Pismo tastature",
        )
        script_row, script_layout, _hint = setting_row(self, "Pismo tastature")
        script_layout.addWidget(self._script_combo, 0, 1, 2, 1)
        layout.addWidget(script_row)

        self._voice_combo = self._controls.choice(
            VOICE_PRESETS, self._voice_combo_changed, self._cycle_voice_preset, "Glas"
        )
        voice_row, voice_layout, self._voice_hint = setting_row(self, "Glas", BOSNIAN_VOICE_HINT)
        voice_layout.addWidget(self._voice_combo, 0, 1, 2, 1)
        layout.addWidget(voice_row)

        row, self._speed_value = self._controls.adjust_row(
            "Brzina govora",
            "Broj riječi u minuti koji koristi eSpeak NG.",
            self._adjust_speech_speed,
            5,
        )
        layout.addWidget(row)
        row, self._letters_group_value = self._controls.adjust_row(
            "Broj slova u grupi",
            "Broj slova u svakoj grupi na ekranima za govor i tastaturu.",
            self._adjust_letters_per_group,
            1,
        )
        layout.addWidget(row)

        layout.addWidget(styled_label("AKCIJE", "groupLabel", page))
        self._test_speech_button = self._controls.button(
            "Isprobaj govor", self._request_speech_test, QSize(240, 58), "fa5s.play"
        )
        self._test_speech_button.setObjectName("primaryButton")
        self._learned_words_button = self._controls.button(
            "Naučene riječi", self._open_learning, QSize(240, 58)
        )
        layout.addLayout(action_grid((self._test_speech_button, self._learned_words_button)))
        layout.addStretch(1)
        return page

    def _open_learning(self) -> None:
        self._select_tab(2)
        self._stack.setCurrentWidget(self._learning_page)
        self._learning_page.show_first_page()

    def _learning_status_changed(self, _message: str) -> None:
        if self._stack.currentWidget() is self._learning_page:
            self._learning_page.refresh()

    def _show_gaze_progress(self, widget: QWidget, progress: float) -> None:
        name = self._controls.name(widget)
        if widget is not self._gaze_target:
            self._set_gaze_target(widget)
            self._set_status(f"Cilj: {name}")
        self._interaction_active = True
        self.interaction_progress_changed.emit(global_rect(widget).center(), progress, name)

    def _fire_gaze_action(self, widget: QWidget, action: GazeCallback, now_ms: float) -> None:
        name = self._controls.name(widget)
        logger.info("Settings gaze action fired: %s", name)
        self._last_gaze_action_ms = now_ms
        self._gaze_selection.complete()
        self._interaction_active = False
        self.interaction_finished.emit(global_rect(widget).center(), name)
        self._set_gaze_target(None)
        action()

    def _set_gaze_target(self, widget: QWidget | None) -> None:
        if widget is self._gaze_target:
            return

        if self._gaze_target is not None:
            set_gaze_feedback(self._gaze_target, False)

        self._gaze_target = widget

        if self._gaze_target is not None:
            set_gaze_feedback(self._gaze_target, True)

    def _cancel_interaction(self) -> None:
        if not self._interaction_active:
            return

        self._interaction_active = False
        self.interaction_cancelled.emit()

    def _select_tab(self, index: int) -> None:
        self.cancel_gaze_interaction(require_leave=True)
        self._stack.setCurrentIndex(index)
        for tab, button in enumerate(self._tab_buttons):
            button.setChecked(tab == index)
        self._set_status(self._tab_buttons[index].text())

    def _toggle_move_pointer(self) -> None:
        checked = not self._gaze_settings.move_mouse
        self._gaze_settings = replace(self._gaze_settings, move_mouse=checked)
        self._emit_gaze_settings("Pomjeranje pokazivača je ažurirano.")

    def _toggle_gaze_bubble(self) -> None:
        checked = not self._gaze_settings.show_gaze_bubble
        self._gaze_settings = replace(self._gaze_settings, show_gaze_bubble=checked)
        self._emit_gaze_settings("Oznaka pogleda je ažurirana.")

    def _toggle_interaction_overlay(self) -> None:
        checked = not self._gaze_settings.show_interaction_overlay
        self._gaze_settings = replace(self._gaze_settings, show_interaction_overlay=checked)
        self._emit_gaze_settings("Prikaz napretka radnje je ažuriran.")

    def _toggle_precision_zoom(self) -> None:
        checked = not self._gaze_settings.use_precision_zoom
        self._gaze_settings = replace(self._gaze_settings, use_precision_zoom=checked)
        status = (
            "Precizno uvećanje je uključeno." if checked else "Precizno uvećanje je isključeno."
        )
        self._emit_gaze_settings(status)

    def _toggle_start_with_windows(self) -> None:
        desired = not self._gaze_settings.start_with_windows
        self._set_status(
            "Uključujem pokretanje uz Windows." if desired else "Isključujem pokretanje uz Windows."
        )
        result = set_windows_startup_enabled(
            desired,
            show_launcher_window=self._gaze_settings.show_launcher_window,
        )
        self._gaze_settings = replace(self._gaze_settings, start_with_windows=result.enabled)
        self._emit_gaze_settings(result.message)

    def _toggle_logging_enabled(self) -> None:
        desired = not self._gaze_settings.logging_enabled
        status = "Zapisivanje je uključeno." if desired else "Zapisivanje je isključeno."
        try:
            self._gaze_settings = replace(self._gaze_settings, logging_enabled=desired)
            set_application_logging_enabled(desired)
        except Exception:
            logger.exception("Could not update application logging state.")
            self._gaze_settings = replace(self._gaze_settings, logging_enabled=not desired)
            status = "Ažuriranje zapisivanja nije uspjelo."
        self._emit_gaze_settings(status)

    def _toggle_show_launcher_window(self) -> None:
        desired = not self._gaze_settings.show_launcher_window
        status = (
            "PowerShell prozor će biti prikazan pri pokretanju."
            if desired
            else "PowerShell pokretač će raditi tiho u pozadini."
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
        self._emit_gaze_settings("Vrijeme zadržavanja pogleda je ažurirano.")

    def _adjust_selection_pause(self, delta: int) -> None:
        value = _clamp_int(
            self._gaze_settings.selection_pause_ms + delta,
            MIN_SELECTION_PAUSE_MS,
            MAX_SELECTION_PAUSE_MS,
        )
        self._gaze_settings = replace(self._gaze_settings, selection_pause_ms=value)
        self._emit_gaze_settings("Pauza prije odabira je ažurirana.")

    def _adjust_dwell_radius(self, delta: int) -> None:
        value = _clamp_int(self._gaze_settings.dwell_radius_px + delta, 10, 160)
        self._gaze_settings = replace(self._gaze_settings, dwell_radius_px=value)
        self._emit_gaze_settings("Radijus stabilnog pogleda je ažuriran.")

    def _adjust_click_cooldown(self, delta: int) -> None:
        value = _clamp_int(self._gaze_settings.click_cooldown_ms + delta, 100, 5000)
        self._gaze_settings = replace(self._gaze_settings, click_cooldown_ms=value)
        self._emit_gaze_settings("Pauza između radnji je ažurirana.")

    def _adjust_smoothing(self, delta: float) -> None:
        value = round(_clamp_float(self._gaze_settings.smoothing + delta, 0.05, 1.0), 2)
        self._gaze_settings = replace(self._gaze_settings, smoothing=value)
        self._emit_gaze_settings("Uglađivanje pokazivača je ažurirano.")

    def _adjust_speech_speed(self, delta: int) -> None:
        value = _clamp_int(self._speech_settings.speed + delta, 80, 320)
        self._speech_settings = replace(self._speech_settings, speed=value)
        self._emit_speech_settings("Brzina govora je ažurirana.")

    def _adjust_letters_per_group(self, delta: int) -> None:
        value = _clamp_int(self._speech_settings.letters_per_group + delta, 1, 12)
        self._speech_settings = replace(self._speech_settings, letters_per_group=value)
        self._emit_speech_settings("Broj slova u grupi je ažuriran.")

    def _voice_combo_changed(self, index: int) -> None:
        if self._speech_settings.keyboard_script == ARABIC_SCRIPT:
            return
        value = self._voice_combo.itemData(index)
        if not isinstance(value, str) or not value:
            value = VOICE_PRESET_DEFAULT

        if value == self._speech_settings.voice_preset:
            return

        self._speech_settings = replace(self._speech_settings, voice_preset=value)
        self._emit_speech_settings("Glas je ažuriran.")

    def _script_combo_changed(self, index: int) -> None:
        script = self._script_combo.itemData(index)
        if script not in dict(KEYBOARD_SCRIPTS):
            script = LATIN_SCRIPT
        if script == self._speech_settings.keyboard_script:
            return
        self.cancel_gaze_interaction(require_leave=True)
        self._speech_settings = replace(self._speech_settings, keyboard_script=script)
        self._emit_speech_settings("Pismo tastature je ažurirano.")

    def _cycle_keyboard_script(self) -> None:
        self._script_combo.setCurrentIndex(
            (self._script_combo.currentIndex() + 1) % self._script_combo.count()
        )

    def _cycle_voice_preset(self) -> None:
        if self._speech_settings.keyboard_script == ARABIC_SCRIPT:
            return
        count = self._voice_combo.count()
        if count <= 0:
            return

        next_index = (self._voice_combo.currentIndex() + 1) % count
        self._voice_combo.setCurrentIndex(next_index)

    def _emit_gaze_settings(self, status: str) -> None:
        self._refresh_values()
        self._set_status(status)
        self.gaze_settings_changed.emit(replace(self._gaze_settings))

    def _emit_speech_settings(self, status: str) -> None:
        self._refresh_values()
        self._set_status(status)
        self.speech_settings_changed.emit(replace(self._speech_settings))

    def _request_calibration(self) -> None:
        self._set_status("Pokrećem Tobii kalibraciju.")
        self.calibration_requested.emit()

    def _request_speech_test(self) -> None:
        self._set_status("Isprobavam govor.")
        self.speech_test_requested.emit()

    def _request_quit(self) -> None:
        self._set_status("Isključujem aplikaciju.")
        self.quit_requested.emit()

    def _refresh_values(self) -> None:
        self._selection_pause_value.setText(f"{self._gaze_settings.selection_pause_ms} ms")
        self._dwell_value.setText(f"{self._gaze_settings.dwell_ms} ms")
        self._radius_value.setText(f"{self._gaze_settings.dwell_radius_px} px")
        self._cooldown_value.setText(f"{self._gaze_settings.click_cooldown_ms} ms")
        self._smoothing_value.setText(f"{self._gaze_settings.smoothing:.2f}")
        self._speed_value.setText(f"{self._speech_settings.speed} riječi/min")
        self._letters_group_value.setText(str(self._speech_settings.letters_per_group))
        self._move_pointer_button.setChecked(self._gaze_settings.move_mouse)
        self._gaze_bubble_button.setChecked(self._gaze_settings.show_gaze_bubble)
        self._interaction_overlay_button.setChecked(self._gaze_settings.show_interaction_overlay)
        self._precision_zoom_checkbox.setChecked(self._gaze_settings.use_precision_zoom)
        self._startup_checkbox.setChecked(self._gaze_settings.start_with_windows)
        self._logging_checkbox.setChecked(self._gaze_settings.logging_enabled)
        self._launcher_window_checkbox.setChecked(self._gaze_settings.show_launcher_window)
        self._sync_voice_combo()
        with QSignalBlocker(self._script_combo):
            self._script_combo.setCurrentIndex(
                max(0, self._script_combo.findData(self._speech_settings.keyboard_script))
            )
        arabic = self._speech_settings.keyboard_script == ARABIC_SCRIPT
        self._voice_combo.setEnabled(not arabic)
        self._voice_hint.setText(ARABIC_VOICE_HINT if arabic else BOSNIAN_VOICE_HINT)

    def _sync_voice_combo(self) -> None:
        arabic = self._speech_settings.keyboard_script == ARABIC_SCRIPT
        arabic_index = self._voice_combo.findData(ARABIC_VOICE_ITEM)
        with QSignalBlocker(self._voice_combo):
            if arabic and arabic_index < 0:
                self._voice_combo.addItem("Prirodni · Hamed", ARABIC_VOICE_ITEM)
            elif not arabic and arabic_index >= 0:
                self._voice_combo.removeItem(arabic_index)
            self._voice_combo.setCurrentIndex(self._voice_combo.findData(self._shown_voice(arabic)))

    def _shown_voice(self, arabic: bool) -> str:
        if arabic:
            return ARABIC_VOICE_ITEM
        desired = self._speech_settings.voice_preset or VOICE_PRESET_DEFAULT
        return desired if self._voice_combo.findData(desired) >= 0 else VOICE_PRESET_DEFAULT

    def _set_status(self, text: str) -> None:
        logger.info("Settings status: %s", text)
        self._status_label.setText(text)

    def _install_shortcuts(self) -> None:
        self._escape_shortcut = QShortcut(QKeySequence("Esc"), self)
        self._escape_shortcut.activated.connect(self.close)

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
    return (Path(__file__).resolve().parents[1] / "assets" / "checkbox_x.svg").as_posix()
