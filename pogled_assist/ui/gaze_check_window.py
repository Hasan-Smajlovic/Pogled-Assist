"""Caregiver-operated, side-effect-free positioning and gaze validation window."""

from __future__ import annotations

import time
from dataclasses import replace

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
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

TARGETS = (
    ("Sredina", 0.5, 0.5),
    ("Gore lijevo", 0.12, 0.14),
    ("Gore desno", 0.88, 0.14),
    ("Dolje lijevo", 0.12, 0.86),
    ("Dolje desno", 0.88, 0.86),
)
COLORS = {True: "#70dfa1", False: "#f0c84a", None: "#bac5d4"}
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
"""


def _label(text: str, parent: QWidget, name: str = "") -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


class EyePositionView(QWidget):
    """Projection of the reported normalized box; not a camera image."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.snapshot = CheckSnapshot()
        self.setMinimumHeight(145)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        box = QRectF(26, 12, max(1, self.width() - 52), max(1, self.height() - 56))
        painter.setPen(QPen(QColor("#58647a"), 2, Qt.DashLine))
        painter.drawRoundedRect(box, 10, 10)
        positions = (self.snapshot.left_position, self.snapshot.right_position)
        for name, position in zip(("L", "D"), positions, strict=True):
            if position is None:
                continue
            # TBCS x runs right to left. Show a front projection with user-eye labels.
            x = box.left() + (1 - min(1.0, max(0.0, position[0]))) * box.width()
            y = box.top() + min(1.0, max(0.0, position[1])) * box.height()
            inside = all(0 <= value <= 1 for value in position)
            painter.setPen(QPen(QColor(COLORS[inside]), 3))
            painter.setBrush(QColor("#1c2029"))
            painter.drawEllipse(QPointF(x, y), 16, 16)
            painter.drawText(QRectF(x - 16, y - 16, 32, 32), Qt.AlignCenter, name)
        painter.setPen(QColor("#bac5d4"))
        if all(position is None for position in positions):
            painter.drawText(box, Qt.AlignCenter, "Položaj očiju nije dostupan")
        depth = QRectF(26, self.height() - 23, max(1, self.width() - 52), 8)
        painter.setBrush(QColor("#394253"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(depth, 4, 4)
        for position in positions:
            if position is not None:
                painter.setBrush(QColor(COLORS[0 <= position[2] <= 1]))
                painter.drawEllipse(
                    QPointF(
                        depth.left() + min(1.0, max(0.0, position[2])) * depth.width(),
                        depth.center().y(),
                    ),
                    6,
                    6,
                )


class CheckTargetView(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.target_index = 0
        self.trial = False
        self.progress = 0.0
        self.radius = 36
        self.setMinimumHeight(180)

    def center(self) -> QPoint:
        ratios = (
            ((0.5, 0.5), (0.2, 0.5), (0.8, 0.5))
            if self.trial
            else tuple((x, y) for _, x, y in TARGETS)
        )
        x, y = ratios[self.target_index]
        return QPoint(round(x * (self.width() - 1)), round(y * (self.height() - 1)))

    def button_rect(self) -> QRect:
        center = self.center()
        return QRect(center.x() - 80, center.y() - 55, 160, 110)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#8bd5f5"), 2))
        painter.setBrush(QColor("#1c2029"))
        center = self.center()
        if self.trial:
            rect = self.button_rect()
            painter.drawRoundedRect(rect, 10, 10)
            painter.fillRect(
                QRect(
                    rect.left() + 4,
                    rect.bottom() - 12,
                    round((rect.width() - 8) * self.progress),
                    8,
                ),
                QColor("#70dfa1"),
            )
            painter.setPen(QColor("#eef2f8"))
            painter.drawText(rect, Qt.AlignCenter, "Pogledaj")
        else:
            painter.drawEllipse(center, self.radius, self.radius)
            painter.setPen(QPen(QColor("#eef2f8"), 3))
            painter.drawLine(center + QPoint(-9, 0), center + QPoint(9, 0))
            painter.drawLine(center + QPoint(0, -9), center + QPoint(0, 9))


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
        self._trial_deadline = 0.0
        self._trial_ready_at = 0.0
        self._trial_sample_at: float | None = None
        self._trial_losses = 0
        self._trial_departures = 0
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
        copy.addWidget(
            _label(
                "Ukućanin podešava ekran. Korisnik ostaje u udobnom položaju.", self, "checkHint"
            )
        )
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
            "Upravljanje računarom pogledom je pauzirano dok je ovaj ekran otvoren.",
            self,
            "checkHint",
        )
        layout.addWidget(self._notice)
        if self._simulated:
            layout.addWidget(
                _label("SIMULACIJA MIŠEM · Rezultati ne predstavljaju Tobii mjerenja.", self)
            )
        footer = QHBoxLayout()
        self._calibration_button = self._button("Otvori Tobii kalibraciju", self._calibrate)
        self._primary_button = self._button("Provjeri preciznost", self._next)
        self._primary_button.setObjectName("checkPrimary")
        self._repeat_button = self._button("Ponovi provjeru", self.reset_check)
        self._repeat_button.hide()
        for button in (self._calibration_button, self._primary_button, self._repeat_button):
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
        layout.addWidget(self._eyes_view, 1)
        layout.addWidget(_label("Okvir: položaj očiju · traka: dubina", card, "checkHint"))
        self._position_label = _label("— Položaj nije dostupan", card)
        self._distance_label = _label("— Udaljenost nije dostupna", card)
        layout.addWidget(self._position_label)
        layout.addWidget(self._distance_label)
        columns.addWidget(card, 1)
        card, layout = self._card(page, "Šta uređaj trenutno vidi")
        self._left_label = _label("— Lijevo oko · čekam podatke", card)
        self._right_label = _label("— Desno oko · čekam podatke", card)
        self._stability_label = _label("— Prikupljam podatke o praćenju", card)
        self._gaze_label = _label("— Čekam položaj pogleda", card)
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
                "Kratki prekidi mogu biti treptaji. Zelene oznake još ne potvrđuju preciznost.",
                card,
                "checkHint",
            )
        )
        columns.addWidget(card, 1)
        self._pages.addWidget(page)

    def _build_test_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self._test_hint = _label("", page)
        layout.addWidget(self._test_hint)
        self._target = CheckTargetView(page)
        layout.addWidget(self._target, 1)
        self._pages.addWidget(page)

    def _build_result_page(self) -> None:
        card, layout = self._card(self, "Rezultat ove provjere")
        self._result_summary = _label("", card, "cardTitle")
        self._result_detail = _label("", card)
        self._result_advice = _label("", card)
        self._trial_summary = _label("— Probni izbor nije urađen.", card)
        layout.addWidget(self._result_summary)
        layout.addWidget(self._result_detail)
        layout.addWidget(self._result_advice)
        layout.addWidget(self._trial_summary)
        layout.addStretch(1)
        layout.addWidget(
            _label(
                "Ovo je kratka provjera na označenim mjestima. Pomjeranje ekrana ili promjena "
                "položaja mogu promijeniti rezultat. Po potrebi provjerite Tobii kalibraciju.",
                card,
                "checkHint",
            )
        )
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
        if self._phase in ("precision", "trial"):
            self.reset_check()
            self._notice.setText("Veličina ekrana se promijenila. Pokrenite novu provjeru.")

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if (
            event.type() == QEvent.WindowStateChange
            and self.isMinimized()
            and self._phase in ("precision", "trial")
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

    def handle_eye_status(self, left: bool, right: bool) -> None:
        if not (left and right):
            self._cancel_trial_progress(loss=True)

    def tracking_unavailable(self) -> None:
        self._snapshot = CheckSnapshot()
        self._snapshot_at = None
        self._cancel_trial_progress(loss=True)
        if self._phase in ("precision", "trial"):
            self.reset_check()
            self._notice.setText(
                "Praćenje je prekinuto. Nakon povezivanja pokrenite novu provjeru."
            )
        self._render_position()

    def _tick(self) -> None:
        now = time.monotonic()
        if self._snapshot_at is None or now - self._snapshot_at >= FRESH_SECONDS:
            self._snapshot = CheckSnapshot()
        if self._snapshot.gaze_at is None or now - self._snapshot.gaze_at >= FRESH_SECONDS:
            self._cancel_trial_progress(loss=True)
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
            self._test_hint.setText(
                f"Gledajte sredinu mete {self._check.index + 1}/5 · još {remaining} s. "
                "Prelazi sama; ne trebate kliknuti."
            )
        elif self._phase == "trial" and now >= self._trial_deadline:
            self._finish_trial_target(False, now)

    @staticmethod
    def _state(label: QLabel, state: bool | None, text: str) -> None:
        mark = {True: "✓", False: "!", None: "—"}[state]
        label.setText(f"{mark} {text}")
        label.setStyleSheet(f"color: {COLORS[state]}; font-size: 19px;")

    def _render_position(self) -> None:
        snapshot = self._snapshot
        for name, label, state in (
            ("Lijevo oko", self._left_label, snapshot.left),
            ("Desno oko", self._right_label, snapshot.right),
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
            "Položaj pogleda stiže" if snapshot.gaze is not None else "Čekam položaj pogleda",
        )
        self._stability_label.setToolTip(
            f"Oba oka: {snapshot.available_fraction:.0%} vremena "
            f"u posljednjih {snapshot.observed_seconds:.1f} s."
        )
        self._eyes_view.snapshot = snapshot
        self._eyes_view.update()
        guidance = "Zadržite položaj i provjerite preciznost na označenim metama."
        if snapshot.left is None or snapshot.right is None:
            guidance = "Čekam svježe podatke. Provjerite vezu uređaja i pogledajte prema ekranu."
        elif not (snapshot.left and snapshot.right):
            guidance = "Polako podesite položaj i nagib ekrana dok uređaj ponovo vidi oba oka."
        elif snapshot.gaze is None:
            guidance = (
                "Oči su prepoznate, ali nema svježeg položaja pogleda. Pogledajte prema ekranu."
            )
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
        self._trial_summary.setText("— Probni izbor nije urađen.")
        self._pages.setCurrentIndex(0)
        self._step.setText("1 · Položaj i praćenje")
        self._primary_button.setText("Provjeri preciznost")
        self._primary_button.show()
        self._repeat_button.hide()
        self._calibration_button.show()
        self._notice.setText(
            "Upravljanje računarom pogledom je pauzirano dok je ovaj ekran otvoren."
        )
        self._render_position()

    def _start_precision(self) -> None:
        self._pages.setCurrentIndex(1)
        self._phase = "precision"
        self._step.setText("2 · Preciznost · pet kratkih meta")
        self._target.trial = False
        self._target.target_index = 0
        self._test_hint.setText("Gledajte sredinu mete. Prelazi sama; ne trebate kliknuti.")
        self._check = None
        self._primary_button.hide()
        self._calibration_button.hide()
        self._repeat_button.setText("Prekini test")
        self._repeat_button.show()
        self._target.update()
        # Let Qt settle footer/page geometry before freezing normalized target locations.
        QTimer.singleShot(0, self._begin_precision_measurement)

    def _begin_precision_measurement(self) -> None:
        if self._phase != "precision" or not self.isVisible():
            return
        self.layout().activate()
        self._pages.layout().activate()
        self._target.parentWidget().layout().activate()
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

    def _show_results(self) -> None:
        self._phase = "results"
        self._pages.setCurrentIndex(2)
        self._step.setText("Rezultat · položaj se može ponovo podesiti")
        results = self._check.results if self._check is not None else []
        near = sum(result.near is True for result in results)
        missing = sum(result.near is None for result in results)
        self._result_summary.setText(
            f"Pogled je bio blizu {near} od {len(results)} meta."
            if not missing
            else f"Za {missing} od {len(results)} meta nema dovoljno podataka."
        )
        lines = []
        measurements = []
        for result in results:
            if result.near is None:
                lines.append(f"— {result.name}: nedovoljno podataka")
            else:
                mark = "✓" if result.near else "!"
                detail = "pogled uglavnom unutar kruga" if result.near else "pogled izlazi iz kruga"
                lines.append(f"{mark} {result.name}: {detail}")
                measurements.append(
                    f"{result.name}: odstupanje {result.median_error:.0f} px; "
                    f"rasipanje {result.spread:.0f} px."
                )
        self._result_detail.setText("\n".join(lines))
        self._result_detail.setToolTip(
            "\n".join(measurements)
            + "\nQt logički pikseli. Odstupanje: medijan udaljenosti od mete. Rasipanje: "
            "90. percentil udaljenosti od sredine izmjerenog pogleda. Blizu: najmanje "
            "90% uzoraka unutar kruga od 36 px uz dovoljno svježih podataka."
        )
        if missing:
            advice = "Prvo provjerite prate li se oba oka i stiže li pogled, pa ponovite test."
        elif near == len(results) and results:
            advice = "Mete su provjerene. Još probajte izbor dugmeta."
        else:
            advice = "Podesite položaj i ponovite test. Ako pogled i dalje promašuje, provjerite Tobii kalibraciju."
        self._result_advice.setText(advice)
        self._primary_button.setText("Probaj izbor dugmeta")
        self._primary_button.show()
        self._calibration_button.show()
        self._repeat_button.setText("Ponovi provjeru")
        self._repeat_button.show()

    def _start_trial(self) -> None:
        self._phase = "trial"
        self._pages.setCurrentIndex(1)
        self._step.setText("3 · Probni izbor · bez klika drugim programima")
        self._target.trial = True
        self._target.target_index = 0
        self._target.progress = 0.0
        self._trial_results.clear()
        self._trial_losses = self._trial_departures = 0
        self._trial_sample_at = None
        self._selection.cancel()
        self._trial_ready_at = time.monotonic()
        self._set_trial_deadline(self._trial_ready_at)
        self._primary_button.hide()
        self._calibration_button.hide()
        self._repeat_button.setText("Prekini test")
        self._target.update()

    def _set_trial_deadline(self, now: float) -> None:
        duration = (self._settings.selection_pause_ms + self._settings.dwell_ms) / 1000
        self._trial_deadline = now + max(10.0, duration + 6.0)
        self._test_hint.setText(
            f"Zadržite pogled na dugmetu {len(self._trial_results) + 1}/3. "
            f"Pauza {self._settings.selection_pause_ms} ms + zadržavanje {self._settings.dwell_ms} ms."
        )

    def _trial_sample(self, snapshot: CheckSnapshot, now: float) -> None:
        if now >= self._trial_deadline:
            self._finish_trial_target(False, now)
            return
        if snapshot.gaze is None or not (snapshot.left and snapshot.right):
            self._cancel_trial_progress(loss=True)
            return
        at = snapshot.gaze_at
        if at is None or at == self._trial_sample_at or now < self._trial_ready_at:
            return
        if now - at >= FRESH_SECONDS or at < self._trial_ready_at:
            self._cancel_trial_progress(loss=True)
            return
        if self._trial_sample_at is not None and at - self._trial_sample_at >= FRESH_SECONDS:
            self._cancel_trial_progress(loss=True)
        self._trial_sample_at = at
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
        target = self._target.target_index if rect.contains(point) else None
        margin = TOOLBAR_EDGE_MARGIN_PX
        hold = target is None and rect.adjusted(-margin, -margin, margin, margin).contains(point)
        previous = self._selection.target
        result = self._selection.update(
            target,
            at * 1000,
            pause_ms=self._settings.selection_pause_ms,
            dwell_ms=self._settings.dwell_ms,
            can_hold=hold,
            hold_ms=TOOLBAR_LEAVE_GRACE_MS,
        )
        if previous is not None and self._selection.target is None:
            self._trial_departures += 1
        self._target.progress = result.progress or 0.0
        self._target.update()
        if result.ready:
            self._finish_trial_target(True, now)

    def _cancel_trial_progress(self, *, loss: bool) -> None:
        if self._phase == "trial" and self._selection.target is not None and loss:
            self._trial_losses += 1
        self._selection.cancel()
        self._target.progress = 0.0
        self._target.update()

    def _finish_trial_target(self, selected: bool, now: float) -> None:
        self._trial_results.append(selected)
        self._selection.cancel()
        self._target.progress = 0.0
        if len(self._trial_results) == 3:
            self._trial_summary.setText(
                f"Probni izbor: {sum(self._trial_results)}/3 dugmeta. "
                f"Izlasci iz dugmeta: {self._trial_departures}; "
                f"prekidi praćenja tokom izbora: {self._trial_losses}."
            )
            self._show_results()
        else:
            self._target.target_index = len(self._trial_results)
            self._trial_ready_at = now + 1.0
            self._set_trial_deadline(self._trial_ready_at)
        self._target.update()

    def _calibrate(self) -> None:
        self.reset_check()
        self._notice.setText(
            "Kalibracija se otvara u Tobii aplikaciji. Nakon nje vratite ovaj prozor "
            "s trake zadataka i ponovite provjeru."
        )
        self.showMinimized()
        self.calibration_requested.emit()

    def set_calibration_notice(self, message: str) -> None:
        self._notice.setText(f"{message} Nakon povratka ponovite provjeru.")
