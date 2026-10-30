"""Live per-eye tracking availability, interruptions and left/right gaze agreement."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from ..tracking.gaze_check import EYE_LOW_FRACTION, HISTORY_SECONDS, EyeTrackingResult
from .gaze_check_text import eye_agreement_text, eye_interruptions_text, eye_tracking_advice
from .gaze_check_views import COLORS

EYE_ROWS = (("left", "Lijevo oko"), ("right", "Desno oko"), ("both", "Oba oka"))
# A short first window would show a blink as a large share of the time.
SETTLED_SECONDS = 3.0


def _label(text: str, parent: QWidget, name: str = "") -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


class EyeTrackingPanel(QFrame):
    """Shows a rolling result in the position card; EyeTrackingRun owns the measurement."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("checkEyes")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(4)
        title = f"Praćenje po oku · zadnjih {HISTORY_SECONDS:.0f} s"
        self.title_label = _label(title, self, "checkHint")
        self.title_label.setToolTip(
            "Procenat je dio vremena u kojem uređaj javlja da vidi oko, a ne Tobii ocjena "
            "pouzdanosti. Prekid je svaki gubitak pogleda, i treptaj."
        )
        layout.addWidget(self.title_label)
        rows = QGridLayout()
        rows.setHorizontalSpacing(12)
        rows.setVerticalSpacing(2)
        self.eye_labels: dict[str, QLabel] = {}
        self.eye_bars: dict[str, QProgressBar] = {}
        for row, (key, name) in enumerate(EYE_ROWS):
            label = _label(name, self)
            label.setMinimumWidth(150)
            bar = QProgressBar(self)
            bar.setRange(0, 1000)
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            bar.setAccessibleName(f"{name}: dio vremena s praćenjem")
            rows.addWidget(label, row, 0)
            rows.addWidget(bar, row, 1)
            self.eye_labels[key] = label
            self.eye_bars[key] = bar
        rows.setColumnStretch(1, 1)
        layout.addLayout(rows)
        self.interruptions_label = _label("", self)
        layout.addWidget(self.interruptions_label)
        self.agreement_label = _label("", self, "checkHint")
        layout.addWidget(self.agreement_label)
        self.advice_label = _label("", self)
        layout.addWidget(self.advice_label)

    def show_result(self, result: EyeTrackingResult) -> None:
        settled = result.observed_seconds >= SETTLED_SECONDS
        for key, name in EYE_ROWS:
            fraction = getattr(result, key)
            state = fraction >= EYE_LOW_FRACTION if settled else None
            label = self.eye_labels[key]
            label.setText(f"{name} · {fraction:.0%}")
            label.setStyleSheet(f"color: {COLORS[state]}; font-size: 16px;")
            self.eye_bars[key].setValue(round(1000 * fraction))
        self.interruptions_label.setText(eye_interruptions_text(result))
        self.interruptions_label.setStyleSheet("font-size: 16px;")
        self.agreement_label.setText(eye_agreement_text(result))
        advice, state = eye_tracking_advice(result) if settled else ("", None)
        # Healthy tracking needs no advice; the position guidance already says what to do.
        self.advice_label.setVisible(bool(advice) and state is False)
        self.advice_label.setText(advice)
        self.advice_label.setStyleSheet(f"color: {COLORS[state]}; font-size: 16px;")
