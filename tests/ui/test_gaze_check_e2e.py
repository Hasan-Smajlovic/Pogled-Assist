from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QWidget

from pogled_assist.interaction.mouse_controller import GazeSettings
from pogled_assist.tracking.gaze_check import CheckSnapshot, FixationResult

pytestmark = pytest.mark.e2e


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


def test_switching_check_modes_clears_previous_target_feedback(gaze_check, qtbot):
    window, _now, _screen = gaze_check
    for phase, start in (
        ("trial", window._start_trial),
        ("free", window._start_free),
        ("precision", window._start_precision),
    ):
        window._target.target_index = 2
        window._target.progress = 0.75
        window._target.progress_target = 1
        window._target.gaze_point = QPoint(200, 300)
        start()
        qtbot.wait(1)
        assert window._phase == phase
        assert window._target.trial == (phase == "trial")
        assert window._target.free == (phase == "free")
        assert window._target.target_index == 0
        assert window._target.progress == 0
        assert window._target.progress_target is None
        assert window._target.gaze_point is None
        assert window._test_progress.isVisible() == (phase == "precision")


def test_gaze_check_live_states_and_timeout_are_not_false_successes(gaze_check):
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


def test_gaze_check_runs_five_targets_without_any_gaze_click(gaze_check, qtbot):
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


@pytest.mark.parametrize("missing", ["eyes", "gaze", "stale"])
def test_trial_without_fresh_gaze_explains_missing_data_and_retry(gaze_check, qtbot, missing):
    window, now, _screen = gaze_check
    window._start_precision()
    qtbot.wait(1)
    window._check.results = [
        FixationResult(name, 90, 0.9, 12, 8, True, (x, y)) for name, x, y in window._check.targets
    ]
    window._start_trial()
    for _ in range(3):
        now[0] = window._trial_ready_at + 0.1
        if missing == "eyes":
            snapshot = CheckSnapshot(True, False)
        elif missing == "gaze":
            snapshot = CheckSnapshot(True, True)
        else:
            snapshot = CheckSnapshot(True, True, gaze=(0.5, 0.5), gaze_at=now[0] - 0.6)
        window.handle_snapshot(snapshot)
        now[0] = window._trial_deadline + 0.01
        window._tick()
    assert window._phase == "results"
    assert window._trial_results == [False] * 3
    assert window._trial_losses == 0  # No pending selection ever started.
    assert "poništeni izbori: 0" in window._trial_summary.text()
    assert "nije bilo dovoljno podataka o pogledu" in window._result_advice.text()
    assert "Podesite položaj" in window._result_advice.text()
    assert "nisu odabrana na vrijeme" not in window._result_advice.text()
    assert "0/3" in window._trial_summary.text()
    window._start_trial()
    assert not window._trial_tracked_targets


@pytest.mark.parametrize("samples", ["single", "repeated", "sparse", "interrupted"])
def test_trial_with_isolated_gaze_prioritizes_tracking_over_fixation(gaze_check, qtbot, samples):
    window, now, _screen = gaze_check
    window._start_precision()
    qtbot.wait(1)
    window._check.results = [
        FixationResult(name, 90, 0.9, 12, 8, True, (x, y)) for name, x, y in window._check.targets
    ]
    window._start_trial()
    interruptions = 0
    for _ in range(3):
        start = window._trial_ready_at
        count = 1 if samples == "single" else 90
        for index in range(count):
            now[0] = start + 0.1 + index * 0.1
            at = start + 0.1 if samples == "repeated" else now[0]
            if samples == "sparse" and index % 10:
                continue
            if samples == "interrupted":
                interruptions += 1
            window.handle_snapshot(
                CheckSnapshot(
                    True, True, gaze=(0.99, 0.5), gaze_at=at, gaze_interruptions=interruptions
                )
            )
        now[0] = window._trial_deadline + 0.01
        window._tick()
    assert window._trial_losses == 0  # No pending dwell to cancel outside the buttons.
    assert "Podesite položaj" in window._result_advice.text()
    assert "nisu odabrana na vrijeme" not in window._result_advice.text()


def test_trial_distinguishes_available_gaze_from_missing_data_and_clears_retry(gaze_check, qtbot):
    window, now, _screen = gaze_check
    window._start_precision()
    qtbot.wait(1)
    window._check.results = [
        FixationResult(name, 90, 0.9, 12, 8, True, (x, y)) for name, x, y in window._check.targets
    ]
    window._start_trial()
    for _ in range(3):
        start = window._trial_ready_at
        # Sustained fresh gaze outside the buttons is data without pending dwell.
        for index in range(100):
            now[0] = start + index * 0.1
            window.handle_snapshot(CheckSnapshot(True, True, gaze=(0.99, 0.5), gaze_at=now[0]))
        now[0] = window._trial_deadline + 0.01
        window._tick()
    assert window._trial_tracked_targets == {0, 1, 2}
    assert "nisu odabrana na vrijeme" in window._result_advice.text()
    assert "nije bilo dovoljno podataka o pogledu" not in window._result_advice.text()
    window._start_trial()
    for _ in range(3):
        now[0] = window._trial_deadline + 0.01
        window._tick()
    assert "nije bilo dovoljno podataka o pogledu" in window._result_advice.text()
    assert not window._trial_tracked_targets
    window.reset_check()
    assert not window._trial_tracked_targets


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


def test_free_check_shows_nine_targets_and_only_fresh_both_eye_gaze(gaze_check, qtbot):
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


def test_trial_counts_wrong_neighbor_once_and_requires_correct_button(gaze_check, qtbot):
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


@pytest.mark.parametrize("loss", ["eyes", "invalid", "coalesced", "stale"])
def test_trial_blink_cannot_repeat_an_already_selected_neighbor(gaze_check, loss):
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


@pytest.mark.parametrize("scenario", [0, 1, 2])
def test_trial_edge_hold_matches_normal_control_bounds(gaze_check, scenario):
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


def test_trial_counts_direct_neighbor_departure_and_restarts_progress(gaze_check):
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


def test_position_copy_distinguishes_unsupported_waiting_and_disconnected(gaze_check):
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


def test_trial_cancels_on_eye_loss_and_uses_fresh_samples_to_complete(gaze_check, qtbot):
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


def test_trial_offscreen_gaze_does_not_overflow_or_choose_a_button(gaze_check):
    window, now, _screen = gaze_check
    window._start_trial()
    window.handle_snapshot(CheckSnapshot(True, True, gaze=(1e300, -1e300), gaze_at=now[0]))
    assert window._trial_results == []
    assert window._selection.target is None


@pytest.mark.parametrize("simulated", [False, True])
def test_check_buttons_and_labels_fit_at_150_percent(gaze_check, qtbot, simulated):
    from PySide6.QtWidgets import QLabel, QPushButton

    window, _now, _screen = gaze_check
    window._simulated = simulated
    for phase in ("position", "precision", "results", "details", "trial", "trial-no-gaze", "free"):
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
        elif phase == "trial-no-gaze":
            window._trial_results = [False] * 3
            window._show_results()
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
    window, _now, _screen = gaze_check
    window._start_precision()
    qtbot.wait(1)
    window._check.results = [
        FixationResult(name, 90, 0.9, 12, 8, True, (x, y)) for name, x, y in window._check.targets
    ]
    window._show_results()
    window._start_trial()
    window._trial_results = selected
    window._trial_tracked_targets = {0, 1, 2}
    window._trial_wrong_selections = wrong
    window._trial_losses = loss
    window._show_results()
    assert advice in window._result_advice.text()
    assert window._trial_summary.isVisible()
    assert f"pogrešni izbori: {wrong}" in window._trial_summary.text()
    assert f"poništeni izbori: {loss}" in window._trial_summary.text()
    assert window._primary_button.text() == "Ponovi probu dugmadi"
    assert "Izlasci iz dugmeta" not in window._trial_summary.text()
    if all(selected) and not wrong:
        assert window._trial_summary.text().startswith("✓")
        assert "Podesite ekran" not in window._result_advice.text()


@pytest.mark.parametrize("state", [False, None])
def test_gaze_check_feedback_successful_trial_never_overrides_precision_problem(
    gaze_check, qtbot, state
):
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


def test_gaze_check_feedback_precision_progress_and_loss_do_not_move_target(gaze_check, qtbot):
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


def test_gaze_check_feedback_precision_does_not_claim_stale_gaze_is_ready(gaze_check, qtbot):
    window, now, _screen = gaze_check
    window._start_precision()
    qtbot.wait(1)
    window.handle_snapshot(CheckSnapshot(True, True, gaze=(0.5, 0.5), gaze_at=now[0] - 0.6))
    window._tick()
    assert "Čekam pogled" in window._test_hint.text()
    assert "Zadržite pogled" not in window._test_hint.text()


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


def test_gaze_check_feedback_trial_explains_neighbor_and_lost_progress(gaze_check):
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


def test_trial_copy_distinguishes_other_button_from_wrong_selection(gaze_check, monkeypatch):
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
