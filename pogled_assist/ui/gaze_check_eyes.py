"""Per-eye tracking availability and left/right gaze agreement in the gaze check."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from ..tracking.gaze_check import EYE_LOW_FRACTION, EYE_RUN_SECONDS, EyeTrackingResult
from .gaze_check_text import eye_agreement_text, eye_tracking_advice, eye_tracking_status
from .gaze_check_views import COLORS

EYE_ROWS = (("left", "Lijevo oko"), ("right", "Desno oko"), ("both", "Oba oka istovremeno"))


def _label(text: str, parent: QWidget, name: str = "") -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


class EyeTrackingPanel(QFrame):
    """Shows one run; the measurement itself is owned by EyeTrackingRun."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("checkCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(_label(f"Praćenje po oku · {EYE_RUN_SECONDS:.0f} s", self, "cardTitle"))
        self.status_label = _label("", self)
        layout.addWidget(self.status_label)
        rows = QGridLayout()
        rows.setHorizontalSpacing(16)
        rows.setVerticalSpacing(10)
        self.eye_labels: dict[str, QLabel] = {}
        self.eye_bars: dict[str, QProgressBar] = {}
        for row, (key, name) in enumerate(EYE_ROWS):
            label = _label(name, self)
            label.setMinimumWidth(260)
            bar = QProgressBar(self)
            bar.setRange(0, 1000)
            bar.setTextVisible(False)
            bar.setFixedHeight(12)
            bar.setAccessibleName(f"{name}: dio vremena s praćenjem")
            rows.addWidget(label, row, 0)
            rows.addWidget(bar, row, 1)
            self.eye_labels[key] = label
            self.eye_bars[key] = bar
        rows.setColumnStretch(1, 1)
        layout.addLayout(rows)
        self.agreement_label = _label("", self)
        layout.addWidget(self.agreement_label)
        self.advice_label = _label("", self)
        layout.addWidget(self.advice_label)
        layout.addStretch(1)
        layout.addWidget(
            _label(
                "Procenat je dio vremena u kojem uređaj javlja da vidi oko, a ne Tobii ocjena "
                "pouzdanosti. Vrijednosti pokazuju gubitke praćenja i razilaženje očiju, "
                "ali ne i njihov uzrok.",
                self,
                "checkHint",
            )
        )

    def show_result(self, result: EyeTrackingResult, remaining: int | None) -> None:
        self.status_label.setText(eye_tracking_status(result, remaining))
        for key, name in EYE_ROWS:
            fraction = getattr(result, key)
            state = None if remaining is not None else fraction >= EYE_LOW_FRACTION
            label = self.eye_labels[key]
            label.setText(f"{name} · {fraction:.0%}")
            label.setStyleSheet(f"color: {COLORS[state]}; font-size: 19px;")
            self.eye_bars[key].setValue(round(1000 * fraction))
        self.agreement_label.setText(eye_agreement_text(result))
        if remaining is not None:
            self.advice_label.setText("")
            return
        advice, state = eye_tracking_advice(result)
        self.advice_label.setText(advice)
        self.advice_label.setStyleSheet(f"color: {COLORS[state]};")
