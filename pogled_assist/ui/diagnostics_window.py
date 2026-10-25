"""Caregiver recording controls; recording belongs to the app, not this window."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..diagnostic_recording import DURATIONS
from ..interaction.eye_tracking_policy import EYE_TRACKING_POLICY_CHOICES
from .gaze_check_history import scroll_content
from .gaze_check_window import STYLESHEET
from .recording_badge import RecordingBadge

REASONS = {
    "manual": "Ručno zaustavljeno",
    "time": "Isteklo trajanje",
    "size": "Limit 32 MiB",
    "shutdown": "Zatvorena aplikacija",
    "writer_error": "Greška zapisivanja",
    "missing_end": "Nedostaje potvrđeni završetak",
}


def text_label(text="", *, title=False):
    label = QLabel(text)
    label.setTextFormat(Qt.PlainText)
    label.setWordWrap(True)
    label.setObjectName("cardTitle" if title else "checkHint")
    return label


class DiagnosticsWindow(QWidget):
    closed = Signal()

    def __init__(
        self, recordings, reports, context, *, logging_enabled, origin="Postavke", parent=None
    ):
        super().__init__(parent)
        self.recordings, self.reports = recordings, reports
        self._context_source, self._logging_enabled = context, logging_enabled
        self._minutes = 2
        self._was_busy = recordings.busy
        self._history_signature = None
        self._selected = None
        self._export_id = None
        self.setWindowTitle("Dijagnostičko snimanje")
        self.setObjectName("gazeCheck")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Window)
        self.setStyleSheet(
            STYLESHEET + "QListWidget { background: #283442; color: #edf2f7; font-size: 16px; }"
            "QListWidget::item { padding: 12px; min-height: 68px; }"
            "QListWidget::item:selected { background: #2e6478; }"
            "QTabBar::tab { min-height: 50px; min-width: 260px; padding: 0 20px; font-size: 18px; }"
            "QTabBar::tab:selected { background: #1d242d; border-bottom: 3px solid #84c5d9; }"
            "QTabWidget::pane { border: none; background: #15191f; }"
            "QTabBar::tab { background: transparent; color: #b8c5d2; border: 0; border-bottom: 1px solid #394959; }"
            "QScrollArea QPushButton { border: 1px solid #71869b; background: #334355; }"
            "QScrollArea QPushButton:checked { background: #2e6478; border-color: #84c5d9; }"
            "QScrollArea QComboBox { border: 1px solid #71869b; background: #15191f; }"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        header = QHBoxLayout()
        copy = QVBoxLayout()
        self._title = text_label("Dijagnostičko snimanje", title=True)
        self._title.setObjectName("checkTitle")
        copy.addWidget(self._title)
        copy.addWidget(text_label("Zabilježite kratak primjer problema s pogledom ili odabirom."))
        header.addLayout(copy, 1)
        self._recording_badge = RecordingBadge(self)
        self._recording_badge.bind_indicator(recordings.indicator)
        header.addWidget(self._recording_badge)
        header.addWidget(self._button("Zatvori · Esc", self.close))
        root.addLayout(header)
        self._tabs = QTabWidget(self)
        self._tabs.setDocumentMode(True)
        self._tabs.tabBar().setExpanding(True)
        root.addWidget(self._tabs, 1)
        self._build_new()
        self._build_history()
        footer = QHBoxLayout()
        footer.setSpacing(16)
        self._status = text_label("Izaberite trajanje, zatim pokrenite snimanje.")
        footer.addWidget(self._status, 1)
        self._return = self._button(f"Vrati se u {origin}", self.close)
        self._primary = self._button("Pokreni snimanje", self._activate)
        self._primary.setObjectName("checkPrimary")
        footer.addWidget(self._return)
        footer.addWidget(self._primary)
        root.addLayout(footer)
        self._tabs.currentChanged.connect(self._tab_changed)
        recordings.changed.connect(self._refresh)
        recordings.exported.connect(self._export_finished)
        reports.changed.connect(self._refresh_reports)
        self._escape = QShortcut(QKeySequence("Esc"), self)
        self._escape.activated.connect(self.close)
        self._refresh_reports()
        self._refresh()
        recordings.load()
        reports.load()

    def _button(self, title, callback):
        button = QPushButton(title, self)
        button.setMinimumHeight(58)
        button.clicked.connect(callback)
        return button

    def _card(self):
        card = QFrame()
        card.setObjectName("checkCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        return card, layout

    def _build_new(self):
        page = QWidget()
        columns = QHBoxLayout(page)
        columns.setSpacing(16)
        card, layout = self._card()
        layout.addWidget(text_label("Snimite problem tokom korištenja", title=True))
        layout.addWidget(
            text_label("Pokrenite snimanje, vratite se u aplikaciju i pokušajte ponoviti problem.")
        )
        layout.addWidget(text_label("Trajanje snimanja"))
        row = QHBoxLayout()
        self._durations = QButtonGroup(self)
        for minutes in DURATIONS:
            button = self._button(
                f"{minutes} min", lambda _checked=False, m=minutes: self._choose_duration(m)
            )
            button.setCheckable(True)
            button.setChecked(minutes == 2)
            self._durations.addButton(button, minutes)
            row.addWidget(button)
        layout.addLayout(row)
        self._state = text_label("Spremno za snimanje", title=True)
        layout.addWidget(self._state)
        self._metrics = text_label()
        layout.addWidget(self._metrics)
        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setMaximumHeight(8)
        layout.addWidget(self._progress)
        self._logging_copy = text_label()
        layout.addWidget(self._logging_copy)
        self._context = text_label()
        layout.addWidget(self._context)
        layout.addStretch(1)
        columns.addWidget(scroll_content(card), 6)
        guide, body = self._card()
        body.addWidget(text_label("Šta se bilježi", title=True))
        body.addWidget(
            text_label(
                "• Položaj pogleda, stanje očiju i prekidi podataka.\n\n"
                "• Vrijeme odabira, poništavanja i geometrija kontrola.\n\n"
                "• Postavke pogleda i tehnički podaci o aplikaciji i prikazu."
            )
        )
        body.addWidget(
            text_label(
                "Nema snimanja ekrana ili zvuka. Poruke, izgovoreni tekst, lična biblioteka i ključevi nisu dio paketa."
            )
        )
        body.addWidget(text_label("Dok ponavljate problem", title=True))
        body.addWidget(
            text_label(
                "Koristite Govor, Tastaturu ili druge kontrole kao i inače. Snimanje ne mijenja režim očiju ni trajanje odabira."
            )
        )
        body.addWidget(
            text_label(
                "Normalni unos ostaje pauziran dok je Provjera pogleda otvorena. Zatvaranje ovog prozora ne zaustavlja snimanje."
            )
        )
        body.addWidget(
            text_label(
                "Detaljne koordinate i raspored kontrola mogu otkriti aktivnost. Pregledajte sadržaj prije dijeljenja."
            )
        )
        body.addStretch(1)
        columns.addWidget(scroll_content(guide), 5)
        self._tabs.addTab(page, "Novo snimanje")

    def _build_history(self):
        page = QWidget()
        columns = QHBoxLayout(page)
        columns.setSpacing(16)
        self._list = QListWidget()
        self._list.setFixedWidth(310)
        self._list.setAccessibleName("Sačuvani dijagnostički snimci")
        self._list.currentItemChanged.connect(self._select_recording)
        left = QVBoxLayout()
        left.addWidget(self._list, 1)
        left.addWidget(
            text_label("Čuva se najnovijih 5, do 200 MiB. Ručno izvezeni ZIP-ovi ostaju sačuvani.")
        )
        self._reload = self._button("Osvježi listu", self.recordings.load)
        left.addWidget(self._reload)
        columns.addLayout(left)
        card, body = self._card()
        self._detail = text_label("Izaberite snimak za pregled")
        self._detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.addWidget(self._detail)
        self._context_toggle = self._button("Postavke i okruženje snimka", self._toggle_context)
        self._context_toggle.setCheckable(True)
        body.addWidget(self._context_toggle)
        self._context_detail = text_label()
        self._context_detail.hide()
        body.addWidget(self._context_detail)
        body.addWidget(text_label("Paket za podršku", title=True))
        body.addWidget(text_label("Dodaj rezultat Provjere pogleda · nije obavezno"))
        self._check = QComboBox()
        self._check.setMinimumHeight(52)
        self._check.setAccessibleName("Opcionalni rezultat Provjere pogleda")
        body.addWidget(self._check)
        body.addWidget(
            text_label(
                "Rezultat se ne dodaje automatski. Možete izabrati i prekinutu provjeru ili rezultat u memoriji."
            )
        )
        body.addWidget(
            text_label(
                "ZIP: snimak.jsonl, kontekst.json, sazetak.txt, manifest.json; po izboru provjera/rezultat.json i provjera/izvjestaj.txt.\n\n"
                "Izvoz pravi lokalni paket. Podaci se ne šalju automatski."
            )
        )
        body.addStretch(1)
        columns.addWidget(scroll_content(card), 1)
        self._tabs.addTab(page, "Sačuvani snimci")

    def _choose_duration(self, minutes):
        self._minutes = minutes
        self._refresh()

    def _tab_changed(self, index):
        if index == 1:
            self.recordings.load()
        self._refresh()

    def _refresh(self):
        service = self.recordings
        state = service.status or {}
        if self._was_busy and not service.busy:
            self._tabs.setCurrentIndex(1)
            self._status.setText(
                "Snimanje je završeno. Provjerite razlog i potpunost podataka uz snimak."
            )
        self._was_busy = service.busy
        seconds = int(state.get("remaining_seconds", self._minutes * 60))
        self._state.setText(
            {
                "starting": "Pripremam snimanje…",
                "recording": "Snimanje u toku",
                "finishing": "Završavam snimak…",
                "error": "Greška zapisivanja",
            }.get(state.get("state"), "Spremno za snimanje")
        )
        self._metrics.setText(
            f"Preostalo vrijeme: {seconds // 60:02}:{seconds % 60:02}\n"
            f"Zauzeti prostor: {state.get('bytes', 0) / 1048576:.2f} / 32 MiB"
        )
        duration = state.get("minutes", self._minutes) * 60 if service.busy else self._minutes * 60
        self._progress.setRange(0, duration)
        self._progress.setValue(max(0, duration - seconds) if service.busy else 0)
        self._logging_copy.setText(
            "Opće zapisivanje: "
            + ("Uključeno" if self._logging_enabled() else "Isključeno")
            + ". Ručno snimanje radi nezavisno i ne mijenja ovu postavku."
        )
        context = self._context_source()
        settings = context.get("gaze_settings", {})
        policy = dict(EYE_TRACKING_POLICY_CHOICES).get(settings.get("eye_tracking_policy"), "—")
        self._context.setText(
            f"Trenutni režim: {policy} · Pauza {settings.get('selection_pause_ms')} ms · "
            f"Zadržavanje {settings.get('dwell_ms')} ms"
            + ("\nSIMULACIJA · Bez Tobii mjerenja." if context.get("simulated") else "")
        )
        for button in self._durations.buttons():
            button.setEnabled(not service.busy)
        signature = (
            service.loading,
            service.history_error,
            [(e["id"], e.get("state"), e.get("complete")) for e in service.entries],
        )
        if signature != self._history_signature:
            self._history_signature = signature
            selected = self._selected
            self._list.blockSignals(True)
            self._list.clear()
            for entry in service.entries:
                reason = REASONS.get(entry.get("reason"), "Nečitljiv snimak")
                item = QListWidgetItem(
                    f"{entry.get('started_at', 'Nepoznat datum')[:19].replace('T', ' ')}\n{reason}",
                    self._list,
                )
                item.setData(Qt.UserRole, entry["id"])
            self._list.blockSignals(False)
            index = next(
                (
                    i
                    for i in range(self._list.count())
                    if self._list.item(i).data(Qt.UserRole) == selected
                ),
                0,
            )
            self._list.setCurrentRow(index)
            if not service.entries:
                self._detail.setText(
                    "Učitavam snimke…"
                    if service.loading
                    else "Čitanje nije uspjelo. Pokušajte osvježiti listu."
                    if service.history_error
                    else "Još nema snimaka. Otvorite „Novo snimanje“."
                )
        self._primary.setText(
            ("Zaustavi snimanje" if service.busy else "Pokreni snimanje")
            if self._tabs.currentIndex() == 0
            else "Izvezi ZIP"
        )
        self._primary.setEnabled(
            (
                (service.busy and state.get("state") in ("starting", "recording"))
                or (not service.busy and not service.loading and not service.history_error)
            )
            if self._tabs.currentIndex() == 0
            else self._selected is not None
            and self._entry().get("state") != "unreadable"
            and not service._exporting
        )
        if service.history_error:
            self._status.setText(
                "Provjera sačuvanih snimaka nije uspjela. Otvorite Sačuvani snimci i osvježite listu."
            )

    def _entry(self):
        return next((e for e in self.recordings.entries if e["id"] == self._selected), {})

    def _select_recording(self, *_args):
        item = self._list.currentItem()
        selected = item.data(Qt.UserRole) if item else None
        if selected != self._selected:
            self._check.setCurrentIndex(0)
        self._selected = selected
        entry = self._entry()
        if entry:
            seconds = entry.get("duration_seconds")
            duration = "Nije dostupno" if seconds is None else f"{seconds:.1f} s"
            self._detail.setText(
                "Snimak nije čitljiv ili format nije podržan."
                if entry.get("state") == "unreadable"
                else f"{entry.get('started_at')}\nID: {entry['id']}\n"
                f"Trajanje: {duration} · Podaci: {entry.get('bytes', 0) / 1048576:.2f} MiB\n"
                f"Razlog: {REASONS.get(entry.get('reason'), entry.get('reason'))}\n"
                f"Potpun snimak: {'Da' if entry.get('complete') else 'Ne'} · "
                f"Završni zapis: {'Da' if entry.get('session_end_present') else 'Ne'}\n"
                f"Izostavljeni događaji: {sum(entry.get('health', {}).get('dropped', {}).values())} · "
                f"Greške: {entry.get('health', {}).get('writer_errors', 0)} · "
                f"Skraćeni podaci: {entry.get('health', {}).get('bounded_snapshots', 0)}"
            )
            self._context_detail.setText(
                json.dumps(entry.get("context", {}), ensure_ascii=False, indent=2)
            )
        self._refresh()

    def _toggle_context(self):
        self._context_detail.setVisible(self._context_toggle.isChecked())

    def _refresh_reports(self):
        previous = self._check.currentData()
        self._check.clear()
        self._check.addItem("Bez rezultata provjere", None)
        for report in sorted(
            self.reports.reports.values(), key=lambda r: r.started_at, reverse=True
        ):
            policy = dict(EYE_TRACKING_POLICY_CHOICES).get(
                report.settings.get("eye_tracking_policy"), "—"
            )
            self._check.addItem(
                f"{report.started_at[:19].replace('T', ' ')} · {policy} · "
                + ("Prekinuto" if report.state == "interrupted" else "Završeno")
                + (" · SIMULACIJA" if report.simulated else ""),
                report.id,
            )
        self._check.setCurrentIndex(max(0, self._check.findData(previous)))

    def _activate(self):
        if self._tabs.currentIndex() == 0:
            if self.recordings.busy:
                self.recordings.stop()
            elif not self.recordings.start(self._minutes, self._context_source()):
                self._status.setText(
                    "Snimanje se nije moglo pokrenuti. Sačekajte potvrđeni završetak prethodnog."
                )
            return
        if not self._selected:
            return
        recording_id = self._selected
        report = self.reports.reports.get(self._check.currentData())
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Izvezi paket za podršku",
            f"pogled-dijagnostika-{recording_id}.zip",
            "ZIP paket (*.zip)",
        )
        if not path:
            return
        if self.recordings.export(recording_id, Path(path), report):
            self._export_id = recording_id
            self._status.setText("Izvozim ZIP… Možete nastaviti koristiti aplikaciju.")
        else:
            self._status.setText("Izvoz se nije mogao pokrenuti. Pokušajte ponovo.")
        self._refresh()

    def _export_finished(self, recording_id, success):
        if recording_id == self._export_id:
            self._status.setText(
                "ZIP je izvezen."
                if success
                else "Izvoz ZIP-a nije uspio. Snimak ostaje dostupan; pokušajte ponovo."
            )
            self._export_id = None
            self._refresh()

    def show_fullscreen_on_primary(self):
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)
