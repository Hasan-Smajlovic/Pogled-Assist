r"""Opt-in software benchmark, excluded from ordinary verification by default.

On the same Windows PC, close other workloads and run in PowerShell:
    $env:POGLED_ASSIST_RUN_GAZE_BENCHMARK = '1'
    .\dev.ps1 test -Workers 1 -TestPaths tests/ui/test_gaze_performance.py
    Remove-Item Env:POGLED_ASSIST_RUN_GAZE_BENCHMARK

Results and synthetic logs go to a unique dist/gaze-benchmark directory. Compare
repeated runs on the same machine and Qt platform. No tracker, Windows input,
speech process, user settings or personal learning data is accessed. This is not
a hardware benchmark or a measurement of physical gaze-to-screen latency.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import platform
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest
from _ui_fakes import FakeAlarmSound, FakeLibraryStore, FakeSpeech
from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer

from pogled_assist import logging_setup
from pogled_assist.diagnostic_report import LatencySummary
from pogled_assist.interaction.mouse_controller import GazeMouseController
from pogled_assist.log_reader import summarize
from pogled_assist.log_transport import LogWriter, QueueLogHandler
from pogled_assist.suggestions.service import SuggestionService
from pogled_assist.tracking.gaze_provider import (
    GAZE_DELIVERY_GAP_SECONDS,
    GAZE_EMIT_INTERVAL_MS,
    TobiiGazeProvider,
)
from pogled_assist.ui.speech_window import SpeechWindow

pytestmark = pytest.mark.skipif(
    os.environ.get("POGLED_ASSIST_RUN_GAZE_BENCHMARK") != "1" or sys.platform != "win32",
    reason="Explicit opt-in and Windows are required for the gaze performance benchmark",
)


def _working_set_bytes() -> int | None:
    from ctypes import wintypes

    class MemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("faults", wintypes.DWORD),
            *[
                (name, ctypes.c_size_t)
                for name in (
                    "peak_working",
                    "working",
                    "peak_paged",
                    "paged",
                    "peak_nonpaged",
                    "nonpaged",
                    "pagefile",
                    "peak_pagefile",
                )
            ],
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(MemoryCounters),
        wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = MemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(
        kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
    ):
        return None
    return counters.working


def _benchmark_logging(mode, folder, monkeypatch):
    writer = LogWriter() if mode != "off" else None
    root = logging.getLogger()
    previous_disabled = root.manager.disable
    if writer is not None:
        writer.start_segment(folder / "logs" / "latest.txt", None, trace=mode == "trace")
    monkeypatch.setattr(logging_setup, "_writer", writer)
    monkeypatch.setattr(root, "handlers", [QueueLogHandler(writer)] if writer else [])
    monkeypatch.setattr(root, "level", logging.INFO)
    logging.disable(logging.NOTSET if writer else logging.CRITICAL)
    return writer, previous_disabled


class _BenchmarkProbe:
    def __init__(self, window, controller, gaze, eyes):
        self.window = window
        self.controller = controller
        self.gaze = gaze
        self.eyes = eyes
        self.metrics = {
            name: LatencySummary()
            for name in (
                "callback_to_controller_done",
                "controller_work",
                "producer_work",
                "qt_timer_lateness",
                "delivery_interval",
            )
        }
        self.measuring = threading.Event()
        self.stopped = threading.Event()
        self.worker_errors = []
        self.produced = 0
        self.eligible = 0
        self.last_delivery_at = None
        self.max_delivery_gap_ms = 0.0
        self.memory = []
        self.tick_at = time.perf_counter()
        self.phase = 0
        self.surfaces = None

    def handle_gaze(self, x, y, stamp):
        before = time.perf_counter_ns()
        self.controller.handle_gaze(x, y, stamp)
        after = time.perf_counter_ns()
        if self.measuring.is_set():
            self.metrics["callback_to_controller_done"].add((after - stamp) / 1e6)
            self.metrics["controller_work"].add((after - before) / 1e6)
            self._delivery_interval(after / 1e9)

    def _delivery_interval(self, delivered_at):
        if self.last_delivery_at is not None:
            gap_ms = max(0.0, (delivered_at - self.last_delivery_at) * 1000)
            self.metrics["delivery_interval"].add(gap_ms)
            self.max_delivery_gap_ms = max(self.max_delivery_gap_ms, gap_ms)
        self.last_delivery_at = delivered_at

    def produce(self):
        sequence = 0
        was_measuring = False
        deadline = time.perf_counter()
        try:
            while not self.stopped.is_set():
                active = self.measuring.is_set()
                if active and not was_measuring:
                    sequence = 0
                was_measuring = active
                self._produce_sample(sequence, active)
                sequence += 1
                deadline += 1 / 60
                # Do not flood callbacks trying to replay a scheduler backlog.
                deadline = max(deadline, time.perf_counter())
                self.stopped.wait(max(0.0, deadline - time.perf_counter()))
        except Exception as error:
            self.worker_errors.append(type(error).__name__)

    def _produce_sample(self, sequence, active):
        before = time.perf_counter_ns()
        # Same 60 Hz input and brief eye loss in every logging mode.
        both_valid = sequence % 180 < 174
        self.eyes(True, both_valid, before)
        self.gaze(0.5, 0.5, before)
        if active:
            self.produced += 1
            self.eligible += int(both_valid)
            self.metrics["producer_work"].add((time.perf_counter_ns() - before) / 1e6)

    def heartbeat(self):
        now = time.perf_counter()
        if self.measuring.is_set():
            self.metrics["qt_timer_lateness"].add(max(0.0, (now - self.tick_at) * 1000 - 20))
        self.tick_at = now

    def change_surface(self):
        self._show_phase(self.phase % 6)
        self.phase += 1
        if self.phase == 12:
            self.surfaces.stop()
        if self.measuring.is_set():
            self.sample_memory()

    def _show_phase(self, step):
        if step == 0:
            self.window.hide()
        elif step == 1:
            self.window.show()
        elif step in {2, 3}:
            self.window._switch_keyboard_script()
        elif step == 4:
            self.window._show_letter_group(0)
        else:
            if self.window._dialogs.active is not None:
                self.window._dialogs.active.done(0)
            self.window._input.setText("Dobro jutro" if self.phase % 12 == 5 else "Dobar dan")

    def sample_memory(self):
        value = _working_set_bytes()
        if value is not None:
            self.memory.append(value)
        return value


def _measure_mode(mode, folder, qtbot, monkeypatch):
    folder.mkdir(parents=True)
    writer, previous_disabled = _benchmark_logging(mode, folder, monkeypatch)
    suggestions = SuggestionService(path=folder / "learning.json")
    window = SpeechWindow(
        FakeSpeech(),
        library_store=FakeLibraryStore(),
        alarm_sound=FakeAlarmSound(),
        suggestions=suggestions,
    )
    # Each mode owns and deletes its widgets before the next mode starts.
    # Registering with qtbot as well would close an already deleted C++ object.
    window.setGeometry(0, 0, 1280, 720)
    window.show()
    controller = GazeMouseController(window, pointer_movement_enabled=False)
    controller._logical_screen_rect = (0, 0, 1280, 720)
    controller._physical_screen_rect = (0, 0, 1280, 720)
    # Never start the Windows input backend or dispatch gaze actions to the UI.
    window.interaction_context_changed.connect(controller.cancel_toolbar_interaction)
    provider = TobiiGazeProvider()
    gaze, eyes = provider._new_stream_callbacks()
    provider.eye_status_changed.connect(controller.handle_eye_status)
    probe = _BenchmarkProbe(window, controller, gaze, eyes)
    provider.gaze_updated.connect(probe.handle_gaze)
    timer = QTimer()
    timer.setTimerType(Qt.TimerType.PreciseTimer)
    timer.setInterval(20)
    timer.timeout.connect(probe.heartbeat)
    surfaces = QTimer()
    surfaces.setInterval(500)
    surfaces.timeout.connect(probe.change_surface)
    probe.surfaces = surfaces
    worker = threading.Thread(target=probe.produce, name="synthetic-gaze-benchmark", daemon=True)
    drained = True
    try:
        provider._emit_timer.start()
        timer.start()
        worker.start()
        # Load the real bundled suggestions model before steady-state measurement.
        suggestions.request("benchmark-warmup", 1, "Dobro")
        qtbot.waitUntil(lambda: not suggestions._predicting, timeout=30_000)
        qtbot.wait(1000)
        assert not suggestions.status
        initial_memory = probe.sample_memory()
        before_cpu, before_wall = time.process_time(), time.perf_counter()
        with provider._sample_lock:
            replaced_before = provider._dropped_sample_count
        probe.last_delivery_at = before_wall
        probe.measuring.set()
        surfaces.start()
        qtbot.wait(6500)
        probe.measuring.clear()
        elapsed = time.perf_counter() - before_wall
        measurement_end = before_wall + elapsed
        probe.max_delivery_gap_ms = max(
            probe.max_delivery_gap_ms, (measurement_end - probe.last_delivery_at) * 1000
        )
        with provider._sample_lock:
            replaced_samples = provider._dropped_sample_count - replaced_before
        cpu = time.process_time() - before_cpu
        final_memory = probe.sample_memory()
    finally:
        probe.measuring.clear()
        surfaces.stop()
        timer.stop()
        probe.stopped.set()
        if worker.ident is not None:
            worker.join(3)
        provider.stop()
        window.close()
        suggestions.close()
        for resource in (window, provider, controller, timer, surfaces, suggestions):
            resource.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()
        if writer is not None:
            drained = writer.stop(5)
        logging.disable(previous_disabled)
    assert not worker.is_alive()
    assert not probe.worker_errors
    delivered_samples = probe.metrics["callback_to_controller_done"].count
    delivered_hz = delivered_samples / elapsed
    # A short latency among a few surviving samples cannot make a starved
    # pipeline a valid performance result. Include eye-loss pauses in the gap.
    assert delivered_hz >= 0.5 * (1000 / GAZE_EMIT_INTERVAL_MS), "Too few delivered samples"
    assert probe.max_delivery_gap_ms < GAZE_DELIVERY_GAP_SECONDS * 1000, "Gaze delivery stalled"
    assert probe.phase == 12, "The complete surface workload must run in every mode"
    assert drained, "The logging worker did not finish"
    health = writer.health() if writer else None
    _assert_complete_session(health, folder, mode)
    return {
        "mode": mode,
        "produced_samples": probe.produced,
        "eligible_samples": probe.eligible,
        "delivered_samples": delivered_samples,
        "produced_hz": probe.produced / elapsed,
        "delivered_hz": delivered_hz,
        "provider_replaced_samples": replaced_samples,
        "max_delivery_gap_ms": probe.max_delivery_gap_ms,
        "surface_changes": probe.phase,
        "duration_s": elapsed,
        "cpu_percent_of_one_core": cpu / elapsed * 100,
        "working_set_initial_bytes": initial_memory,
        "working_set_final_bytes": final_memory,
        "working_set_sampled_peak_bytes": max(probe.memory) if probe.memory else None,
        "latency": {name: summary.result() for name, summary in probe.metrics.items()},
        "log_bytes": sum(
            path.stat().st_size for path in (folder / "logs").rglob("*") if path.is_file()
        ),
        "writer_drained": drained,
        "logging_health": health,
    }


def _assert_complete_session(health, folder, mode):
    if health is not None:
        assert not health["writer_errors"], "Logging failed; performance results are invalid"
        assert not health["dropped"], "Logging lost records; performance results are invalid"
        assert not health["bounded_snapshots"], "Logging truncated records"
        paths = list((folder / "logs" / "diagnostics").glob("*.jsonl"))
        assert len(paths) == 1
        session = summarize(paths[0])
        assert session["complete"], "The diagnostic session must be readable and complete"
        assert session["events"].get("stream_summary", 0) > 0
        assert bool(session["events"].get("provider_gaze")) == (mode == "trace")


def test_gaze_logging_performance(qtbot, qapp, monkeypatch, request):
    if hasattr(request.config, "workerinput"):
        pytest.skip("Run with -Workers 1 to avoid concurrent benchmark interference")
    output = Path(__file__).resolve().parents[2] / "dist" / "gaze-benchmark" / uuid.uuid4().hex
    runs = []
    modes = ("off", "basic", "trace")
    # Rotate order so warm caches and thermal changes do not always favor one mode.
    for repeat in range(3):
        for mode in modes[repeat:] + modes[:repeat]:
            with monkeypatch.context() as patch:
                result = _measure_mode(mode, output / f"{repeat}-{mode}", qtbot, patch)
                runs.append({"repeat": repeat, **result})
    report = {
        "schema_version": 1,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "pyside": pyside_version,
        "qt_platform": qapp.platformName(),
        "logical_size": [1280, 720],
        "synthetic_input_hz": 60,
        "runs": runs,
        "comparisons_vs_off": [
            {
                "repeat": run["repeat"],
                "mode": run["mode"],
                "same_surface_change_count": run["surface_changes"] == baseline["surface_changes"],
                "cpu_percentage_point_delta": (
                    run["cpu_percent_of_one_core"] - baseline["cpu_percent_of_one_core"]
                ),
                "delivered_hz_delta": run["delivered_hz"] - baseline["delivered_hz"],
                "max_delivery_gap_delta_ms": (
                    run["max_delivery_gap_ms"] - baseline["max_delivery_gap_ms"]
                ),
                "callback_to_controller_p95_delta_ms": (
                    run["latency"]["callback_to_controller_done"]["p95_ms"]
                    - baseline["latency"]["callback_to_controller_done"]["p95_ms"]
                ),
            }
            for run in runs
            if run["mode"] != "off"
            for baseline in runs
            if baseline["mode"] == "off" and baseline["repeat"] == run["repeat"]
        ],
        "limits": (
            "Software-only warmed Speech UI workload; opening/hiding, keyboard scripts, letters "
            "and real offline suggestions. No rendering-completion or hardware latency measurement. "
            "CPU covers this pytest process, including the producer and logging workers. "
            "Memory is sampled, not an OS peak. File logging has no console sink. "
            "Log byte totals include warmup and shutdown; CPU and latency cover measurement only. "
            "Provider replacements are expected with 60 Hz input and a 20 ms delivery timer. "
            "Delivery rate and maximum gaps include intentional short eye-loss periods. "
            "Delivery guards reject a starved workload; comparisons measure logging overhead. "
            "Use repeated same-PC comparisons; these numbers are not portable pass/fail thresholds."
        ),
    }
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Gaze benchmark: {output / 'report.json'}")
