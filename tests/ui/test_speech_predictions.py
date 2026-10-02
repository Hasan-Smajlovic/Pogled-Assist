from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, QPoint, Signal
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from pogled_assist.ui.speech_predictions import PredictionControls, SpeechPredictions


class FakePredictions(QObject):
    predictions_ready = Signal(object, int, list)
    status_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.requests = []

    def request(self, owner, revision, text):
        self.requests.append((owner, revision, text))


@pytest.fixture
def predictions(qtbot):
    window = QWidget()
    qtbot.addWidget(window)
    layout = QVBoxLayout(window)
    controls = PredictionControls(
        QLineEdit(window), QLabel(window), [QPushButton(window)], QPushButton(window)
    )
    for widget in [controls.input, controls.label, *controls.buttons, controls.undo]:
        layout.addWidget(widget)
    window.show()
    service = FakePredictions()
    state = {"allowed": True, "contexts": 0}

    def changed():
        state["contexts"] += 1

    presenter = SpeechPredictions(controls, service, lambda: state["allowed"], changed)
    yield presenter, service, controls, state


def test_speech_predictions_ignore_old_revisions_and_other_inputs(predictions):
    presenter, service, controls, state = predictions
    controls.input.setText("Ž")
    presenter.refresh(can_undo=False)
    old_owner, old_revision, _text = service.requests[-1]
    controls.input.setText("ŽE")
    presenter.refresh(can_undo=True)
    owner, revision, text = service.requests[-1]

    service.predictions_ready.emit(old_owner, old_revision, ["staro"])
    service.predictions_ready.emit(object(), revision, ["tuđe"])
    assert not controls.buttons[0].isEnabled()
    service.predictions_ready.emit(owner, revision, ["želim"])

    assert text == "ŽE"
    assert presenter.candidate(0) == "ŽELIM"
    assert controls.undo.isEnabled()
    assert state["contexts"] == 2


@pytest.mark.parametrize("change", ["text", "allowed"])
def test_speech_predictions_reject_results_after_input_context_changes(predictions, change):
    presenter, service, controls, state = predictions
    controls.input.setText("ŽE")
    presenter.refresh(can_undo=False)
    owner, revision, _text = service.requests[-1]
    if change == "text":
        controls.input.setText("DRUGO")
    else:
        state["allowed"] = False
    service.predictions_ready.emit(owner, revision, ["želim"])

    assert presenter.candidate(0) is None
    assert not controls.buttons[0].isEnabled()


def test_speech_prediction_replaced_under_gaze_requires_leaving_its_button(predictions):
    presenter, service, controls, _state = predictions
    controls.input.setText("ŽE")
    presenter.refresh(can_undo=False)
    owner, revision, _text = service.requests[-1]
    service.predictions_ready.emit(owner, revision, ["želim"])
    button = controls.buttons[0]
    center = button.mapToGlobal(button.rect().center())
    assert presenter.allows_gaze(center)

    presenter.refresh(can_undo=False)
    owner, revision, _text = service.requests[-1]
    service.predictions_ready.emit(owner, revision, ["žena"])

    assert not presenter.allows_gaze(center)
    assert not presenter.allows_action(button)
    assert presenter.allows_gaze(QPoint(-1000, -1000))
    assert presenter.allows_action(button)
    assert presenter.candidate(0) == "ŽENA"
