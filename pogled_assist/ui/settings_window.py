"""Fullscreen gaze-selectable settings UI."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from ..interaction.eye_tracking_policy import EyeTrackingGate
from ..interaction.gaze_selection import (
    MAX_SELECTION_PAUSE_MS,
    MIN_SELECTION_PAUSE_MS,
    GazeSelectionTimer,
)
from ..interaction.mouse_controller import GazeSettings
from ..keyboard_layouts import ARABIC_SCRIPT, KEYBOARD_SCRIPTS, LATIN_SCRIPT
from ..logging_setup import set_application_logging_enabled
from ..release_update import ReleaseUpdateManager
from ..settings_limits import (
    CLICK_COOLDOWN_MS_RANGE,
    DWELL_MS_RANGE,
    DWELL_RADIUS_RANGE,
    EDGE_HOLD_MS_RANGE,
    EYE_TRACKING_HOLD_MS_RANGE,
    LETTERS_PER_GROUP_RANGE,
    SMOOTHING_RANGE,
    SPEECH_SPEED_RANGE,
    clamp,
)
from ..speech.eleven_account import ElevenAccount
from ..speech.speech_service import SpeechSettings
from ..suggestions.service import SuggestionService
from ..windows.startup_tasks import StartupRequest, StartupTasks
from ..windows.windows_startup import (
    StartupTaskResult,
    is_windows_startup_enabled,
    set_windows_startup_enabled,
)
from .elevenlabs_settings import ElevenLabsPage, SavedAudioPage
from .gaze_feedback import set_gaze_feedback, set_gaze_paused
from .gaze_settings_page import GazeSettingsPage
from .general_settings_page import GeneralSettingsPage
from .learned_words_page import LearnedWordsPage
from .settings_controls import GazeCallback, SettingsControls, global_rect, styled_label
from .speech_settings_page import SpeechSettingsPage

logger = logging.getLogger(__name__)


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
            QLineEdit {
                background: #0f1110;
                border: 1px solid #4c534e;
                border-radius: 10px;
                color: #ffffff;
                font-size: 18px;
                padding: 8px 12px;
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


@dataclass(frozen=True)
class SettingsServices:
    account: ElevenAccount | None = None
    clear_audio: Callable[[], bool] | None = None
    update_manager: ReleaseUpdateManager | None = None
    suggestions: SuggestionService | None = None


class SettingsWindow(QWidget):
    """Fullscreen settings surface that can be operated by gaze dwell."""

    closed = Signal()
    gaze_settings_changed = Signal(object)
    speech_settings_changed = Signal(object)
    save_retry_requested = Signal()
    calibration_requested = Signal()
    gaze_check_requested = Signal()
    diagnostics_requested = Signal()
    speech_test_requested = Signal()
    speech_stop_requested = Signal()
    efendija_test_requested = Signal()
    update_requested = Signal(object)
    restart_confirmed = Signal()
    install_cancelled = Signal()
    quit_requested = Signal()
    interaction_progress_changed = Signal(QPoint, float, str)
    interaction_finished = Signal(QPoint, str)
    interaction_cancelled = Signal()
    interaction_hold_changed = Signal(bool)
    _startup_task_completed = Signal(int, object, object)

    def __init__(
        self,
        gaze_settings: GazeSettings,
        speech_settings: SpeechSettings,
        parent: QWidget | None = None,
        *,
        services: SettingsServices | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Postavke")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Window)
        self.setObjectName("settingsRoot")

        self._gaze_settings = replace(gaze_settings)
        self._speech_settings = replace(speech_settings)
        self._speech_playback_state = "stopped"
        services = services or SettingsServices()
        self._eleven_account = services.account or ElevenAccount(self)
        self._eleven_account.configure(self._speech_settings)
        self._clear_audio = services.clear_audio or (lambda: False)
        self._update_manager = services.update_manager
        self._suggestions = services.suggestions or SuggestionService(self)
        self._controls = SettingsControls(
            self, lambda: self.cancel_gaze_interaction(require_leave=True)
        )
        self._setup_gaze()
        self._startup_revision = 0
        self._startup_busy = False
        self._startup_closed = False
        self._startup_desired_enabled: bool | None = None
        self._startup_tasks = StartupTasks(
            self._startup_task_completed.emit,
            query=is_windows_startup_enabled,
            update=set_windows_startup_enabled,
        )
        self._startup_task_completed.connect(
            self._finish_startup_task, Qt.ConnectionType.QueuedConnection
        )

        self._build_ui()
        self._suggestions.status_changed.connect(self._learning_status_changed)
        self._install_shortcuts()
        self._refresh_values()
        self._eleven_account.changed.connect(self._account_changed)
        self._general_page._update_row.start()
        self._sync_startup_setting_from_windows()
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
        self._startup_closed = True
        self._startup_tasks.close()
        self._eleven_page.clear_input()
        self._eleven_account.cancel_check()
        self.cancel_gaze_interaction()
        self.closed.emit()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:
        if hasattr(self, "_gaze_selection"):
            self.cancel_gaze_interaction(require_leave=True)
        super().resizeEvent(event)

    def moveEvent(self, event) -> None:
        if hasattr(self, "_gaze_selection"):
            self.cancel_gaze_interaction(require_leave=True)
        super().moveEvent(event)

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
        self._eleven_account.configure(self._speech_settings)
        self._refresh_values()

    def show_update_error(self, message: str) -> None:
        self._general_page._update_row.show_error(message)

    def confirm_update_restart(self) -> None:
        self._select_tab(0)
        self._general_page._update_row.confirm_restart()

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
        self._general_page = GeneralSettingsPage(self)
        self._stack.addWidget(self._general_page)
        self._gaze_page = GazeSettingsPage(self)
        self._stack.addWidget(self._gaze_page)
        self._speech_page = SpeechSettingsPage(self)
        self._stack.addWidget(self._speech_page)
        self._learning_page = LearnedWordsPage(self._controls, self._suggestions, self)
        self._learning_page.back_requested.connect(lambda: self._select_tab(2))
        self._learning_page.status_changed.connect(self._set_status)
        self._stack.addWidget(self._learning_page)
        self._eleven_page = ElevenLabsPage(self._controls, self._eleven_account, self)
        self._eleven_page.back_requested.connect(lambda: self._select_tab(2))
        self._eleven_page.selection_changed.connect(self._eleven_selection)
        self._eleven_page.test_requested.connect(self.efendija_test_requested.emit)
        self._eleven_page.stop_requested.connect(self.speech_stop_requested.emit)
        self._eleven_page.tuning_changed.connect(self._eleven_tuning)
        self._stack.addWidget(self._eleven_page)
        self._audio_page = SavedAudioPage(self._controls, self._clear_audio, self)
        self._audio_page.back_requested.connect(lambda: self._select_tab(2))
        self._stack.addWidget(self._audio_page)
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

    def _request_gaze_check(self) -> None:
        self.cancel_gaze_interaction()
        self.gaze_check_requested.emit()

    def _open_eleven(self) -> None:
        self._select_tab(2)
        self._eleven_page.configure(self._speech_settings)
        self._stack.setCurrentWidget(self._eleven_page)
        self._eleven_account.refresh_subscription()

    def _eleven_tuning(self, stability: int, similarity: int) -> None:
        self._speech_settings = replace(
            self._speech_settings, elevenlabs_stability=stability, elevenlabs_similarity=similarity
        )
        self._eleven_account.configure(self._speech_settings)
        self._emit_speech_settings("Postavke Efendijinog glasa su ažurirane.")

    def set_speech_playback_state(self, state: str) -> None:
        before = self._dynamic_control_state()
        self._speech_playback_state = state
        self._eleven_page.set_playback_state(state)
        self._speech_page.refresh(self._speech_settings, state, self._eleven_account)
        self._cancel_changed_target(before)

    def _open_audio(self) -> None:
        self._select_tab(2)
        self._stack.setCurrentWidget(self._audio_page)

    def _eleven_selection(self, voice: str, model: str) -> None:
        if not model:
            model = self._speech_settings.elevenlabs_model_id
        self._speech_settings = replace(
            self._speech_settings, elevenlabs_voice_id=voice, elevenlabs_model_id=model
        )
        self._eleven_account.configure(self._speech_settings)
        self._emit_speech_settings("ElevenLabs glas i model su ažurirani.")

    def _account_changed(self, state) -> None:
        before = self._dynamic_control_state()
        self._speech_page.refresh(
            self._speech_settings, self._speech_playback_state, self._eleven_account
        )
        self._eleven_page.refresh(state)
        self._cancel_changed_target(before)

    def _open_learning(self) -> None:
        self._select_tab(2)
        self._stack.setCurrentWidget(self._learning_page)
        self._learning_page.show_first_page()

    def _learning_status_changed(self, _message: str) -> None:
        if self._stack.currentWidget() is self._learning_page:
            self._learning_page.refresh()

    def _select_tab(self, index: int) -> None:
        self.cancel_gaze_interaction(require_leave=True)
        self._eleven_page.clear_input()
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

    def _toggle_tracking_notifications(self) -> None:
        enabled = not self._gaze_settings.show_tracking_notifications
        self._gaze_settings = replace(self._gaze_settings, show_tracking_notifications=enabled)
        self._emit_gaze_settings(
            "Obavijesti o praćenju su uključene."
            if enabled
            else "Obavijesti o praćenju su isključene."
        )

    def _toggle_precision_zoom(self) -> None:
        checked = not self._gaze_settings.use_precision_zoom
        self._gaze_settings = replace(self._gaze_settings, use_precision_zoom=checked)
        status = (
            "Precizno uvećanje je uključeno." if checked else "Precizno uvećanje je isključeno."
        )
        self._emit_gaze_settings(status)

    def _toggle_start_with_windows(self) -> None:
        desired = not (
            self._gaze_settings.start_with_windows
            if self._startup_desired_enabled is None
            else self._startup_desired_enabled
        )
        self._startup_desired_enabled = desired
        self._set_status(
            "Uključujem pokretanje uz Windows." if desired else "Isključujem pokretanje uz Windows."
        )
        self._queue_startup_task(desired)

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

        if self._startup_desired_enabled is not False:
            # None means the initial query has not established the OS state.
            # Resolve it in the worker before deciding whether to update the task.
            self._queue_startup_task(
                self._startup_desired_enabled, status=status, update_launcher=True
            )

        self._emit_gaze_settings(status)

    def _select_eye_tracking_policy(self, index: int) -> None:
        policy = self._gaze_page._policy_combo.itemData(index)
        self._gaze_settings = replace(self._gaze_settings, eye_tracking_policy=policy)
        self._emit_gaze_settings("Režim praćenja očiju je ažuriran.")

    def _cycle_eye_tracking_policy(self) -> None:
        combo = self._gaze_page._policy_combo
        combo.setCurrentIndex((combo.currentIndex() + 1) % combo.count())

    def _adjust_eye_tracking_hold(self, delta: int) -> None:
        value = clamp(self._gaze_settings.eye_tracking_hold_ms + delta, EYE_TRACKING_HOLD_MS_RANGE)
        self._gaze_settings = replace(self._gaze_settings, eye_tracking_hold_ms=value)
        self._emit_gaze_settings("Trajanje kratkog prekida je ažurirano.")

    def _adjust_dwell_ms(self, delta: int) -> None:
        value = clamp(self._gaze_settings.dwell_ms + delta, DWELL_MS_RANGE)
        self._gaze_settings = replace(self._gaze_settings, dwell_ms=value)
        self._emit_gaze_settings("Vrijeme zadržavanja pogleda je ažurirano.")

    def _adjust_edge_hold(self, delta: int) -> None:
        self.cancel_gaze_interaction(require_leave=True)
        value = clamp(self._gaze_settings.edge_hold_ms + delta, EDGE_HOLD_MS_RANGE)
        self._gaze_settings = replace(self._gaze_settings, edge_hold_ms=value)
        self._emit_gaze_settings("Čuvanje odabira uz rub je ažurirano.")

    def _adjust_selection_pause(self, delta: int) -> None:
        value = clamp(
            self._gaze_settings.selection_pause_ms + delta,
            (MIN_SELECTION_PAUSE_MS, MAX_SELECTION_PAUSE_MS),
        )
        self._gaze_settings = replace(self._gaze_settings, selection_pause_ms=value)
        self._emit_gaze_settings("Pauza prije odabira je ažurirana.")

    def _adjust_dwell_radius(self, delta: int) -> None:
        value = clamp(self._gaze_settings.dwell_radius_px + delta, DWELL_RADIUS_RANGE)
        self._gaze_settings = replace(self._gaze_settings, dwell_radius_px=value)
        self._emit_gaze_settings("Radijus stabilnog pogleda je ažuriran.")

    def _adjust_click_cooldown(self, delta: int) -> None:
        value = clamp(self._gaze_settings.click_cooldown_ms + delta, CLICK_COOLDOWN_MS_RANGE)
        self._gaze_settings = replace(self._gaze_settings, click_cooldown_ms=value)
        self._emit_gaze_settings("Pauza između radnji je ažurirana.")

    def _adjust_smoothing(self, delta: float) -> None:
        value = round(clamp(self._gaze_settings.smoothing + delta, SMOOTHING_RANGE), 2)
        self._gaze_settings = replace(self._gaze_settings, smoothing=value)
        self._emit_gaze_settings("Uglađivanje pokazivača je ažurirano.")

    def _adjust_speech_speed(self, delta: int) -> None:
        value = clamp(self._speech_settings.speed + delta, SPEECH_SPEED_RANGE)
        self._speech_settings = replace(self._speech_settings, speed=value)
        self._emit_speech_settings("Brzina govora je ažurirana.")

    def _adjust_letters_per_group(self, delta: int) -> None:
        value = clamp(self._speech_settings.letters_per_group + delta, LETTERS_PER_GROUP_RANGE)
        self._speech_settings = replace(self._speech_settings, letters_per_group=value)
        self._emit_speech_settings("Broj slova u grupi je ažuriran.")

    def _set_voice_preset(self, value: str) -> None:
        if self._speech_settings.keyboard_script == ARABIC_SCRIPT:
            return
        if value == self._speech_settings.voice_preset:
            self._speech_page._voice_buttons[value].setChecked(True)
            return
        self.cancel_gaze_interaction(require_leave=True)
        self._speech_settings = replace(self._speech_settings, voice_preset=value)
        self._emit_speech_settings("Glas je ažuriran.")

    def _script_combo_changed(self, index: int) -> None:
        script = self._speech_page._script_combo.itemData(index)
        if script not in dict(KEYBOARD_SCRIPTS):
            script = LATIN_SCRIPT
        if script == self._speech_settings.keyboard_script:
            return
        self.cancel_gaze_interaction(require_leave=True)
        self._speech_settings = replace(self._speech_settings, keyboard_script=script)
        self._emit_speech_settings("Pismo tastature je ažurirano.")

    def _cycle_keyboard_script(self) -> None:
        self._speech_page._script_combo.setCurrentIndex(
            (self._speech_page._script_combo.currentIndex() + 1)
            % self._speech_page._script_combo.count()
        )

    def _emit_gaze_settings(self, status: str) -> None:
        self._eye_gate.configure(
            self._gaze_settings.eye_tracking_policy, self._gaze_settings.eye_tracking_hold_ms
        )
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
        self._gaze_page.refresh(self._gaze_settings)
        self._general_page.refresh(self._gaze_settings, self._startup_desired_enabled)
        self._speech_page.refresh(
            self._speech_settings, self._speech_playback_state, self._eleven_account
        )
        self._eleven_page.configure(self._speech_settings)

    def _set_status(self, text: str) -> None:
        logger.info("Settings status: %s", text)
        self._status_label.setText(text)

    def _install_shortcuts(self) -> None:
        self._escape_shortcut = QShortcut(QKeySequence("Esc"), self)
        self._escape_shortcut.activated.connect(self.close)

    def _sync_startup_setting_from_windows(self) -> None:
        self._queue_startup_task(None)

    def _queue_startup_task(
        self,
        enabled: bool | None,
        *,
        status: str | None = None,
        update_launcher: bool = False,
    ) -> None:
        if self._startup_closed:
            return
        self._startup_revision += 1
        request = StartupRequest(
            self._startup_revision,
            enabled,
            self._gaze_settings.show_launcher_window,
            status,
            update_launcher,
        )
        self._startup_busy = True
        self._startup_tasks.submit(request)

    @Slot(int, object, object)
    def _finish_startup_task(self, revision: int, result: object, status: str | None) -> None:
        if revision != self._startup_revision:
            return
        self._startup_busy = False
        if self._startup_closed:
            return
        if isinstance(result, bool):
            self._startup_desired_enabled = result
            self._gaze_settings = replace(self._gaze_settings, start_with_windows=result)
            self._refresh_values()
        elif isinstance(result, StartupTaskResult):
            self._startup_desired_enabled = result.enabled
            self._gaze_settings = replace(self._gaze_settings, start_with_windows=result.enabled)
            self._emit_gaze_settings(
                status if status is not None and result.success else result.message
            )
        else:
            self._startup_desired_enabled = self._gaze_settings.start_with_windows
            self._set_status("Ažuriranje pokretanja uz Windows nije uspjelo.")

    def _setup_gaze(self):
        self._gaze_target: QWidget | None = None
        self._gaze_selection = GazeSelectionTimer()
        self._last_gaze_action_ms = 0.0
        self._interaction_active = False
        self._eye_gate = EyeTrackingGate(self)
        self._eye_gate.configure(
            self._gaze_settings.eye_tracking_policy, self._gaze_settings.eye_tracking_hold_ms
        )
        self._eye_gate.interrupted.connect(self.pause_gaze_interaction)
        self._eye_gate.hold_started.connect(self._hold_tracking)
        self._eye_gate.hold_finished.connect(lambda: self._set_tracking_paused(False))
        self._tracking_hold_rect = None

    def handle_eye_status(self, left: bool, right: bool, at: float | None = None) -> None:
        self._eye_gate.update_eyes(left, right, at)

    def _hold_tracking(self, deadline_ms: float) -> None:
        self._gaze_selection.hold_tracking(deadline_ms)
        widget = self._gaze_selection.target
        if isinstance(widget, QWidget) and self._gaze_selection.tracking_held:
            self._tracking_hold_rect = global_rect(widget)
            self._set_tracking_paused(True)

    def _set_tracking_paused(self, paused: bool) -> None:
        if self._gaze_target is not None:
            set_gaze_paused(self._gaze_target, paused)
        self.interaction_hold_changed.emit(paused)

    def handle_gaze(self, point: QPoint, received_at: float | None = None) -> None:
        if not self._eye_gate.sample(received_at):
            return
        if self._learning_page.blocks_gaze_at(point):
            self.cancel_gaze_interaction(require_leave=True)
            return
        if not self.isVisible():
            self.cancel_gaze_interaction()
            return

        target = self._controls.action_at(point)
        now_ms = time.monotonic() * 1000
        if target is None:
            if self._gaze_still_on_blocked_target(point):
                # A disabled action under unchanged gaze is not a departure.
                self.pause_gaze_interaction()
            else:
                self.cancel_gaze_interaction()
            return

        widget, action = target
        if self._gaze_selection.tracking_held and (
            widget is not self._gaze_selection.target
            or global_rect(widget) != self._tracking_hold_rect
        ):
            self.pause_gaze_interaction()
        self._update_gaze(widget, action, now_ms)

    def _update_gaze(self, widget, action, now_ms):
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

    def _gaze_still_on_blocked_target(self, point) -> bool:
        blocked = self._gaze_selection.target
        return (
            self._gaze_selection.is_blocked
            and isinstance(blocked, QWidget)
            and blocked.isVisible()
            and global_rect(blocked).contains(point)
        )

    def cancel_gaze_interaction(self, *, require_leave: bool = False) -> None:
        self._gaze_selection.cancel(require_leave=require_leave)
        self._set_gaze_target(None)
        self._cancel_interaction()

    def pause_gaze_interaction(self) -> None:
        self._set_tracking_paused(False)
        self._gaze_selection.pause()
        self._set_gaze_target(None)
        self._cancel_interaction()

    def _dynamic_control_state(self):
        controls = (
            self._speech_page._test_speech_button,
            self._speech_page._stop_speech_button,
            self._eleven_page.test_button,
            self._eleven_page.stop_button,
            self._eleven_page.check_button,
        )
        return {
            button: (button.text(), button.isVisible(), button.isEnabled()) for button in controls
        }

    def _cancel_changed_target(self, before):
        target = self._gaze_selection.target
        after = self._dynamic_control_state()
        if target in before and before[target] != after[target]:
            self.cancel_gaze_interaction(require_leave=True)

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


def _checkbox_x_image_url() -> str:
    return (Path(__file__).resolve().parents[1] / "assets" / "checkbox_x.svg").as_posix()
