from __future__ import annotations

import pytest
from _clock import freeze_monotonic
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QWidget

from pogled_assist.interaction.mouse_controller import GazeSettings
from pogled_assist.tracking.gaze_check import CheckSnapshot, FixationResult

pytestmark = pytest.mark.e2e


@pytest.fixture
def gaze_check(qtbot, monkeypatch, request):
    from types import SimpleNamespace

    from pogled_assist.ui import gaze_check_window as module

    screen = QRect(-100, 20, 1280, 720)
    monkeypatch.setattr(
        module.QGuiApplication, "primaryScreen", lambda: SimpleNamespace(geometry=lambda: screen)
    )
    window = module.GazeCheckWindow(getattr(request, "param", GazeSettings()))
    qtbot.addWidget(window)
    window.setGeometry(screen)
    window.show()
    qtbot.wait(1)
    window._timer.stop()
    now = freeze_monotonic(monkeypatch, 10.0)
    return window, now, screen


@pytest.mark.parametrize("simulated", [False, True])
def test_header_context_and_actions_align_without_footer_notice(qtbot, simulated):
    from pogled_assist.ui.gaze_check_window import GazeCheckWindow

    window = GazeCheckWindow(GazeSettings(eye_tracking_policy="any"), simulated=simulated)
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()

    def rect(widget):
        return QRect(widget.mapTo(window, QPoint()), widget.size())

    def assert_header():
        buttons = [window._history_button, window._diagnostics_button, window._close_button]
        buttons = [button for button in buttons if button.isVisible()]
        assert len({rect(button).top() for button in buttons}) == 1
        assert all(button.height() == 60 for button in buttons)
        assert rect(window._policy_label).left() > rect(window._title_label).right()
        assert rect(window._notice).bottom() < rect(window._pages).top()
        assert rect(window._notice).right() < rect(window._diagnostics_button).left()
        assert all(window.rect().contains(rect(widget)) for widget in buttons)

    qtbot.waitUntil(assert_header)
    assert window._simulation_label.isVisible() == simulated
    if simulated:
        assert rect(window._simulation_label).left() > rect(window._title_label).right()
        assert "Bez Tobii mjerenja" in window._simulation_label.text()
    window._start_precision()
    qtbot.waitUntil(lambda: window._check is not None)
    window._stop_test()
    qtbot.waitUntil(assert_header)
    window._open_history()
    qtbot.waitUntil(assert_header)
    window.reset_check()
    window.set_calibration_notice("Tobii postavke nisu dostupne.")
    qtbot.waitUntil(assert_header)
    assert "Tobii postavke nisu dostupne" in window._notice.text()


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


def test_precision_summary_keeps_missing_and_unmeasured_targets_distinct(gaze_check, qtbot):
    window, _now, _screen = gaze_check
    window._start_precision()
    qtbot.waitUntil(lambda: window._check is not None)
    window._check.results = [
        FixationResult("Sredina", 90, 0.9, 12, 8, True, (0.5, 0.5)),
        FixationResult("Gore lijevo", 90, 0.9, 80, 12, False, (0.3, 0.3)),
        FixationResult("Gore desno", 2, 0.1, None, None, None, None),
    ]
    window._show_results()
    assert [label.text() for label in window._precision_counts.counts] == ["1", "1", "1", "2"]


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
    assert window._phase == "precision"
    qtbot.wait(1)
    assert window._check is not None


@pytest.mark.parametrize("missing", ["eyes", "gaze", "stale"])
def test_trial_without_fresh_gaze_explains_missing_data_and_retry(gaze_check, qtbot, missing):
    window, now, _screen = gaze_check
    window._start_precision()
    qtbot.wait(1)
    window._check.results = [
        FixationResult(name, 90, 0.9, 12, 8, True, (x, y)) for name, x, y in window._check.targets
    ]
    window._show_results()
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


def _feed_isolated_trial(window, now, samples, interruptions):
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
    return interruptions


@pytest.mark.parametrize("samples", ["single", "repeated", "sparse", "interrupted"])
def test_trial_with_isolated_gaze_prioritizes_tracking_over_fixation(gaze_check, qtbot, samples):
    window, now, _screen = gaze_check
    window._start_precision()
    qtbot.wait(1)
    window._check.results = [
        FixationResult(name, 90, 0.9, 12, 8, True, (x, y)) for name, x, y in window._check.targets
    ]
    window._show_results()
    window._start_trial()
    interruptions = 0
    for _ in range(3):
        interruptions = _feed_isolated_trial(window, now, samples, interruptions)
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
    window._show_results()
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
    "gaze_check,scenario",
    [
        (GazeSettings(selection_pause_ms=500, dwell_ms=500, edge_hold_ms=duration), scenario)
        for duration, scenario in ((0, 0), (120, 0), (240, 0), (120, 1), (120, 2))
    ],
    indirect=["gaze_check"],
)
def test_trial_uses_saved_edge_duration_even_when_gaze_enters_neighbor(gaze_check, scenario):
    window, _now, _screen = gaze_check
    window._start_trial()
    window._target.target_index = scenario
    first = window._target.button_rect(0)
    second = window._target.button_rect(1)
    a = first.center()
    b = QPoint(second.left() + 1, second.center().y())
    duration = window._settings.edge_hold_ms
    window._advance_trial_selection(a, 10.0)
    window._advance_trial_selection(a, 10.8)
    window._advance_trial_selection(b, 10.82)
    if duration:
        assert window._selection.target == 0
        assert window._selection.diagnostic_snapshot()["credited_ms"] == pytest.approx(800)
        window._advance_trial_selection(b, 10.821 + duration / 1000)
    assert window._selection.target == 1
    assert window._selection.diagnostic_snapshot()["credited_ms"] == 0


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


@pytest.mark.parametrize(
    "gaze_check",
    [
        GazeSettings(
            eye_tracking_policy="hold",
            eye_tracking_hold_ms=300,
            selection_pause_ms=850,
            dwell_ms=650,
        )
    ],
    indirect=True,
)
@pytest.mark.parametrize("credited_ms", [800, 1000])
def test_trial_counts_only_discarded_progress_at_each_hold_stage(gaze_check, qtbot, credited_ms):
    window, now, screen = gaze_check
    window._start_trial()
    qtbot.wait(1)
    point = window._target.mapToGlobal(window._target.button_rect().center())
    gaze = (
        (point.x() - screen.left()) / (screen.width() - 1),
        (point.y() - screen.top()) / (screen.height() - 1),
    )
    start = window._trial_ready_at + 0.01
    for elapsed in range(0, credited_ms + 1, 100):
        now[0] = start + elapsed / 1000
        window.handle_snapshot(CheckSnapshot(True, True, gaze=gaze, gaze_at=now[0]))
    assert window._selection.target is not None
    now[0] += 0.01
    lost_at = now[0]
    window.handle_eye_status(True, False)
    assert window._target.paused
    now[0] = lost_at + 0.301
    window._eye_gate._deadline.timeout.emit()
    assert window._trial_losses == (1 if credited_ms == 800 else 0)
    if credited_ms == 800:
        assert window._selection.target is None
        assert "Praćenje je prekinuto" in window._test_hint.text()
    else:
        assert window._target.paused
        assert window._target.progress == 0
        assert "početna pauza završena" in window._test_hint.text()
    now[0] = lost_at + 0.501
    window._eye_gate._deadline.timeout.emit()
    assert window._trial_losses == 1
    assert window._selection.target is None
    assert window._trial_results == []


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


def _pass_precision(window):
    window._check.results = [
        FixationResult(name, 90, 0.9, 12, 8, True, (x, y)) for name, x, y in window._check.targets
    ]
    window._show_results()


def _show_fit_phase(window, phase):
    if phase == "precision":
        window._start_precision()
    elif phase == "results":
        _pass_precision(window)
    elif phase == "details":
        window._details_button.click()
    elif phase == "trial":
        window._start_trial()
    elif phase == "trial-no-gaze":
        for _index in range(3):
            window._finish_trial_target(False, window._trial_deadline)
    elif phase == "free":
        window._start_free()


def _assert_fit_child(window, child, phase):
    from PySide6.QtWidgets import QPushButton, QScrollArea

    ancestor = child.parentWidget()
    while ancestor is not None and not isinstance(ancestor, QScrollArea):
        ancestor = ancestor.parentWidget()
    if ancestor is not None:
        viewport = ancestor.viewport()
        bounds = QRect(viewport.mapTo(window, QPoint()), viewport.size())
        assert window.rect().contains(bounds)
        return
    bounds = QRect(child.mapTo(window, QPoint(0, 0)), child.size())
    assert window.rect().contains(bounds), (phase, child.text(), bounds)
    if isinstance(child, QPushButton):
        assert child.height() >= (
            48 if child in (window._history_button, window._diagnostics_button) else 60
        )
        assert child.fontMetrics().horizontalAdvance(child.text()) + 32 <= child.width()
    elif child.hasHeightForWidth():
        assert child.heightForWidth(child.width()) <= child.height(), (phase, child.text())


@pytest.mark.parametrize("simulated", [False, True])
def test_check_buttons_and_labels_fit_at_150_percent(gaze_check, qtbot, simulated):
    from PySide6.QtWidgets import QLabel, QPushButton

    window, _now, _screen = gaze_check
    window._simulated = simulated
    for phase in ("position", "precision", "results", "details", "trial", "trial-no-gaze", "free"):
        _show_fit_phase(window, phase)
        qtbot.wait(1)
        assert (window.width(), window.height()) == (1280, 720)
        for child in window.findChildren(QWidget):
            if child.isVisible() and isinstance(child, (QLabel, QPushButton)):
                _assert_fit_child(window, child, phase)


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
        ([True, True, True], 0, 1, "govornu tastaturu"),
        ([True, True, False], 1, 0, "pogrešna dugmad"),
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
    window._trial_wrong_selections = wrong
    window._trial_losses = loss
    for choice in selected:
        start = window._trial_ready_at
        for sample in range(100):
            window._trial_coverage.add(start + sample * 0.02)
        window._finish_trial_target(choice, start + 2)
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
    window._show_results()
    window._start_trial()
    for _index in range(3):
        start = window._trial_ready_at
        for sample in range(100):
            window._trial_coverage.add(start + sample * 0.02)
        window._finish_trial_target(True, start + 2)
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
    assert "Čekam svjež validan pogled" in window._test_hint.text()
    assert "Zadržite pogled" not in window._test_hint.text()


@pytest.mark.parametrize("button,color", [(0, "#efd092"), (1, "#a3d5ba")])
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
