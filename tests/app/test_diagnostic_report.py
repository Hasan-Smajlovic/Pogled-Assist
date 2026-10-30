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


def test_counter_copy_without_baseline_counts_only_visible_intervals(tmp_path):
    result = read_report(
        tmp_path,
        [
            record("session_start", 10),
            record(
                "selection_summary",
                11,
                observation_stream_id="stream",
                interval_index=7,
                counts={"outcome:completed": 1},
                cumulative_counts={"outcome:completed": 42},
            ),
            record(
                "selection_summary",
                13,
                observation_stream_id="stream",
                interval_index=9,
                cumulative_counts={"outcome:completed": 44},
            ),
            record("session_end", 14),
        ],
    )
    analysis = result["analysis"]
    assert analysis["reason_totals_from_counters"] == {"outcome:completed": 3}
    assert analysis["missing_counter_intervals"] == 1
    assert analysis["partial_counter_streams"] == 1
    assert analysis["evidence_incomplete"]


def test_overlapping_counter_context_with_equal_timestamps_keeps_earlier_intervals(tmp_path):
    # Folder traversal reads the manual destination first. Its boundary snapshot
    # and later intervals must not hide the earlier ordinary interval.
    manual = tmp_path / "a.jsonl"
    ordinary = tmp_path / "z.jsonl"
    summary = dict(observation_stream_id="stream")
    manual.write_text(
        "\n".join(
            json.dumps(item)
            for item in [
                record("session_start", 10),
                record(
                    "segment_context",
                    10,
                    snapshot={
                        "event": "selection_summary",
                        "data": {
                            **summary,
                            "interval_index": 2,
                            "cumulative_counts": {"outcome:target_departure": 4},
                        },
                    },
                ),
                record(
                    "selection_summary",
                    10,
                    **summary,
                    interval_index=3,
                    counts={"outcome:completed": 2},
                    cumulative_counts={"outcome:target_departure": 4, "outcome:completed": 2},
                ),
                record("session_end", 11),
            ]
        ),
        encoding="utf-8",
    )
    rows = [
        record("session_start", 10),
        record(
            "selection_summary",
            10,
            **summary,
            interval_index=1,
            cumulative_counts={"outcome:target_departure": 3},
        ),
        record("session_end", 11),
    ]
    ordinary.write_text(
        "\n".join(json.dumps({**item, "session_id": "session-z"}) for item in rows),
        encoding="utf-8",
    )
    assert summarize(tmp_path)["analysis"]["reason_totals_from_counters"] == {
        "outcome:target_departure": 4,
        "outcome:completed": 2,
    }


def test_manual_baseline_does_not_hide_missing_initial_ordinary_intervals(tmp_path):
    ordinary = tmp_path / "ordinary.jsonl"
    ordinary.write_text(
        "\n".join(
            json.dumps(row) for row in [record("session_start", 0), record("session_end", 4)]
        ),
        encoding="utf-8",
    )
    initial = {
        "observation_stream_id": "stream",
        "observation_started_monotonic_s": 0.5,
        "observation_start_sessions": ["session-a"],
    }
    rows = [
        record("session_start", 2),
        record(
            "segment_context",
            2,
            snapshot={
                "event": "selection_summary",
                "data": {
                    **initial,
                    "interval_index": 2,
                    "cumulative_counts": {"outcome:completed": 4},
                },
            },
        ),
        record(
            "selection_summary",
            3,
            **initial,
            interval_index=3,
            counts={"outcome:completed": 2},
            cumulative_counts={"outcome:completed": 6},
        ),
        record("session_end", 4),
    ]
    manual = tmp_path / "manual.jsonl"
    manual.write_text(
        "\n".join(json.dumps({**row, "session_id": "session-manual"}) for row in rows),
        encoding="utf-8",
    )
    assert summarize(manual)["analysis"]["reason_totals_from_counters"] == {"outcome:completed": 2}
    merged = summarize(tmp_path)["analysis"]
    assert merged["reason_totals_from_counters"] == {"outcome:completed": 6}
    assert merged["missing_counter_intervals"] == 2


@pytest.mark.parametrize("index", [2**63, 2**100])
def test_folder_reader_keeps_evidence_with_large_counter_index(tmp_path, index):
    read_report(
        tmp_path,
        [
            record("session_start", 0),
            record(
                "selection_summary",
                1,
                observation_stream_id="stream",
                interval_index=index,
                counts={"outcome:completed": 1},
                cumulative_counts={"outcome:completed": 42},
            ),
            record("selection_end", 2, reason="completed"),
            record("session_end", 3),
        ],
    )
    result = summarize(tmp_path)
    assert result["analysis"]["reason_totals_from_counters"] == {"outcome:completed": 1}
    assert result["analysis"]["observed_selection_outcomes"] == {"completed": 1}


def test_bridge_observations_keep_failure_separate_from_shutdown_and_drop_extra_fields(tmp_path):
    result = read_report(
        tmp_path,
        [
            record("session_start", 0),
            record(
                "bridge_connection",
                1,
                decision="failure",
                stream_generation=4,
                reason="stdout_eof",
                process_state="running",
                exit_code=None,
                native_eye_age_ms=350,
                shutdown_requested=False,
                typed_text="PRIVATE MESSAGE",
            ),
            record(
                "bridge_connection",
                2,
                decision="shutdown",
                stream_generation=4,
                reason="app_shutdown",
                process_state="exited",
                exit_code=-15,
                native_eye_age_ms=400,
                shutdown_requested=True,
            ),
            record("session_end", 3),
        ],
    )
    events = result["analysis"]["bridge_connections"]
    assert events[0]["process_state"] == "running"
    assert events[0]["exit_code"] is None
    assert events[0]["native_eye_age_ms"] == 350
    assert not events[0]["shutdown_requested"]
    assert events[1]["exit_code"] == -15
    assert events[1]["shutdown_requested"]
    assert "PRIVATE MESSAGE" not in json.dumps(result)


def test_bridge_reader_bounds_observations_and_rejects_malformed_fields(tmp_path):
    result = read_report(
        tmp_path,
        [
            record("session_start", 0),
            *(
                record(
                    "bridge_connection",
                    index + 1,
                    decision=[],
                    process_state={},
                    reason="x" * 1000,
                    exit_code=True,
                    native_eye_age_ms=-1,
                )
                for index in range(70)
            ),
            record("session_end", 72),
        ],
    )
    events = result["analysis"]["bridge_connections"]
    assert len(events) == 64
    assert result["analysis"]["details_truncated"]
    assert events[0]["decision"] == "unknown"
    assert events[0]["process_state"] == "unknown"
    assert events[0]["exit_code"] is None
    assert events[0]["native_eye_age_ms"] is None
    assert len(events[0]["reason"]) == 128


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
