"""Caregiver-operated, side-effect-free positioning and gaze validation window."""

from __future__ import annotations

import math
import time
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

from ..interaction.gaze_selection import GazeSelectionTimer
from ..interaction.mouse_controller import (
    TOOLBAR_EDGE_MARGIN_PX,
    TOOLBAR_LEAVE_GRACE_MS,
    GazeSettings,
)
from ..tracking.gaze_check import (
    FRESH_SECONDS,
    TARGET_SECONDS,
    CheckSnapshot,
    FixationCheck,
)
from ..tracking.status import TrackingState, TrackingStatus
from .gaze_check_views import COLORS, TARGETS, CheckTargetView, EyePositionView, ResultMapView

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
"""


def _label(text: str, parent: QWidget, name: str = "") -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


class GazeCheckWindow(QWidget):
    closed = Signal()
    calibration_requested = Signal()

    def __init__(
        self,
        settings: GazeSettings,
        parent: QWidget | None = None,
        *,
        simulated: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Provjera pogleda")
        self.setObjectName("gazeCheck")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Window)
        self.setStyleSheet(STYLESHEET)
        self._settings = replace(settings)
        self._simulated = simulated
        self._snapshot = CheckSnapshot()
        self._snapshot_at: float | None = None
        self._check: FixationCheck | None = None
        self._phase = "position"
        self._selection = GazeSelectionTimer()
        self._trial_results: list[bool] = []
        self._trial_gaze_targets: set[int] = set()
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
        copy.addWidget(_label("Provjera pogleda", self, "checkTitle"))
        if self._simulated:
            copy.addWidget(_label("SIMULACIJA MIŠEM · Bez Tobii mjerenja.", self, "checkHint"))
        header.addLayout(copy, 1)
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
        self._repeat_button = self._button("Ponovi provjeru", self.reset_check)
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
        self._stability_label = _label("— Prikupljam podatke o praćenju", card)
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
        layout.setSpacing(6)
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
        self._test_back_button = self._button("Vrati na položaj", self.reset_check)
        self._test_close_button = self._button("Zatvori · Esc", self.close)
        buttons.addWidget(self._test_back_button)
        buttons.addWidget(self._test_close_button)
        layout.addLayout(buttons)

    def _build_result_page(self) -> None:
        card, layout = self._card(self, "")
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self._result_summary = _label("", card, "cardTitle")
        self._result_detail = _label("", card)
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
        layout.addWidget(self._result_summary)
        layout.addLayout(columns, 1)
        layout.addWidget(self._result_advice)
        layout.addWidget(self._trial_summary)
        self._details_button = self._button("Prikaži mjerenja", self._render_result_details)
        self._details_button.setCheckable(True)
        layout.addWidget(self._details_button, 0, Qt.AlignLeft)
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
        layout.addWidget(self._metrics_hint)
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

    def closeEvent(self, event) -> None:
        self._timer.stop()
        self._selection.cancel()
        self._check = None
        self._snapshot = CheckSnapshot()
        self.closed.emit()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._phase in ("precision", "trial", "free"):
            self.reset_check()
            self._notice.setText("Veličina ekrana se promijenila. Pokrenite novu provjeru.")

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if (
            event.type() == QEvent.WindowStateChange
            and self.isMinimized()
            and self._phase in ("precision", "trial", "free")
        ):
            self.reset_check()

    def handle_snapshot(self, snapshot: CheckSnapshot) -> None:
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

    def handle_eye_status(self, left: bool, right: bool) -> None:
        if not (left and right):
            self._snapshot = replace(
                self._snapshot, left=left, right=right, gaze=None, gaze_at=None
            )
            self._cancel_trial_progress(loss=True)
            if self._phase == "precision" and self._check is not None:
                self._check.interrupt()
            elif self._phase == "free":
                self._render_free()

    def tracking_unavailable(self) -> None:
        self._snapshot = CheckSnapshot()
        self._snapshot_at = None
        self._cancel_trial_progress(loss=True)
        if self._phase in ("precision", "trial", "free"):
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
        if self._snapshot_at is None or now - self._snapshot_at >= FRESH_SECONDS:
            self._snapshot = CheckSnapshot(
                position_supported=self._snapshot.position_supported,
                gaze_interruptions=self._snapshot.gaze_interruptions,
            )
        if self._snapshot.gaze_at is None or now - self._snapshot.gaze_at >= FRESH_SECONDS:
            self._cancel_trial_progress(loss=True)
            if self._phase == "precision" and self._check is not None:
                self._check.interrupt()
        if self._phase == "position":
            self._render_position()
        elif self._phase == "precision" and self._check is not None:
            if self._check.advance(now):
                if self._check.finished:
                    self._show_results()
                    return
                self._target.target_index = self._check.index
                self._target.update()
            remaining = max(1, round(TARGET_SECONDS - (now - self._check.started_at)))
            feedback = f"Zadržite pogled · još {remaining} s."
            state = None
            if self._snapshot.left is False and self._snapshot.right is True:
                feedback, state = "Uređaj ne vidi lijevo oko. Pogledajte prema ekranu.", False
            elif self._snapshot.right is False and self._snapshot.left is True:
                feedback, state = "Uređaj ne vidi desno oko. Pogledajte prema ekranu.", False
            elif (
                self._snapshot.gaze is None
                or self._snapshot.gaze_at is None
                or not 0 <= now - self._snapshot.gaze_at < FRESH_SECONDS
            ):
                feedback = "Čekam pogled s oba oka. Ako se ne vrati, odaberite „Prekini test“."
            self._set_test_hint(
                f"Meta {self._check.index + 1} od 5 · Gledajte križić u krugu.", feedback, state
            )
            elapsed = self._check.index * TARGET_SECONDS + now - self._check.started_at
            self._test_progress.setValue(round(1000 * elapsed / (5 * TARGET_SECONDS)))
        elif self._phase == "trial" and now >= self._trial_deadline:
            self._finish_trial_target(False, now)
        elif self._phase == "free":
            self._render_free()

    @staticmethod
    def _state(label: QLabel, state: bool | None, text: str) -> None:
        mark = {True: "✓", False: "!", None: "—"}[state]
        label.setText(f"{mark} {text}")
        label.setStyleSheet(f"color: {COLORS[state]}; font-size: 19px;")

    def _render_position(self) -> None:
        snapshot = self._snapshot
        if self._tracking_state in (
            TrackingState.RETRYING,
            TrackingState.STOPPED,
            TrackingState.UNAVAILABLE,
        ):
            position_notice = "Veza uređaja je prekinuta. Čekam ponovno povezivanje."
        elif snapshot.position_supported is False:
            position_notice = (
                "Uređaj ne šalje položaje očiju za ovaj prikaz. Koristite Tobii prikaz položaja."
            )
        elif snapshot.left_position is None and snapshot.right_position is None:
            position_notice = "Čekam svježe podatke o položaju očiju."
        else:
            position_notice = "Okvir pokazuje položaj očiju, traka ispod udaljenost."
        self._position_notice.setText(position_notice)
        left_visible = snapshot.left_position is not None or snapshot.left
        right_visible = snapshot.right_position is not None or snapshot.right
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
                True: "Praćenje je uglavnom neprekinuto",
                False: "Praćenje ima prekide",
                None: "Prikupljam podatke o praćenju",
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
        guidance = "Zadržite položaj i odaberite „Provjeri preciznost“."
        if left_visible is None or right_visible is None:
            guidance = "Čekam svježe podatke. Provjerite vezu uređaja i pogledajte prema ekranu."
        elif not (left_visible and right_visible):
            guidance = "Polako podesite položaj i nagib ekrana dok uređaj ponovo vidi oba oka."
        elif position is False:
            guidance = "Pomjerajte i nagnite ekran tako da su obje oznake unutar okvira."
        elif depth is False:
            depths = [snapshot.left_position[2], snapshot.right_position[2]]
            if max(depths) < 0:
                guidance = "Polako odmaknite ekran od lica."
            elif min(depths) > 1:
                guidance = "Polako približite ekran licu."
            else:
                guidance = "Podesite udaljenost i nagib ekrana; pratite oznake na traci."
        elif snapshot.gaze is None:
            guidance = "Oči su prepoznate, ali pogled se još ne prati. Pogledajte prema ekranu."
        elif snapshot.stable is False:
            guidance = (
                "Zadržite ekran mirno. Ako se prekidi nastave, provjerite položaj i osvjetljenje."
            )
        elif position is None or depth is None:
            guidance = (
                "Uređaj ne šalje položaj za ovaj prikaz. Podesite ekran uz Tobii prikaz položaja."
            )
        self._guidance.setText(guidance)

    def _next(self) -> None:
        if self._phase == "position":
            self._start_precision()
        elif self._phase == "results":
            self._start_trial()

    def reset_check(self) -> None:
        self._phase = "position"
        self._check = None
        self._selection.cancel()
        self._trial_results.clear()
        self._trial_gaze_targets.clear()
        self._target.hide()
        self._target.gaze_point = None
        self._trial_summary.hide()
        self._details_button.setChecked(False)
        self._pages.setCurrentIndex(0)
        self._step.setText("1 · Položaj i praćenje")
        self._primary_button.setText("Provjeri preciznost")
        self._primary_button.show()
        self._repeat_button.hide()
        self._calibration_button.show()
        self._free_button.show()
        self._notice.setText("Upravljanje pogledom je pauzirano tokom provjere.")
        self._render_position()

    def _set_test_mode(self, phase: str) -> None:
        self._pages.setCurrentIndex(1)
        self._phase = phase
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
            targets, (screen.width(), screen.height()), self._target.radius, time.monotonic()
        )

    def _show_test_stage(self) -> None:
        self._target.setGeometry(self.rect())
        self._target.show()
        self._target.raise_()
        width = min(760, self.width() - 32)
        top = round(self.height() * 0.72) - 70 if self._phase == "free" else self.height() - 158
        self._test_controls.setGeometry((self.width() - width) // 2, top, width, 148)
        self._test_controls.show()
        self._test_controls.raise_()
        self._test_back_button.setText(
            "Prekini test" if self._phase != "free" else "Vrati na položaj"
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
        if (
            snapshot.left
            and snapshot.right
            and snapshot.gaze is not None
            and snapshot.gaze_at is not None
            and 0 <= now - snapshot.gaze_at < FRESH_SECONDS
            and all(math.isfinite(value) and 0 <= value <= 1 for value in snapshot.gaze)
        ):
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
            else "Čekam pogled s oba oka. Ako oznake nema, vratite se na položaj.",
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
        self._target.hide()
        self._phase = "results"
        self._pages.setCurrentIndex(2)
        self._step.setText("Rezultat provjere")
        results = self._check.results if self._check is not None else []
        near = sum(result.near is True for result in results)
        missing = sum(result.near is None for result in results)
        trial_finished = len(self._trial_results) == 3
        state = None if missing or not results else near == len(results)
        summary = (
            f"Za {missing} od {len(results)} meta nema dovoljno podataka."
            if missing
            else f"Pogled je bio blizu {near} od {len(results)} meta."
        )
        if not results:
            summary = "Preciznost još nije provjerena."
        mark = {True: "✓", False: "!", None: "—"}[state]
        self._result_summary.setText(f"{mark} {summary}")
        self._result_summary.setStyleSheet(f"color: {COLORS[state]}; font-size: 23px;")
        self._render_result_details()
        self._result_map.results = results
        self._result_map.targets = self._check.targets if self._check is not None else []
        self._result_map.update()
        if missing or not results:
            advice = "Odaberite „Podesi položaj“. Kad se prate oba oka, ponovite provjeru."
        elif state is True:
            advice = "Još provjerite izbor dugmeta pogledom."
            if trial_finished:
                if any(
                    not selected and index not in self._trial_gaze_targets
                    for index, selected in enumerate(self._trial_results)
                ):
                    advice = (
                        "Tokom dijela probe nije bilo podataka o pogledu. Podesite položaj "
                        "dok se prate oba oka, pa ponovite probu."
                    )
                elif self._trial_losses and not all(self._trial_results):
                    advice = (
                        "Prekidi praćenja poništavali su izbor. Podesite ekran dok uređaj "
                        "ne vidi oba oka, pa ponovite probu."
                    )
                elif self._trial_wrong_selections:
                    advice = (
                        "Odabrana su i pogrešna dugmad. Provjerite položaj i kalibraciju, "
                        "pa ponovite probu."
                    )
                elif not all(self._trial_results):
                    advice = (
                        "Neka dugmad nisu odabrana na vrijeme. Ponovite probu; zadržite "
                        "pogled na „Pogledaj“ dok se traka ne popuni."
                    )
                else:
                    advice = "Zatvorite provjeru i probajte govornu tastaturu."
                    if self._trial_losses:
                        advice += " Ako se izbor često poništava, ponovo podesite položaj."
        else:
            advice = (
                "Odaberite „Podesi položaj“. Ako pogled i dalje promašuje, "
                "otvorite Tobii postavke i ponovite kalibraciju korisnikovog profila."
            )
        self._result_advice.setText(advice)
        self._trial_summary.setVisible(trial_finished)
        if trial_finished:
            trial_ok = all(self._trial_results) and not self._trial_wrong_selections
            self._state(
                self._trial_summary,
                trial_ok,
                f"Probni izbor: {sum(self._trial_results)}/3 · "
                f"pogrešni izbori: {self._trial_wrong_selections} · "
                f"poništeni izbori: {self._trial_losses}",
            )
        self._primary_button.setText(
            "Ponovi probu dugmadi" if trial_finished else "Probaj izbor dugmeta"
        )
        self._primary_button.show()
        self._calibration_button.show()
        self._free_button.show()
        self._repeat_button.setText("Podesi položaj" if state is not True else "Ponovi provjeru")
        self._repeat_button.show()

    def _render_result_details(self) -> None:
        detailed = self._details_button.isChecked()
        self._details_button.setText("Sakrij mjerenja" if detailed else "Prikaži mjerenja")
        self._metrics_hint.setVisible(detailed)
        results = self._check.results if self._check is not None else []
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
                    f"<td>{result.coverage:.0%}</td><td>{error}</td><td>{spread}</td>"
                )
            else:
                row = (
                    f'<td>{escape(result.name)}</td><td style="color: {color}">{mark} {status}</td>'
                )
            rows.append(f"<tr>{row}</tr>")
        headings = (
            ("Meta", "Podaci", "Odstupanje", "Rasipanje") if detailed else ("Meta", "Rezultat")
        )
        table = '<table width="100%" cellspacing="8"><tr>'
        table += "".join(f'<th align="left">{heading}</th>' for heading in headings)
        table += "</tr>" + "".join(rows) + "</table>"
        if detailed and self._trial_results:
            table += (
                f"<p>Izlasci iz dugmeta: {self._trial_departures}. "
                f"Prekidi tokom izbora: {self._trial_losses}.</p>"
            )
        self._result_detail.setText(table)

    def _start_trial(self) -> None:
        self._set_test_mode("trial")
        self._step.setText("3 · Probni izbor · bez klika drugim programima")
        self._trial_results.clear()
        self._trial_gaze_targets.clear()
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
            self._cancel_trial_progress(loss=True)
            self._trial_interruptions = snapshot.gaze_interruptions
        if now >= self._trial_deadline:
            self._finish_trial_target(False, now)
            return
        if snapshot.gaze is None or not (snapshot.left and snapshot.right):
            self._cancel_trial_progress(loss=True)
            return
        at = snapshot.gaze_at
        if at is None or at == self._trial_sample_at or now < self._trial_ready_at:
            return
        if not 0 <= now - at < FRESH_SECONDS or at < self._trial_ready_at:
            self._cancel_trial_progress(loss=True)
            return
        if self._trial_sample_at is not None and at - self._trial_sample_at >= FRESH_SECONDS:
            self._cancel_trial_progress(loss=True)
        self._trial_sample_at = at
        self._trial_gaze_targets.add(len(self._trial_results))
        self._trial_feedback_loss = False
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
        rect = self._target.button_rect()
        target = next(
            (index for index in range(3) if self._target.button_rect(index).contains(point)), None
        )
        previous = self._selection.target
        hold_rect = self._target.button_rect(previous) if previous is not None else rect
        margin = min(TOOLBAR_EDGE_MARGIN_PX, hold_rect.width() // 4, hold_rect.height() // 4)
        hold = target is None and hold_rect.adjusted(-margin, -margin, margin, margin).contains(
            point
        )
        result = self._selection.update(
            target,
            at * 1000,
            pause_ms=self._settings.selection_pause_ms,
            dwell_ms=self._settings.dwell_ms,
            can_hold=hold,
            hold_ms=TOOLBAR_LEAVE_GRACE_MS,
        )
        if previous is not None and self._selection.target != previous:
            self._trial_departures += 1
        self._target.progress = result.progress or 0.0
        self._target.progress_target = self._selection.target
        self._target.update()
        if result.ready:
            self._selection.complete()
            if target == self._target.expected_button:
                self._finish_trial_target(True, now)
                return
            self._trial_wrong_selections += 1
        if target == self._target.expected_button:
            self._set_trial_hint("Zadržite pogled dok se traka ne popuni.")
        elif target is None:
            self._set_trial_hint("Pogled je izvan dugmeta. Vratite ga na „Pogledaj“.", False)
        elif self._selection.is_blocked:
            self._set_trial_hint("Odabrano je pogrešno dugme. Pogledajte „Pogledaj“.", False)
        else:
            self._set_trial_hint("Pogled je na drugom dugmetu. Pogledajte „Pogledaj“.", False)

    def _cancel_trial_progress(self, *, loss: bool) -> None:
        if loss:
            if (
                self._phase == "trial"
                and self._selection.target is not None
                and not self._selection.is_blocked
            ):
                self._trial_losses += 1
                self._trial_feedback_loss = True
                self._set_trial_hint(
                    "Praćenje je prekinuto. Pogledajte „Pogledaj“ za novi izbor.", False
                )
            elif (
                self._phase == "trial"
                and not self._selection.is_blocked
                and not self._trial_feedback_loss
            ):
                self._set_trial_hint("Čekam pogled s oba oka. Pogledajte prema ekranu.")
            self._selection.pause()
        else:
            self._selection.cancel()
            if self._phase == "trial":
                self._set_trial_hint("Pogled je izvan dugmeta. Vratite ga na „Pogledaj“.", False)
        self._target.progress = 0.0
        self._target.progress_target = None
        self._target.update()

    def _finish_trial_target(self, selected: bool, now: float) -> None:
        self._trial_results.append(selected)
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
