from __future__ import annotations

from types import SimpleNamespace

import pytest

from gaze_mouse.gaze_provider import (
    TobiiGazeProvider,
    _choose_tracker,
    _normalize_stream_engine_point,
    _tracker_label,
    _valid_gaze_point,
)


def test_valid_gaze_point_requires_valid_finite_coordinates():
    data = {
        "left_gaze_point_validity": 1,
        "left_gaze_point_on_display_area": (0.25, 0.75),
    }
    assert _valid_gaze_point(data, "left") == (0.25, 0.75)

    for point in ((float("nan"), 0.5), (0.5, float("inf")), None, (0.5,)):
        data["left_gaze_point_on_display_area"] = point
        assert _valid_gaze_point(data, "left") is None

    data["left_gaze_point_validity"] = 0
    data["left_gaze_point_on_display_area"] = (0.25, 0.75)
    assert _valid_gaze_point(data, "left") is None


def test_tracker_choice_prefers_4c_and_builds_readable_labels():
    generic = SimpleNamespace(model="Tobii Pro", device_name="", serial_number="123")
    tracker_4c = SimpleNamespace(model="", device_name="Eye Tracker 4C", serial_number="ABC")

    assert _choose_tracker((generic, tracker_4c)) is tracker_4c
    assert _tracker_label(tracker_4c) == "Eye Tracker 4C ABC"
    assert _tracker_label(SimpleNamespace()) == "Tobii eye tracker"


@pytest.mark.parametrize(
    ("point", "geometry", "expected"),
    [
        ((0.2, 0.8), (0, 0, 1920, 1080), (0.2, 0.8)),
        ((-0.2, 1.2), (0, 0, 1920, 1080), (0.0, 1.0)),
        ((100.0, 50.0), (0, 0, 201, 101), (0.5, 0.5)),
        ((150.0, 250.0), (100, 200, 101, 101), (0.5, 0.5)),
        ((500.0, -50.0), None, (1.0, 0.0)),
    ],
)
def test_stream_engine_coordinates_are_normalized_and_clamped(point, geometry, expected):
    assert _normalize_stream_engine_point(*point, geometry) == pytest.approx(expected)


def test_provider_averages_two_valid_eyes_and_coalesces_samples(qapp):
    provider = TobiiGazeProvider()
    gaze = []
    eyes = []
    provider.gaze_updated.connect(lambda x, y, timestamp: gaze.append((x, y, timestamp)))
    provider.eye_status_changed.connect(lambda left, right: eyes.append((left, right)))

    provider._on_gaze_data(
        {
            "left_gaze_point_validity": 1,
            "left_gaze_point_on_display_area": (0.2, 0.4),
            "right_gaze_point_validity": 1,
            "right_gaze_point_on_display_area": (0.6, 0.8),
            "system_time_stamp": 42,
        }
    )
    provider._emit_latest_gaze_sample()

    assert eyes == [(True, True)]
    assert gaze[0][:2] == pytest.approx((0.4, 0.6))
    assert gaze[0][2] == 42

    provider._queue_gaze_sample("test", 0.1, 0.9, 42)
    provider._queue_gaze_sample("test", 0.9, 0.1, 43)
    provider._emit_latest_gaze_sample()

    assert gaze[-1] == (0.9, 0.1, 43)
    assert provider._dropped_sample_count == 1


def test_provider_stops_emitting_when_either_eye_is_invalid(qapp):
    provider = TobiiGazeProvider()
    gaze = []
    eyes = []
    provider.gaze_updated.connect(lambda *sample: gaze.append(sample))
    provider.eye_status_changed.connect(lambda left, right: eyes.append((left, right)))
    provider._queue_gaze_sample("test", 0.5, 0.5, 1)

    provider._on_gaze_data(
        {
            "left_gaze_point_validity": 1,
            "left_gaze_point_on_display_area": (0.2, 0.4),
            "right_gaze_point_validity": 0,
        }
    )
    provider._emit_latest_gaze_sample()

    assert eyes == [(True, False)]
    assert gaze == []
