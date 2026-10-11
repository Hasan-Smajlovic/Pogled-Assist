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
from PySide6.QtCore import QEvent, Qt, QTimer

from pogled_assist import logging_setup
from pogled_assist.diagnostic_report import LatencySummary
from pogled_assist.interaction.mouse_controller import GazeMouseController
from pogled_assist.log_reader import summarize
from pogled_assist.log_transport import LogWriter, QueueLogHandler
from pogled_assist.suggestions.service import SuggestionService
from pogled_assist.tracking.gaze_provider import TobiiGazeProvider
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


def _measure_mode(mode, folder, qtbot, qapp, monkeypatch):
    folder.mkdir(parents=True)
    writer = LogWriter() if mode != "off" else None
    root = logging.getLogger()
    previous_disabled = root.manager.disable
    if writer is not None:
        writer.start_segment(folder / "logs" / "latest.txt", None, trace=mode == "trace")
    monkeypatch.setattr(logging_setup, "_writer", writer)
    monkeypatch.setattr(root, "handlers", [QueueLogHandler(writer)] if writer else [])
    monkeypatch.setattr(root, "level", logging.INFO)
    logging.disable(logging.NOTSET if writer else logging.CRITICAL)
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
    metrics = {
        name: LatencySummary()
        for name in (
            "callback_to_controller_done",
            "controller_work",
            "producer_work",
            "qt_timer_lateness",
        )
    }
    measuring = threading.Event()
    stopped = threading.Event()
    worker_errors = []
    produced = [0]
    memory = []

    def handle_gaze(x, y, stamp):
        before = time.perf_counter_ns()
        controller.handle_gaze(x, y, stamp)
        after = time.perf_counter_ns()
        if measuring.is_set():
            metrics["callback_to_controller_done"].add((after - stamp) / 1e6)
            metrics["controller_work"].add((after - before) / 1e6)

    def produce():
        sequence = 0
        was_measuring = False
        deadline = time.perf_counter()
        try:
            while not stopped.is_set():
                active = measuring.is_set()
                if active and not was_measuring:
                    sequence = 0
                was_measuring = active
                before = time.perf_counter_ns()
                # Same 60 Hz input and brief eye loss in every logging mode.
                eyes(True, sequence % 180 < 174, before)
                gaze(0.5, 0.5, before)
                if active:
                    produced[0] += 1
                    metrics["producer_work"].add((time.perf_counter_ns() - before) / 1e6)
                sequence += 1
                deadline += 1 / 60
                # Do not flood callbacks trying to replay a scheduler backlog.
                deadline = max(deadline, time.perf_counter())
                stopped.wait(max(0.0, deadline - time.perf_counter()))
        except Exception as error:
            worker_errors.append(type(error).__name__)

    provider.gaze_updated.connect(handle_gaze)
    tick_at = [time.perf_counter()]

    def heartbeat():
        now = time.perf_counter()
        if measuring.is_set():
            metrics["qt_timer_lateness"].add(max(0.0, (now - tick_at[0]) * 1000 - 20))
        tick_at[0] = now

    timer = QTimer()
    timer.setTimerType(Qt.TimerType.PreciseTimer)
    timer.setInterval(20)
    timer.timeout.connect(heartbeat)
    phase = [0]

    def change_surface():
        step = phase[0] % 6
        if step == 0:
            window.hide()
        elif step == 1:
            window.show()
        elif step in {2, 3}:
            window._switch_keyboard_script()
        elif step == 4:
            window._open_letter_dialog(0)
        else:
            if window._dialogs.active is not None:
                window._dialogs.active.done(0)
            window._input.setText("Dobro jutro" if phase[0] % 12 == 5 else "Dobar dan")
        phase[0] += 1
        if phase[0] == 12:
            surfaces.stop()
        if measuring.is_set():
            value = _working_set_bytes()
            if value is not None:
                memory.append(value)

    surfaces = QTimer()
    surfaces.setInterval(500)
    surfaces.timeout.connect(change_surface)
    worker = threading.Thread(target=produce, name="synthetic-gaze-benchmark", daemon=True)
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
        initial_memory = _working_set_bytes()
        if initial_memory is not None:
            memory.append(initial_memory)
        before_cpu, before_wall = time.process_time(), time.perf_counter()
        measuring.set()
        surfaces.start()
        qtbot.wait(6500)
        measuring.clear()
        elapsed = time.perf_counter() - before_wall
        cpu = time.process_time() - before_cpu
        final_memory = _working_set_bytes()
        if final_memory is not None:
            memory.append(final_memory)
    finally:
        measuring.clear()
        surfaces.stop()
        timer.stop()
        stopped.set()
        if worker.ident is not None:
            worker.join(3)
        provider.stop()
        window.close()
        suggestions.close()
        for resource in (window, provider, controller, timer, surfaces, suggestions):
            resource.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()
        if writer is not None:
            drained = writer.stop(5)
        logging.disable(previous_disabled)
    assert not worker.is_alive()
    assert not worker_errors
    assert metrics["callback_to_controller_done"].count > 0
    assert phase[0] == 12, "The complete surface workload must run in every mode"
    assert drained, "The logging worker did not finish"
    health = writer.health() if writer else None
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
    return {
        "mode": mode,
        "produced_samples": produced[0],
        "surface_changes": phase[0],
        "duration_s": elapsed,
        "cpu_percent_of_one_core": cpu / elapsed * 100,
        "working_set_initial_bytes": initial_memory,
        "working_set_final_bytes": final_memory,
        "working_set_sampled_peak_bytes": max(memory) if memory else None,
        "latency": {name: summary.result() for name, summary in metrics.items()},
        "log_bytes": sum(
            path.stat().st_size for path in (folder / "logs").rglob("*") if path.is_file()
        ),
        "writer_drained": drained,
        "logging_health": health,
    }


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
                result = _measure_mode(mode, output / f"{repeat}-{mode}", qtbot, qapp, patch)
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
            "Use repeated same-PC comparisons; these numbers are not portable pass/fail thresholds."
        ),
    }
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Gaze benchmark: {output / 'report.json'}")
