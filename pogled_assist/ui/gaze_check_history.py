"""Caregiver-only report history, context and export controls."""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..interaction.eye_tracking_policy import EYE_TRACKING_POLICY_CHOICES
from ..tracking.gaze_check_report import ENVIRONMENT_KEYS, SETTING_KEYS

STATES = {"completed": "Završeno", "interrupted": "Prekinuto"}
STORAGE = {
    "memory": "Samo u ovoj sesiji · rezultat nije sačuvan na disk. ZIP možete izvesti ručno.",
    "saving": "Čuvam rezultat… Možete nastaviti koristiti aplikaciju.",
    "saved": "Rezultat je sačuvan. Najnovijih 100 izvještaja, do ukupno 10 MiB.",
    "error": "Čuvanje nije uspjelo. Rezultat je u memoriji; pokušajte ponovo ili izvezite ZIP.",
}


def scroll_content(widget: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.NoFrame)
    scroll.setWidget(widget)
    return scroll


class GazeCheckHistory:
    def _build_report_controls(self, card, layout, precision_page) -> None:
        self._report_meta = QLabel(card)
        self._report_meta.setObjectName("checkHint")
        self._report_meta.setTextFormat(Qt.PlainText)
        self._report_meta.setWordWrap(True)
        layout.insertWidget(0, self._report_meta)
        self._result_tabs = QTabWidget(card)
        self._result_tabs.setStyleSheet(
            "QTabBar::tab { min-height: 48px; min-width: 180px; padding: 0 12px; "
            "color: #edf2f7; background: #334355; font-size: 17px; } "
            "QTabBar::tab:selected { background: #1d242d; border-bottom: 3px solid #84c5d9; }"
            "QTabWidget::pane { border: none; }"
        )
        self._result_tabs.addTab(scroll_content(precision_page), "Preciznost")
        trial_page = QWidget()
        trial_layout = QVBoxLayout(trial_page)
        self._trial_attempts = QComboBox(trial_page)
        self._trial_attempts.setAccessibleName("Pokušaj probnog izbora")
        self._trial_attempts.setMinimumHeight(48)
        self._trial_attempts.currentIndexChanged.connect(self._render_trial_attempt)
        trial_layout.addWidget(self._trial_attempts)
        self._trial_detail = QLabel(trial_page)
        self._trial_detail.setWordWrap(True)
        self._trial_detail.setTextFormat(Qt.RichText)
        self._trial_detail.setAlignment(Qt.AlignTop)
        trial_layout.addWidget(scroll_content(self._trial_detail), 1)
        self._result_tabs.addTab(trial_page, "Probni izbor")
        self._context_detail = QLabel()
        self._context_detail.setWordWrap(True)
        self._context_detail.setTextFormat(Qt.PlainText)
        self._context_detail.setAlignment(Qt.AlignTop)
        self._result_tabs.addTab(scroll_content(self._context_detail), "Postavke i uređaj")
        layout.addWidget(self._result_tabs, 1)
        footer = QHBoxLayout()
        self._storage_label = QLabel(card)
        self._storage_label.setObjectName("checkHint")
        self._storage_label.setWordWrap(True)
        footer.addWidget(self._storage_label, 1)
        self._retry_save_button = self._button("Pokušaj ponovo", self._retry_report)
        self._export_button = self._button("Izvezi ZIP", self._export_report)
        footer.addWidget(self._retry_save_button)
        footer.addWidget(self._export_button)
        layout.addLayout(footer)
        self._export_status = QLabel(card)
        self._export_status.setWordWrap(True)
        self._export_status.setObjectName("checkHint")
        self._export_status.hide()
        layout.addWidget(self._export_status)

    def _build_history_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        columns = QHBoxLayout()
        self._history_list = QListWidget(page)
        self._history_list.setAccessibleName("Sačuvani rezultati Provjere pogleda")
        self._history_list.setStyleSheet(
            "QListWidget { background: #283442; color: #edf2f7; font-size: 17px; }"
            "QListWidget::item { padding: 14px; min-height: 64px; }"
            "QListWidget::item:selected { background: #2e6478; }"
        )
        self._history_list.currentItemChanged.connect(self._history_selected)
        columns.addWidget(self._history_list, 1)
        self._history_preview = QLabel(page)
        self._history_preview.setTextFormat(Qt.PlainText)
        self._history_preview.setWordWrap(True)
        self._history_preview.setAlignment(Qt.AlignTop)
        columns.addWidget(scroll_content(self._history_preview), 1)
        layout.addLayout(columns, 1)
        self._history_status = QLabel(page)
        self._history_status.setWordWrap(True)
        layout.addWidget(self._history_status)
        layout.addWidget(
            QLabel(
                "Na disku: najnovijih 100 izvještaja, do 10 MiB. "
                "Ručno izvezeni ZIP-ovi se ne brišu. Stavke u memoriji traju do zatvaranja aplikacije.",
                page,
            )
        )
        self._history_page = page
        self._pages.addWidget(page)

    def _open_history(self) -> None:
        self._finalize_attempt("Otvorena lista rezultata")
        self._target.hide()
        self._phase = "history"
        self._diagnostics_button.setEnabled(True)
        self._title_label.setText("Sačuvani rezultati")
        self._policy_label.setText("Rezultati ovog uređaja · najnoviji su prvi")
        self._simulation_label.hide()
        self._history_button.hide()
        self._step.hide()
        self._pages.setCurrentWidget(self._history_page)
        self._step.setText("Sačuvani rezultati")
        self._primary_button.setText("Otvori rezultat")
        self._primary_button.show()
        self._repeat_button.setText("Nazad na provjeru")
        self._repeat_button.show()
        self._device_group.hide()
        self._flow_title.hide()
        self._calibration_button.hide()
        self._free_button.hide()
        self._reports.load()
        self._refresh_history()

    def _refresh_history(self) -> None:
        item = self._history_list.currentItem()
        previous = item.data(Qt.UserRole) if item else None
        self._history_list.blockSignals(True)
        self._history_list.clear()
        for report in sorted(
            self._reports.reports.values(),
            key=lambda r: datetime.fromisoformat(r.started_at),
            reverse=True,
        ):
            policy = dict(EYE_TRACKING_POLICY_CHOICES).get(
                report.settings.get("eye_tracking_policy"), "—"
            )
            trial = f" · proba: {STATES[report.trials[-1].state]}" if report.trials else ""
            storage = "disk" if self._reports.states.get(report.id) == "saved" else "memorija"
            text = f"{report.started_at[:19].replace('T', ' ')} · {STATES[report.state]}{trial}\n{policy} · {storage}"
            if report.simulated:
                text += " · SIMULACIJA"
            entry = QListWidgetItem(text, self._history_list)
            entry.setData(Qt.UserRole, report.id)
        for unreadable in self._reports.unreadable:
            entry = QListWidgetItem(
                "Rezultat nije čitljiv ili format nije podržan", self._history_list
            )
            entry.setToolTip(unreadable.error)
        self._history_list.blockSignals(False)
        row = next(
            (
                i
                for i in range(self._history_list.count())
                if self._history_list.item(i).data(Qt.UserRole) == previous
            ),
            0,
        )
        self._history_list.setCurrentRow(row)
        self._history_selected()
        text = "Učitavam sačuvane rezultate…" if self._reports.loading else ""
        if self._reports.history_error:
            text = "Lista s diska nije učitana. Zatvorite i ponovo otvorite listu za novi pokušaj."
        elif not self._reports.loading and not self._history_list.count():
            text = "Još nema rezultata. Pokrenite provjeru preciznosti."
        self._history_status.setText(text)

    def _history_selected(self, *_args) -> None:
        item = self._history_list.currentItem()
        key = item.data(Qt.UserRole) if item else None
        report = self._reports.reports.get(key)
        self._primary_button.setEnabled(report is not None)
        text = "Izaberite čitljiv rezultat za pregled i izvoz."
        if report is not None:
            policy = dict(EYE_TRACKING_POLICY_CHOICES).get(
                report.settings.get("eye_tracking_policy"), "—"
            )
            measured = sum(row.state != "unmeasured" for row in report.precision)
            trial = STATES[report.trials[-1].state] if report.trials else "Nije pokrenuto"
            text = (
                f"{STATES[report.state]} · {report.started_at}\n\nRežim: {policy}\n"
                f"Preciznost: {measured} od {len(report.precision)} meta završeno\n"
                f"Probni izbor: {len(report.trials)} pokušaja · {trial}\n"
                f"Simulacija: {'Da' if report.simulated else 'Ne'}\n"
                f"ID: {report.id}\n\nOtvorite rezultat za mjerenja, korištene postavke i izvoz ZIP-a."
            )
        self._history_preview.setText(text)

    def _open_selected_report(self) -> None:
        item = self._history_list.currentItem()
        report = self._reports.reports.get(item.data(Qt.UserRole)) if item else None
        if report is not None:
            self._view_report = report
            self._archived = True
            self._render_report()

    def _reports_changed(self) -> None:
        if self._view_report is not None:
            self._render_storage()
        if self._phase == "history":
            self._refresh_history()

    def _render_storage(self) -> None:
        report = self._view_report
        state = self._reports.states.get(report.id, "memory")
        self._storage_label.setText(STORAGE[state])
        self._retry_save_button.setVisible(state == "error" and self._settings.logging_enabled)

    def _retry_report(self) -> None:
        if self._view_report is not None and self._settings.logging_enabled:
            self._reports.retry(self._view_report.id)

    def _render_report_context(self) -> None:
        report = self._view_report
        simulation = " · SIMULACIJA" if report.simulated else ""
        self._report_meta.setText(
            f"{STATES[report.state]}{simulation} · {report.started_at[:19].replace('T', ' ')} · "
            f"{report.duration_seconds:.1f} s · ID: {report.id}"
            + (f"\n{report.reason}" if report.reason else "")
        )
        labels = {
            "eye_tracking_policy": "Režim praćenja očiju",
            "eye_tracking_hold_ms": "Čuvanje pri gubitku oka (ms)",
            "selection_pause_ms": "Pauza prije odabira (ms)",
            "dwell_ms": "Vrijeme zadržavanja pogleda (ms)",
            "edge_hold_ms": "Čuvanje uz rub (ms)",
            "click_cooldown_ms": "Pauza između radnji (ms)",
            "show_interaction_overlay": "Prikaz napretka",
            "app_version": "Verzija aplikacije",
            "build_revision": "Revizija",
            "build_dirty": "Lokalne izmjene izvora",
            "backend": "Backend",
            "sdk_version": "SDK",
            "model": "Uređaj",
            "firmware_version": "Firmware",
            "platform": "Sistem",
            "logical_screen": "Ekran (x, y, širina, visina u logičkim px)",
            "device_pixel_ratio": "Omjer fizičkih i logičkih px",
            "logical_dpi": "Logički DPI",
        }
        lines = ["Postavke korištene tokom mjerenja · pregled ne mijenja postavke aplikacije.", ""]
        for mapping, keys in (
            (report.settings, SETTING_KEYS),
            (report.environment, ENVIRONMENT_KEYS),
        ):
            for key in keys:
                value = mapping.get(key)
                if key == "eye_tracking_policy":
                    value = dict(EYE_TRACKING_POLICY_CHOICES).get(value, value)
                elif type(value) is bool:
                    value = "Da" if value else "Ne"
                lines.append(f"{labels[key]}: {value if value is not None else 'Nije dostupno'}")
            lines.append("")
        self._context_detail.setText("\n".join(lines))
        self._trial_attempts.blockSignals(True)
        self._trial_attempts.clear()
        for index, trial in enumerate(report.trials, 1):
            self._trial_attempts.addItem(
                f"Pokušaj {index} · {STATES[trial.state]} · {trial.started_at[:19].replace('T', ' ')}"
            )
        self._trial_attempts.setCurrentIndex(len(report.trials) - 1)
        self._trial_attempts.setVisible(bool(report.trials))
        self._trial_attempts.blockSignals(False)
        self._render_trial_attempt()
        self._render_storage()

    def _render_trial_attempt(self, *_args) -> None:
        report = self._view_report
        trials = []
        selected = self._trial_attempts.currentIndex()
        for index, trial in enumerate(report.trials, 1):
            if index - 1 != selected:
                continue
            trials.append(
                f"<p><b>Pokušaj {index} · {STATES[trial.state]}</b> · {escape(trial.started_at)} · {trial.duration_seconds:.1f} s<br>{escape(trial.reason or '')}</p>"
            )
            trials.append(
                '<table width="100%" cellspacing="8"><tr><th>Grupa / px</th><th>Rezultat</th><th>Podaci</th><th>Pogrešni / poništeni / izlasci</th></tr>'
            )
            for row in trial.rows:
                status = (
                    "Nije izmjereno"
                    if row.state == "unmeasured"
                    else (
                        "Odabrano"
                        if row.selected
                        else "Premalo podataka"
                        if row.state == "insufficient"
                        else "Nije odabrano na vrijeme"
                    )
                )
                coverage = f"{row.coverage:.0%}" if row.coverage is not None else "—"
                trials.append(
                    f"<tr><td>{row.index + 1} · {row.size_logical_px[0]} &times; {row.size_logical_px[1]}</td><td>{status}</td><td>{coverage}</td><td>{row.wrong_selections} / {row.cancelled_selections} / {row.departures}</td></tr>"
                )
            trials.append("</table>")
        self._trial_detail.setText(
            "".join(trials)
            or "Probni izbor još nije pokrenut. Preciznost je već dostupna za čuvanje i izvoz."
        )

    def _export_report(self) -> None:
        report = self._view_report
        if report is None:
            return
        filename = f"pogled-provjera-{report.started_at[:10]}-{report.id}.zip"
        path, _filter = QFileDialog.getSaveFileName(
            self, "Izvezi rezultat Provjere pogleda", filename, "ZIP izvještaj (*.zip)"
        )
        if not path:
            return
        destination = Path(path)
        self._export_status.show()
        self._export_status.setText("Izvozim ZIP s JSON podacima i TXT izvještajem…")
        self._export_token = self._reports.export(report, destination)

    def _export_finished(self, token: str, success: bool) -> None:
        if token != self._export_token:
            return
        self._export_status.show()
        self._export_status.setText(
            "ZIP je izvezen. Sadrži rezultat.json i izvjestaj.txt."
            if success
            else "Izvoz nije uspio. Rezultat je zadržan; izaberite Izvezi ZIP za novi pokušaj."
        )
