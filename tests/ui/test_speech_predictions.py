from __future__ import annotations

from threading import Thread, get_ident

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


@pytest.mark.parametrize("notification", ["predictions", "status"])
def test_worker_notifications_update_controls_only_on_ui_thread(
    predictions, qtbot, monkeypatch, notification
):
    presenter, service, controls, _state = predictions
    controls.input.setText("ŽE")
    presenter.refresh(can_undo=False)
    owner, revision, _text = service.requests[-1]
    widget = controls.buttons[0] if notification == "predictions" else controls.label
    set_text = widget.setText
    updates = []
    ui_thread = get_ident()

    def record_update(text):
        updates.append((get_ident(), text))
        set_text(text)

    monkeypatch.setattr(widget, "setText", record_update)

    def notify():
        if notification == "predictions":
            service.predictions_ready.emit(owner, revision, ["želim"])
        else:
            service.status_changed.emit("Spremno")

    worker = Thread(target=notify)
    worker.start()
    worker.join(timeout=2)
    assert not worker.is_alive()
    # Joining does not dispatch Qt events: a worker must never touch the controls directly.
    assert updates == []
    qtbot.waitUntil(lambda: bool(updates))

    expected = "ŽELIM" if notification == "predictions" else "Brzi izbor · Spremno"
    assert updates == [(ui_thread, expected)]


def test_queued_worker_prediction_is_rejected_after_another_edit(predictions, qapp, qtbot):
    presenter, service, controls, _state = predictions
    controls.input.setText("ŽE")
    presenter.refresh(can_undo=False)
    owner, revision, _text = service.requests[-1]
    worker = Thread(target=lambda: service.predictions_ready.emit(owner, revision, ["želim"]))
    worker.start()
    worker.join(timeout=2)
    assert not worker.is_alive()

    controls.input.setText("VO")
    presenter.refresh(can_undo=False)
    qapp.processEvents()
    assert not controls.buttons[0].isEnabled()
    assert presenter.candidate(0) is None

    owner, revision, _text = service.requests[-1]
    service.predictions_ready.emit(owner, revision, ["vode"])
    qtbot.waitUntil(controls.buttons[0].isEnabled)
    assert presenter.candidate(0) == "VODE"
