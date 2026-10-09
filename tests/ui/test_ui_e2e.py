from __future__ import annotations

import pytest
from _speech_fixtures import make_speech_window as make_speech_window
from _ui_fakes import FakeAppBar, FakeControllerInput, FakeLibraryStore, FakeSpeech
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QWidget

from pogled_assist.interaction.mouse_controller import GazeSettings
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.ui.controller_window import CONTROLLER_WINDOW_ACTION_PREFIX, ControllerWindow
from pogled_assist.ui.speech_window import SPEECH_WINDOW_ACTION_PREFIX


@pytest.mark.e2e
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
    window._input.setText("TREBAM VODE")
    window._input.setSelection(0, 6)
    if context == "letters":
        window._open_letter_dialog(0)
    elif context == "confirm":
        window._open_clear_dialog()
    qtbot.wait(1)
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


@pytest.mark.e2e
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


@pytest.mark.e2e
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


@pytest.mark.e2e
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


@pytest.fixture
def gaze_check(qtbot, monkeypatch):
    from types import SimpleNamespace

    from pogled_assist.ui import gaze_check_window as module

    screen = QRect(-100, 20, 1280, 720)
    monkeypatch.setattr(
        module.QGuiApplication, "primaryScreen", lambda: SimpleNamespace(geometry=lambda: screen)
    )
    window = module.GazeCheckWindow(GazeSettings())
    qtbot.addWidget(window)
    window.setGeometry(screen)
    window.show()
    qtbot.wait(1)
    window._timer.stop()
    now = [10.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    return window, now, screen


@pytest.mark.e2e
def test_gaze_check_live_states_and_timeout_are_not_false_successes(gaze_check):
    from pogled_assist.tracking.gaze_check import CheckSnapshot

    window, now, _screen = gaze_check
    window.handle_snapshot(
        CheckSnapshot(
            True,
            True,
            (0.6, 0.5, 0.5),
            (0.4, 0.5, 0.5),
            gaze=(0.5, 0.5),
            gaze_at=now[0],
            observed_seconds=5,
            available_fraction=0.98,
            longest_loss_seconds=0.1,
        )
    )
    window._tick()
    assert window._distance_label.text().startswith("✓")
    assert window._left_label.text().startswith("✓")
    now[0] += 0.6
    window._tick()
    assert window._distance_label.text().startswith("—")
    assert window._left_label.text().startswith("—")
    window.handle_snapshot(CheckSnapshot(True, False))
    window._tick()
    assert window._right_label.text().startswith("!")
    assert window._distance_label.text().startswith("—")


@pytest.mark.e2e
def test_gaze_check_runs_five_targets_without_any_gaze_click(gaze_check, qtbot):
    from pogled_assist.tracking.gaze_check import CheckSnapshot

    window, now, _screen = gaze_check
    window._primary_button.click()
    qtbot.wait(1)
    assert window._phase == "precision"
    assert window._check is not None
    for index in range(5):
        name, x, y = window._check.targets[index]
        start = window._check.started_at
        for sample in range(100):
            now[0] = start + 1 + sample * 0.02
            window.handle_snapshot(CheckSnapshot(True, True, gaze=(x, y), gaze_at=now[0]))
        now[0] = start + 3.01
        window._tick()
        assert window._check.results[index].name == name
        assert window._check.results[index].near is True
    assert window._phase == "results"
    assert "5 od 5" in window._result_summary.text()
    window._repeat_button.click()
    assert window._check is None
    assert window._phase == "position"


@pytest.mark.e2e
def test_precision_does_not_bridge_coalesced_eye_losses(gaze_check, qtbot):
    import threading

    from pogled_assist.tracking.gaze_provider import TobiiGazeProvider

    window, now, _screen = gaze_check
    provider = TobiiGazeProvider()
    provider.set_check_active(True)
    gaze, eyes = provider._new_stream_callbacks()
    provider.eye_status_changed.connect(window.handle_eye_status)
    provider.diagnostics_updated.connect(window.handle_snapshot)
    window._primary_button.click()
    qtbot.wait(1)
    start = window._check.started_at
    _name, x, y = window._check.targets[0]

    def feed(at):
        now[0] = at - 0.09
        eyes(False, True, 0)
        now[0] = at
        eyes(True, True, 0)
        gaze(x, y, 0)

    for sample in range(20):
        # Both eye events arrive before Qt delivers the next valid snapshot.
        thread = threading.Thread(target=feed, args=(start + 1 + sample * 0.1,))
        thread.start()
        thread.join(2)
        assert not thread.is_alive()
        provider._emit_latest_gaze_sample()
    now[0] = start + 3.01
    window._tick()
    result = window._check.results[0]
    assert result.samples == 20
    assert result.coverage == 0
    assert result.near is None
    window._show_results()
    assert "Premalo podataka" in window._result_detail.text()


@pytest.mark.e2e
def test_research_eye_positions_remain_visible_without_enabling_gaze(gaze_check):
    from pogled_assist.tracking.gaze_provider import TobiiGazeProvider

    window, now, _screen = gaze_check
    provider = TobiiGazeProvider()
    provider.set_check_active(True)
    provider.eye_status_changed.connect(window.handle_eye_status)
    provider.diagnostics_updated.connect(window.handle_snapshot)
    delivered = []
    provider.gaze_updated.connect(lambda *sample: delivered.append(sample))
    data = {
        "left_gaze_point_validity": 0,
        "right_gaze_point_validity": 0,
        "left_gaze_point_on_display_area": (0.5, 0.5),
        "right_gaze_point_on_display_area": (0.5, 0.5),
        "left_gaze_origin_validity": 1,
        "right_gaze_origin_validity": 1,
        "left_gaze_origin_in_trackbox_coordinate_system": (0.4, 0.5, 0.6),
        "right_gaze_origin_in_trackbox_coordinate_system": (0.6, 0.5, 0.6),
    }
    provider._on_gaze_data(data)
    provider._emit_latest_gaze_sample()
    window._tick()
    assert window._left_label.text().startswith("✓")
    assert window._right_label.text().startswith("✓")
    assert window._distance_label.text().startswith("✓")
    assert window._eyes_view.snapshot.left_position == (0.4, 0.5, 0.6)
    assert window._gaze_label.text().endswith("Čekam pogled na ekranu")
    assert "Oči su prepoznate" in window._guidance.text()
    assert window._snapshot.left is window._snapshot.right is False
    assert window._snapshot.gaze is None
    assert delivered == []
    window._start_trial()
    for _ in range(100):
        now[0] += 0.02
        provider._on_gaze_data(data)
        provider._emit_latest_gaze_sample()
    assert window._trial_results == []
    assert window._target.progress == 0
    assert delivered == []


@pytest.mark.e2e
def test_precision_targets_use_final_geometry_and_unclamped_logical_screen(gaze_check, qtbot):
    window, _now, screen = gaze_check
    window._primary_button.click()
    qtbot.wait(1)
    for index, (_name, x, y) in enumerate(window._check.targets):
        window._target.target_index = index
        painted = window._target.mapToGlobal(window._target.center())
        assert abs(painted.x() - (screen.left() + x * (screen.width() - 1))) <= 1
        assert abs(painted.y() - (screen.top() + y * (screen.height() - 1))) <= 1
        if index:
            assert x < 0.06 or x > 0.94
            assert y < 0.08 or y > 0.92
    window.resize(1200, 680)
    qtbot.wait(1)
    assert window._phase == "position"
    assert window._check is None


@pytest.mark.e2e
def test_free_check_shows_nine_targets_and_only_fresh_both_eye_gaze(gaze_check, qtbot):
    from pogled_assist.tracking.gaze_check import CheckSnapshot

    window, now, screen = gaze_check
    window._free_button.click()
    qtbot.wait(1)
    assert window._phase == "free"
    assert window._check is None
    assert len(window._target.free_centers()) == 9
    controls = window._test_controls.geometry()
    for point in window._target.free_centers():
        assert not controls.adjusted(-36, -36, 36, 36).contains(point)
    window.handle_snapshot(CheckSnapshot(True, True, gaze=(0.25, 0.75), gaze_at=now[0]))
    expected = window._target.mapFromGlobal(
        QPoint(
            round(screen.left() + 0.25 * (screen.width() - 1)),
            round(screen.top() + 0.75 * (screen.height() - 1)),
        )
    )
    assert window._target.gaze_point == expected
    window.handle_eye_status(True, False)
    assert window._target.gaze_point is None
    window.handle_snapshot(CheckSnapshot(True, True, gaze=(0.25, 0.75), gaze_at=now[0]))
    now[0] += 0.6
    window._tick()
    assert window._target.gaze_point is None
    assert window._phase == "free"
    assert window._check is None
    window._test_back_button.click()
    assert window._phase == "position"
    assert not window._target.isVisible()


@pytest.mark.e2e
@pytest.mark.parametrize("size", [(1280, 720), (1440, 900)])
def test_trial_neighbors_remain_visible_beside_caregiver_controls(gaze_check, qtbot, size):
    window, now, _screen = gaze_check
    window.resize(*size)
    qtbot.wait(1)
    window._start_trial()
    qtbot.wait(1)
    for scenario in range(3):
        assert window._target.target_index == scenario
        controls = window._test_controls.geometry().adjusted(-8, -8, 8, 8)
        for index in range(3):
            button = window._target.button_rect(index)
            assert window._target.rect().contains(button.adjusted(-2, -2, 2, 2))
            assert not controls.intersects(button), (scenario, index)
        window._finish_trial_target(True, now[0])


@pytest.mark.e2e
def test_trial_counts_wrong_neighbor_once_and_requires_correct_button(gaze_check, qtbot):
    from pogled_assist.tracking.gaze_check import CheckSnapshot

    window, now, screen = gaze_check
    window._start_trial()
    qtbot.wait(1)
    wrong = window._target.mapToGlobal(window._target.button_rect(0).center())
    gaze = (
        (wrong.x() - screen.left()) / (screen.width() - 1),
        (wrong.y() - screen.top()) / (screen.height() - 1),
    )
    for sample in range(100):
        now[0] = 10 + sample * 0.02
        window.handle_snapshot(CheckSnapshot(True, True, gaze=gaze, gaze_at=now[0]))
    assert window._trial_wrong_selections == 1
    assert window._trial_results == []
    assert window._selection.is_blocked
    correct = window._target.mapToGlobal(window._target.center())
    gaze = (
        (correct.x() - screen.left()) / (screen.width() - 1),
        (correct.y() - screen.top()) / (screen.height() - 1),
    )
    for sample in range(60):
        now[0] = 12 + sample * 0.02
        window.handle_snapshot(CheckSnapshot(True, True, gaze=gaze, gaze_at=now[0]))
    assert window._trial_results == [True]
    assert window._trial_wrong_selections == 1
    assert window._target.button_rect().size().width() == 96


@pytest.mark.e2e
@pytest.mark.parametrize("loss", ["eyes", "invalid", "coalesced", "stale"])
def test_trial_blink_cannot_repeat_an_already_selected_neighbor(gaze_check, loss):
    from pogled_assist.tracking.gaze_check import CheckSnapshot

    window, now, screen = gaze_check
    window._start_trial()
    wrong = window._target.mapToGlobal(window._target.button_rect(0).center())
    gaze = (
        (wrong.x() - screen.left()) / (screen.width() - 1),
        (wrong.y() - screen.top()) / (screen.height() - 1),
    )
    interruptions = 0

    def feed(point=gaze):
        now[0] += 0.02
        window.handle_snapshot(
            CheckSnapshot(True, True, gaze=point, gaze_at=now[0], gaze_interruptions=interruptions)
        )

    for _ in range(60):
        feed()
    assert window._trial_wrong_selections == 1
    if loss == "eyes":
        window.handle_eye_status(False, True)
    elif loss == "invalid":
        window.handle_snapshot(CheckSnapshot(True, True))
    elif loss == "coalesced":
        interruptions += 1
    else:
        now[0] += 0.6
        window._tick()
    for _ in range(60):
        feed()
    assert window._trial_wrong_selections == 1
    assert window._trial_losses == 0  # The completed selection had no pending progress.
    assert window._selection.is_blocked
    feed((-0.1, 0.5))  # A fresh off-screen departure does unlock it.
    for _ in range(60):
        feed()
    assert window._trial_wrong_selections == 2


@pytest.mark.e2e
@pytest.mark.parametrize("scenario", [0, 1, 2])
def test_trial_edge_hold_matches_normal_control_bounds(gaze_check, scenario):
    from pogled_assist.tracking.gaze_check import CheckSnapshot

    window, now, screen = gaze_check
    window._start_trial()
    window._target.target_index = scenario
    rect = window._target.button_rect()

    def feed(point, at):
        now[0] = at
        global_point = window._target.mapToGlobal(point)
        gaze = (
            (global_point.x() - screen.left()) / (screen.width() - 1),
            (global_point.y() - screen.top()) / (screen.height() - 1),
        )
        window.handle_snapshot(CheckSnapshot(True, True, gaze=gaze, gaze_at=at))

    for sample in range(41):
        feed(rect.center(), 10 + sample * 0.02)
    assert window._target.progress > 0
    margin = min(24, rect.width() // 4, rect.height() // 4)
    # Just beyond the real controls' tolerance, but inside the old fixed 24 px.
    feed(QPoint(rect.center().x(), rect.bottom() + margin + 1), 10.82)
    assert window._selection.target is None
    assert window._target.progress == 0
    assert window._trial_departures == 1


@pytest.mark.e2e
@pytest.mark.parametrize(
    "left,right,labels",
    [
        ((1.2, 0.5, 0.5), (1.1, 0.5, 0.5), {"L/D"}),
        ((0.51, 0.5, 0.5), (0.49, 0.5, 0.5), {"L/D"}),
        ((0.6, 0.5, 0.5), (0.4, 0.5, 0.5), {"L", "D"}),
        ((0.6, 0.5, 0.5), None, {"L"}),
        ((1.2, -0.1, 0.5), (1.1, -0.1, 0.5), {"L/D"}),
        ((-0.2, 1.1, 0.5), (-0.1, 1.1, 0.5), {"L/D"}),
    ],
)
def test_position_markers_keep_both_eye_labels_visible(
    gaze_check, monkeypatch, left, right, labels
):
    from pogled_assist.tracking.gaze_check import CheckSnapshot
    from pogled_assist.ui import gaze_check_views

    painted_text = []
    painted_bounds = []

    class RecordingPainter(gaze_check_views.QPainter):
        def drawText(self, *args):
            painted_text.append(args[-1])
            return super().drawText(*args)

        def drawEllipse(self, center, rx, ry):
            painted_bounds.append(
                gaze_check_views.QRectF(center.x() - rx, center.y() - ry, 2 * rx, 2 * ry)
            )
            return super().drawEllipse(center, rx, ry)

    monkeypatch.setattr(gaze_check_views, "QPainter", RecordingPainter)
    window, _now, _screen = gaze_check
    snapshot = CheckSnapshot(False, False, left, right)
    window.handle_snapshot(snapshot)
    window._tick()
    window._eyes_view.grab()
    assert set(painted_text) & {"L", "D", "L/D"} == labels
    bounds = gaze_check_views.QRectF(window._eyes_view.rect())
    assert all(bounds.contains(rect.adjusted(-2, -2, 2, 2)) for rect in painted_bounds)
    assert window._snapshot == snapshot  # Grouping is presentation-only.


@pytest.mark.e2e
@pytest.mark.parametrize(
    "left,right,instruction",
    [
        ((0.6, 0.5, -0.2), (0.4, 0.5, -0.1), "odmaknite ekran"),
        ((0.6, 0.5, 1.2), (0.4, 0.5, 1.1), "približite ekran"),
        ((1.2, 0.5, 0.5), (1.1, 0.5, 0.5), "obje oznake unutar okvira"),
    ],
)
def test_position_guidance_uses_eye_positions_before_valid_gaze(
    gaze_check, left, right, instruction
):
    from pogled_assist.tracking.gaze_check import CheckSnapshot

    window, now, _screen = gaze_check
    window.handle_snapshot(CheckSnapshot(False, False, left, right))
    window._tick()
    assert instruction in window._guidance.text()
    assert window._gaze_label.text().endswith("Čekam pogled na ekranu")
    assert window._snapshot.gaze is None
    now[0] += 0.6
    window._tick()
    assert instruction not in window._guidance.text()
    assert "Čekam svježe podatke" in window._guidance.text()


@pytest.mark.e2e
def test_trial_counts_direct_neighbor_departure_and_restarts_progress(gaze_check):
    from pogled_assist.tracking.gaze_check import CheckSnapshot

    window, now, screen = gaze_check
    window._start_trial()

    def feed(index):
        now[0] += 0.02
        point = window._target.mapToGlobal(window._target.button_rect(index).center())
        gaze = (
            (point.x() - screen.left()) / (screen.width() - 1),
            (point.y() - screen.top()) / (screen.height() - 1),
        )
        window.handle_snapshot(CheckSnapshot(True, True, gaze=gaze, gaze_at=now[0]))

    for _ in range(40):
        feed(1)
    assert window._target.progress > 0
    feed(0)  # A sampled saccade can skip the gap between the two buttons.
    assert window._target.progress == 0
    assert window._selection.target == 0
    assert window._trial_departures == 1
    assert window._trial_losses == 0
    assert window._trial_results == []
    feed(0)
    assert window._trial_departures == 1
    feed(1)
    assert window._trial_departures == 2
    assert window._target.progress == 0
    assert window._trial_results == []


@pytest.mark.e2e
def test_position_copy_distinguishes_unsupported_waiting_and_disconnected(gaze_check):
    from pogled_assist.tracking.gaze_check import CheckSnapshot
    from pogled_assist.tracking.status import TrackingState, TrackingStatus

    window, _now, _screen = gaze_check
    window.handle_snapshot(CheckSnapshot(position_supported=False))
    window._tick()
    assert "ne šalje" in window._position_notice.text()
    window.handle_snapshot(CheckSnapshot(position_supported=True))
    window._tick()
    assert "Čekam svježe" in window._position_notice.text()
    window.handle_tracking_status(TrackingStatus(TrackingState.RETRYING))
    assert "prekinuta" in window._position_notice.text()


@pytest.mark.e2e
def test_trial_cancels_on_eye_loss_and_uses_fresh_samples_to_complete(gaze_check, qtbot):
    from pogled_assist.tracking.gaze_check import CheckSnapshot

    window, now, screen = gaze_check
    window._start_trial()
    qtbot.wait(1)

    def feed(at):
        now[0] = at
        point = window._target.mapToGlobal(window._target.center())
        x = (point.x() - screen.left()) / (screen.width() - 1)
        y = (point.y() - screen.top()) / (screen.height() - 1)
        window.handle_snapshot(CheckSnapshot(True, True, gaze=(x, y), gaze_at=at))

    for i in range(45):
        feed(10 + i * 0.02)
    assert window._target.progress > 0
    window.handle_eye_status(True, False)
    assert window._target.progress == 0
    assert window._trial_losses == 1
    feed(10.91)
    feed(11.0)
    assert window._trial_results == []
    # Repeating the same gaze sample cannot advance selection.
    now[0] = 11.9
    window.handle_snapshot(CheckSnapshot(True, True, gaze=(0.5, 0.5), gaze_at=11.0))
    assert window._trial_results == []
    for i in range(56):
        feed(12 + i * 0.02)
    assert window._trial_results == [True]
    for _ in range(2):
        start = window._trial_ready_at
        for i in range(56):
            feed(start + i * 0.02)
    assert window._phase == "results"
    assert "3/3" in window._trial_summary.text()


@pytest.mark.e2e
def test_check_disconnect_and_escape_require_no_valid_gaze(gaze_check, qtbot):
    window, _now, _screen = gaze_check
    window._start_precision()
    qtbot.wait(1)
    window.tracking_unavailable()
    assert window._phase == "position"
    assert window._check is None
    assert "prekinuto" in window._notice.text()
    closed = []
    window.closed.connect(lambda: closed.append(True))
    window.activateWindow()
    qtbot.keyClick(window, Qt.Key_Escape)
    assert closed == [True]


@pytest.mark.e2e
def test_trial_offscreen_gaze_does_not_overflow_or_choose_a_button(gaze_check):
    from pogled_assist.tracking.gaze_check import CheckSnapshot

    window, now, _screen = gaze_check
    window._start_trial()
    window.handle_snapshot(CheckSnapshot(True, True, gaze=(1e300, -1e300), gaze_at=now[0]))
    assert window._trial_results == []
    assert window._selection.target is None


@pytest.mark.e2e
@pytest.mark.parametrize("simulated", [False, True])
def test_check_buttons_and_labels_fit_at_150_percent(gaze_check, qtbot, simulated):
    from PySide6.QtWidgets import QLabel, QPushButton

    from pogled_assist.tracking.gaze_check import FixationResult

    window, _now, _screen = gaze_check
    window._simulated = simulated
    for phase in ("position", "precision", "results", "details", "trial", "free"):
        if phase == "precision":
            window._start_precision()
        elif phase == "results":
            window._check.results = [
                FixationResult(name, 90, 0.9, 12, 8, True, (x, y))
                for name, x, y in window._check.targets
            ]
            window._show_results()
        elif phase == "details":
            window._details_button.click()
        elif phase == "trial":
            window._start_trial()
        elif phase == "free":
            window._start_free()
        qtbot.wait(1)
        assert (window.width(), window.height()) == (1280, 720)
        for child in window.findChildren(QWidget):
            if not child.isVisible() or not isinstance(child, (QLabel, QPushButton)):
                continue
            bounds = QRect(child.mapTo(window, QPoint(0, 0)), child.size())
            assert window.rect().contains(bounds), (phase, child.text(), bounds)
            if isinstance(child, QPushButton):
                assert child.height() >= 60
                assert child.fontMetrics().horizontalAdvance(child.text()) + 32 <= child.width()
            elif child.hasHeightForWidth():
                assert child.heightForWidth(child.width()) <= child.height(), (phase, child.text())


@pytest.mark.e2e
@pytest.mark.parametrize(
    "states,advice",
    [
        ([True] * 5, "izbor dugmeta"),
        ([True, False, True, False, True], "Tobii postavke"),
        ([True, False, True, None, True], "Podesi položaj"),
        ([None] * 5, "Podesi položaj"),
    ],
)
def test_gaze_check_feedback_results_explain_next_action_without_metrics(
    gaze_check, qtbot, states, advice
):
    from pogled_assist.tracking.gaze_check import FixationResult

    window, _now, _screen = gaze_check
    window._start_precision()
    qtbot.wait(1)
    window._check.results = [
        FixationResult(name, 90, 0.9, 12, 8, state, (x, y))
        for (name, x, y), state in zip(window._check.targets, states, strict=True)
    ]
    window._show_results()
    assert advice in window._result_advice.text()
    assert "px" not in window._result_detail.text()
    assert "Rasipanje" not in window._result_detail.text()
    assert not window._trial_summary.isVisible()
    if None in states:
        assert "Premalo podataka" in window._result_detail.text()
        assert window._result_summary.text().startswith("—")
    elif False in states:
        assert "Pogled izvan mete" in window._result_detail.text()
        assert window._result_summary.text().startswith("!")
    else:
        assert window._result_summary.text().startswith("✓")
    results = list(window._check.results)
    window._details_button.click()
    assert "Rasipanje" in window._result_detail.text()
    assert "12 px" in window._result_detail.text()
    assert window._metrics_hint.isVisible()
    window._details_button.click()
    assert "px" not in window._result_detail.text()
    assert not window._metrics_hint.isVisible()
    assert window._check.results == results
    window.reset_check()
    assert not window._details_button.isChecked()


@pytest.mark.e2e
@pytest.mark.parametrize(
    "selected,wrong,loss,advice",
    [
        ([True, True, True], 0, 0, "govornu tastaturu"),
        ([True, True, True], 0, 1, "govornu tastaturu"),
        ([True, True, True], 1, 0, "pogrešna dugmad"),
        ([True, True, False], 0, 2, "Prekidi praćenja"),
        ([False, False, False], 0, 0, "nisu odabrana na vrijeme"),
    ],
)
def test_gaze_check_feedback_trial_result_replaces_pending_trial_advice(
    gaze_check, qtbot, selected, wrong, loss, advice
):
    from pogled_assist.tracking.gaze_check import FixationResult

    window, _now, _screen = gaze_check
    window._start_precision()
    qtbot.wait(1)
    window._check.results = [
        FixationResult(name, 90, 0.9, 12, 8, True, (x, y)) for name, x, y in window._check.targets
    ]
    window._show_results()
    window._start_trial()
    window._trial_results = selected
    window._trial_wrong_selections = wrong
    window._trial_losses = loss
    window._show_results()
    assert advice in window._result_advice.text()
    assert window._trial_summary.isVisible()
    assert f"pogrešni izbori: {wrong}" in window._trial_summary.text()
    assert window._primary_button.text() == "Ponovi probu dugmadi"
    assert "Izlasci iz dugmeta" not in window._trial_summary.text()
    if all(selected) and not wrong:
        assert window._trial_summary.text().startswith("✓")
        assert "Podesite ekran" not in window._result_advice.text()


@pytest.mark.e2e
@pytest.mark.parametrize("state", [False, None])
def test_gaze_check_feedback_successful_trial_never_overrides_precision_problem(
    gaze_check, qtbot, state
):
    from pogled_assist.tracking.gaze_check import FixationResult

    window, _now, _screen = gaze_check
    window._start_precision()
    qtbot.wait(1)
    window._check.results = [
        FixationResult(name, 90, 0.9, 12, 8, state, (x, y)) for name, x, y in window._check.targets
    ]
    window._trial_results = [True] * 3
    window._show_results()
    assert "govornu tastaturu" not in window._result_advice.text()
    assert "Podesi položaj" in window._result_advice.text()


@pytest.mark.e2e
def test_gaze_check_feedback_precision_progress_and_loss_do_not_move_target(gaze_check, qtbot):
    from pogled_assist.tracking.gaze_check import CheckSnapshot

    window, now, _screen = gaze_check
    window._start_precision()
    qtbot.wait(1)
    center = window._target.center()
    now[0] = window._check.started_at + 1.5
    window.handle_snapshot(CheckSnapshot(True, True, gaze=(0.5, 0.5), gaze_at=now[0]))
    window._tick()
    assert window._test_progress.isVisible()
    assert 0 < window._test_progress.value() < window._test_progress.maximum()
    assert "Meta 1 od 5" in window._test_hint.text()
    window.handle_eye_status(True, False)
    window._tick()
    assert "desno oko" in window._test_hint.text()
    assert window._target.center() == center
    assert window._phase == "precision"
    window._start_free()
    assert not window._test_progress.isVisible()


@pytest.mark.e2e
def test_gaze_check_feedback_precision_does_not_claim_stale_gaze_is_ready(gaze_check, qtbot):
    from pogled_assist.tracking.gaze_check import CheckSnapshot

    window, now, _screen = gaze_check
    window._start_precision()
    qtbot.wait(1)
    window.handle_snapshot(CheckSnapshot(True, True, gaze=(0.5, 0.5), gaze_at=now[0] - 0.6))
    window._tick()
    assert "Čekam pogled" in window._test_hint.text()
    assert "Zadržite pogled" not in window._test_hint.text()


@pytest.mark.e2e
@pytest.mark.parametrize("button,color", [(0, "#f0c84a"), (1, "#70dfa1")])
def test_gaze_check_feedback_trial_progress_distinguishes_neighbor(
    gaze_check, monkeypatch, button, color
):
    from pogled_assist.ui import gaze_check_views

    colors = []

    class RecordingPainter(gaze_check_views.QPainter):
        def fillRect(self, rect, brush):
            colors.append(brush.name())
            return super().fillRect(rect, brush)

    monkeypatch.setattr(gaze_check_views, "QPainter", RecordingPainter)
    window, _now, _screen = gaze_check
    window._start_trial()
    window._target.progress_target = button
    window._target.progress = 0.6
    window._target.grab()
    assert color in colors


@pytest.mark.e2e
def test_gaze_check_feedback_trial_explains_neighbor_and_lost_progress(gaze_check):
    from pogled_assist.tracking.gaze_check import CheckSnapshot

    window, now, screen = gaze_check
    window._start_trial()

    def feed(index):
        now[0] += 0.02
        point = window._target.mapToGlobal(window._target.button_rect(index).center())
        window.handle_snapshot(
            CheckSnapshot(
                True,
                True,
                gaze=(
                    (point.x() - screen.left()) / (screen.width() - 1),
                    (point.y() - screen.top()) / (screen.height() - 1),
                ),
                gaze_at=now[0],
            )
        )

    for _ in range(60):
        feed(0)
    assert "Odabrano je pogrešno dugme" in window._test_hint.text()
    assert window._trial_wrong_selections == 1
    for _ in range(40):
        feed(1)
    assert window._target.progress > 0
    window.handle_eye_status(False, True)
    assert window._target.progress == 0
    assert "prekinuto" in window._test_hint.text()
    now[0] += 0.1
    window._tick()
    assert "prekinuto" in window._test_hint.text()
    feed(1)
    assert "Zadržite pogled" in window._test_hint.text()
    assert window._trial_results == []


@pytest.mark.e2e
def test_trial_copy_distinguishes_other_button_from_wrong_selection(gaze_check, monkeypatch):
    from pogled_assist.tracking.gaze_check import CheckSnapshot
    from pogled_assist.ui import gaze_check_views

    labels = []

    class RecordingPainter(gaze_check_views.QPainter):
        def drawText(self, *args):
            if isinstance(args[-1], str):
                labels.append(args[-1])
            return super().drawText(*args)

    monkeypatch.setattr(gaze_check_views, "QPainter", RecordingPainter)
    window, now, screen = gaze_check
    window._start_trial()
    window._target.grab()
    assert labels.count("Drugo") == 2
    assert labels.count("Pogledaj") == 1
    point = window._target.mapToGlobal(window._target.button_rect(0).center())
    window.handle_snapshot(
        CheckSnapshot(
            True,
            True,
            gaze=(
                (point.x() - screen.left()) / (screen.width() - 1),
                (point.y() - screen.top()) / (screen.height() - 1),
            ),
            gaze_at=now[0],
        )
    )
    assert "Pogled je na drugom dugmetu" in window._test_hint.text()
    assert "Odabrano" not in window._test_hint.text()
    assert window._trial_wrong_selections == 0


@pytest.mark.e2e
@pytest.mark.parametrize("script", ["latin", "arabic"])
def test_speech_rest_control_uses_bosnian_copy_and_preserves_message(
    qtbot, make_speech_window, script
):
    speech = FakeSpeech()
    speech._settings = SpeechSettings(keyboard_script=script)
    window = make_speech_window(speech, library_store=FakeLibraryStore())
    window.resize(1280, 720)
    window.show()
    window._input.setText("TREBAM ODMOR")
    rest = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}sleep:start"]
    assert rest.text() == "Odmor\nOdmori oči"
    rest.click()
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.sleep)
    window.handle_gaze_action(f"{SPEECH_WINDOW_ACTION_PREFIX}sleep:wake")
    assert window._dialogs.active is None
    assert window._input.text() == "TREBAM ODMOR"


@pytest.mark.e2e
@pytest.mark.parametrize("script", ["latin", "arabic"])
@pytest.mark.parametrize("letters_per_group", [2, 5])
@pytest.mark.parametrize("size", [(320, 640), (380, 640), (380, 950)])
def test_controller_keyboard_rows_fill_sidebar_width(
    qtbot, monkeypatch, script, letters_per_group, size
):
    from pogled_assist.ui import sidebar_panel

    monkeypatch.setattr(sidebar_panel, "WindowsAppBar", FakeAppBar)
    window = ControllerWindow(
        GazeSettings(),
        SpeechSettings(keyboard_script=script, letters_per_group=letters_per_group),
    )
    qtbot.addWidget(window)
    window._input = FakeControllerInput()
    window.resize(*size)
    window.show()
    prefix = CONTROLLER_WINDOW_ACTION_PREFIX

    def check_row(buttons):
        qtbot.wait(1)
        rects = [QRect(button.mapTo(window, QPoint(0, 0)), button.size()) for button in buttons]
        assert min(rect.left() for rect in rects) == 10
        assert max(rect.right() for rect in rects) == window.width() - 11
        assert max(rect.width() for rect in rects) - min(rect.width() for rect in rects) <= 1
        assert all(window.rect().contains(rect) for rect in rects)
        for button in buttons:
            center = button.mapToGlobal(button.rect().center())
            expected = (
                next(
                    action for action, target in window._action_buttons.items() if target is button
                )
                if button.isEnabled()
                else None
            )
            assert window.action_at_global_point(center) == expected

    window._tab_buttons["keyboard"].click()
    for tab, group_command, key_command in (
        ("letters", "keyboard_group", "keyboard_letter:0"),
        ("numpad", "keyboard_numpad_group", "keyboard_numpad"),
        ("symbols", "keyboard_symbol_group", "keyboard_symbol"),
    ):
        window._keyboard_tab_buttons[tab].click()
        check_row(list(window._keyboard_tab_buttons.values()))
        check_row([window._action_buttons[f"{prefix}{group_command}:{i}"] for i in (0, 1)])
        check_row(
            [
                window._action_buttons[f"{prefix}{command}"]
                for command in ("keyboard_space", "keyboard_backspace")
            ]
        )
        if f"{prefix}keyboard-page:1" in window._action_buttons:
            check_row([window._action_buttons[f"{prefix}keyboard-page:{i}"] for i in (-1, 1)])
            window._action_buttons[f"{prefix}keyboard-page:1"].click()
            check_row(list(window._keyboard_tab_buttons.values()))
            window._action_buttons[f"{prefix}keyboard-page:-1"].click()

        window._action_buttons[f"{prefix}{group_command}:0"].click()
        check_row(list(window._keyboard_tab_buttons.values()))
        if f"{prefix}{key_command}:2" in window._action_buttons:
            check_row([window._action_buttons[f"{prefix}{key_command}:{i}"] for i in range(3)])
        check_row(
            [
                window._action_buttons[f"{prefix}{command}"]
                for command in ("keyboard_groups", "keyboard_space", "keyboard_backspace")
            ]
        )
        window.handle_gaze_action(f"{prefix}{key_command}:0")
        check_row(list(window._keyboard_tab_buttons.values()))
        check_row([window._action_buttons[f"{prefix}{group_command}:{i}"] for i in (0, 1)])

    for tab in ("general", "settings"):
        window._tab_buttons[tab].click()
        qtbot.wait(1)
        buttons = [
            button
            for button in window._action_buttons.values()
            if button.isVisible() and button.objectName() in ("shortcutButton", "checkButton")
        ]
        first_row = [
            button for button in buttons if button.y() == min(target.y() for target in buttons)
        ]
        check_row(first_row)


@pytest.mark.e2e
def test_twelve_letter_dialog_fits_150_percent_display_and_accepts_gaze(qtbot, make_speech_window):
    window = make_speech_window(
        FakeSpeech(), letters_per_group=12, library_store=FakeLibraryStore()
    )
    window.resize(1280, 720)
    window.show()
    qtbot.waitUntil(window.isVisible)

    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"].click()
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.letter)
    dialog = window._dialogs.letter
    assert dialog.height() <= window.height() - 64
    assert dialog.width() <= window.width() - 64

    bounds = dialog.rect()
    for action in window._dialogs.letter_actions:
        button = window._action_buttons[action]
        rect = QRect(button.mapTo(dialog, QPoint(0, 0)), button.size())
        assert bounds.contains(rect), action
        assert button.width() >= 140, action
        assert button.height() >= 110, action
        assert window.action_at_global_point(button.mapToGlobal(button.rect().center())) == action

    last_letter = f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:11"
    window.handle_gaze_action(last_letter)
    qtbot.waitUntil(lambda: window._dialogs.active is None)
    assert window._input.text() == window._letter_groups[0][-1]


@pytest.mark.e2e
def test_single_letter_groups_fit_150_percent_display(qtbot, make_speech_window):
    window = make_speech_window(FakeSpeech(), letters_per_group=1, library_store=FakeLibraryStore())
    window.resize(1280, 720)
    window.show()
    qtbot.waitUntil(window.isVisible)

    assert window.size().width() <= 1280
    assert window.size().height() <= 720
    bounds = QRect(0, 0, 1280, 720)
    group_actions = [
        f"{SPEECH_WINDOW_ACTION_PREFIX}group:{index}" for index in range(len(window._letter_groups))
    ]
    for action in (*group_actions, f"{SPEECH_WINDOW_ACTION_PREFIX}keyboard-toggle"):
        button = window._action_buttons[action]
        rect = QRect(button.mapTo(window, QPoint(0, 0)), button.size())
        assert bounds.contains(rect), action
        assert button.height() >= 72, action


@pytest.mark.e2e
def test_speech_symbols_backspace_clear_and_play(qtbot, make_speech_window):
    speech = FakeSpeech()
    window = make_speech_window(speech, library_store=FakeLibraryStore())
    window.show()
    qtbot.waitUntil(window.isVisible)

    qtbot.mouseClick(window._keyboard_toggle_button, Qt.LeftButton)
    assert window._symbols_mode is True
    symbol = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}symbol:0"]
    qtbot.waitUntil(symbol.isVisible)
    qtbot.mouseClick(symbol, Qt.LeftButton)
    assert window._input.text() == "1"

    qtbot.mouseClick(window._keyboard_toggle_button, Qt.LeftButton)
    assert window._symbols_mode is False
    assert f"{SPEECH_WINDOW_ACTION_PREFIX}group:0" in window._action_buttons

    for value in ("DŽ", "LJ", "NJ", "dž", "lj", "nj"):
        window._input.setText(value)
        qtbot.mouseClick(window._backspace_button, Qt.LeftButton)
        assert window._input.text() == ""

    window._input.setText("Trebam pomoć")
    qtbot.mouseClick(window._play_button, Qt.LeftButton)
    assert speech.requests[-1][0] == "TREBAM POMOĆ"
    assert window._input.text() == "TREBAM POMOĆ"

    qtbot.mouseClick(window._clear_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.confirm)
    qtbot.mouseClick(
        window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:cancel"], Qt.LeftButton
    )
    qtbot.waitUntil(lambda: window._dialogs.active is None)
    assert window._input.text() == "TREBAM POMOĆ"

    qtbot.mouseClick(window._clear_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.confirm)
    qtbot.mouseClick(
        window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:accept"], Qt.LeftButton
    )
    qtbot.waitUntil(lambda: window._dialogs.active is None)
    assert window._input.text() == ""

    qtbot.mouseClick(window._clear_button, Qt.LeftButton)
    assert window._dialogs.active is None


@pytest.mark.e2e
def test_library_retry_is_gaze_selectable_and_preserves_the_message(
    qtbot, make_speech_window, tmp_path, monkeypatch
):
    from pathlib import Path

    from pogled_assist.speech.speech_library import (
        CategoryRecord,
        PhraseRecord,
        SpeechLibrary,
        SpeechLibraryStore,
    )

    primary, legacy = tmp_path / "library.json", tmp_path / "phrases.json"
    original = SpeechLibrary(
        [CategoryRecord("Synthetic custom", ["Synthetic answer"])],
        [PhraseRecord("Synthetic phrase", 5)],
    )
    assert SpeechLibraryStore(primary, legacy_path=legacy).save(original)
    before = primary.read_bytes()
    read_text = Path.read_text

    def unavailable(path, *args, **kwargs):
        if path == primary:
            raise PermissionError("Synthetic failure")
        return read_text(path, *args, **kwargs)

    store = SpeechLibraryStore(primary, legacy_path=legacy)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", unavailable)
        window = make_speech_window(FakeSpeech(), library_store=store)
    window.resize(1280, 720)
    window.show()
    window._view_mode = "phrases"
    window._show_list_level()
    qtbot.wait(1)
    window._input.setText("SYNTHETIC MESSAGE")
    window.handle_gaze_action(f"{SPEECH_WINDOW_ACTION_PREFIX}list:select:0")
    message = window._input.text()
    assert "SYNTHETIC PHRASE" in message
    assert primary.read_bytes() == before
    assert window._add_item_button.isHidden()
    assert window._delete_mode_button.isHidden()
    retry = window._retry_library_button
    assert retry.isVisible() and retry.height() >= 80
    assert window.rect().contains(QRect(retry.mapTo(window, QPoint()), retry.size()))
    assert (
        window.action_at_global_point(retry.mapToGlobal(retry.rect().center()))
        == f"{SPEECH_WINDOW_ACTION_PREFIX}list:retry"
    )
    window.handle_gaze_action(f"{SPEECH_WINDOW_ACTION_PREFIX}list:retry")
    assert not store.read_error
    assert window._library == original
    assert window._input.text() == message
    assert retry.isHidden()
    assert window._add_item_button.isVisible()


@pytest.mark.e2e
def test_speech_lifecycle_updates_status_and_ignores_previous_request(qtbot, make_speech_window):
    speech = FakeSpeech()
    window = make_speech_window(speech, library_store=FakeLibraryStore())
    window.show()
    window._input.setText("SYNTHETIC MESSAGE")
    window._play_button.click()
    first = speech.request_id
    assert window._status_label.text() == "Pokrećem govor."
    speech.playback_changed.emit(first, "speaking")
    assert window._status_label.text() == "Poruka se izgovara."
    speech.playback_changed.emit(first, "failed")
    assert window._status_label.text() == "Govor nije uspio. Pokušajte ponovo."
    assert window._input.text() == "SYNTHETIC MESSAGE"
    window._play_button.click()
    second = speech.request_id
    speech.playback_changed.emit(first, "finished")
    assert window._status_label.text() == "Pokrećem govor."
    speech.playback_changed.emit(second, "finished")
    assert window._status_label.text() == "Čitanje je završeno."
