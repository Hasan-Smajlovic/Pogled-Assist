from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from pogled_assist.tracking.gaze_check import CheckSnapshot, CheckTelemetry, FixationCheck
from pogled_assist.tracking.gaze_provider import TobiiGazeProvider


def test_diagnostics_are_opt_in_and_closing_discards_measurements(qapp):
    provider = TobiiGazeProvider()
    provider._on_stream_engine_eye_status(True, True, 1)
    provider._on_stream_engine_gaze(0.5, 0.5, 1)
    assert provider.check_snapshot() == CheckSnapshot()
    provider.set_check_active(True)
    provider._on_stream_engine_eye_status(True, True, 2)
    provider._on_stream_engine_gaze(0.5, 0.5, 2)
    assert provider.check_snapshot().gaze == (0.5, 0.5)
    provider.set_check_active(False)
    assert provider.check_snapshot() == CheckSnapshot()
    gaze = []
    provider.gaze_updated.connect(lambda *args: gaze.append(args))
    provider._on_stream_engine_gaze(0.4, 0.6, 3)
    provider._emit_latest_gaze_sample()
    assert gaze == [(0.4, 0.6, 3)]


def test_coalesced_blink_is_delivered_before_diagnostic_sample(qapp):
    import threading

    provider = TobiiGazeProvider()
    provider.set_check_active(True)
    gaze, eyes = provider._new_stream_callbacks()
    eyes(True, True, 1)
    events = []
    provider.eye_status_changed.connect(lambda left, right: events.append((left, right)))
    provider.diagnostics_updated.connect(lambda _sample: events.append("diagnostic"))

    def worker():
        eyes(False, True, 2)
        eyes(True, True, 3)
        gaze(0.5, 0.5, 3)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(2)
    assert not thread.is_alive()
    provider._emit_latest_gaze_sample()
    assert events == [(False, True), (True, True), "diagnostic"]


def test_availability_is_time_weighted_and_brief_blink_is_not_instability():
    telemetry = CheckTelemetry()
    for i in range(501):
        now = i / 100
        telemetry.record_eyes(not (2.0 <= now < 2.1), True, now)
    result = telemetry.snapshot(5.0)
    assert result.observed_seconds == 5.0
    assert result.available_fraction == pytest.approx(0.98)
    assert result.longest_loss_seconds == pytest.approx(0.1)
    assert result.stable is True


def test_long_loss_and_missing_samples_cannot_remain_green():
    telemetry = CheckTelemetry()
    for i in range(41):
        now = i / 10
        telemetry.record_eyes(not (2 <= now < 3), True, now)
    telemetry.positions = ((0.4, 0.5, 0.6), (0.6, 0.5, 0.6), 4.0)
    telemetry.record_gaze(0.5, 0.5, 4.0)
    assert telemetry.snapshot(4.0).stable is False
    assert telemetry.snapshot(4.0).in_box((2,)) is True
    expired = telemetry.snapshot(4.6)
    assert expired.left is expired.right is None
    assert expired.gaze is None
    assert expired.in_box((2,)) is None
    assert expired.stable is None
    # Resuming after an unreported gap must include that gap in the history.
    telemetry.record_eyes(True, True, 10)
    assert telemetry.snapshot(10).available_fraction < 0.5
    assert telemetry.snapshot(10).longest_loss_seconds >= 5


def test_one_eye_and_out_of_box_coordinates_are_not_passes():
    telemetry = CheckTelemetry()
    telemetry.record_eyes(True, True, 1)
    telemetry.positions = ((0.4, 0.5, 1.2), (0.6, 0.5, 1.3), 1)
    assert telemetry.snapshot(1).in_box((0, 1)) is True
    assert telemetry.snapshot(1).in_box((2,)) is False
    telemetry.record_eyes(True, False, 1.1)
    telemetry.positions = ((0.4, 0.5, 0.6), None, 1.1)
    assert telemetry.snapshot(1.1).right_position is None
    assert telemetry.snapshot(1.1).in_box((0, 1)) is None


@pytest.mark.parametrize("offset,near", [(0.0, True), (0.15, False), (2.0, False)])
def test_fixation_measures_unclamped_error_after_settling(offset, near):
    check = FixationCheck([("Center", 0.5, 0.5)], (1280, 720), 36, 10)
    # Wrong gaze during the settling second must not bias measured accuracy.
    for i in range(150):
        at = 10 + i * 0.02
        x = 0.0 if at < 11 else 0.5 + offset
        check.add(CheckSnapshot(True, True, gaze=(x, 0.5), gaze_at=at), at)
    assert check.advance(13)
    assert check.finished
    result = check.results[0]
    assert result.near is near
    assert result.median_error == pytest.approx(abs(offset) * 1279)
    assert result.spread == 0


def test_repeated_sample_or_short_burst_cannot_pass_and_targets_do_not_skip_after_stall():
    check = FixationCheck([("One", 0.5, 0.5), ("Two", 0.2, 0.2)], (1280, 720), 36, 0)
    sample = CheckSnapshot(True, True, gaze=(0.5, 0.5), gaze_at=1.1)
    for _ in range(100):
        check.add(sample, 1.1)
    assert check.advance(30)
    assert not check.finished
    assert check.index == 1
    assert check.started_at == 30
    assert check.results[0].near is None
    assert check.results[0].samples == 1


@pytest.mark.parametrize(
    "interruption",
    [
        CheckSnapshot(),
        CheckSnapshot(False, True, gaze=(0.5, 0.5)),
        CheckSnapshot(True, False, gaze=(0.5, 0.5)),
        CheckSnapshot(True, True, gaze=(float("nan"), 0.5)),
    ],
)
def test_fixation_does_not_count_time_across_invalid_snapshots(interruption):
    check = FixationCheck([("Center", 0.5, 0.5)], (1280, 720), 36, 0)
    for sample in range(20):
        at = 1 + sample * 0.1
        check.add(CheckSnapshot(True, True, gaze=(0.5, 0.5), gaze_at=at), at)
        check.add(replace(interruption, gaze_at=at + 0.01), at + 0.01)
    check.advance(3)
    assert check.results[0].samples == 20
    assert check.results[0].coverage == 0
    assert check.results[0].near is None


def test_fixation_keeps_valid_intervals_around_a_blink_and_resets_between_targets():
    check = FixationCheck([("One", 0.5, 0.5), ("Two", 0.5, 0.5)], (1280, 720), 36, 0)
    for sample in range(100):
        at = 1 + sample * 0.02
        if 40 <= sample < 45:
            check.add(CheckSnapshot(False, True), at)
        else:
            check.add(CheckSnapshot(True, True, gaze=(0.5, 0.5), gaze_at=at), at)
    check.advance(3)
    assert check.results[0].near is True
    assert check.results[0].coverage == pytest.approx(0.93)
    sample = CheckSnapshot(True, True, gaze=(0.5, 0.5), gaze_at=4.0)
    check.add(sample, 4.0)
    check.interrupt()
    check.add(sample, 4.01)
    check.add(replace(sample, gaze_at=4.02), 4.02)
    check.advance(6)
    assert check.results[1].samples == 2
    assert check.results[1].coverage == 0
    assert check.results[1].near is None


def test_fixation_spread_rejects_scattered_gaze_even_with_good_median():
    check = FixationCheck([("Center", 0.5, 0.5)], (1280, 720), 36, 0)
    for i in range(100):
        at = 1 + i * 0.02
        x = 0.5 if i < 75 else 0.8
        check.add(CheckSnapshot(True, True, gaze=(x, 0.5), gaze_at=at), at)
    check.advance(3)
    assert check.results[0].median_error == 0
    assert check.results[0].spread > 100
    assert check.results[0].near is False


def test_provider_diagnostics_keep_raw_coordinates_and_expire_positions(qapp, monkeypatch):
    now = [1.0]
    monkeypatch.setattr("pogled_assist.tracking.gaze_provider.time.monotonic", lambda: now[0])
    provider = TobiiGazeProvider()
    provider.set_check_active(True)
    backend = SimpleNamespace()
    gaze, eyes = provider._new_stream_callbacks()
    provider._attach_check_observers(backend)
    eyes(True, True, 1)
    backend.eye_position_callback((0.4, 0.5, 0.6), (0.6, 0.5, 0.6), 1)
    gaze(-0.2, 1.5, 1)
    delivered = []
    provider.gaze_updated.connect(lambda x, y, _t: delivered.append((x, y)))
    provider._emit_latest_gaze_sample()
    assert delivered == [(0, 1)]  # Existing control mapping is unchanged.
    assert provider.check_snapshot().gaze == (-0.2, 1.5)
    assert provider.check_snapshot().in_box((2,)) is True
    now[0] = 1.6
    assert provider.check_snapshot().left is None
    assert provider.check_snapshot().left_position is None
    provider.stop()
    eyes(True, True, 2)
    backend.eye_position_callback((0.4, 0.5, 0.6), (0.6, 0.5, 0.6), 2)
    gaze(0.5, 0.5, 2)
    assert provider.check_snapshot() == CheckSnapshot()


@pytest.mark.parametrize("gaze_valid,origin_valid", [(0, 0), (0, 1), (1, 0), (1, 1)])
def test_research_positions_use_origin_validity_not_gaze_validity(qapp, gaze_valid, origin_valid):
    provider = TobiiGazeProvider()
    provider.set_check_active(True)
    provider._on_gaze_data(
        {
            "left_gaze_point_validity": gaze_valid,
            "right_gaze_point_validity": gaze_valid,
            "left_gaze_point_on_display_area": (0.5, 0.5),
            "right_gaze_point_on_display_area": (0.5, 0.5),
            "left_gaze_origin_validity": origin_valid,
            "right_gaze_origin_validity": 1,
            "left_gaze_origin_in_trackbox_coordinate_system": (0.4, 0.5, 0.6),
            "right_gaze_origin_in_trackbox_coordinate_system": (0.6, 0.5, 0.6),
        }
    )
    snapshot = provider.check_snapshot()
    assert snapshot.left is bool(gaze_valid)
    assert snapshot.left_position == ((0.4, 0.5, 0.6) if origin_valid else None)
    assert snapshot.right_position == (0.6, 0.5, 0.6)
    assert snapshot.gaze == ((0.5, 0.5) if gaze_valid else None)


def test_positions_expire_and_clear_without_fresh_gaze_validity():
    telemetry = CheckTelemetry()
    telemetry.positions = ((0.4, 0.5, 0.6), (0.6, 0.5, 0.6), 1)
    snapshot = telemetry.snapshot(1)
    assert snapshot.left is snapshot.right is None
    assert snapshot.left_position == (0.4, 0.5, 0.6)
    assert snapshot.in_box((0, 1, 2)) is True
    assert snapshot.gaze is None
    assert telemetry.snapshot(1.5).left_position is None
    assert telemetry.snapshot(1.5).right_position is None
    telemetry.positions = (None, None, 1.6)
    assert telemetry.snapshot(1.6).in_box((0, 1, 2)) is None


def test_position_expiry_is_independent_of_fresh_eye_and_gaze_stream(qapp, monkeypatch):
    now = [1.0]
    monkeypatch.setattr("pogled_assist.tracking.gaze_provider.time.monotonic", lambda: now[0])
    provider = TobiiGazeProvider()
    provider.set_check_active(True)
    backend = SimpleNamespace()
    provider._attach_check_observers(backend)
    backend.eye_position_callback((0.4, 0.5, 0.6), (0.6, 0.5, 0.6), 1)
    now[0] = 2
    provider._on_stream_engine_eye_status(True, True, 2)
    provider._on_stream_engine_gaze(0.5, 0.5, 2)
    snapshot = provider.check_snapshot()
    assert snapshot.left is True
    assert snapshot.gaze == (0.5, 0.5)
    assert snapshot.left_position is None
    assert replace(snapshot, observed_seconds=4).in_box((2,)) is None
