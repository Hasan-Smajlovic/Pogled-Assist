"""Caregiver-operated positioning, gaze validation and aggregate reports."""

from __future__ import annotations

import platform
import time
from collections.abc import Callable
from dataclasses import replace
from html import escape

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import diagnostics
from ..build_info import build_identity
from ..interaction.eye_tracking_policy import (
    EYE_TRACKING_POLICY_CHOICES,
    EyeTrackingGate,
    eyes_usable,
)
from ..interaction.gaze_selection import GazeSelectionTimer
from ..interaction.mouse_controller import (
    TOOLBAR_EDGE_MARGIN_PX,
    GazeSettings,
)
from ..logging_setup import get_project_root
from ..tracking.gaze_check import (
    FRESH_SECONDS,
    HISTORY_SECONDS,
    TARGET_SECONDS,
    CheckSnapshot,
    EyeTrackingResult,
    EyeTrackingRun,
    FixationCheck,
    FixationResult,
    TrialGazeCoverage,
)
from ..tracking.gaze_check_report import (
    ENVIRONMENT_KEYS,
    SETTING_KEYS,
    EyeTrackingSummary,
    GazeCheckReport,
    PrecisionRow,
    TrialAttempt,
    TrialRow,
    identity,
    timestamp,
)
from ..tracking.gaze_check_store import GazeCheckStore
from ..tracking.status import TrackingState, TrackingStatus
from .gaze_check_eyes import EyeTrackingPanel
from .gaze_check_feedback import result_advice
from .gaze_check_history import GazeCheckHistory
from .gaze_check_reports import GazeCheckReports
from .gaze_check_text import (
    eye_summary_text,
    free_gaze_is_visible,
    position_guidance,
    position_notice,
    precision_feedback,
    visible_eyes,
)
from .gaze_check_views import (
    COLORS,
    TARGET_RADIUS,
    TARGETS,
    TRIAL_KEYS,
    TRIAL_WORD,
    CheckTargetView,
    EyePositionView,
    PrecisionSummary,
    ResultMapView,
)
from .information_button import InformationButton
from .recording_badge import RecordingBadge
from .theme import apply_theme

# Word-test instructions in logical px; the panel grows so two lines stay unclipped.
TRIAL_HINT_PX = 24
TRIAL_CONTROLS_HEIGHT = 210

STYLESHEET = """
QWidget#gazeCheck { background: #15191f; color: #edf2f7; font-family: Segoe UI; }
QLabel { color: #edf2f7; background: transparent; font-size: 17px; }
QLabel#checkTitle { font-size: 29px; font-weight: 650; }
QLabel#cardTitle { font-size: 23px; font-weight: 600; }
QLabel#checkHint { font-size: 15px; color: #b8c5d2; }
QLabel#checkSimulation { font-size: 13px; color: #efd092; }
QFrame#checkHeader { border: 0; border-bottom: 1px solid #394959; }
QFrame#checkContext { border: 0; border-left: 1px solid #394959; }
QFrame#checkCard { background: #1d242d; border: 1px solid #394959; border-radius: 12px; }
QFrame#checkEyes { border: 0; border-top: 1px solid #394959; }
QPushButton { background: #283442; color: #edf2f7; border: 1px solid #71869b;
    border-radius: 9px; padding: 10px 16px; font-size: 18px; font-weight: 600; }
QPushButton:hover { background: #334355; border-color: #84c5d9; }
QPushButton:focus { border: 2px solid #84c5d9; }
QFrame#checkResources, QFrame#checkDeviceActions { border: 0; border-right: 1px solid #394959; }
QPushButton#checkPrimary { background: #2e6478; border-color: #84c5d9; }
QProgressBar { background: #394959; border: none; border-radius: 3px; }
QProgressBar::chunk { background: #84c5d9; border-radius: 3px; }
QScrollArea, QScrollArea QWidget { background: #1d242d; border: none; }
QComboBox { background: #334355; color: #edf2f7; padding: 8px; font-size: 17px; }
QComboBox QAbstractItemView { background: #334355; color: #edf2f7; }
"""


def _label(text: str, parent: QWidget, name: str = "") -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


class GazeCheckWindow(GazeCheckHistory, QWidget):
    closed = Signal()
    calibration_requested = Signal()
    diagnostics_requested = Signal()

    def __init__(
        self,
        settings: GazeSettings,
        parent: QWidget | None = None,
        *,
        simulated: bool = False,
        reports: GazeCheckReports | None = None,
        environment: Callable[[], dict] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Provjera pogleda")
        self.setObjectName("gazeCheck")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Window)
        apply_theme(self, STYLESHEET)
        self._settings = replace(settings)
        self._simulated = simulated
        self._reports = reports or GazeCheckReports(
            GazeCheckStore(get_project_root() / "logs" / "gaze-check"), self
        )
        self._auto_save = reports is not None and settings.logging_enabled
        self._environment_source = environment or (lambda: {})
        self._environment: dict = {}
        self._report: GazeCheckReport | None = None
        self._view_report: GazeCheckReport | None = None
        self._archived = False
        self._attempt_id: str | None = None
        self._attempt_started_at = ""
        self._attempt_started_mono = 0.0
        self._trial_rows: list[TrialRow] = []
        self._trial_baseline = (0, 0, 0)
        self._export_token: str | None = None
        self._displayed_report_id: str | None = None
        self._snapshot = CheckSnapshot()
        self._snapshot_at: float | None = None
        self._check: FixationCheck | None = None
        self._live_eyes = self._eye_run(window=HISTORY_SECONDS)
        # Per-test availability, saved with that test's result.
        self._stage_eyes: EyeTrackingRun | None = None
        self._phase = "position"
        self._selection = GazeSelectionTimer()
        self._trial_results: list[bool] = []
        self._trial_tracked_targets: set[int] = set()
        self._trial_coverage: TrialGazeCoverage | None = None
        self._trial_deadline = 0.0
        self._trial_ready_at = 0.0
        self._trial_sample_at: float | None = None
        self._trial_losses = 0
        self._trial_departures = 0
        self._trial_wrong_selections = 0
        self._trial_interruptions = 0
        self._trial_feedback_loss = False
        self._tracking_state: TrackingState | None = None
        self._build_ui()
        self._reports.changed.connect(self._reports_changed)
        self._reports.exported.connect(self._export_finished)
        self._eye_gate = EyeTrackingGate(self)
        self._eye_gate.configure(settings.eye_tracking_policy, settings.eye_tracking_hold_ms)
        self._eye_gate.interrupted.connect(self._tracking_interrupted)
        self._eye_gate.hold_started.connect(self._hold_tracking)
        self._eye_gate.pause_retained.connect(self._retain_tracking_pause)
        self._eye_gate.hold_finished.connect(self._resume_tracking)
        self._policy_sample_at: float | None = None
        self._escape = QShortcut(QKeySequence("Esc"), self)
        self._escape.activated.connect(self.close)
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._tick)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(12)
        layout.addWidget(self._build_header())
        self._step = _label("1 · Položaj i praćenje", self, "cardTitle")
        layout.addWidget(self._step)
        self._pages = QStackedWidget(self)
        layout.addWidget(self._pages, 1)
        self._build_position_page()
        self._build_test_page()
        self._build_result_page()
        self._build_history_page()
        layout.addLayout(self._build_footer())

    def _build_header(self) -> QFrame:
        frame = QFrame(self)
        frame.setObjectName("checkHeader")
        header = QVBoxLayout(frame)
        header.setContentsMargins(0, 0, 0, 12)
        header.setSpacing(12)
        title = QHBoxLayout()
        title.setSpacing(16)
        self._title_label = _label("Provjera pogleda", self, "checkTitle")
        self._title_label.setWordWrap(False)
        title.addWidget(self._title_label)
        context = QFrame(frame)
        context.setObjectName("checkContext")
        copy = QVBoxLayout(context)
        copy.setContentsMargins(16, 0, 0, 0)
        copy.setSpacing(2)
        self._policy_text = dict(EYE_TRACKING_POLICY_CHOICES)[self._settings.eye_tracking_policy]
        self._policy_label = _label(f"Režim: {self._policy_text}", self, "checkHint")
        copy.addWidget(self._policy_label)
        self._simulation_label = _label(
            "Simulacija mišem · Bez Tobii mjerenja", self, "checkSimulation"
        )
        self._simulation_label.setVisible(self._simulated)
        copy.addWidget(self._simulation_label)
        title.addWidget(context, 1)
        self._recording_badge = RecordingBadge(self)
        title.addWidget(self._recording_badge)
        header.addLayout(title)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(16)
        self._notice = _label(
            "Upravljanje pogledom pauzirano · Koristite miš ili tastaturu.", self, "checkHint"
        )
        toolbar.addWidget(self._notice, 1)
        resources = QFrame(self)
        resources.setObjectName("checkResources")
        grid = QHBoxLayout(resources)
        grid.setContentsMargins(0, 0, 24, 0)
        grid.setSpacing(12)
        self._history_button = self._button("Sačuvani rezultati", self._open_history)
        self._diagnostics_button = self._button("Dijagnostičko snimanje", self._request_diagnostics)
        for button in (self._history_button, self._diagnostics_button):
            button.setFixedHeight(60)
            button.setStyleSheet("font-size: 16px;")
            grid.addWidget(button)
        toolbar.addWidget(resources)
        self._close_button = self._button("Zatvori · Esc", self.close)
        self._close_button.setFixedHeight(60)
        self._close_button.setStyleSheet("font-size: 16px;")
        toolbar.addWidget(self._close_button)
        header.addLayout(toolbar)
        return frame

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.setSpacing(24)
        self._device_group = QFrame(self)
        self._device_group.setObjectName("checkDeviceActions")
        device = QVBoxLayout(self._device_group)
        device.setContentsMargins(0, 0, 24, 0)
        device.setSpacing(6)
        self._device_title = _label("Podešavanje uređaja", self, "checkHint")
        device.addWidget(self._device_title)
        self._calibration_button = self._button("Otvori Tobii postavke", self._calibrate)
        device.addWidget(self._calibration_button)
        footer.addWidget(self._device_group, 1)
        flow = QVBoxLayout()
        flow.setSpacing(6)
        self._flow_title = _label("Sljedeći korak", self, "checkHint")
        flow.addWidget(self._flow_title)
        actions = QHBoxLayout()
        actions.setSpacing(16)
        self._free_button = self._button("Slobodna provjera", self._start_free)
        self._primary_button = self._button("Pokreni provjeru", self._next)
        self._primary_button.setObjectName("checkPrimary")
        self._repeat_button = self._button("Ponovi provjeru", self._repeat)
        self._repeat_button.hide()
        for button in (self._free_button, self._primary_button, self._repeat_button):
            actions.addWidget(button, 1)
        flow.addLayout(actions)
        footer.addLayout(flow, 2)
        return footer

    def _button(self, text: str, callback) -> QPushButton:
        button = QPushButton(text, self)
        button.setMinimumHeight(60)
        button.clicked.connect(callback)
        return button

    def _card(self, parent: QWidget, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame(parent)
        card.setObjectName("checkCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        if title:
            layout.addWidget(_label(title, card, "cardTitle"))
        return card, layout

    def _build_position_page(self) -> None:
        page = QWidget(self)
        columns = QHBoxLayout(page)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(16)
        card, layout = self._card(page, "")
        heading = QHBoxLayout()
        heading.addWidget(_label("Položaj očiju uživo", card, "cardTitle"), 1)
        self._position_help = InformationButton(
            "O položaju i udaljenosti",
            "Prikaz pokazuje položaj očiju unutar područja koje Tobii može pratiti. "
            "Udaljenost nije mjerenje u centimetrima. Preciznost provjerite na metama.",
            card,
        )
        self._position_help.setFixedSize(44, 44)
        heading.addWidget(self._position_help)
        layout.addLayout(heading)
        layout.addWidget(_label("Polako pomjerajte ekran s pričvršćenim Tobijem.", card))
        self._eyes_view = EyePositionView(card)
        self._eyes_view.setToolTip(
            "Udaljenost unutar područja koje uređaj može pratiti; nije mjerenje u centimetrima."
        )
        layout.addWidget(self._eyes_view, 1)
        self._position_notice = _label("Čekam podatke o položaju očiju.", card, "checkHint")
        layout.addWidget(self._position_notice)
        self._position_label = _label("— Položaj nije dostupan", card)
        self._distance_label = _label("— Udaljenost nije dostupna", card)
        layout.addWidget(self._position_label)
        layout.addWidget(self._distance_label)
        columns.addWidget(card, 1)
        card, layout = self._card(page, "Šta uređaj trenutno vidi")
        self._left_label = _label("— Lijevo oko · čekam podatke", card)
        self._right_label = _label("— Desno oko · čekam podatke", card)
        self._gaze_label = _label("— Čekam pogled na ekranu", card)
        self._guidance = _label("Pogledajte prema ekranu.", card)
        for label in (
            self._left_label,
            self._right_label,
            self._gaze_label,
            self._guidance,
        ):
            layout.addWidget(label)
        self._eye_panel = EyeTrackingPanel(card)
        layout.addWidget(self._eye_panel)
        layout.addStretch(1)
        columns.addWidget(card, 1)
        self._pages.addWidget(page)

    def _build_test_page(self) -> None:
        page = QWidget(self)
        self._pages.addWidget(page)
        self._target = CheckTargetView(self)
        self._test_controls = QFrame(self._target)
        self._test_controls.setObjectName("checkCard")
        layout = QVBoxLayout(self._test_controls)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)
        metadata = QHBoxLayout()
        metadata.addWidget(
            _label(f"Režim: {self._policy_text}", self._test_controls, "checkHint"), 1
        )
        self._test_recording_badge = RecordingBadge(self._test_controls)
        self._test_recording_badge.setFixedHeight(26)
        metadata.addWidget(self._test_recording_badge)
        layout.addLayout(metadata)
        self._test_hint = _label("", self._test_controls)
        self._test_hint.setTextFormat(Qt.RichText)
        layout.addWidget(self._test_hint, 1)
        self._test_progress = QProgressBar(self._test_controls)
        self._test_progress.setRange(0, 1000)
        self._test_progress.setTextVisible(False)
        self._test_progress.setFixedHeight(6)
        self._test_progress.setAccessibleName("Napredak provjere preciznosti")
        layout.addWidget(self._test_progress)
        buttons = QHBoxLayout()
        buttons.setSpacing(16)
        self._test_back_button = self._button("Prekini i prikaži rezultat", self._stop_test)
        self._test_close_button = self._button("Zatvori · Esc", self.close)
        buttons.addWidget(self._test_back_button)
        buttons.addWidget(self._test_close_button)
        layout.addLayout(buttons)

    def _build_result_page(self) -> None:
        card, layout = self._card(self, "")
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        precision = QWidget(card)
        precision_layout = QVBoxLayout(precision)
        precision_layout.setContentsMargins(0, 0, 0, 0)
        self._result_summary = _label("", precision, "cardTitle")
        self._result_detail = _label("", precision)
        self._result_detail.setStyleSheet("font-size: 16px;")
        self._result_detail.setTextFormat(Qt.RichText)
        columns = QHBoxLayout()
        columns.setSpacing(24)
        map_column = QVBoxLayout()
        self._result_map = ResultMapView(card)
        self._result_map.setMinimumHeight(110)
        self._result_map.setMaximumHeight(130)
        map_column.addWidget(self._result_map, 1)
        map_column.addWidget(
            _label(
                "Krug = meta · tačka = pogled\nLinija pokazuje koliko je pogled promašio.",
                card,
                "checkHint",
            )
        )
        columns.addLayout(map_column, 1)
        details = QVBoxLayout()
        details.setSpacing(6)
        details.addWidget(self._result_detail)
        details.addStretch(1)
        columns.addLayout(details, 3)
        self._result_advice = _label("", card)
        self._trial_summary = _label("", card)
        self._trial_summary.hide()
        self._eye_summary_label = _label("", card)
        self._eye_summary_label.setStyleSheet("font-size: 16px;")
        summary = QHBoxLayout()
        summary.setSpacing(20)
        summary.addWidget(self._result_summary, 1)
        self._precision_counts = PrecisionSummary(precision)
        summary.addWidget(self._precision_counts, 2)
        precision_layout.addLayout(summary)
        precision_layout.addLayout(columns, 1)
        precision_layout.addWidget(self._result_advice)
        precision_layout.addWidget(self._trial_summary)
        precision_layout.addWidget(self._eye_summary_label)
        self._details_button = self._button("Prikaži mjerenja", self._render_result_details)
        self._details_button.setCheckable(True)
        self._details_button.setMinimumHeight(44)
        self._details_button.setStyleSheet("font-size: 16px; padding: 6px 12px;")
        map_column.addWidget(self._details_button)
        self._metrics_hint = _label(
            "Podaci: dio vremena s važećim pogledom. Odstupanje: udaljenost od mete. "
            "Rasipanje: koliko se pogled pomjerao. Vrijednosti su u pikselima prikaza (px).",
            card,
            "checkHint",
        )
        self._metrics_hint.setToolTip(
            "Qt logički pikseli. Odstupanje: medijan od mete. Rasipanje: 90. percentil "
            "od sredine pogleda. Pragovi aplikacije: 90% uzoraka u krugu od 36 px, "
            "najmanje 60% podataka. Promjena položaja može promijeniti rezultat."
        )
        self._metrics_hint.hide()
        details.insertWidget(1, self._metrics_hint)
        self._build_report_controls(card, layout, precision)
        self._pages.addWidget(card)

    def show_fullscreen_on_primary(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())
        self.show()
        self.raise_()
        self.activateWindow()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Time spent in another window was not measured; start the live view again.
        self._live_eyes = self._eye_run(window=HISTORY_SECONDS)
        self._timer.start()
        diagnostics.emit("gaze_check_open", priority=True, phase=self._phase)

    def closeEvent(self, event) -> None:
        self._finalize_attempt("Zatvorena provjera")
        diagnostics.emit("gaze_check_close", priority=True, phase=self._phase)
        self._timer.stop()
        self._selection.cancel()
        self._check = None
        self._stage_eyes = None
        self._snapshot = CheckSnapshot()
        self.closed.emit()
        super().closeEvent(event)

    def _request_diagnostics(self) -> None:
        if self._phase in ("precision", "trial"):
            return
        self._timer.stop()
        self._selection.cancel()
        self._target.gaze_point = None
        self._snapshot = CheckSnapshot()
        self.diagnostics_requested.emit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._phase in ("precision", "trial", "free"):
            self._finalize_attempt("Promijenjena veličina prozora")
            self.reset_check()
            self._notice.setText("Veličina ekrana se promijenila. Pokrenite novu provjeru.")

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() != QEvent.WindowStateChange:
            return
        if self.isMinimized() and self._phase in ("precision", "trial", "free"):
            self._finalize_attempt("Prozor je minimiziran")
            self.reset_check()

    def handle_snapshot(self, snapshot: CheckSnapshot) -> None:
        snapshot = self._apply_snapshot_policy(snapshot)
        self._snapshot = snapshot
        now = time.monotonic()
        self._snapshot_at = now
        if not self.isVisible() or self.isMinimized():
            return
        self._live_eyes.add(snapshot)
        if self._stage_eyes is not None:
            self._stage_eyes.add(snapshot)
        if self._phase == "precision" and self._check is not None:
            self._check.add(snapshot, now)
        if self._phase == "trial":
            self._trial_sample(snapshot, now)
        elif self._phase == "free":
            self._render_free()

    def _apply_snapshot_policy(self, snapshot: CheckSnapshot) -> CheckSnapshot:
        known_eyes = snapshot.left is not None and snapshot.right is not None
        if known_eyes and self._eye_gate.eyes != (snapshot.left, snapshot.right):
            self.handle_eye_status(snapshot.left, snapshot.right)
        if snapshot.gaze is None or snapshot.gaze_at == self._policy_sample_at:
            return snapshot
        if self._eye_gate.sample(snapshot.gaze_at):
            self._policy_sample_at = snapshot.gaze_at
            return snapshot
        return replace(snapshot, gaze=None, gaze_at=None)

    def handle_eye_status(self, left: bool, right: bool, received_at: float | None = None) -> None:
        self._eye_gate.update_eyes(left, right, received_at)
        if not eyes_usable(self._settings.eye_tracking_policy, left, right):
            self._snapshot = replace(
                self._snapshot, left=left, right=right, gaze=None, gaze_at=None
            )
            if not self._eye_gate.holding:
                self._cancel_trial_progress(loss=True)
            if self._phase == "precision" and self._check is not None:
                self._check.interrupt()
            elif self._phase == "free":
                self._render_free()

    def _tracking_interrupted(self) -> None:
        self._policy_sample_at = None
        self._cancel_trial_progress(loss=True)
        if self._check is not None:
            self._check.interrupt()

    def _hold_tracking(self, deadline_ms: float, retention_deadline_ms: float) -> None:
        self._selection.hold_tracking(deadline_ms, retention_deadline_ms)
        if self._trial_coverage is not None:
            self._trial_coverage.interrupt()
        if self._selection.tracking_held:
            self._target.paused = True
            self._target.update()
            self._set_trial_hint("Na čekanju · čuvam napredak do povratka oba oka.")

    def _retain_tracking_pause(self) -> None:
        # Count a discarded attempt before the timer clears its target.
        if not self._selection.pause_completed:
            self._cancel_trial_progress(loss=True)
            return
        if not self._selection.retain_completed_pause():
            return
        self._target.progress = 0.0
        self._target.update()
        self._set_trial_hint("Na čekanju · početna pauza završena, punjenje kreće od nule.")

    def _resume_tracking(self) -> None:
        self._target.paused = False
        self._target.update()

    def tracking_unavailable(self) -> None:
        self._eye_gate.cancel()
        self._snapshot = CheckSnapshot()
        self._snapshot_at = None
        self._cancel_trial_progress(loss=True)
        if self._phase in ("precision", "trial", "free"):
            self._finalize_attempt("Veza s uređajem je prekinuta")
            self.reset_check()
            self._notice.setText(
                "Praćenje je prekinuto. Nakon povezivanja pokrenite novu provjeru."
            )
        self._render_position()

    def handle_tracking_status(self, status: TrackingStatus) -> None:
        self._tracking_state = status.state
        if status.state not in (TrackingState.CONNECTED, TrackingState.SIMULATING):
            self.tracking_unavailable()
        else:
            self._render_position()

    def _tick(self) -> None:
        now = time.monotonic()
        self._expire_snapshot(now)
        if self._phase == "position":
            self._render_position()
        elif self._phase == "precision" and self._check is not None:
            self._tick_precision(now)
        elif self._phase == "trial" and now >= self._trial_deadline:
            self._finish_trial_target(False, now)
        elif self._phase == "free":
            self._render_free()
        self._render_eyes(now)

    def _eye_run(self, *, window: float | None = None) -> EyeTrackingRun:
        screen = QGuiApplication.primaryScreen().geometry()
        return EyeTrackingRun(
            (screen.width(), screen.height()),
            TARGET_RADIUS,
            time.monotonic(),
            policy=self._settings.eye_tracking_policy,
            window=window,
        )

    def _render_eyes(self, now: float) -> None:
        result = self._live_eyes.result(now)
        self._eye_panel.show_result(result)

    def _expire_snapshot(self, now: float) -> None:
        if self._snapshot_at is None or now - self._snapshot_at >= FRESH_SECONDS:
            self._snapshot = CheckSnapshot(
                position_supported=self._snapshot.position_supported,
                gaze_interruptions=self._snapshot.gaze_interruptions,
            )
        gaze_stale = self._snapshot.gaze_at is None
        if not gaze_stale:
            gaze_stale = now - self._snapshot.gaze_at >= FRESH_SECONDS
        if not self._eye_gate.holding and gaze_stale:
            self._cancel_trial_progress(loss=True)
            if self._phase == "precision" and self._check is not None:
                self._check.interrupt()

    def _tick_precision(self, now: float) -> None:
        if self._check.advance(now):
            if self._check.finished:
                self._precision_finished()
                return
            self._target.target_index = self._check.index
            self._target.update()
        remaining = max(1, round(TARGET_SECONDS - (now - self._check.started_at)))
        feedback, state = precision_feedback(
            self._snapshot, remaining, now, self._settings.eye_tracking_policy
        )
        self._set_test_hint(
            f"Meta {self._check.index + 1} od 5 · Gledajte križić u krugu.", feedback, state
        )
        elapsed = self._check.index * TARGET_SECONDS + now - self._check.started_at
        self._test_progress.setValue(round(1000 * elapsed / (5 * TARGET_SECONDS)))

    @staticmethod
    def _state(label: QLabel, state: bool | None, text: str) -> None:
        mark = {True: "✓", False: "!", None: "—"}[state]
        label.setText(f"{mark} {text}")
        label.setStyleSheet(f"color: {COLORS[state]}; font-size: 19px;")

    def _render_position(self) -> None:
        snapshot = self._snapshot
        self._position_notice.setText(position_notice(snapshot, self._tracking_state))
        left_visible, right_visible = visible_eyes(snapshot)
        for name, label, state in (
            ("Lijevo oko", self._left_label, left_visible),
            ("Desno oko", self._right_label, right_visible),
        ):
            detail = {True: "prepoznato", False: "trenutno se ne prati", None: "čekam podatke"}[
                state
            ]
            self._state(label, state, f"{name} · {detail}")
        position, depth = snapshot.in_box((0, 1)), snapshot.in_box((2,))
        self._state(
            self._position_label,
            position,
            {
                True: "Položaj u području praćenja",
                False: "Položaj izvan područja praćenja",
                None: "Položaj nije dostupan",
            }[position],
        )
        self._state(
            self._distance_label,
            depth,
            {
                True: "Udaljenost u području praćenja",
                False: "Udaljenost izvan područja praćenja",
                None: "Udaljenost nije dostupna",
            }[depth],
        )
        self._state(
            self._gaze_label,
            True if snapshot.gaze is not None else None,
            "Pogled se prati" if snapshot.gaze is not None else "Čekam pogled na ekranu",
        )
        self._eyes_view.snapshot = snapshot
        self._eyes_view.update()
        self._guidance.setText(position_guidance(snapshot, self._settings.eye_tracking_policy))

    def _next(self) -> None:
        if self._phase == "position":
            self._start_precision()
        elif self._phase == "results":
            self._start_trial()
        elif self._phase == "history":
            self._open_selected_report()

    def _repeat(self) -> None:
        if self._phase == "history":
            if self._report is not None:
                self._view_report = self._report
                self._archived = False
                self._render_report()
            else:
                self.reset_check()
        elif self._archived:
            self._open_history()
        elif self._phase in ("precision", "trial"):
            self._stop_test()
        else:
            self._start_precision()

    def _stop_test(self) -> None:
        self._finalize_attempt("Korisnik je prekinuo test")
        if self._report is not None and self._phase in ("precision", "trial"):
            self._view_report = self._report
            self._render_report()
        else:
            self.reset_check()

    def reset_check(self) -> None:
        self._finalize_attempt("Ponovljena provjera ili podešavanje položaja")
        diagnostics.emit("gaze_check_phase", priority=True, phase="position", previous=self._phase)
        self._phase = "position"
        self._archived = False
        self._diagnostics_button.setEnabled(True)
        self._title_label.setText("Provjera pogleda")
        self._simulation_label.setVisible(self._simulated)
        self._history_button.show()
        self._step.show()
        self._policy_label.setText(f"Režim: {self._policy_text}")
        self._check = None
        self._stage_eyes = None
        self._selection.cancel()
        self._trial_results.clear()
        self._trial_tracked_targets.clear()
        self._trial_coverage = None
        self._target.hide()
        self._target.gaze_point = None
        self._trial_summary.hide()
        self._details_button.setChecked(False)
        self._pages.setCurrentIndex(0)
        self._step.setText("1 · Položaj i praćenje")
        self._primary_button.setText("Pokreni provjeru")
        self._primary_button.show()
        self._primary_button.setEnabled(True)
        self._repeat_button.hide()
        self._device_group.show()
        self._device_title.show()
        self._flow_title.show()
        self._calibration_button.show()
        self._calibration_button.setText("Otvori Tobii postavke")
        self._free_button.show()
        self._notice.setText("Upravljanje pogledom pauzirano · Koristite miš ili tastaturu.")
        self._render_position()

    def _set_test_mode(self, phase: str) -> None:
        self._finalize_attempt("Pokrenuta druga provjera")
        self._archived = False
        self._policy_label.setText(f"Režim: {self._policy_text}")
        diagnostics.emit("gaze_check_phase", priority=True, phase=phase, previous=self._phase)
        self._pages.setCurrentIndex(1)
        self._phase = phase
        self._diagnostics_button.setEnabled(phase not in ("precision", "trial"))
        self._target.trial = phase == "trial"
        self._target.free = phase == "free"
        self._target.target_index = 0
        self._target.gaze_point = None
        self._target.progress = 0.0
        self._target.progress_target = None
        self._test_hint.setToolTip("")
        self._test_progress.setVisible(phase == "precision")

    def _start_precision(self) -> None:
        self._set_test_mode("precision")
        self._report = None
        self._view_report = None
        self._trial_results.clear()
        self._trial_tracked_targets.clear()
        self._trial_losses = self._trial_wrong_selections = self._trial_departures = 0
        self._begin_attempt()
        self._stage_eyes = self._eye_run()
        self._step.setText("2 · Tačke · pet kratkih meta")
        self._set_test_hint(
            "Meta 1 od 5 · Gledajte križić u krugu.",
            "Meta se mijenja sama; ne trebate kliknuti.",
        )
        self._test_progress.setValue(0)
        self._check = None
        self._primary_button.hide()
        self._device_group.hide()
        self._flow_title.hide()
        self._calibration_button.hide()
        self._repeat_button.setText("Prekini test")
        self._repeat_button.show()
        self._target.update()
        self._show_test_stage()
        # Freeze target locations only after Qt has settled the screen geometry.
        QTimer.singleShot(0, self._begin_precision_measurement)

    def _begin_attempt(self) -> None:
        self._attempt_id = identity()
        self._attempt_started_at = timestamp()
        self._attempt_started_mono = time.monotonic()
        self._export_status.hide()
        self._export_token = None
        self._result_tabs.setCurrentIndex(0)
        self._environment = {
            key: value
            for key, value in self._environment_source().items()
            if key in ENVIRONMENT_KEYS
        }
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geometry = screen.geometry()
            self._environment.update(
                logical_screen=[geometry.x(), geometry.y(), geometry.width(), geometry.height()],
                device_pixel_ratio=screen.devicePixelRatio()
                if hasattr(screen, "devicePixelRatio")
                else None,
                logical_dpi=screen.logicalDotsPerInch()
                if hasattr(screen, "logicalDotsPerInch")
                else None,
            )
        self._environment["platform"] = platform.system()
        self._environment.update(build_identity())

    def _finalize_attempt(self, reason: str | None) -> None:
        if self._attempt_id is None or self._phase not in ("precision", "trial"):
            return
        attempt_id, self._attempt_id = self._attempt_id, None
        now = time.monotonic()
        attempt = {
            "id": attempt_id,
            "started_at": self._attempt_started_at,
            "ended_at": timestamp(),
            "duration_seconds": max(0, now - self._attempt_started_mono),
            "state": "interrupted" if reason else "completed",
            "reason": reason,
        }
        if self._phase == "precision":
            self._finalize_precision(attempt)
        else:
            self._finalize_trial(attempt, now)
        self._view_report = self._report
        self._reports.record(self._report, auto_save=self._auto_save)
        diagnostics.emit(
            "gaze_check_result",
            priority=True,
            report_id=self._report.id,
            attempt_id=attempt_id,
            phase=self._phase,
            state=attempt["state"],
        )

    def _report_settings(self) -> dict:
        return {key: getattr(self._settings, key, None) for key in SETTING_KEYS}

    def _finalize_precision(self, attempt: dict) -> None:
        targets = self._check.targets if self._check is not None else TARGETS
        results = self._check.results if self._check is not None else []
        rows = [PrecisionRow(name, (x, y)) for name, x, y in targets]
        for index, result in enumerate(results):
            rows[index] = PrecisionRow(
                result.name,
                rows[index].target_normalized,
                "insufficient" if result.near is None else "measured",
                result.samples,
                result.coverage,
                result.median_error,
                result.spread,
                result.near,
                result.gaze_center,
            )
        self._report = GazeCheckReport(
            **attempt,
            simulated=self._simulated,
            settings=self._report_settings(),
            environment=self._environment.copy(),
            precision=rows,
            precision_eyes=self._finish_stage_eyes("precision"),
        )
        self._observe_fixations(results)

    def _finish_stage_eyes(self, stage: str) -> EyeTrackingSummary | None:
        run, self._stage_eyes = self._stage_eyes, None
        if run is None:
            return None
        result = run.result(time.monotonic())
        diagnostics.emit(
            "gaze_check_eye_tracking",
            priority=True,
            stage=stage,
            observed_seconds=round(result.observed_seconds, 3),
            left_fraction=round(result.left, 4),
            right_fraction=round(result.right, 4),
            both_fraction=round(result.both, 4),
            interruptions=result.interruptions,
            longest_interruption_seconds=round(result.longest_interruption, 3),
            agreement_supported=result.agreement_supported,
            agreement_samples=result.agreement_samples,
            median_separation_px=result.median_separation,
            agreement_fraction=result.agreement_fraction,
            agreement_threshold_px=result.threshold,
            eye_tracking_policy=self._settings.eye_tracking_policy,
        )
        return self._eye_summary(result)

    @staticmethod
    def _eye_summary(result: EyeTrackingResult) -> EyeTrackingSummary:
        return EyeTrackingSummary(
            result.observed_seconds,
            result.left,
            result.right,
            result.both,
            result.interruptions,
            result.longest_interruption,
            result.agreement_supported,
            result.agreement_samples,
            result.agreement_fraction,
            result.median_separation,
        )

    def _finalize_trial(self, attempt: dict, now: float) -> None:
        if self._report is None:
            self._report = GazeCheckReport(
                identity(),
                self._attempt_started_at,
                attempt["ended_at"],
                0,
                "interrupted",
                "Preciznost nije pokrenuta",
                self._simulated,
                self._report_settings(),
                self._environment.copy(),
                [PrecisionRow(name, (x, y)) for name, x, y in TARGETS],
            )
        rows = list(self._trial_rows)
        for index in range(len(rows), len(TRIAL_WORD)):
            rows.append(TrialRow(index, self._target.key_size()))
        if attempt["reason"] and len(self._trial_rows) < len(TRIAL_WORD):
            self._fill_interrupted_trial(rows[len(self._trial_rows)], now)
        self._report.trials.append(
            TrialAttempt(
                **attempt,
                rows=rows,
                environment=self._environment.copy(),
                word=TRIAL_WORD,
                eyes=self._finish_stage_eyes("word"),
            )
        )

    def _fill_interrupted_trial(self, row: TrialRow, now: float) -> None:
        row.coverage = (
            self._trial_coverage.fraction(min(now, self._trial_deadline))
            if self._trial_coverage
            else 0
        )
        row.duration_seconds = max(0, min(now, self._trial_deadline) - self._trial_ready_at)
        row.wrong_selections = self._trial_wrong_selections - self._trial_baseline[0]
        row.cancelled_selections = self._trial_losses - self._trial_baseline[1]
        row.departures = self._trial_departures - self._trial_baseline[2]

    def _begin_precision_measurement(self) -> None:
        if self._phase != "precision" or not self.isVisible():
            return
        self.layout().activate()
        self._pages.layout().activate()
        screen = QGuiApplication.primaryScreen().geometry()
        origin = self._target.mapToGlobal(QPoint(0, 0))
        targets = [
            (
                name,
                (origin.x() - screen.left() + x * (self._target.width() - 1))
                / max(1, screen.width() - 1),
                (origin.y() - screen.top() + y * (self._target.height() - 1))
                / max(1, screen.height() - 1),
            )
            for name, x, y in TARGETS
        ]
        self._check = FixationCheck(
            targets,
            (screen.width(), screen.height()),
            self._target.radius,
            time.monotonic(),
            policy=self._settings.eye_tracking_policy,
        )

    def _show_test_stage(self) -> None:
        self._target.setGeometry(self.rect())
        self._target.show()
        self._target.raise_()
        # The word test's instructions are larger so they stay readable on a laptop screen.
        word = self._phase == "trial"
        width = min(960 if word else 760, self.width() - 32)
        height = TRIAL_CONTROLS_HEIGHT if word else 168
        top = (
            round(self.height() * 0.72) - 70
            if self._phase == "free"
            else self.height() - height - 10
        )
        self._test_controls.setGeometry((self.width() - width) // 2, top, width, height)
        self._test_hint.setStyleSheet(f"font-size: {TRIAL_HINT_PX}px;" if word else "")
        self._test_controls.show()
        self._test_controls.raise_()
        self._test_back_button.setText(
            "Prekini i prikaži rezultat" if self._phase != "free" else "Vrati na položaj"
        )

    def _start_free(self) -> None:
        self._set_test_mode("free")
        self._check = None
        self._stage_eyes = None
        self._selection.cancel()
        self._show_test_stage()
        self._render_free()

    def _render_free(self) -> None:
        snapshot = self._snapshot
        now = time.monotonic()
        point = None
        if free_gaze_is_visible(snapshot, now, self._settings.eye_tracking_policy):
            x, y = snapshot.gaze
            screen = QGuiApplication.primaryScreen().geometry()
            point = self._target.mapFromGlobal(
                QPoint(
                    round(screen.left() + x * (screen.width() - 1)),
                    round(screen.top() + y * (screen.height() - 1)),
                )
            )
        self._target.gaze_point = point
        self._set_test_hint(
            "Gledajte križiće redom. Zelena oznaka pokazuje vaš pogled.",
            "Bez odbrojavanja; sami pogledajte je li oznaka blizu križića."
            if point is not None
            else "Čekam svjež validan pogled. Ako oznake nema, vratite se na položaj.",
        )
        self._target.update()

    def _set_test_hint(self, instruction: str, feedback: str, state: bool | None = None) -> None:
        prefix = "SIMULACIJA MIŠEM · " if self._simulated else ""
        text = (
            f"{escape(prefix + instruction)}<br>"
            f'<span style="color: {COLORS[state]}">{escape(feedback)}</span>'
        )
        if self._test_hint.text() != text:
            self._test_hint.setText(text)

    def _precision_finished(self) -> None:
        # The word test follows the targets in the same check.
        self._finalize_attempt(None)
        self._start_trial()

    def _show_results(self) -> None:
        reason = None
        precision_incomplete = self._check is None or len(self._check.results) < 5
        if self._phase == "precision" and precision_incomplete:
            reason = "Provjera preciznosti nije završena"
        self._finalize_attempt(reason)
        self._view_report = self._report
        self._archived = False
        self._render_report()

    def _fixations(self, *, include_unmeasured: bool = False) -> list[FixationResult]:
        if self._view_report is None:
            return self._check.results if self._check else []
        return [
            FixationResult(
                row.name,
                row.samples or 0,
                row.coverage or 0,
                row.median_error_logical_px,
                row.spread_logical_px,
                row.near,
                row.gaze_center_normalized,
            )
            for row in self._view_report.precision
            if include_unmeasured or row.state != "unmeasured"
        ]

    def _render_report(self) -> None:
        report_id = self._view_report.id if self._view_report is not None else None
        if report_id != self._displayed_report_id:
            self._export_status.hide()
            self._export_token = None
            self._displayed_report_id = report_id
        self._target.hide()
        self._phase = "results"
        self._diagnostics_button.setEnabled(True)
        self._pages.setCurrentIndex(2)
        self._step.setText("Rezultat provjere")
        results = self._fixations()
        diagnostics.emit("gaze_check_phase", priority=True, phase="results")
        selected, tracked, losses, wrong, policy = self._report_trial_data()
        expected = self._report_trial_length()
        trial_finished = len(selected) == expected
        self._render_precision_summary(results)
        self._render_result_details()
        self._result_map.results = self._fixations(include_unmeasured=True)
        self._result_map.targets = (
            [(row.name, *row.target_normalized) for row in self._view_report.precision]
            if self._view_report is not None
            else self._check.targets
            if self._check
            else []
        )
        self._result_map.update()
        self._result_advice.setText(
            result_advice(
                results,
                trial_results=selected,
                tracked_targets=tracked,
                losses=losses,
                wrong_selections=wrong,
                policy=policy,
                expected=expected,
            )
        )
        if self._view_report is not None and self._view_report.state == "interrupted":
            self._result_advice.setText(
                "Provjera je prekinuta. Završene mete su sačuvane; "
                "izaberite „Ponovi provjeru“ za cijeli test."
            )
        self._render_trial_summary(selected, losses, wrong, expected)
        self._render_eye_summary()
        self._render_result_actions(trial_finished)
        self._render_report_identity()

    def _report_trial_data(self):
        selected = self._trial_results
        tracked = self._trial_tracked_targets
        losses, wrong = self._trial_losses, self._trial_wrong_selections
        policy = self._settings.eye_tracking_policy
        if self._view_report is not None:
            trial = self._view_report.trials[-1] if self._view_report.trials else None
            selected = (
                [row.selected is True for row in trial.rows if row.state != "unmeasured"]
                if trial
                else []
            )
            tracked = (
                {row.index for row in trial.rows if row.state == "measured"} if trial else set()
            )
            losses = sum(row.cancelled_selections for row in trial.rows) if trial else 0
            wrong = sum(row.wrong_selections for row in trial.rows) if trial else 0
            policy = self._view_report.settings.get("eye_tracking_policy", policy)
        return selected, tracked, losses, wrong, policy

    def _render_precision_summary(self, results) -> None:
        near = sum(result.near is True for result in results)
        missing = sum(result.near is None for result in results)
        state = None if missing or not results else near == len(results)
        summary = (
            f"Za {missing} od {len(results)} meta nema dovoljno podataka."
            if missing
            else f"Pogled je bio blizu {near} od {len(results)} meta."
        )
        if not results:
            summary = "Preciznost još nije provjerena."
        if self._view_report is not None and self._view_report.state == "interrupted":
            state = None
            summary = (
                f"Prekinuto · završeno {len(results)} od {len(self._view_report.precision)} meta."
            )
        mark = {True: "✓", False: "!", None: "—"}[state]
        total = len(self._view_report.precision) if self._view_report else len(TARGETS)
        self._precision_counts.set_results(results, total)
        self._result_summary.setText(f"{mark} {summary}")
        self._result_summary.setStyleSheet(f"color: {COLORS[state]}; font-size: 19px;")

    def _report_trial_length(self) -> int:
        report = self._view_report
        if report is not None and report.trials:
            return len(report.trials[-1].rows)
        return len(TRIAL_WORD)

    def _render_trial_summary(self, selected, losses, wrong, expected) -> None:
        trial_finished = len(selected) == expected
        self._trial_summary.setVisible(trial_finished)
        if trial_finished:
            trial_ok = all(selected) and not wrong
            word = self._view_report.trials[-1].word if self._view_report else TRIAL_WORD
            name = "Probni izbor" if word is None else f"Riječ „{word}“"
            self._state(
                self._trial_summary,
                trial_ok,
                f"{name}: {sum(selected)}/{expected} · "
                f"pogrešni izbori: {wrong} · poništeni izbori: {losses}",
            )

    def _render_eye_summary(self) -> None:
        report = self._view_report
        trial = report.trials[-1] if report is not None and report.trials else None
        lines = [eye_summary_text("Tačke", report.precision_eyes if report else None)]
        if trial is not None:
            lines.append(eye_summary_text("Riječ", trial.eyes))
        self._eye_summary_label.setText("\n".join(lines))

    def _render_result_actions(self, trial_finished: bool) -> None:
        self._primary_button.setText(
            "Ponovi test riječi" if trial_finished else "Pokreni test riječi"
        )
        self._primary_button.show()
        self._primary_button.setEnabled(True)
        if self._view_report is not None:
            self._primary_button.setEnabled(self._view_report.state == "completed")
        self._primary_button.setVisible(not self._archived)
        self._device_group.setVisible(not self._archived)
        self._device_title.hide()
        self._flow_title.hide()
        self._calibration_button.setVisible(not self._archived)
        self._calibration_button.setText("Podesi položaj")
        self._free_button.hide()
        self._repeat_button.setText("Nazad na listu" if self._archived else "Ponovi provjeru")
        self._repeat_button.show()

    def _render_report_identity(self) -> None:
        if self._view_report is not None:
            self._step.hide()
            self._title_label.setText(
                "Raniji rezultat provjere" if self._archived else "Provjera pogleda"
            )
            self._simulation_label.setVisible(self._view_report.simulated)
            self._history_button.setVisible(not self._archived)
            self._render_report_context()
            policy = dict(EYE_TRACKING_POLICY_CHOICES).get(
                self._view_report.settings.get("eye_tracking_policy"), "—"
            )
            self._policy_label.setText(f"Režim rezultata: {policy}")

    @staticmethod
    def _observe_fixations(results) -> None:
        if diagnostics.tracing():
            for index, result in enumerate(results):
                diagnostics.emit(
                    "fixation_result",
                    trace=True,
                    priority=True,
                    target_index=index,
                    samples=result.samples,
                    coverage=result.coverage,
                    median_error_logical_px=result.median_error,
                    spread_logical_px=result.spread,
                    near=result.near,
                    gaze_center_normalized=result.gaze_center,
                )

    def _render_result_details(self) -> None:
        detailed = self._details_button.isChecked()
        self._details_button.setText("Sakrij mjerenja" if detailed else "Prikaži mjerenja")
        self._metrics_hint.setVisible(detailed)
        rows = [self._result_row(result, detailed) for result in self._fixations()]
        if self._view_report is not None:
            rows.extend(
                f'<tr><td>{escape(result.name)}</td><td colspan="4">Nije izmjereno</td></tr>'
                for result in self._view_report.precision
                if result.state == "unmeasured"
            )
        headings = (
            ("Meta", "Uzorci", "Podaci", "Odstupanje", "Rasipanje")
            if detailed
            else ("Meta", "Rezultat")
        )
        table = '<table width="100%" cellspacing="8"><tr>'
        table += "".join(f'<th align="left">{heading}</th>' for heading in headings)
        table += "</tr>" + "".join(rows) + "</table>"
        self._result_detail.setText(table)

    @staticmethod
    def _result_row(result: FixationResult, detailed: bool) -> str:
        mark = {True: "✓", False: "!", None: "—"}[result.near]
        status = {
            True: "Pogled blizu mete",
            False: "Pogled izvan mete",
            None: "Premalo podataka",
        }[result.near]
        color = COLORS[result.near]
        if detailed:
            error = f"{result.median_error:.0f} px" if result.median_error is not None else "—"
            spread = f"{result.spread:.0f} px" if result.spread is not None else "—"
            row = (
                f'<td style="color: {color}">{mark} {escape(result.name)}</td>'
                f"<td>{result.samples}</td><td>{result.coverage:.0%}</td>"
                f"<td>{error}</td><td>{spread}</td>"
            )
        else:
            row = f'<td>{escape(result.name)}</td><td style="color: {color}">{mark} {status}</td>'
        return f"<tr>{row}</tr>"

    def _start_trial(self) -> None:
        self._set_test_mode("trial")
        self._begin_attempt()
        self._stage_eyes = self._eye_run()
        self._trial_rows = []
        self._trial_baseline = (0, 0, 0)
        self._step.setText(f"3 · Riječ · napišite „{TRIAL_WORD}“ pogledom")
        self._trial_results.clear()
        self._trial_tracked_targets.clear()
        self._trial_losses = self._trial_departures = 0
        self._trial_wrong_selections = 0
        self._trial_interruptions = self._snapshot.gaze_interruptions
        self._trial_sample_at = None
        self._trial_feedback_loss = False
        self._selection.cancel()
        self._trial_ready_at = time.monotonic()
        self._set_trial_deadline(self._trial_ready_at)
        self._primary_button.hide()
        self._device_group.hide()
        self._flow_title.hide()
        self._calibration_button.hide()
        self._repeat_button.setText("Prekini test")
        self._target.update()
        self._show_test_stage()

    def _set_trial_deadline(self, now: float) -> None:
        self._trial_feedback_loss = False
        duration = (self._settings.selection_pause_ms + self._settings.dwell_ms) / 1000
        self._trial_deadline = now + max(10.0, duration + 6.0)
        self._trial_coverage = TrialGazeCoverage(now)
        self._set_trial_hint("Zadržite pogled dok se traka ne popuni.")
        self._test_hint.setToolTip(
            f"Pauza {self._settings.selection_pause_ms} ms + "
            f"zadržavanje {self._settings.dwell_ms} ms, kao u aplikaciji."
        )

    def _set_trial_hint(self, feedback: str, state: bool | None = None) -> None:
        index = min(len(self._trial_results), len(TRIAL_WORD) - 1)
        self._set_test_hint(
            f"Slovo {index + 1} od {len(TRIAL_WORD)} · Pogledajte „{TRIAL_WORD[index]}“.",
            feedback,
            state,
        )

    def _trial_sample(self, snapshot: CheckSnapshot, now: float) -> None:
        self._check_trial_interruptions(snapshot)
        if now >= self._trial_deadline:
            self._finish_trial_target(False, now)
            return
        if not self._trial_sample_ready(snapshot, now):
            return
        point = self._trial_point(snapshot.gaze)
        if point is None:
            return
        target, result = self._advance_trial_selection(point, snapshot.gaze_at)
        if result.ready and self._complete_trial_selection(target, now):
            return
        self._update_trial_hint(target)

    def _check_trial_interruptions(self, snapshot: CheckSnapshot) -> None:
        if snapshot.gaze_interruptions != self._trial_interruptions:
            if not self._selection.tracking_held:
                self._cancel_trial_progress(loss=True)
            self._trial_interruptions = snapshot.gaze_interruptions

    def _trial_point(self, gaze: tuple[float, float]) -> QPoint | None:
        screen = QGuiApplication.primaryScreen().geometry()
        x, y = gaze
        if not (0 <= x <= 1 and 0 <= y <= 1):
            if self._selection.target is not None:
                self._trial_departures += 1
            self._cancel_trial_progress(loss=False)
            return None
        global_point = QPoint(
            round(screen.left() + x * (screen.width() - 1)),
            round(screen.top() + y * (screen.height() - 1)),
        )
        return self._target.mapFromGlobal(global_point)

    def _trial_sample_ready(self, snapshot: CheckSnapshot, now: float) -> bool:
        if snapshot.gaze is None:
            if not self._eye_gate.holding:
                self._cancel_trial_progress(loss=True)
            return False
        if not eyes_usable(self._settings.eye_tracking_policy, snapshot.left, snapshot.right):
            self._cancel_trial_progress(loss=True)
            return False
        at = snapshot.gaze_at
        if not self._trial_timestamp_ready(at, now):
            return False
        self._record_trial_sample(at)
        return True

    def _trial_timestamp_ready(self, at: float | None, now: float) -> bool:
        if at is None or at == self._trial_sample_at:
            return False
        if now < self._trial_ready_at:
            return False
        if not 0 <= now - at < FRESH_SECONDS or at < self._trial_ready_at:
            self._cancel_trial_progress(loss=True)
            return False
        return True

    def _record_trial_sample(self, at: float) -> None:
        if self._trial_sample_at is not None and at - self._trial_sample_at >= FRESH_SECONDS:
            self._cancel_trial_progress(loss=True)
        self._trial_sample_at = at
        if self._trial_coverage is not None:
            self._trial_coverage.add(at)
        self._trial_feedback_loss = False

    def _advance_trial_selection(self, point: QPoint, at: float):
        rect = self._target.button_rect()
        target = next(
            (
                index
                for index in range(len(TRIAL_KEYS))
                if self._target.button_rect(index).contains(point)
            ),
            None,
        )
        previous = self._selection.target
        hold_rect = self._target.button_rect(previous) if previous is not None else rect
        margin = min(TOOLBAR_EDGE_MARGIN_PX, hold_rect.width() // 4, hold_rect.height() // 4)
        hold = self._target.rect().contains(point) and hold_rect.adjusted(
            -margin, -margin, margin, margin
        ).contains(point)
        result = self._selection.update(
            target,
            at * 1000,
            pause_ms=self._settings.selection_pause_ms,
            dwell_ms=self._settings.dwell_ms,
            can_hold=hold,
            hold_ms=self._settings.edge_hold_ms,
        )
        if previous is not None and self._selection.target != previous:
            self._trial_departures += 1
        self._target.progress = result.progress or 0.0
        self._target.progress_target = self._selection.target
        self._target.update()
        return target, result

    def _complete_trial_selection(self, target: int | None, now: float) -> bool:
        self._selection.complete()
        if target == self._target.expected_button:
            self._finish_trial_target(True, now)
            return True
        self._trial_wrong_selections += 1
        return False

    def _update_trial_hint(self, target: int | None) -> None:
        if target == self._target.expected_button:
            self._set_trial_hint("Zadržite pogled dok se traka ne popuni.")
        elif target is None:
            self._set_trial_hint("Pogled je izvan slova. Vratite ga na traženo slovo.", False)
        elif self._selection.is_blocked:
            self._set_trial_hint("Odabrano je pogrešno slovo. Pogledajte traženo slovo.", False)
        else:
            self._set_trial_hint("Pogled je na drugom slovu. Pogledajte traženo slovo.", False)

    def _cancel_trial_progress(self, *, loss: bool) -> None:
        self._target.paused = False
        if loss:
            self._record_trial_loss()
            self._selection.pause()
        else:
            self._selection.cancel()
            if self._phase == "trial":
                self._set_trial_hint("Pogled je izvan slova. Vratite ga na traženo slovo.", False)
        self._target.progress = 0.0
        self._target.progress_target = None
        self._target.update()

    def _record_trial_loss(self) -> None:
        if self._trial_coverage is not None:
            self._trial_coverage.interrupt()
        if self._phase != "trial" or self._selection.is_blocked:
            return
        if self._selection.target is not None:
            self._trial_losses += 1
            self._trial_feedback_loss = True
            self._set_trial_hint(
                "Praćenje je prekinuto. Pogledajte traženo slovo za novi izbor.", False
            )
        elif not self._trial_feedback_loss:
            self._set_trial_hint("Čekam svjež validan pogled. Pogledajte prema ekranu.")

    def _finish_trial_target(self, selected: bool, now: float) -> None:
        coverage = (
            self._trial_coverage.fraction(min(now, self._trial_deadline))
            if self._trial_coverage
            else 0.0
        )
        baseline = self._trial_baseline
        self._trial_rows.append(
            TrialRow(
                len(self._trial_results),
                self._target.key_size(),
                "measured" if coverage >= 0.6 else "insufficient",
                selected,
                coverage,
                max(0, min(now, self._trial_deadline) - self._trial_ready_at),
                self._trial_wrong_selections - baseline[0],
                self._trial_losses - baseline[1],
                self._trial_departures - baseline[2],
            )
        )
        self._trial_baseline = (
            self._trial_wrong_selections,
            self._trial_losses,
            self._trial_departures,
        )
        if self._trial_coverage is not None and self._trial_coverage.sufficient(
            min(now, self._trial_deadline)
        ):
            self._trial_tracked_targets.add(len(self._trial_results))
        self._trial_results.append(selected)
        diagnostics.emit(
            "trial_result",
            trace=True,
            priority=True,
            target_index=len(self._trial_results) - 1,
            selected=selected,
            tracked=len(self._trial_results) - 1 in self._trial_tracked_targets,
            eye_losses=self._trial_losses,
            departures=self._trial_departures,
            wrong_selections=self._trial_wrong_selections,
        )
        self._selection.cancel()
        self._target.progress = 0.0
        self._target.progress_target = None
        if len(self._trial_results) == len(TRIAL_WORD):
            self._show_results()
        else:
            self._target.target_index = len(self._trial_results)
            self._trial_ready_at = now + 1.0
            self._set_trial_deadline(self._trial_ready_at)
        self._target.update()

    def _calibrate(self) -> None:
        if self._phase == "results":
            self.reset_check()
            return
        self._finalize_attempt("Otvorene Tobii postavke")
        self.reset_check()
        self._notice.setText(
            "U Tobii Core odaberite profil korisnika > Test and recalibrate > Recalibrate. "
            "Vratite se ovdje i ponovite provjeru."
        )
        self.showMinimized()
        self.calibration_requested.emit()

    def set_calibration_notice(self, message: str) -> None:
        self._notice.setText(
            f"{message}\nOdaberite profil korisnika > Test and recalibrate > Recalibrate, "
            "zatim se vratite ovdje i ponovite provjeru."
        )
