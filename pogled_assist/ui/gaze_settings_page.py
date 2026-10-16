"""Controls and value rendering for the gaze Settings page."""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QGridLayout, QFrame
from .settings_controls import action_grid, content_layout, styled_label


class GazeSettingsPage(QFrame):
    def __init__(self, owner):
        super().__init__(owner)
        self._owner = owner
        self._controls = owner._controls
        self._build()

    def _build(self):
        page = self
        layout = content_layout(page)
        header = QGridLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setVerticalSpacing(4)
        header.setColumnStretch(0, 1)
        header.addWidget(styled_label("Postavke pogleda", "sectionTitle", page), 0, 0)
        header.addWidget(
            styled_label(
                "Podesite brzinu, stabilnost i povratnu informaciju pogleda.",
                "sectionDescription",
                page,
            ),
            1,
            0,
        )
        self._tracking_notifications_checkbox = self._controls.checkbox(
            "Obavijesti o praćenju pogleda", self._owner._toggle_tracking_notifications, QSize(300, 58)
        )
        header.addWidget(self._tracking_notifications_checkbox, 0, 1, 2, 1)
        layout.addLayout(header)

        row, self._selection_pause_value = self._controls.adjust_row(
            "Pauza prije odabira",
            "Vrijeme čekanja prije nego što se krug napretka počne puniti.",
            self._owner._adjust_selection_pause,
            50,
        )
        layout.addWidget(row)
        row, self._dwell_value = self._controls.adjust_row(
            "Vrijeme zadržavanja pogleda",
            "Vrijeme punjenja kruga napretka nakon početne pauze.",
            self._owner._adjust_dwell_ms,
            50,
        )
        layout.addWidget(row)
        row, self._radius_value = self._controls.adjust_row(
            "Radijus stabilnog pogleda",
            "Koliko mirno pogled mora ostati prije pokretanja odabrane radnje.",
            self._owner._adjust_dwell_radius,
            2,
        )
        layout.addWidget(row)
        row, self._cooldown_value = self._controls.adjust_row(
            "Pauza između radnji",
            "Vrijeme čekanja nakon jedne radnje prije pokretanja sljedeće.",
            self._owner._adjust_click_cooldown,
            50,
        )
        layout.addWidget(row)
        row, self._smoothing_value = self._controls.adjust_row(
            "Uglađivanje pokazivača",
            "Niže vrijednosti su mirnije, a više brže prate pogled.",
            self._owner._adjust_smoothing,
            0.05,
        )
        layout.addWidget(row)

        layout.addWidget(styled_label("PONAŠANJE I KALIBRACIJA", "groupLabel", page))
        layout.addLayout(self._build_gaze_actions())
        layout.addStretch(1)

    def _build_gaze_actions(self) -> QGridLayout:
        self._move_pointer_button = self._controls.toggle_button(
            "Pomjeraj pokazivač pogledom",
            self._owner._toggle_move_pointer,
            QSize(220, 58),
            "fa5s.mouse-pointer",
        )
        self._gaze_bubble_button = self._controls.toggle_button(
            "Prikaži oznaku pogleda", self._owner._toggle_gaze_bubble, QSize(210, 58), "fa5s.bullseye"
        )
        self._interaction_overlay_button = self._controls.toggle_button(
            "Prikaži napredak radnje",
            self._owner._toggle_interaction_overlay,
            QSize(210, 58),
            "fa5s.circle-notch",
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
                self._interaction_overlay_button,
                self._precision_zoom_checkbox,
                self._calibration_button,
                self._gaze_check_button,
            )
        )

    def refresh(self, settings):
        self._selection_pause_value.setText(f"{settings.selection_pause_ms} ms")
        self._dwell_value.setText(f"{settings.dwell_ms} ms")
        self._radius_value.setText(f"{settings.dwell_radius_px} px")
        self._cooldown_value.setText(f"{settings.click_cooldown_ms} ms")
        self._smoothing_value.setText(f"{settings.smoothing:.2f}")
        self._move_pointer_button.setChecked(settings.move_mouse)
        self._gaze_bubble_button.setChecked(settings.show_gaze_bubble)
        self._interaction_overlay_button.setChecked(settings.show_interaction_overlay)
        self._tracking_notifications_checkbox.setChecked(
            settings.show_tracking_notifications
        )
        self._precision_zoom_checkbox.setChecked(settings.use_precision_zoom)
