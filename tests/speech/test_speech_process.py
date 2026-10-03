from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path

import pytest
from PySide6.QtCore import QThread

from pogled_assist.speech import speech_service
from pogled_assist.windows.speech_process import WindowsSpeechProcess


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(speech_service, "find_espeak_ng", lambda: Path("synthetic.exe"))
    monkeypatch.setattr(speech_service, "find_edge_playback", lambda: None)
    instance = speech_service.SpeechService()
    yield instance
    instance.stop()


def test_playback_reports_delayed_failure_on_qt_thread_without_waiting(
    service, monkeypatch, qtbot, caplog
):
    started, release, closed = threading.Event(), threading.Event(), threading.Event()
    fail_playback = threading.Event()

    class Process:
        def poll(self):
            return 9 if fail_playback.is_set() else None

        def close(self):
            closed.set()

    def start(*_args):
        started.set()
        assert release.wait(3), "UI did not regain control during startup"
        return Process()

    monkeypatch.setattr(speech_service, "start_speech_process", start)
    events = []
    service.playback_changed.connect(
        lambda request, state: events.append((request, state, QThread.currentThread()))
    )
    caplog.set_level(logging.INFO)
    try:
        assert service.speak("Synthetic private message")
        assert started.wait(1)
        assert events == []
        release.set()
        qtbot.waitUntil(lambda: any(state == "speaking" for _, state, _ in events))
        fail_playback.set()
        qtbot.waitUntil(lambda: any(state == "failed" for _, state, _ in events))
        assert all(thread == service.thread() for _, _, thread in events)
        assert closed.is_set()
        assert "Synthetic private message" not in caplog.text
        assert "code 9" in caplog.text
    finally:
        release.set()
        fail_playback.set()


def test_replacement_waits_for_cleanup_without_blocking_ui_and_discards_old_events(
    service, monkeypatch, qtbot
):
    closing, release, second_started = threading.Event(), threading.Event(), threading.Event()
    calls = []

    class Process:
        def __init__(self, index):
            self.index = index

        def poll(self):
            return None if self.index == 0 else 0

        def close(self):
            if self.index == 0:
                closing.set()
                assert release.wait(3)

    def start(*_args):
        index = len(calls)
        calls.append(index)
        if index:
            second_started.set()
        return Process(index)

    monkeypatch.setattr(speech_service, "start_speech_process", start)
    events = []
    service.playback_changed.connect(lambda request, state: events.append((request, state)))
    try:
        service.speak("Synthetic first")
        old = service.request_id
        qtbot.waitUntil(lambda: (old, "speaking") in events)
        service.speak("Synthetic second")
        current = service.request_id
        assert closing.wait(1)
        assert not second_started.is_set()
        service._worker_state.emit(old, "failed")
        release.set()
        qtbot.waitUntil(lambda: (current, "finished") in events)
        assert (old, "failed") not in events
    finally:
        release.set()


def test_start_failure_does_not_log_private_exception(service, monkeypatch, qtbot, caplog):
    def fail(*_args):
        raise OSError("Synthetic private message")

    monkeypatch.setattr(speech_service, "start_speech_process", fail)
    events = []
    service.playback_changed.connect(lambda _request, state: events.append(state))
    service.speak("Synthetic private message")
    qtbot.waitUntil(lambda: "failed" in events)
    assert "Synthetic private message" not in caplog.text


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process ownership")
def test_windows_process_preserves_unicode_arguments_and_environment(tmp_path, qtbot):
    result = tmp_path / "arguments.json"
    script = "import json,os,sys; from pathlib import Path; Path(sys.argv[1]).write_text(json.dumps([sys.argv[2],os.environ['SPEECH_TEST_VALUE']]),encoding='utf-8')"
    text = 'Synthetic čćž سَلَامٌ "quoted" & $(literal) \\ end'
    process = WindowsSpeechProcess(
        [sys.executable, "-c", script, str(result), text], {**os.environ, "SPEECH_TEST_VALUE": "čž"}
    )
    try:
        qtbot.waitUntil(lambda: process.poll() is not None, timeout=5000)
        assert process.poll() == 0
        assert json.loads(result.read_text(encoding="utf-8")) == [text, "čž"]
    finally:
        process.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process ownership")
@pytest.mark.parametrize("parent_exits", [False, True])
def test_windows_job_closes_descendants_even_after_parent_exits(tmp_path, qtbot, parent_exits):
    import ctypes
    from ctypes import wintypes

    child_pid = tmp_path / "child.pid"
    child_code = "import time; time.sleep(60)"
    script = (
        "import subprocess,sys,time; from pathlib import Path; p=subprocess.Popen([sys.executable,'-c',sys.argv[2]]); Path(sys.argv[1]).write_text(str(p.pid)); "
        + ("" if parent_exits else "time.sleep(60)")
    )
    process = WindowsSpeechProcess([sys.executable, "-c", script, str(child_pid), child_code], None)
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    child = None
    try:
        qtbot.waitUntil(lambda: child_pid.exists() and child_pid.stat().st_size > 0, timeout=5000)
        child = api.OpenProcess(0x100000, False, int(child_pid.read_text()))
        assert child
        assert api.WaitForSingleObject(child, 0) == 258
        if parent_exits:
            qtbot.waitUntil(lambda: process.poll() == 0, timeout=5000)
        process.close()
        qtbot.waitUntil(lambda: api.WaitForSingleObject(child, 0) == 0, timeout=5000)
    finally:
        process.close()
        if child:
            api.CloseHandle(child)


def test_stop_during_startup_closes_process_without_late_ui_events(service, monkeypatch, qtbot):
    started, release, closed = threading.Event(), threading.Event(), threading.Event()

    class Process:
        def poll(self):
            return None

        def close(self):
            closed.set()

    def start(*_args):
        started.set()
        assert release.wait(3)
        return Process()

    monkeypatch.setattr(speech_service, "start_speech_process", start)
    events = []
    service.playback_changed.connect(lambda _request, state: events.append(state))
    try:
        service.speak("Synthetic text")
        assert started.wait(1)
        service.stop()
        assert events == ["stopped"]
        release.set()
        qtbot.waitUntil(closed.is_set)
        assert events == ["stopped"]
    finally:
        release.set()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process ownership")
def test_job_assignment_failure_never_resumes_child_and_releases_handles(tmp_path, monkeypatch):
    from pogled_assist.windows import speech_process

    api = speech_process._kernel_api()
    terminate = api.TerminateProcess
    close = api.CloseHandle
    terminated, closed = [], []

    def terminate_process(handle, code):
        result = terminate(handle, code)
        terminated.append(handle)
        assert api.WaitForSingleObject(handle, 3000) == 0
        return result

    def close_handle(handle):
        closed.append(handle)
        return close(handle)

    api.AssignProcessToJobObject = lambda *_args: False
    api.TerminateProcess = terminate_process
    api.CloseHandle = close_handle
    monkeypatch.setattr(speech_process, "_kernel_api", lambda: api)
    marker = tmp_path / "should-not-execute"
    with pytest.raises(OSError):
        WindowsSpeechProcess(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; import sys; Path(sys.argv[1]).touch()",
                str(marker),
            ],
            None,
        )
    assert not marker.exists()
    assert len(terminated) == 1
    assert len(closed) == 3  # job, process, initial suspended thread
    assert terminated[0] in closed


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process ownership")
def test_online_cli_help_can_run_without_inherited_console_handles(qtbot):
    process = WindowsSpeechProcess([sys.executable, "-m", "edge_playback", "--help"], None)
    try:
        qtbot.waitUntil(lambda: process.poll() is not None, timeout=5000)
        assert process.poll() == 0
    finally:
        process.close()
