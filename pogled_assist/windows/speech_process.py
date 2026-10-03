"""Own a speech process and its descendants without waiting on pipe EOF."""

from __future__ import annotations

import contextlib
import ctypes
import os
import signal
import subprocess
import sys
from ctypes import wintypes


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [
        ("process", wintypes.HANDLE),
        ("thread", wintypes.HANDLE),
        ("pid", wintypes.DWORD),
        ("tid", wintypes.DWORD),
    ]


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_int64),
        ("job_time", ctypes.c_int64),
        ("flags", wintypes.DWORD),
        ("min_working_set", ctypes.c_size_t),
        ("max_working_set", ctypes.c_size_t),
        ("active_processes", wintypes.DWORD),
        ("affinity", ctypes.c_size_t),
        ("priority", wintypes.DWORD),
        ("scheduling", wintypes.DWORD),
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", _BasicLimits),
        ("io", ctypes.c_uint64 * 6),
        ("process_memory", ctypes.c_size_t),
        ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t),
        ("peak_job_memory", ctypes.c_size_t),
    ]


def _kernel_api():
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
        "SetInformationJobObject": (
            [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD],
            wintypes.BOOL,
        ),
        "CreateProcessW": (
            [
                wintypes.LPCWSTR,
                wintypes.LPWSTR,
                ctypes.c_void_p,
                ctypes.c_void_p,
                wintypes.BOOL,
                wintypes.DWORD,
                ctypes.c_void_p,
                wintypes.LPCWSTR,
                ctypes.POINTER(_StartupInfo),
                ctypes.POINTER(_ProcessInfo),
            ],
            wintypes.BOOL,
        ),
        "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        "ResumeThread": ([wintypes.HANDLE], wintypes.DWORD),
        "TerminateProcess": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        "GetExitCodeProcess": ([wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(api, name)
        function.argtypes = arguments
        function.restype = result
    return api


class WindowsSpeechProcess:
    """Assign the suspended process to a private kill-on-close Windows job.

    Assignment precedes execution, so even a fast-launching child belongs to
    this job. No unrelated process is ever found or terminated by executable name.
    """

    def __init__(self, command: list[str], environment: dict[str, str] | None) -> None:
        if any("\0" in argument for argument in command):
            raise ValueError("Speech arguments cannot contain NUL characters.")
        self._api = _kernel_api()
        self._job = None
        self._process = None
        info = _ProcessInfo()
        try:
            self._job = self._api.CreateJobObjectW(None, None)
            if not self._job:
                raise ctypes.WinError(ctypes.get_last_error())
            limits = _ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not self._api.SetInformationJobObject(
                self._job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            startup = _StartupInfo()
            startup.cb = ctypes.sizeof(startup)
            startup.dwFlags = 1  # STARTF_USESHOWWINDOW, SW_HIDE
            environment_block = None
            if environment is not None:
                environment_block = ctypes.create_unicode_buffer(
                    "\0".join(
                        f"{key}={value}"
                        for key, value in sorted(
                            environment.items(), key=lambda item: item[0].upper()
                        )
                    )
                    + "\0\0"
                )
            # No handles are inherited, including stdin/stdout/stderr. Speech
            # diagnostics use exit codes; engine output may contain private text.
            if not self._api.CreateProcessW(
                command[0],
                ctypes.create_unicode_buffer(subprocess.list2cmdline(command)),
                None,
                None,
                False,
                0x08000004 | 0x400,  # NO_WINDOW | SUSPENDED | UNICODE_ENVIRONMENT
                environment_block,
                None,
                ctypes.byref(startup),
                ctypes.byref(info),
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            self._process = info.process
            if not self._api.AssignProcessToJobObject(self._job, self._process):
                raise ctypes.WinError(ctypes.get_last_error())
            if self._api.ResumeThread(info.thread) == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            if info.process:
                self._api.TerminateProcess(info.process, 1)
            self.close()
            raise
        finally:
            if info.thread:
                self._api.CloseHandle(info.thread)

    def poll(self) -> int | None:
        result = self._api.WaitForSingleObject(self._process, 0)
        if result == 258:  # WAIT_TIMEOUT
            return None
        if result != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        code = wintypes.DWORD()
        if not self._api.GetExitCodeProcess(self._process, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value

    def close(self) -> None:
        if self._job:
            self._api.CloseHandle(self._job)
            self._job = None
        if self._process:
            self._api.CloseHandle(self._process)
            self._process = None


class PosixSpeechProcess:
    def __init__(self, command: list[str], environment: dict[str, str] | None) -> None:
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=environment,
            start_new_session=True,
        )

    def poll(self) -> int | None:
        return self._process.poll()

    def close(self) -> None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(self._process.pid, signal.SIGKILL)
        self._process.wait(timeout=1)


def start_speech_process(command: list[str], environment: dict[str, str] | None):
    process_type = WindowsSpeechProcess if sys.platform == "win32" else PosixSpeechProcess
    return process_type(command, environment)
