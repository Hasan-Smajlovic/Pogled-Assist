from __future__ import annotations

import ctypes
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows file sharing is required")

ARCHIVE_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "release" / "compress_package.ps1"
)


def test_package_archive_retries_a_temporarily_locked_file(tmp_path: Path) -> None:
    package = tmp_path / "PogledAssist"
    package.mkdir()
    source = package / "base_library.zip"
    source.write_bytes(b"bundled Python library")
    archive_path = tmp_path / "PogledAssist.zip"

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    )
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel32.CreateFileW(str(source), 0x80000000, 0, None, 3, 0, None)
    assert handle != ctypes.c_void_p(-1).value, ctypes.get_last_error()

    try:
        process = subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ARCHIVE_SCRIPT),
                "-PackageRoot",
                str(package),
                "-ArtifactPath",
                str(archive_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert process.stdout is not None
        output: list[str] = []
        retry_seen = threading.Event()

        def read_output() -> None:
            for line in process.stdout:
                output.append(line)
                if "retrying in 2 seconds" in line:
                    retry_seen.set()

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        saw_retry = retry_seen.wait(timeout=20)
    finally:
        kernel32.CloseHandle(handle)

    try:
        returncode = process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        raise
    reader.join(timeout=5)
    assert saw_retry, "".join(output)
    assert returncode == 0, "".join(output)
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.read("PogledAssist/base_library.zip") == source.read_bytes()
