"""Controls and value rendering for the gaze Settings page."""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
)

from ..interaction.eye_tracking_policy import (
    BRIEF_INTERRUPTION,
    EYE_TRACKING_POLICY_CHOICES,
    policy_description,
)
from ..settings_limits import EDGE_HOLD_MS_STEP
from .settings_content import SettingsContent
from .settings_controls import action_grid, content_layout, guidance_note, setting_row, styled_label


class GazeSettingsPage(QFrame):
    def __init__(self, owner):
        super().__init__(owner)
        self._owner = owner
        self._controls = owner._controls
        self._build()

    def _build(self):
        page = self
        layout = content_layout(page)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)
        header = QGridLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setVerticalSpacing(4)
        header.setColumnStretch(0, 1)
        header.addWidget(styled_label("Pogled i odabir", "sectionTitle", page), 0, 0)
        header.addWidget(
            styled_label(
                "Podesite odabir pogledom, pokazivač i provjeru praćenja.",
                "sectionDescription",
                page,
            ),
            1,
            0,
        )
        layout.addLayout(header)

        tabs = QHBoxLayout()
        self._tabs = []
        for index, title in enumerate(
            ("Odabir pogledom", "Pokazivač i provjera", "Stabilnost uz rub")
        ):
            button = self._controls.toggle_button(
                title, lambda index=index: self.show_tab(index), QSize(220, 58)
            )
            button.setObjectName("sectionTab")
            tabs.addWidget(button, 1)
            self._tabs.append(button)
        layout.addLayout(tabs)
        self._stack = SettingsContent(self)
        layout.addWidget(self._stack, 1)
        selection_page = QFrame(self)
        selection = QVBoxLayout(selection_page)
        selection.setContentsMargins(0, 0, 0, 0)
        selection.setSpacing(6)
        self._stack.addWidget(selection_page)
        row, grid, self._policy_hint = setting_row(self, "Režim praćenja očiju", " ")
        self._policy_combo = self._controls.choice(
            EYE_TRACKING_POLICY_CHOICES,
            self._owner._select_eye_tracking_policy,
            self._owner._cycle_eye_tracking_policy,
            "Režim praćenja očiju",
        )
        self._policy_combo.setFixedWidth(380)
        grid.addWidget(self._policy_combo, 0, 1, 2, 1)
        selection.addWidget(row)
        self._hold_row, self._hold_value = self._controls.adjust_row(
            "Trajanje kratkog prekida",
            "Čuvanje napretka pri gubitku jednog oka: 50 do 500 ms.",
            self._owner._adjust_eye_tracking_hold,
            50,
        )
        selection.addWidget(self._hold_row)

        row, self._selection_pause_value = self._controls.adjust_row(
            "Pauza prije odabira",
            "Vrijeme čekanja prije nego što se krug napretka počne puniti.",
            self._owner._adjust_selection_pause,
            50,
        )
        selection.addWidget(row)
        row, self._dwell_value = self._controls.adjust_row(
            "Vrijeme zadržavanja pogleda",
            "Vrijeme punjenja kruga napretka nakon početne pauze.",
            self._owner._adjust_dwell_ms,
            50,
        )
        selection.addWidget(row)
        row, self._cooldown_value = self._controls.adjust_row(
            "Pauza između radnji",
            "Vrijeme čekanja nakon jedne radnje prije pokretanja sljedeće.",
            self._owner._adjust_click_cooldown,
            50,
        )
        selection.addWidget(row)
        feedback_group = QFrame(self)
        feedback_group.setObjectName("settingsFeedback")
        feedback_group.setAccessibleName("Obavijesti i prikaz napretka")
        feedback_group.setStyleSheet(
            "QFrame#settingsFeedback { border: 0; border-top: 1px solid #394959; }"
        )
        feedback = QHBoxLayout(feedback_group)
        feedback.setContentsMargins(0, 8, 0, 8)
        feedback.setSpacing(12)
        self._tracking_notifications_checkbox = self._controls.checkbox(
            "Obavijesti o praćenju pogleda",
            self._owner._toggle_tracking_notifications,
            QSize(300, 58),
        )
        self._interaction_overlay_button = self._controls.checkbox(
            "Prikaži napredak radnje",
            self._owner._toggle_interaction_overlay,
            QSize(210, 58),
        )
        feedback.addWidget(self._tracking_notifications_checkbox)
        feedback.addWidget(self._interaction_overlay_button)
        selection.addWidget(feedback_group)
        selection.addWidget(
            guidance_note(
                self,
                "<b>Primjena režima.</b> Režim važi za kontrole aplikacije, uključujući Upravljač. "
                "Pomjeranje pokazivača i direktni klikovi na desktopu zahtijevaju oba oka.",
            )
        )
        selection.addStretch(1)

        pointer_page = QFrame(self)
        pointer = QVBoxLayout(pointer_page)
        pointer.setContentsMargins(0, 0, 0, 0)
        pointer.setSpacing(12)
        self._stack.addWidget(pointer_page)
        row, self._radius_value = self._controls.adjust_row(
            "Radijus stabilnog pogleda",
            "Koliko mirno pogled mora ostati prije pokretanja odabrane radnje.",
            self._owner._adjust_dwell_radius,
            2,
        )
        pointer.addWidget(row)
        row, self._smoothing_value = self._controls.adjust_row(
            "Uglađivanje pokazivača",
            "Niže vrijednosti su mirnije, a više brže prate pogled.",
            self._owner._adjust_smoothing,
            0.05,
        )
        pointer.addWidget(row)

        pointer.addWidget(styled_label("POKAZIVAČ I PROVJERA", "groupLabel", page))
        pointer.addLayout(self._build_gaze_actions())
        pointer.addWidget(
            guidance_note(
                self,
                "<b>Pokazivač i provjera.</b> Pokazivač, Brze radnje i precizno uvećanje "
                "zahtijevaju oba oka u svakom režimu. Provjera pogleda koristi izabrani režim "
                "i ne šalje unos drugim programima.",
            )
        )
        pointer.addStretch(1)

        stability_page = QFrame(self)
        stability = QVBoxLayout(stability_page)
        stability.setContentsMargins(0, 0, 0, 0)
        stability.setSpacing(12)
        self._stack.addWidget(stability_page)
        row, self._edge_hold_value = self._controls.adjust_row(
            "Čuvanje odabira uz rub",
            "Govor, Tastatura i gornja traka. 0 isključuje čuvanje.",
            self._owner._adjust_edge_hold,
            EDGE_HOLD_MS_STEP,
        )
        stability.addWidget(row)
        stability.addWidget(
            guidance_note(
                self,
                "<p><b>Kako djeluje čuvanje uz rub</b></p>"
                "<p><b>Kratak izlazak:</b> napredak se zamrzne. Povratak na isto dugme prije "
                "isteka nastavlja odabir. Izvan dugmeta nema napretka ni potvrde.</p>"
                "<p><b>Prelazak na drugo dugme:</b> ako pogled ostane na susjednom dugmetu, "
                "ono nakon isteka počinje od nule. Duže čuvanje usporava taj prelazak. "
                "Udaljeniji odlazak odmah prekida čuvanje.</p>"
                "<p><b>Raspon:</b> 0 do 300 ms, korak 20 ms; zadano 120 ms. "
                "Prostorna tolerancija ostaje ista.</p>"
                "<p>Ovo ne mijenja režim praćenja očiju niti ispravlja kalibraciju.</p>",
            )
        )
        stability.addStretch(1)
        self.show_tab(0)

    def show_tab(self, index: int) -> None:
        self._owner.cancel_gaze_interaction(require_leave=True)
        self._stack.setCurrentIndex(index)
        for tab_index, button in enumerate(self._tabs):
            button.setChecked(tab_index == index)

    def _build_gaze_actions(self) -> QGridLayout:
        self._move_pointer_button = self._controls.toggle_button(
            "Pomjeraj pokazivač pogledom",
            self._owner._toggle_move_pointer,
            QSize(220, 58),
            "fa5s.mouse-pointer",
        )
        self._gaze_bubble_button = self._controls.toggle_button(
            "Prikaži oznaku pogleda",
            self._owner._toggle_gaze_bubble,
            QSize(210, 58),
            "fa5s.bullseye",
        )
        self._precision_zoom_checkbox = self._controls.checkbox(
            "Koristi precizno uvećanje", self._owner._toggle_precision_zoom, QSize(220, 58)
        )
        self._calibration_button = self._controls.button(
            "Pokreni Tobii kalibraciju",
            self._owner._request_calibration,
            QSize(220, 58),
            "fa5s.crosshairs",
        )
        self._gaze_check_button = self._controls.button(
            "Provjera pogleda", self._owner._request_gaze_check, QSize(220, 58), "fa5s.eye"
        )
        return action_grid(
            (
                self._move_pointer_button,
                self._gaze_bubble_button,
                self._precision_zoom_checkbox,
                self._calibration_button,
                self._gaze_check_button,
            )
        )

    def refresh(self, settings):
        self._policy_combo.blockSignals(True)
        self._policy_combo.setCurrentIndex(
            self._policy_combo.findData(settings.eye_tracking_policy)
        )
        self._policy_combo.blockSignals(False)
        self._policy_hint.setText(
            policy_description(settings.eye_tracking_policy, settings.eye_tracking_hold_ms)
        )
        self._hold_value.setText(f"{settings.eye_tracking_hold_ms} ms")
        self._hold_row.setEnabled(settings.eye_tracking_policy == BRIEF_INTERRUPTION)
        self._edge_hold_value.setText(
            f"{settings.edge_hold_ms} ms" if settings.edge_hold_ms else "Isključeno"
        )
        self._selection_pause_value.setText(f"{settings.selection_pause_ms} ms")
        self._dwell_value.setText(f"{settings.dwell_ms} ms")
        self._radius_value.setText(f"{settings.dwell_radius_px} px")
        self._cooldown_value.setText(f"{settings.click_cooldown_ms} ms")
        self._smoothing_value.setText(f"{settings.smoothing:.2f}")
        self._move_pointer_button.setChecked(settings.move_mouse)
        self._gaze_bubble_button.setChecked(settings.show_gaze_bubble)
        self._interaction_overlay_button.setChecked(settings.show_interaction_overlay)
        self._tracking_notifications_checkbox.setChecked(settings.show_tracking_notifications)
        self._precision_zoom_checkbox.setChecked(settings.use_precision_zoom)
