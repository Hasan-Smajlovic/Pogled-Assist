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
    TARGET_SECONDS,
    CheckSnapshot,
    FixationCheck,
    FixationResult,
    TrialGazeCoverage,
)
from ..tracking.gaze_check_report import (
    ENVIRONMENT_KEYS,
    SETTING_KEYS,
    GazeCheckReport,
    PrecisionRow,
    TrialAttempt,
    TrialRow,
    identity,
    timestamp,
)
from ..tracking.gaze_check_store import GazeCheckStore
from ..tracking.status import TrackingState, TrackingStatus
from .gaze_check_feedback import result_advice
from .gaze_check_history import GazeCheckHistory
from .gaze_check_reports import GazeCheckReports
from .gaze_check_text import (
    free_gaze_is_visible,
    position_guidance,
    position_notice,
    precision_feedback,
    visible_eyes,
)
from .gaze_check_views import COLORS, TARGETS, CheckTargetView, EyePositionView, ResultMapView
from .recording_badge import RecordingBadge

STYLESHEET = """
QWidget#gazeCheck { background: #111318; color: #eef2f8; font-family: Segoe UI; }
QLabel { color: #eef2f8; background: transparent; font-size: 17px; }
QLabel#checkTitle { font-size: 30px; font-weight: 650; }
QLabel#cardTitle { font-size: 23px; font-weight: 600; }
QLabel#checkHint { font-size: 15px; color: #bac5d4; }
QFrame#checkCard { background: #1c2029; border: 1px solid #394253; border-radius: 12px; }
QPushButton { background: #1c2029; color: #eef2f8; border: 1px solid #58647a;
    border-radius: 9px; padding: 10px 16px; font-size: 18px; font-weight: 600; }
QPushButton:hover { background: #262c38; border-color: #8bd5f5; }
QPushButton:focus { border: 2px solid #8bd5f5; }
QPushButton#checkPrimary { background: #245f9f; border-color: #8bd5f5; }
QProgressBar { background: #394253; border: none; border-radius: 3px; }
QProgressBar::chunk { background: #8bd5f5; border-radius: 3px; }
QScrollArea, QScrollArea QWidget { background: #1c2029; border: none; }
QComboBox { background: #262c38; color: #eef2f8; padding: 8px; font-size: 17px; }
QComboBox QAbstractItemView { background: #262c38; color: #eef2f8; }
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
        self.setStyleSheet(STYLESHEET)
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
        header = QHBoxLayout()
        copy = QVBoxLayout()
        self._title_label = _label("Provjera pogleda", self, "checkTitle")
        copy.addWidget(self._title_label)
        self._policy_text = dict(EYE_TRACKING_POLICY_CHOICES)[self._settings.eye_tracking_policy]
        self._policy_label = _label(f"Režim: {self._policy_text}", self, "checkHint")
        copy.addWidget(self._policy_label)
        self._simulation_label = _label("SIMULACIJA MIŠEM · Bez Tobii mjerenja.", self, "checkHint")
        self._simulation_label.setVisible(self._simulated)
        copy.addWidget(self._simulation_label)
        self._recording_badge = RecordingBadge(self)
        copy.addWidget(self._recording_badge)
        header.addLayout(copy, 1)
        self._diagnostics_button = self._button("Dijagnostičko snimanje", self._request_diagnostics)
        header.addWidget(self._diagnostics_button)
        self._history_button = self._button("Sačuvani rezultati", self._open_history)
        header.addWidget(self._history_button)
        self._close_button = self._button("Zatvori · Esc", self.close)
        header.addWidget(self._close_button)
        layout.addLayout(header)
        self._step = _label("1 · Položaj i praćenje", self, "cardTitle")
        layout.addWidget(self._step)
        self._pages = QStackedWidget(self)
        layout.addWidget(self._pages, 1)
        self._build_position_page()
        self._build_test_page()
        self._build_result_page()
        self._build_history_page()
        self._notice = _label(
            "Upravljanje pogledom je pauzirano tokom provjere.",
            self,
            "checkHint",
        )
        layout.addWidget(self._notice)
        footer = QHBoxLayout()
        self._calibration_button = self._button("Otvori Tobii postavke", self._calibrate)
        self._free_button = self._button("Slobodna provjera", self._start_free)
        self._primary_button = self._button("Provjeri preciznost", self._next)
        self._primary_button.setObjectName("checkPrimary")
        self._repeat_button = self._button("Ponovi preciznost", self._repeat)
        self._repeat_button.hide()
        for button in (
            self._calibration_button,
            self._free_button,
            self._primary_button,
            self._repeat_button,
        ):
            footer.addWidget(button, 1)
        layout.addLayout(footer)

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
        card, layout = self._card(page, "Položaj očiju uživo")
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
        self._stability_label = _label("— Oba oka · prikupljam podatke o praćenju", card)
        self._gaze_label = _label("— Čekam pogled na ekranu", card)
        self._guidance = _label("Pogledajte prema ekranu.", card)
        for label in (
            self._left_label,
            self._right_label,
            self._gaze_label,
            self._stability_label,
            self._guidance,
        ):
            layout.addWidget(label)
        layout.addStretch(1)
        layout.addWidget(
            _label(
                "Kratak prekid može biti treptaj. Preciznost provjerite na metama.",
                card,
                "checkHint",
            )
        )
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
        map_column = QVBoxLayout()
        self._result_map = ResultMapView(card)
        map_column.addWidget(self._result_map, 1)
        map_column.addWidget(
            _label(
                "Krug = meta · tačka = pogled\nLinija pokazuje koliko je pogled promašio.",
                card,
                "checkHint",
            )
        )
        columns.addLayout(map_column, 1)
        columns.addWidget(self._result_detail, 3)
        self._result_advice = _label("", card)
        self._trial_summary = _label("", card)
        self._trial_summary.hide()
        precision_layout.addWidget(self._result_summary)
        precision_layout.addLayout(columns, 1)
        precision_layout.addWidget(self._result_advice)
        precision_layout.addWidget(self._trial_summary)
        self._details_button = self._button("Prikaži mjerenja", self._render_result_details)
        self._details_button.setCheckable(True)
        precision_layout.addWidget(self._details_button, 0, Qt.AlignLeft)
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
        precision_layout.addWidget(self._metrics_hint)
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
        self._timer.start()
        diagnostics.emit("gaze_check_open", priority=True, phase=self._phase)

    def closeEvent(self, event) -> None:
        self._finalize_attempt("Zatvorena provjera")
        diagnostics.emit("gaze_check_close", priority=True, phase=self._phase)
        self._timer.stop()
        self._selection.cancel()
        self._check = None
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
        if (
            snapshot.left is not None
            and snapshot.right is not None
            and self._eye_gate.eyes != (snapshot.left, snapshot.right)
        ):
            self.handle_eye_status(snapshot.left, snapshot.right)
        if snapshot.gaze is not None and snapshot.gaze_at != self._policy_sample_at:
            if self._eye_gate.sample(snapshot.gaze_at):
                self._policy_sample_at = snapshot.gaze_at
            else:
                snapshot = replace(snapshot, gaze=None, gaze_at=None)
        self._snapshot = snapshot
        now = time.monotonic()
        self._snapshot_at = now
        if not self.isVisible() or self.isMinimized():
            return
        if self._phase == "precision" and self._check is not None:
            self._check.add(snapshot, now)
        if self._phase == "trial":
            self._trial_sample(snapshot, now)
        elif self._phase == "free":
            self._render_free()

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

    def _hold_tracking(self, deadline_ms: float) -> None:
        self._selection.hold_tracking(deadline_ms)
        if self._trial_coverage is not None:
            self._trial_coverage.interrupt()
        if self._selection.tracking_held:
            self._target.paused = True
            self._target.update()
            self._set_trial_hint("Na čekanju · čuvam napredak do povratka oba oka.")

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

    def _expire_snapshot(self, now: float) -> None:
        if self._snapshot_at is None or now - self._snapshot_at >= FRESH_SECONDS:
            self._snapshot = CheckSnapshot(
                position_supported=self._snapshot.position_supported,
                gaze_interruptions=self._snapshot.gaze_interruptions,
            )
        if not self._eye_gate.holding and (
            self._snapshot.gaze_at is None or now - self._snapshot.gaze_at >= FRESH_SECONDS
        ):
            self._cancel_trial_progress(loss=True)
            if self._phase == "precision" and self._check is not None:
                self._check.interrupt()

    def _tick_precision(self, now: float) -> None:
        if self._check.advance(now):
            if self._check.finished:
                self._show_results()
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
            self._stability_label,
            snapshot.stable,
            {
                True: "Oba oka · praćenje je uglavnom neprekinuto",
                False: "Oba oka · praćenje ima prekide",
                None: "Oba oka · prikupljam podatke o praćenju",
            }[snapshot.stable],
        )
        self._state(
            self._gaze_label,
            True if snapshot.gaze is not None else None,
            "Pogled se prati" if snapshot.gaze is not None else "Čekam pogled na ekranu",
        )
        self._stability_label.setToolTip(
            f"Oba oka: {snapshot.available_fraction:.0%} vremena "
            f"u posljednjih {snapshot.observed_seconds:.1f} s. Pragovi aplikacije: "
            "najmanje 85%, prekid najviše 0,5 s."
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
        self._primary_button.setText("Provjeri preciznost")
        self._primary_button.show()
        self._primary_button.setEnabled(True)
        self._repeat_button.hide()
        self._calibration_button.show()
        self._calibration_button.setText("Otvori Tobii postavke")
        self._free_button.show()
        self._notice.setText("Upravljanje pogledom je pauzirano tokom provjere.")
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
        self._step.setText("2 · Preciznost · pet kratkih meta")
        self._set_test_hint(
            "Meta 1 od 5 · Gledajte križić u krugu.",
            "Meta se mijenja sama; ne trebate kliknuti.",
        )
        self._test_progress.setValue(0)
        self._check = None
        self._primary_button.hide()
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
        ended = timestamp()
        duration = max(0, now - self._attempt_started_mono)
        state = "interrupted" if reason else "completed"
        settings = {key: getattr(self._settings, key, None) for key in SETTING_KEYS}
        if self._phase == "precision":
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
                attempt_id,
                self._attempt_started_at,
                ended,
                duration,
                state,
                reason,
                self._simulated,
                settings,
                self._environment.copy(),
                rows,
            )
            self._observe_fixations(results)
        else:
            if self._report is None:
                self._report = GazeCheckReport(
                    identity(),
                    self._attempt_started_at,
                    ended,
                    0,
                    "interrupted",
                    "Preciznost nije pokrenuta",
                    self._simulated,
                    settings,
                    self._environment.copy(),
                    [PrecisionRow(name, (x, y)) for name, x, y in TARGETS],
                )
            rows = list(self._trial_rows)
            for index in range(len(rows), 3):
                rows.append(TrialRow(index, ((136, 64), (96, 88), (180, 72))[index]))
            if reason and len(self._trial_rows) < 3:
                row = rows[len(self._trial_rows)]
                row.coverage = (
                    self._trial_coverage.fraction(min(now, self._trial_deadline))
                    if self._trial_coverage
                    else 0
                )
                row.duration_seconds = max(0, min(now, self._trial_deadline) - self._trial_ready_at)
                row.wrong_selections = self._trial_wrong_selections - self._trial_baseline[0]
                row.cancelled_selections = self._trial_losses - self._trial_baseline[1]
                row.departures = self._trial_departures - self._trial_baseline[2]
            self._report.trials.append(
                TrialAttempt(
                    attempt_id,
                    self._attempt_started_at,
                    ended,
                    duration,
                    state,
                    reason,
                    rows,
                    self._environment.copy(),
                )
            )
        self._view_report = self._report
        self._reports.record(self._report, auto_save=self._auto_save)
        diagnostics.emit(
            "gaze_check_result",
            priority=True,
            report_id=self._report.id,
            attempt_id=attempt_id,
            phase=self._phase,
            state=state,
        )

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
        width = min(760, self.width() - 32)
        top = round(self.height() * 0.72) - 70 if self._phase == "free" else self.height() - 178
        self._test_controls.setGeometry((self.width() - width) // 2, top, width, 168)
        self._test_controls.show()
        self._test_controls.raise_()
        self._test_back_button.setText(
            "Prekini i prikaži rezultat" if self._phase != "free" else "Vrati na položaj"
        )

    def _start_free(self) -> None:
        self._set_test_mode("free")
        self._check = None
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

    def _show_results(self) -> None:
        reason = None
        if self._phase == "precision" and (self._check is None or len(self._check.results) < 5):
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
        near = sum(result.near is True for result in results)
        missing = sum(result.near is None for result in results)
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
        trial_finished = len(selected) == 3
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
        self._result_summary.setText(f"{mark} {summary}")
        self._result_summary.setStyleSheet(f"color: {COLORS[state]}; font-size: 23px;")
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
            )
        )
        if self._view_report is not None and self._view_report.state == "interrupted":
            self._result_advice.setText(
                "Provjera je prekinuta. Završene mete su sačuvane; "
                "izaberite „Ponovi preciznost“ za cijeli test."
            )
        self._trial_summary.setVisible(trial_finished)
        if trial_finished:
            trial_ok = all(selected) and not wrong
            self._state(
                self._trial_summary,
                trial_ok,
                f"Probni izbor: {sum(selected)}/3 · "
                f"pogrešni izbori: {wrong} · poništeni izbori: {losses}",
            )
        self._primary_button.setText(
            "Ponovi probu dugmadi" if trial_finished else "Probaj izbor dugmeta"
        )
        self._primary_button.show()
        self._primary_button.setEnabled(True)
        if self._view_report is not None:
            self._primary_button.setEnabled(self._view_report.state == "completed")
        self._primary_button.setVisible(not self._archived)
        self._calibration_button.setVisible(not self._archived)
        self._calibration_button.setText("Podesi položaj")
        self._free_button.hide()
        self._repeat_button.setText("Nazad na listu" if self._archived else "Ponovi preciznost")
        self._repeat_button.show()
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
        results = self._fixations()
        rows = []
        for result in results:
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
                row = (
                    f'<td>{escape(result.name)}</td><td style="color: {color}">{mark} {status}</td>'
                )
            rows.append(f"<tr>{row}</tr>")
        if self._view_report is not None:
            for result in self._view_report.precision:
                if result.state == "unmeasured":
                    rows.append(
                        f'<tr><td>{escape(result.name)}</td><td colspan="4">Nije izmjereno</td></tr>'
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

    def _start_trial(self) -> None:
        self._set_test_mode("trial")
        self._begin_attempt()
        self._trial_rows = []
        self._trial_baseline = (0, 0, 0)
        self._step.setText("3 · Probni izbor · bez klika drugim programima")
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
        self._set_test_hint(
            f"Dugme {len(self._trial_results) + 1} od 3 · Gledajte „Pogledaj“.", feedback, state
        )

    def _trial_sample(self, snapshot: CheckSnapshot, now: float) -> None:
        if snapshot.gaze_interruptions != self._trial_interruptions:
            if not self._selection.tracking_held:
                self._cancel_trial_progress(loss=True)
            self._trial_interruptions = snapshot.gaze_interruptions
        if now >= self._trial_deadline:
            self._finish_trial_target(False, now)
            return
        if not self._trial_sample_ready(snapshot, now):
            return
        screen = QGuiApplication.primaryScreen().geometry()
        x, y = snapshot.gaze
        if not (0 <= x <= 1 and 0 <= y <= 1):
            if self._selection.target is not None:
                self._trial_departures += 1
            self._cancel_trial_progress(loss=False)
            return
        global_point = QPoint(
            round(screen.left() + x * (screen.width() - 1)),
            round(screen.top() + y * (screen.height() - 1)),
        )
        point = self._target.mapFromGlobal(global_point)
        target, result = self._advance_trial_selection(point, snapshot.gaze_at)
        if result.ready and self._complete_trial_selection(target, now):
            return
        self._update_trial_hint(target)

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
            (index for index in range(3) if self._target.button_rect(index).contains(point)), None
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
            self._set_trial_hint("Pogled je izvan dugmeta. Vratite ga na „Pogledaj“.", False)
        elif self._selection.is_blocked:
            self._set_trial_hint("Odabrano je pogrešno dugme. Pogledajte „Pogledaj“.", False)
        else:
            self._set_trial_hint("Pogled je na drugom dugmetu. Pogledajte „Pogledaj“.", False)

    def _cancel_trial_progress(self, *, loss: bool) -> None:
        self._target.paused = False
        if loss:
            self._record_trial_loss()
            self._selection.pause()
        else:
            self._selection.cancel()
            if self._phase == "trial":
                self._set_trial_hint("Pogled je izvan dugmeta. Vratite ga na „Pogledaj“.", False)
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
                "Praćenje je prekinuto. Pogledajte „Pogledaj“ za novi izbor.", False
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
                ((136, 64), (96, 88), (180, 72))[len(self._trial_results)],
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
        if len(self._trial_results) == 3:
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
