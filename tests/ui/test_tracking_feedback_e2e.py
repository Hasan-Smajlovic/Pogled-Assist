from __future__ import annotations

import pytest
from _speech_fixtures import make_speech_window as make_speech_window
from _ui_fakes import FakeLibraryStore, FakeSpeech
from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QWidget

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("size", [(1280, 720), (1440, 900)])
@pytest.mark.parametrize("context", ["message", "letters", "confirm"])
def test_tracking_notice_preserves_targets_message_and_focus(
    make_speech_window, qtbot, qapp, size, context
):
    from PySide6.QtGui import QFont, QFontMetrics

    from pogled_assist.tracking.feedback import TrackingNotice

    window = make_speech_window(FakeSpeech(), library_store=FakeLibraryStore())
    window.resize(*size)
    window.show()
    window.activateWindow()
    qtbot.waitUntil(lambda: qapp.focusWidget() is window._input)
    window._input.setText("TREBAM VODE")
    window._input.setSelection(0, 6)
    if context == "letters":
        window._open_letter_dialog(0)
    elif context == "confirm":
        window._open_clear_dialog()
    active_window = window if context == "message" else window._dialogs.active
    qtbot.waitUntil(lambda: qapp.activeWindow() is active_window)
    widget = (
        window._message_header.notice
        if context == "message"
        else window._dialogs.tracking_notices[window._dialogs.active]
    )
    buttons = {
        action: QRect(button.geometry())
        for action, button in window._action_buttons.items()
        if button.isVisible()
    }
    original_height = window._input.height()
    original_selection = window._input.selectedText()
    assert original_selection == "TREBAM"
    focus = qapp.focusWidget()
    notice = TrackingNotice(
        "Desno oko se trenutno ne prati", "odabir je zaustavljen", eyes=(True, False)
    )
    window.set_tracking_notice(notice)
    qtbot.waitUntil(lambda: widget.progress == 1.0)
    qtbot.wait(1)
    assert widget.isVisible()
    assert "Desno oko se trenutno ne prati · odabir je zaustavljen" in widget.accessibleName()
    assert widget.focusPolicy() == Qt.NoFocus
    assert widget.testAttribute(Qt.WA_TransparentForMouseEvents)
    assert qapp.focusWidget() is focus
    assert window._input.text() == "TREBAM VODE"
    assert window._input.selectedText() == original_selection
    assert window._input.width() == window._input.parentWidget().width()
    assert window.action_at_global_point(widget.mapToGlobal(widget.rect().center())) is None
    font = QFont("Segoe UI")
    font.setPixelSize(11)
    font.setWeight(QFont.DemiBold)
    assert QFontMetrics(font).horizontalAdvance(notice.text) <= widget.width() - 152
    if context == "message":
        assert window._input.height() == original_height - 20
        assert window._input.height() >= window._input.fontMetrics().height() + 16
    for action, rect in buttons.items():
        assert window._action_buttons[action].geometry() == rect
    window.set_tracking_notice(TrackingNotice("Možete nastaviti", tone="ready", eyes=(True, True)))
    assert widget.notice.tone == "ready"
    window.set_tracking_notice(None)
    qtbot.waitUntil(widget.isHidden)
    qtbot.wait(1)
    assert window._input.height() == original_height
    for action, rect in buttons.items():
        assert window._action_buttons[action].geometry() == rect


def test_tracking_notice_follows_dialog_and_immediate_disable_restores_input(
    make_speech_window, qtbot
):
    from pogled_assist.tracking.feedback import TrackingNotice

    window = make_speech_window(FakeSpeech(), library_store=FakeLibraryStore())
    window.resize(1280, 720)
    window.show()
    qtbot.wait(1)
    height = window._input.height()
    notice = TrackingNotice(
        "Lijevo oko se trenutno ne prati", "odabir je zaustavljen", eyes=(False, True)
    )
    window.set_tracking_notice(notice, immediate=True)
    window._open_letter_dialog(0)
    qtbot.waitUntil(lambda: window._dialogs.letter_notice.progress == 1)
    assert window._message_header.notice.isHidden()
    window._close_dialog()
    qtbot.waitUntil(lambda: window._message_header.notice.progress == 1)
    assert window._dialogs.letter_notice.isHidden()
    window.set_tracking_notice(None, immediate=True)
    qtbot.wait(1)
    assert window._message_header.notice.isHidden()
    assert window._input.height() == height


def test_tracking_reconnect_requires_new_eyes_and_gaze(qtbot, monkeypatch):
    from types import SimpleNamespace

    from pogled_assist.tracking.status import TrackingState, TrackingStatus
    from pogled_assist.ui import tracking_feedback

    clock = [0.0]
    monkeypatch.setattr(tracking_feedback, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    parent = QWidget()
    qtbot.addWidget(parent)
    feedback = tracking_feedback.TrackingFeedback(parent, lambda: True)
    feedback._timer.stop()
    feedback.handle_status(TrackingStatus(TrackingState.CONNECTED))
    feedback.handle_eyes(True, True)
    feedback.handle_gaze(0.5, 0.5, 0)
    feedback.handle_status(TrackingStatus(TrackingState.RETRYING))
    clock[0] = 1
    feedback.refresh()
    assert feedback.notice.title == "Uređaj nije povezan"
    feedback.handle_status(TrackingStatus(TrackingState.CONNECTED))
    feedback.handle_gaze(0.5, 0.5, 0)
    assert feedback.notice.title == "Čekam podatke o pogledu"
    feedback.handle_eyes(True, True)
    assert feedback.notice.title == "Čekam podatke o pogledu"
    feedback.handle_gaze(0.5, 0.5, 0)
    clock[0] += 0.51
    feedback.handle_gaze(0.5, 0.5, 0)
    assert feedback.notice.title == "Možete nastaviti"


def test_tracking_notice_can_reverse_its_exit_and_respect_disabled_animations(qtbot, monkeypatch):
    from types import SimpleNamespace

    from pogled_assist.tracking.feedback import TrackingNotice
    from pogled_assist.ui.tracking_feedback import TrackingNoticeWidget

    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(700, 60)
    widget = TrackingNoticeWidget(parent)
    widget.setGeometry(parent.rect())
    parent.show()
    monkeypatch.setattr(widget, "style", lambda: SimpleNamespace(styleHint=lambda *_args: 1))
    notice = TrackingNotice("Možete nastaviti", tone="ready", eyes=(True, True))
    widget.set_notice(notice, immediate=True)
    widget.set_notice(None)
    widget._animation.setCurrentTime(90)
    assert 0 < widget.progress < 1
    warning = TrackingNotice(
        "Desno oko se trenutno ne prati", "odabir je zaustavljen", eyes=(True, False)
    )
    widget.set_notice(warning)
    qtbot.waitUntil(lambda: widget.progress == 1)
    assert widget.isVisible()
    assert widget.notice == warning
    monkeypatch.setattr(widget, "style", lambda: SimpleNamespace(styleHint=lambda *_args: 0))
    widget.set_notice(None)
    assert widget.isHidden()
    assert widget.progress == 0
    widget.set_notice(notice)
    assert widget.progress == 1
    assert widget.isVisible()
