from __future__ import annotations

import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest
from _hotbar_fixtures import hotbar_gaze as hotbar_gaze
from PySide6.QtCore import QPoint, QRect


@pytest.mark.e2e
def test_tracking_notice_uses_provider_signals_without_changing_eye_safety(
    hotbar_gaze, qtbot, monkeypatch
):

    from pogled_assist.tracking.status import TrackingState, TrackingStatus
    from pogled_assist.ui import tracking_feedback

    hotbar, controller, feed, _actions, _progress = hotbar_gaze
    clock = [20.0]
    monkeypatch.setattr(tracking_feedback, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    feedback = hotbar._tracking_feedback
    feedback._timer.stop()
    hotbar._open_speech()
    window = hotbar._speech_window
    window.showNormal()
    window.setGeometry(*controller._logical_screen_rect)
    qtbot.wait(1)
    hotbar._gaze.tracking_status_changed.emit(TrackingStatus(TrackingState.CONNECTED))
    hotbar._gaze.eye_status_changed.emit(True, True)
    hotbar._gaze.gaze_updated.emit(0.5, 0.5, 0)
    assert feedback.notice is None
    window._input.setText("Synthetic test message")
    original_message = window._input.text()
    window._open_clear_dialog()
    qtbot.wait(1)
    target = window._dialogs.confirm_button
    point = target.mapToGlobal(target.rect().center())
    feed(point, 0)
    feed(point, 700)
    assert target.property("gazeTarget")
    hotbar._gaze.eye_status_changed.emit(True, False)
    assert not controller._both_eyes_open
    assert not target.property("gazeTarget")
    assert feedback.notice is None
    clock[0] += 0.81
    feedback.refresh()
    qtbot.waitUntil(lambda: window._dialogs.confirm_notice.progress == 1)
    assert feedback.notice.title.startswith("Desno oko")
    assert window._dialogs.confirm_notice.isVisible()
    hotbar._gaze.eye_status_changed.emit(True, True)
    assert feedback.notice.title == "Čekam podatke o pogledu"
    hotbar._gaze.gaze_updated.emit(0.5, 0.5, 0)
    assert feedback.notice.title == "Praćenje se vraća"
    clock[0] += 0.51
    hotbar._gaze.gaze_updated.emit(0.5, 0.5, 0)
    assert feedback.notice.title == "Možete nastaviti"
    clock[0] += 2.01
    hotbar._gaze.gaze_updated.emit(0.5, 0.5, 0)
    assert feedback.notice is None
    hotbar._gaze.eye_status_changed.emit(False, True)
    clock[0] += 0.81
    feedback.refresh()
    assert feedback.notice.title.startswith("Lijevo oko")
    hotbar._update_gaze_settings(replace(controller.settings, show_tracking_notifications=False))
    assert feedback.notice is None
    assert window._dialogs.confirm_notice.isHidden()
    feed(point, 2500)
    feed(point, 5000)
    assert window._input.text() == original_message
    assert not controller._both_eyes_open

    hotbar._update_gaze_settings(replace(controller.settings, show_tracking_notifications=True))
    assert feedback.notice is None
    clock[0] += 0.81
    feedback.refresh()
    assert feedback.notice.title.startswith("Lijevo oko")


@pytest.mark.e2e
@pytest.mark.parametrize("context", ["sleep", "hidden", "minimized", "settings", "check"])
def test_intentional_contexts_suppress_tracking_notices(hotbar_gaze, qtbot, monkeypatch, context):

    from pogled_assist.tracking.status import TrackingState, TrackingStatus
    from pogled_assist.ui import settings_window, tracking_feedback

    monkeypatch.setattr(settings_window, "is_windows_startup_enabled", lambda: False)
    clock = [20.0]
    monkeypatch.setattr(tracking_feedback, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    hotbar = hotbar_gaze[0]
    hotbar._open_speech()
    window = hotbar._speech_window
    feedback = hotbar._tracking_feedback
    feedback._timer.stop()
    hotbar._gaze.tracking_status_changed.emit(TrackingStatus(TrackingState.CONNECTED))
    hotbar._gaze.eye_status_changed.emit(False, True)
    clock[0] += 1
    feedback.refresh()
    assert feedback.notice is not None
    if context == "sleep":
        window._start_sleep()
    elif context == "hidden":
        window.hide()
    elif context == "minimized":
        window.showMinimized()
    else:
        hotbar._open_settings()
        if context == "check":
            hotbar._open_gaze_check()
    feedback.refresh()
    assert feedback.notice is None
    clock[0] += 10
    feedback.refresh()
    assert feedback.notice is None


@pytest.mark.e2e
def test_hotbar_status_uses_real_simulator_state_and_ignores_diagnostic_text(hotbar_gaze):
    hotbar, _controller, _feed, _actions, _progress = hotbar_gaze
    hotbar._gaze.start()
    status = hotbar._tracking_status
    assert status._title.text() == "Simulacija mišem"
    assert status._detail.text() == "Upravljanje mišem"
    hotbar._gaze.status_changed.emit("Praćenje simulacijom miša je aktivno.")
    hotbar._gaze.tracker_changed.emit("retrying")
    hotbar._set_status("Otvoren je meni brzih radnji.")
    assert status._title.text() == "Simulacija mišem"
    hotbar._gaze.stop()
    assert status._title.text() == "Praćenje zaustavljeno"


@pytest.mark.e2e
def test_hotbar_status_stays_available_when_icon_fonts_cannot_load(hotbar_gaze, monkeypatch):
    from pogled_assist.tracking.status import TrackingState, TrackingStatus
    from pogled_assist.ui import tracking_status

    def unavailable_font(*_args, **_kwargs):
        raise OSError("Synthetic font-loading failure")

    hotbar, _controller, _feed, _actions, _progress = hotbar_gaze
    monkeypatch.setattr(tracking_status.qta, "icon", unavailable_font)
    status = hotbar._tracking_status
    status.set_tracking_status(TrackingStatus(TrackingState.SIMULATING))
    assert status._title.text() == "Simulacija mišem"
    assert status._icon.text() == "↖"
    assert status._icon.isVisible()


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("eyes", "detail"),
    [
        ((False, True), "Lijevo —    Desno ✓"),
        ((True, False), "Lijevo ✓    Desno —"),
        ((False, False), "Lijevo —    Desno —"),
    ],
)
def test_hotbar_status_requires_fresh_gaze_and_updates_on_eye_loss(
    hotbar_gaze, qtbot, eyes, detail
):
    from pogled_assist.tracking.status import TrackingState, TrackingStatus

    hotbar, controller, _feed, _actions, _progress = hotbar_gaze
    status = hotbar._tracking_status
    hotbar._gaze.tracking_status_changed.emit(
        TrackingStatus(TrackingState.CONNECTED, "Fake tracker")
    )
    assert status._title.text() == "Čekam podatke"
    hotbar._gaze.eye_status_changed.emit(True, True)
    assert status._title.text() == "Čekam podatke"
    hotbar._gaze.gaze_updated.emit(0.5, 0.5, 0)
    assert status._title.text() == "Praćenje spremno"
    hotbar._gaze.eye_status_changed.emit(*eyes)
    assert status._title.text() == "Praćenje pauzirano"
    assert status._detail.text() == detail
    assert status._detail.isVisible()
    assert "nema validnog podatka" in status.accessibleName()
    assert controller._both_eyes_open is False
    hotbar._gaze.gaze_updated.emit(0.5, 0.5, 1)
    assert status._title.text() == "Praćenje pauzirano"
    hotbar._gaze.eye_status_changed.emit(True, True)
    assert status._title.text() == "Čekam podatke"
    hotbar._gaze.gaze_updated.emit(0.5, 0.5, 2)
    assert status._title.text() == "Praćenje spremno"
    # The display watchdog must also cover loss of gaze while eye data stays valid.
    status._last_gaze_at -= 0.6
    qtbot.waitUntil(lambda: status._title.text() == "Čekam podatke")
    assert status._detail.text() == "Podaci o pogledu kasne"
    hotbar._gaze.gaze_updated.emit(0.5, 0.5, 3)
    assert status._title.text() == "Praćenje spremno"


@pytest.mark.e2e
def test_tracking_status_distinguishes_no_samples_from_live_invalid_eyes(qtbot, monkeypatch):
    from pogled_assist.tracking import gaze_provider
    from pogled_assist.ui.tracking_status import TrackingStatusWidget

    callbacks = []

    class FakeBackend:
        label = "Synthetic tracker"

        def __init__(self, gaze, eyes):
            callbacks.append((gaze, eyes))

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setitem(
        sys.modules, "tobii_research", SimpleNamespace(find_all_eyetrackers=lambda: [])
    )
    monkeypatch.setattr(gaze_provider, "TobiiStreamEngineBackend", FakeBackend)
    provider = gaze_provider.TobiiGazeProvider()
    status = TrackingStatusWidget()
    qtbot.addWidget(status)
    status.show()
    provider.tracking_status_changed.connect(status.set_tracking_status)
    provider.eye_status_changed.connect(status.set_eye_status)
    provider.gaze_updated.connect(status.handle_gaze)
    try:
        for _connection in range(2):
            provider.start()
            qtbot.waitUntil(lambda: provider._running)
            assert status._detail.text() == "Čekam stanje očiju"
            callbacks[-1][1](False, False, 1)
            assert status._title.text() == "Praćenje pauzirano"
            assert status._detail.text() == "Lijevo —    Desno —"
            callbacks[-1][1](True, True, 2)
            assert status._title.text() == "Čekam podatke"
            callbacks[-1][0](0.5, 0.5, 2)
            provider._emit_latest_gaze_sample()
            assert status._title.text() == "Praćenje spremno"
            assert "Synthetic tracker" in status.toolTip()
            provider.stop()
            assert status._title.text() == "Praćenje zaustavljeno"
            qtbot.waitUntil(lambda: provider._connection_session is None)
    finally:
        provider.stop()
        qtbot.waitUntil(lambda: provider._connection_session is None)


@pytest.mark.e2e
def test_hotbar_status_waiting_and_retry_survive_eye_and_text_notifications(hotbar_gaze):
    from pogled_assist.tracking.status import TrackingState, TrackingStatus

    hotbar, _controller, _feed, _actions, _progress = hotbar_gaze
    status = hotbar._tracking_status
    hotbar._gaze.tracking_status_changed.emit(TrackingStatus(TrackingState.WAITING))
    hotbar._gaze.eye_status_changed.emit(False, False)
    assert status._title.text() == "Čekam podatke"
    assert status._detail.text() == "Podaci o očima kasne"
    hotbar._gaze.tracking_status_changed.emit(TrackingStatus(TrackingState.RETRYING))
    hotbar._gaze.eye_status_changed.emit(True, True)
    hotbar._gaze.gaze_updated.emit(0.5, 0.5, 0)
    hotbar._gaze.status_changed.emit("Praćenje je aktivno putem uređaja.")
    assert status._title.text() == "Uređaj nije povezan"
    hotbar._gaze.tracking_status_changed.emit(TrackingStatus(TrackingState.CONNECTED))
    assert status._title.text() == "Čekam podatke"
    hotbar._gaze.gaze_updated.emit(0.5, 0.5, 1)
    assert status._title.text() == "Praćenje spremno"


@pytest.mark.e2e
def test_hide_removes_entire_status_and_show_restores_latest_state(hotbar_gaze):
    from pogled_assist.tracking.status import TrackingState, TrackingStatus

    hotbar, _controller, _feed, _actions, _progress = hotbar_gaze
    status = hotbar._tracking_status
    assert status.isVisible()
    assert not status.isWindow()
    assert hotbar.action_at_global_point(status.mapToGlobal(status.rect().center())) is None
    hotbar._hide_hotbar()
    assert not status.isVisible()
    assert not status._title.isVisible()
    assert not status._detail.isVisible()
    assert hotbar._restore_button.isVisible()
    hotbar._gaze.tracking_status_changed.emit(TrackingStatus(TrackingState.RETRYING))
    assert not status.isVisible()
    assert status._title.text() == "Uređaj nije povezan"
    hotbar._show_hotbar()
    assert status.isVisible()
    assert status._title.text() == "Uređaj nije povezan"
    assert not hotbar._restore_button.isVisible()


@pytest.mark.e2e
@pytest.mark.parametrize(
    "state",
    [
        "connecting",
        "connected",
        "waiting",
        "retrying",
        "stopped",
        "simulating",
        "unavailable",
        "ready",
        "gaze-waiting",
    ],
)
def test_hotbar_status_and_all_actions_fit_target_display(hotbar_gaze, state):
    from pogled_assist.tracking.status import TrackingState, TrackingStatus

    hotbar, _controller, _feed, _actions, _progress = hotbar_gaze
    status = hotbar._tracking_status
    lifecycle = "connected" if state in ("ready", "gaze-waiting") else state
    status.set_tracking_status(TrackingStatus(TrackingState(lifecycle)))
    status.set_eye_status(state in ("ready", "gaze-waiting"), True)
    if state == "ready":
        status.handle_gaze(0.5, 0.5, 0)
    hotbar.layout().activate()
    assert hotbar.BAR_HEIGHT == 76
    assert hotbar.rect().contains(status.geometry())
    for button in hotbar._buttons.values():
        if button is hotbar._restore_button:
            continue
        rect = QRect(button.mapTo(hotbar, QPoint()), button.size())
        assert hotbar.rect().contains(rect)
        assert not rect.intersects(status.geometry())
        assert button.height() == 58
    for label in (status._title, status._detail):
        assert status.rect().contains(label.geometry()), (state, label.geometry())
        assert (
            label.fontMetrics().horizontalAdvance(label.text()) <= label.contentsRect().width()
        ), (
            state,
            label.text(),
            label.geometry(),
            label.fontMetrics().horizontalAdvance(label.text()),
        )
