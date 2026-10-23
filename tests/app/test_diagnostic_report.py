from __future__ import annotations

import json

import pytest

from pogled_assist.diagnostic_report import LatencySummary
from pogled_assist.log_reader import summarize


def record(event, at, **data):
    return {
        "schema_version": 1,
        "session_id": "session-a",
        "process_instance": "process-a",
        "event": event,
        "monotonic_s": at,
        "data": data,
    }


def read_report(tmp_path, records):
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(json.dumps(item) for item in records), encoding="utf-8")
    return summarize(path)


def test_report_connects_nearby_evidence_including_later_heartbeat(tmp_path):
    result = read_report(
        tmp_path,
        [
            record("session_start", 0),
            record("eye_gate_applied", 9, left_valid=False, right_valid=True),
            record("delivery_gap", 9.2, gap_ms=700),
            record("selection_end", 9.3, reason="eye_gate_closed", elapsed_ms=1300),
            record("ui_heartbeat", 10, interval_s=1.5, qt_timer_late_ms=500),
            record("selection_end", 15, reason="completed", elapsed_ms=2100),
            record("session_end", 16),
        ],
    )
    analysis = result["analysis"]
    assert analysis["recent_selection_ends"][0]["nearby_observations"] == [
        "eye_gate_closed",
        "gaze_delivery_gap",
        "qt_delay_at_least_100ms",
    ]
    assert analysis["recent_selection_ends"][1]["nearby_observations"] == []
    assert analysis["observed_selection_outcomes"] == {"eye_gate_closed": 1, "completed": 1}
    assert "correlation does not establish cause" in analysis["interpretation"]


def test_report_uses_summaries_and_marks_suppressed_evidence_incomplete(tmp_path):
    result = read_report(
        tmp_path,
        [
            record("session_start", 0),
            record(
                "stream_summary",
                1,
                counts={"suppressed:eye_gate_received": 8},
                eye_state_seconds={"native:both_valid": 0.75, "native:stale_unknown": 0.25},
                qt_timer_max_late_ms=50,
            ),
            record(
                "stream_summary",
                2,
                counts={},
                eye_state_seconds={"native:both_valid": 1},
                qt_timer_max_late_ms=0,
            ),
            record("selection_summary", 2, counts={"suppressed:selection_end": 2}),
            record("session_end", 3),
        ],
    )
    analysis = result["analysis"]
    assert result["complete"]
    assert analysis["evidence_incomplete"]
    assert analysis["eye_state_seconds"]["native:both_valid"] == 1.75
    assert analysis["suppressed_events"]["suppressed:selection_end"] == 2
    assert analysis["latency"]["stream_interval_max_lateness"]["max_ms"] == 50
    assert analysis["latency"]["provider_receive_to_emit"]["p95_ms"] is None


@pytest.mark.parametrize("gate_open", [False, True])
def test_report_uses_recorded_application_eligibility(tmp_path, gate_open):
    result = read_report(
        tmp_path,
        [
            record("session_start", 0),
            record(
                "eye_gate_applied",
                1,
                left_valid=False,
                right_valid=True,
                application_gate_open=gate_open,
            ),
            record("selection_end", 1.1, reason="target_departure"),
            record("session_end", 2),
        ],
    )
    assert result["analysis"]["recent_selection_ends"][0]["nearby_observations"] == (
        [] if gate_open else ["eye_gate_closed"]
    )


@pytest.mark.parametrize(
    "reason,health,complete",
    [
        ("manual", {"dropped": {}, "writer_errors": 0, "bounded_snapshots": 0}, True),
        ("time", {"dropped": {"event": 0}, "writer_errors": 0, "bounded_snapshots": 0}, True),
        ("manual", {}, False),
        ("size", {}, False),
        ("shutdown", {}, False),
        ("writer_error", {}, False),
        ("unknown", {}, False),
        (None, {}, False),
        ("manual", {"dropped": {"event": 2}, "writer_errors": 0, "bounded_snapshots": 0}, False),
        ("manual", {"dropped": {}, "writer_errors": 1, "bounded_snapshots": 0}, False),
        ("manual", {"dropped": {}, "writer_errors": 0, "bounded_snapshots": 1}, False),
        ("manual", None, False),
        ("manual", "invalid", False),
    ],
)
def test_manual_report_requires_a_clean_recording_footer(tmp_path, reason, health, complete):
    result = read_report(
        tmp_path,
        [
            record("session_start", 0, mode="manual_trace"),
            record("session_end", 1, reason=reason, recording_health=health),
        ],
    )
    assert result["lifecycle_complete"]
    assert result["complete"] is complete
    assert result["analysis"]["evidence_incomplete"] is (not complete)
    assert result["session_end_reason"] == reason
    assert result["recording_health"] == (health if isinstance(health, dict) else None)


def test_manual_report_keeps_recording_health_separate_from_process_loss(tmp_path):
    process_health = {"dropped": {"event": 20}, "writer_errors": 1, "bounded_snapshots": 4}
    recording_health = {"dropped": {}, "writer_errors": 0, "bounded_snapshots": 0}
    start = record("session_start", 0, mode="manual_trace")
    start["logging_health"] = process_health
    result = read_report(
        tmp_path,
        [start, record("session_end", 1, reason="manual", recording_health=recording_health)],
    )
    assert result["complete"]
    assert not result["analysis"]["evidence_incomplete"]
    assert result["logging_health_process_cumulative"] == process_health
    assert result["recording_health"] == recording_health


@pytest.mark.parametrize(
    "field,invalid",
    [
        ("dropped", -1),
        ("dropped", 0.5),
        ("dropped", True),
        ("dropped", "2"),
        ("dropped", None),
        ("writer_errors", -1),
        ("bounded_snapshots", -1),
    ],
)
def test_manual_report_rejects_invalid_health_counters(tmp_path, field, invalid):
    health = {"dropped": {}, "writer_errors": 0, "bounded_snapshots": 0}
    health[field] = {"event": invalid} if field == "dropped" else invalid
    result = read_report(
        tmp_path,
        [
            record("session_start", 0, mode="manual_trace"),
            record("session_end", 1, reason="manual", recording_health=health),
        ],
    )
    assert not result["complete"]
    assert result["analysis"]["evidence_incomplete"]


@pytest.mark.parametrize("dropped", [None, "lost records", [], 0])
def test_manual_report_rejects_invalid_loss_mapping(tmp_path, dropped):
    result = read_report(
        tmp_path,
        [
            record("session_start", 0, mode="manual_trace"),
            record(
                "session_end",
                1,
                reason="manual",
                recording_health={"dropped": dropped, "writer_errors": 0, "bounded_snapshots": 0},
            ),
        ],
    )
    assert not result["complete"]
    assert result["analysis"]["evidence_incomplete"]


def test_report_does_not_mix_sessions_or_process_clocks(tmp_path):
    other_session = record("selection_end", 2, reason="completed")
    other_session["session_id"] = "session-b"
    other_process = record("eye_gate_applied", 2, left_valid=False)
    other_process["process_instance"] = "process-b"
    result = read_report(
        tmp_path,
        [
            record("session_start", 1),
            other_session,
            other_process,
            record("selection_end", 2, reason="target_departure"),
            record("session_end", 3),
        ],
    )
    assert result["session_id"] == "session-a"
    assert result["analysis"]["observed_selection_outcomes"] == {"target_departure": 1}
    assert result["analysis"]["recent_selection_ends"][0]["nearby_observations"] == []
    assert result["analysis"]["evidence_incomplete"]


def test_report_bounds_details_and_omits_content_fields(tmp_path):
    result = read_report(
        tmp_path,
        [
            record("session_start", 0),
            *[
                record("selection_end", i, reason="target_departure", text="PRIVATE TEXT")
                for i in range(501)
            ],
            record("session_end", 502),
        ],
    )
    assert len(result["analysis"]["recent_selection_ends"]) == 500
    assert result["analysis"]["observed_selection_outcomes"] == {"target_departure": 501}
    assert result["analysis"]["details_truncated"]
    assert "PRIVATE TEXT" not in json.dumps(result)


def test_latency_histogram_reports_tail_without_accepting_invalid_values():
    summary = LatencySummary()
    for value in [None, True, "12", -1, float("nan"), float("inf"), 10**1000]:
        summary.add(value)
    assert summary.result()["count"] == 0
    for value in [1.2] * 19 + [80_000]:
        summary.add(value)
    result = summary.result()
    assert result["count"] == 20
    assert result["mean_ms"] == pytest.approx((19 * 1.2 + 80_000) / 20)
    assert result["p95_ms"] == 2
    assert result["p99_ms"] == 60_000
    assert result["max_ms"] == 80_000
    assert result["over_cap_count"] == 1


def test_report_accepts_missing_or_malformed_optional_measurements(tmp_path):
    result = read_report(
        tmp_path,
        [
            record("session_start", 0),
            record("provider_gaze", 1, age_ms="unknown"),
            record("ui_heartbeat", 2, qt_timer_late_ms=False),
            record("selection_end", 3, reason={"bad": "value"}, elapsed_ms=-1),
            record("session_end", 4),
        ],
    )
    assert result["analysis"]["latency"]["provider_receive_to_emit"]["count"] == 0
    assert result["analysis"]["recent_selection_ends"][0]["outcome"] == "other_or_unknown"
