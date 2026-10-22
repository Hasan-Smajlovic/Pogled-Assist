from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

import pytest
from _powershell import function_definitions, run_powershell_cases

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="The release installer uses Windows PowerShell and Windows executables.",
)

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER_SCRIPT = REPO_ROOT / "packaging" / "windows" / "install_windows.ps1"
PACKAGE_VERSION = "0.2.0"

# The installer still checks real PogledAssist processes; only CIM records are fixed for tests.
INSTALLER_RUNNER = r"""
param([string]$InstallerPath, [string]$InstallRoot, [string]$ExpectedVersion)

function Get-CimInstance {
    [CmdletBinding()]
    param([string]$ClassName, [string]$Filter)

    if ($env:FAKE_CIM_ACCESS_DENIED -eq "1") {
        throw "Access denied"
    }
    if ($env:FAKE_SOURCE_PROCESS_COMMAND) {
        [PSCustomObject]@{
            CommandLine = $env:FAKE_SOURCE_PROCESS_COMMAND
            ExecutablePath = "python.exe"
            ProcessId = 424242
        }
    }
}

& $InstallerPath -InstallRoot $InstallRoot -ExpectedVersion $ExpectedVersion -NoElevation -NoDesktopShortcut
exit $LASTEXITCODE
"""

SMOKE_APP_SOURCE = r"""
using System;
using System.IO;
using System.Threading;
using System.Diagnostics;

public static class Program
{
    public static int Main(string[] args)
    {
        string records = Environment.GetEnvironmentVariable("FAKE_PROCESS_RECORD_DIR");
        if (!String.IsNullOrEmpty(records))
        {
            string[] values = new string[args.Length + 2];
            values[0] = Environment.CurrentDirectory;
            values[1] = Environment.GetEnvironmentVariable("FAKE_INHERITED_VALUE") ?? "";
            Array.Copy(args, 0, values, 2, args.Length);
            File.WriteAllLines(Path.Combine(records, Process.GetCurrentProcess().Id + ".txt"), values);
        }
        if ((args.Length > 0 && args[0] == "--child") ||
            (Environment.GetEnvironmentVariable("FAKE_BOOTSTRAP_CHILD") == "1" &&
             (args.Length == 0 || (args[0] != "--delayed" && args[0] != "--hold"))))
        {
            ProcessStartInfo info = new ProcessStartInfo(Process.GetCurrentProcess().MainModule.FileName);
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.Arguments = Environment.GetEnvironmentVariable("FAKE_CHILD_HOLD") == "1"
                ? "--hold" : "--delayed";
            using (Process child = Process.Start(info)) { }
            return 3010;
        }
        if (args.Length > 0 && args[0] == "--delayed")
        {
            Thread.Sleep(1500);
            File.WriteAllText(Environment.GetEnvironmentVariable("FAKE_CHILD_DONE"), "done");
            return 0;
        }
        if (Environment.GetEnvironmentVariable("FAKE_SMOKE_HOLD") == "1")
        {
            Thread.Sleep(60000);
        }
        string exitCode = Environment.GetEnvironmentVariable("FAKE_EXIT_CODE");
        if (!String.IsNullOrEmpty(exitCode)) return Int32.Parse(exitCode);
        if (args.Length > 0 && args[0] == "--hold")
        {
            Thread.Sleep(60000);
            return 0;
        }

        string failureRoot = Environment.GetEnvironmentVariable("FAKE_SMOKE_FAIL_ROOT");
        string currentRoot = Path.GetFullPath(Environment.CurrentDirectory)
            .TrimEnd(Path.DirectorySeparatorChar);
        if (
            failureRoot == "all" ||
            String.Equals(
                currentRoot,
                failureRoot,
                StringComparison.OrdinalIgnoreCase
            )
        )
        {
            string report = Environment.GetEnvironmentVariable(
                "POGLED_ASSIST_PACKAGE_SMOKE_REPORT"
            );
            if (!String.IsNullOrWhiteSpace(report))
            {
                File.WriteAllText(report, "forced smoke failure");
            }
            return 7;
        }

        return 0;
    }
}
"""


@pytest.fixture(scope="module")
def smoke_app(tmp_path_factory) -> Path:
    # Share only compiled bytes; each test copies them into its own package.
    tmp_path = tmp_path_factory.mktemp("installer-smoke-app")
    source_path = tmp_path / "SmokeApp.cs"
    executable_path = tmp_path / "PogledAssist.exe"
    compiler_path = tmp_path / "compile-smoke-app.ps1"
    source_path.write_text(SMOKE_APP_SOURCE, encoding="utf-8")
    compiler_path.write_text(
        "param([string]$SourcePath, [string]$OutputPath)\n"
        "Add-Type -Path $SourcePath -OutputAssembly $OutputPath "
        "-OutputType ConsoleApplication\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(compiler_path),
            "-SourcePath",
            str(source_path),
            "-OutputPath",
            str(executable_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert executable_path.is_file()
    return executable_path


def _release_package(tmp_path: Path, smoke_app: Path) -> Path:
    package = tmp_path / "release" / "PogledAssist"
    (package / "_internal").mkdir(parents=True)
    shutil.copy2(smoke_app, package / "PogledAssist.exe")
    shutil.copy2(INSTALLER_SCRIPT, package / "install_windows.ps1")
    (package / "start_gaze_mouse.ps1").write_text("# fake launcher\n", encoding="utf-8")
    (package / "update_windows.ps1").write_text("# fake updater\n", encoding="utf-8")
    (package / "README.md").write_text("fake release\n", encoding="utf-8")
    (package / "VERSION").write_text(f"{PACKAGE_VERSION}\n", encoding="utf-8")
    (package / "new-app-file.txt").write_text("new application\n", encoding="utf-8")
    return package


def _existing_installation(tmp_path: Path) -> Path:
    install_root = tmp_path / "installed"
    (install_root / "data").mkdir(parents=True)
    (install_root / "logs").mkdir()
    (install_root / "data" / "app_settings.json").write_bytes(b'{"keep":true}')
    (install_root / "data" / "speech_library.json").write_bytes(b'{"keep":"library"}')
    (install_root / "data" / "speech_phrases.json").write_bytes(b'["keep"]')
    (install_root / "data" / "speech_learning.json").write_bytes(b'{"keep":"learning"}')
    (install_root / "logs" / "latest.txt").write_bytes(b"existing log\r\n")
    (install_root / "logs" / "diagnostics").mkdir()
    (install_root / "logs" / "diagnostics" / "session.jsonl").write_bytes(
        b'{"keep":"diagnostics"}\n'
    )
    (install_root / "logs" / "gaze-check").mkdir()
    (install_root / "logs" / "gaze-check" / "synthetic-report.json").write_bytes(
        b'{"keep":"gaze-check-report"}\n'
    )
    recording = install_root / "logs" / "diagnostic-recordings" / ("a" * 32)
    recording.mkdir(parents=True)
    (recording / "recording.json").write_bytes(b'{"keep":"recording-metadata"}\n')
    (recording / "snimak.jsonl").write_bytes(b'{"keep":"recorded-events"}\n')
    (install_root / "install_info.json").write_bytes(b'{"keep":"metadata"}')
    (install_root / "setup_windows.log").write_bytes(b"existing setup log\r\n")
    (install_root / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (install_root / "old-app-file.txt").write_text("old application\n", encoding="utf-8")
    return install_root


def _installer_environment(**overrides: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PSMODULEPATH", None)
    environment.update(overrides)
    return environment


def _run_installer(
    package: Path,
    install_root: Path,
    *,
    expected_version: str = PACKAGE_VERSION,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    runner = package.parent.parent / "run-installer.ps1"
    runner.write_text(INSTALLER_RUNNER, encoding="utf-8")
    return _run_powershell(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(runner),
            "-InstallerPath",
            str(package / "install_windows.ps1"),
            "-InstallRoot",
            str(install_root),
            "-ExpectedVersion",
            expected_version,
        ],
        cwd=package,
        env=environment or _installer_environment(),
    )


def _run_powershell(command, *, cwd=None, env=None, timeout=30):
    # Bound the harness too: a shell warning must fail the test and close its tree.
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        subprocess.run(
            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            timeout=10,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        process.communicate(timeout=5)
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _mark_downloaded(path):
    Path(str(path) + ":Zone.Identifier").write_text("[ZoneTransfer]\nZoneId=3\n", encoding="ascii")


def test_downloaded_executable_installs_without_shell_warning(tmp_path, smoke_app):
    package = _release_package(tmp_path, smoke_app)
    _mark_downloaded(package / "PogledAssist.exe")
    records = tmp_path / "records"
    records.mkdir()
    install_root = tmp_path / "installed with spaces"
    result = _run_installer(
        package,
        install_root,
        environment=_installer_environment(FAKE_PROCESS_RECORD_DIR=str(records)),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    launches = [p.read_text().splitlines() for p in records.glob("*.txt")]
    assert len(launches) == 2
    assert all(record[2:] == ["--package-smoke-test"] for record in launches)
    assert any(record[0] == str(install_root) for record in launches)
    assert (
        "ZoneId=3" in Path(str(install_root / "PogledAssist.exe") + ":Zone.Identifier").read_text()
    )
    _assert_no_transaction_files(install_root)


@pytest.mark.parametrize("build_script", [False, True])
@pytest.mark.parametrize("outcome", ["success", "failure", "invalid", "timeout"])
def test_package_process_outcomes_restore_environment_and_cleanup(
    package_process_results, build_script, outcome
):
    case = package_process_results[build_script][f"smoke-{outcome}"]
    result = case["result"]
    records = case["records"]
    report = case["report"]
    assert result.returncode == (0 if outcome == "success" else 1), result.stdout + result.stderr
    if outcome != "success":
        assert result.stderr == "Smoke failed", result.stdout + result.stderr
    if outcome == "failure":
        assert "exit code 7" in result.stdout
    if outcome == "timeout":
        assert "timed out" in result.stdout
    if outcome == "invalid":
        assert "not a valid" in result.stdout
    assert not report.exists()
    for record in records.glob("*.txt"):
        assert not _process_running(int(record.stem)), record


def _process_running(pid):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(0x00100000, False, pid)
    if not handle:
        assert ctypes.get_last_error() == 87  # ERROR_INVALID_PARAMETER: exited PID
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == 258  # WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(handle)


@pytest.mark.parametrize("timeout", [False, True])
def test_setup_installer_waits_for_descendants_and_closes_tree(setup_process_results, timeout):
    case = setup_process_results[f"descendants-{timeout}"]
    result = case["result"]
    tmp_path = case["cwd"]
    records = case["records"]
    child_done = case["child_done"]
    launches = [record.read_text().splitlines() for record in records.glob("*.txt")]
    parent = next(record for record in launches if record[2] == "--child")
    assert parent[:2] == [str(tmp_path), "value with spaces"]
    assert parent[2:] == ["--child", "one argument", 'a"b', "C:\\trailing space\\", ""]
    assert len(launches) == 2
    if timeout:
        assert result.returncode != 0
        assert "process tree timed out" in result.stderr
        assert not child_done.exists()
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "3010" in result.stdout
        assert child_done.read_text() == "done"
    for record in records.glob("*.txt"):
        assert not _process_running(int(record.stem)), record


@pytest.mark.parametrize("exit_code", [0, 3010, 7])
def test_official_python_installer_preserves_arguments_and_exit_codes(
    setup_process_results, exit_code
):
    case = setup_process_results[f"python-{exit_code}"]
    result = case["result"]
    records = case["records"]
    assert (result.returncode == 0) is (exit_code in (0, 3010)), result.stdout + result.stderr
    record = next(records.glob("*.txt")).read_text().splitlines()
    assert "TargetDir=C:\\Python with spaces\\" in record[2:]
    assert "Include_pip=0" in record[2:]
    if exit_code == 3010:
        assert "requested a reboot" in result.stdout
    elif exit_code == 7:
        assert "exit code 7" in result.stderr


def test_setup_native_probe_drains_both_output_streams_without_deadlock(setup_process_results):
    case = setup_process_results["native-probe"]
    result = case["result"]
    assert result.returncode == 0, result.stdout + result.stderr
    assert "o" * 1000 in result.stdout and "e" * 1000 in result.stdout


def test_package_launcher_starts_downloaded_executable_in_app_directory(tmp_path, smoke_app):
    root = tmp_path / "portable with spaces"
    root.mkdir()
    launcher = root / "start_gaze_mouse.ps1"
    shutil.copy2(REPO_ROOT / "packaging/windows/start_gaze_mouse.ps1", launcher)
    shutil.copy2(smoke_app, root / "PogledAssist.exe")
    _mark_downloaded(root / "PogledAssist.exe")
    records = tmp_path / "records"
    records.mkdir()
    result = _run_powershell(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(launcher),
            "-NoElevation",
            "-NoPause",
        ],
        env=_installer_environment(FAKE_PROCESS_RECORD_DIR=str(records)),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    record = next(records.glob("*.txt")).read_text().splitlines()
    assert record == [str(root), ""]


def test_installation_check_keeps_normal_window_configuration(package_process_results):
    case = package_process_results[False]["installation-check"]
    result = case["result"]
    assert result.returncode == 0, result.stdout + result.stderr


def test_post_install_launch_passes_launcher_path_with_spaces(package_process_results):
    case = package_process_results[False]["post-install"]
    result = case["result"]
    root = case["root"]
    records = case["records"]
    assert result.returncode == 0, result.stdout + result.stderr
    deadline = time.monotonic() + 5
    while not list(records.glob("*.txt")) and time.monotonic() < deadline:
        time.sleep(0.05)
    record = next(records.glob("*.txt")).read_text().splitlines()
    assert record == [str(root), "", "--post-install"]


def test_setup_installer_rejects_invalid_executable_without_shell(setup_process_results):
    case = setup_process_results["invalid"]
    result = case["result"]
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() in ("NativeErrorCode=193", "NativeErrorCode=216")


@pytest.mark.parametrize("exit_code", [0, 3010, 7])
def test_msi_setup_preserves_exit_codes_and_raw_path_argument(msi_process_results, exit_code):
    case = msi_process_results[str(exit_code)]
    result = case["result"]
    assert (result.returncode == 0) is (exit_code in (0, 3010)), result.stdout + result.stderr
    if exit_code == 3010:
        assert "requested a reboot" in result.stdout
    elif exit_code == 7:
        assert "exit code 7" in result.stderr


def test_newer_older_newer_round_trip_preserves_data_and_supported_edits(
    tmp_path, smoke_app, monkeypatch
):
    from pogled_assist.settings_store import load_app_settings, save_app_settings
    from pogled_assist.speech.speech_library import (
        CategoryRecord,
        PhraseRecord,
        speech_library_store,
    )
    from pogled_assist.suggestions.learning import LearningStore

    package = _release_package(tmp_path, smoke_app)
    install_root = _existing_installation(tmp_path)
    data = install_root / "data"
    (install_root / "VERSION").write_text("0.3.5", encoding="utf-8")
    (data / "app_settings.json").write_text(
        json.dumps(
            {
                "version": 1,
                "gaze": {"dwell_ms": 750, "show_tracking_notifications": False},
                "speech": {"keyboard_script": "arabic", "speed": 180},
                "future_setting": "keep",
            }
        ),
        encoding="utf-8",
    )
    library = {
        "version": 2,
        "categories": [{"name": "Synthetic category", "answers": ["Synthetic answer"]}],
        "phrases": [{"text": "Synthetic phrase", "uses": 7}],
    }
    (data / "speech_library.json").write_text(json.dumps(library), encoding="utf-8")
    (data / "speech_phrases.json").write_text(json.dumps(library["phrases"]), encoding="utf-8")
    (data / "speech_learning.json").write_text(
        '{"version":1,"counts":[["kahva",3]]}', encoding="utf-8"
    )
    extra = data / "custom" / "entry.txt"
    extra.parent.mkdir()
    extra.write_text("Synthetic manual entry", encoding="utf-8")
    before = _persistent_snapshot(install_root)

    downgrade = _run_installer(package, install_root)
    assert downgrade.returncode == 0, downgrade.stdout + downgrade.stderr
    assert _persistent_snapshot(install_root) == before
    first = next((data / "version-history").iterdir())
    assert (first / "app_settings.json").read_bytes() == before["data/app_settings.json"]
    assert not (first / "version-history").exists()
    assert (first / "custom/entry.txt").read_text() == "Synthetic manual entry"

    (data / "app_settings.json").write_text(
        '{"version":1,"gaze":{"dwell_ms":950},"speech":{"speed":210}}', encoding="utf-8"
    )
    library["categories"][0]["answers"].append("Synthetic older answer")
    library["phrases"][0]["uses"] = 9
    (data / "speech_library.json").write_text(json.dumps(library), encoding="utf-8")
    (data / "speech_phrases.json").write_text(json.dumps(library["phrases"]), encoding="utf-8")
    (data / "speech_learning.json").write_text(
        '{"version":1,"counts":[["kahva",4],["ljeto",1]]}', encoding="utf-8"
    )
    (package / "VERSION").write_text("0.4.0", encoding="utf-8")
    upgrade = _run_installer(package, install_root, expected_version="0.4.0")
    assert upgrade.returncode == 0, upgrade.stdout + upgrade.stderr
    monkeypatch.setattr("pogled_assist.settings_store.get_project_root", lambda: install_root)
    gaze, speech = load_app_settings()
    assert gaze.dwell_ms == 950 and gaze.show_tracking_notifications is False
    assert speech.speed == 210 and speech.keyboard_script == "arabic"
    assert save_app_settings(gaze, speech)
    assert json.loads((data / "app_settings.json").read_text())["future_setting"] == "keep"
    returned = speech_library_store(install_root).load()
    assert returned.categories == [
        CategoryRecord("Synthetic category", ["Synthetic answer", "Synthetic older answer"])
    ]
    assert returned.phrases == [PhraseRecord("Synthetic phrase", 9)]
    assert LearningStore(data / "speech_learning.json").snapshot() == {("kahva",): 4, ("ljeto",): 1}
    assert extra.read_text() == "Synthetic manual entry"
    assert len(list((data / "version-history").iterdir())) == 2
    assert (install_root / "logs/latest.txt").read_bytes() == before["logs/latest.txt"]
    assert (install_root / "VERSION").read_text().strip() == "0.4.0"


def test_unsupported_data_format_stops_before_changing_installation(tmp_path, smoke_app):
    package = _release_package(tmp_path, smoke_app)
    install_root = _existing_installation(tmp_path)
    path = install_root / "data/speech_learning.json"
    path.write_text('{"version":999,"counts":[["KAHVA",2]]}', encoding="utf-8")
    before = _persistent_snapshot(install_root)
    completed = _run_installer(package, install_root)
    assert completed.returncode != 0
    _assert_output_contains(completed, "unsupported saved data format")
    assert _persistent_snapshot(install_root) == before
    assert (install_root / "old-app-file.txt").exists()
    assert not (install_root / "data/version-history").exists()
    _assert_no_transaction_files(install_root)


def _persistent_snapshot(install_root: Path) -> dict[str, bytes]:
    return {
        relative_path: (install_root / relative_path).read_bytes()
        for relative_path in (
            "data/app_settings.json",
            "data/speech_library.json",
            "data/speech_phrases.json",
            "data/speech_learning.json",
            "logs/latest.txt",
            "logs/diagnostics/session.jsonl",
            "logs/gaze-check/synthetic-report.json",
            "logs/diagnostic-recordings/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/recording.json",
            "logs/diagnostic-recordings/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/snimak.jsonl",
            "install_info.json",
            "setup_windows.log",
        )
    }


def _assert_no_transaction_files(install_root: Path) -> None:
    leftovers = list(install_root.parent.glob(f".{install_root.name}.install-*"))
    leftovers += list(install_root.parent.glob(f".{install_root.name}.backup-*"))
    assert leftovers == []


def _assert_output_contains(completed: subprocess.CompletedProcess[str], expected: str) -> None:
    # Windows PowerShell can wrap error text at the console width, even inside words.
    compact_expected = "".join(expected.split())
    assert any(
        compact_expected in "".join(stream.split())
        for stream in (completed.stdout, completed.stderr)
    ), completed.stdout + completed.stderr


def _hold_directory(path: Path) -> tuple[object, int]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = create_file(str(path), 1, 3, None, 3, 0x02000000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    return kernel32, handle


def test_upgrade_replaces_bundled_files_and_preserves_user_files(tmp_path, smoke_app):
    package = _release_package(tmp_path, smoke_app)
    install_root = _existing_installation(tmp_path)
    persistent_before = _persistent_snapshot(install_root)
    relative = Path("speech/edge/edge-playback.exe")
    for root, value in ((package, b"new bundled tool"), (install_root, b"old bundled tool")):
        (root / relative).parent.mkdir(parents=True)
        (root / relative).write_bytes(value)
    external = install_root / "tools/espeak-ng/espeak-ng.exe"
    external.parent.mkdir(parents=True)
    external.write_bytes(b"user provided tool")

    completed = _run_installer(package, install_root)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert (install_root / "VERSION").read_text(encoding="utf-8").strip() == PACKAGE_VERSION
    assert (install_root / "new-app-file.txt").is_file()
    assert not (install_root / "old-app-file.txt").exists()
    assert (install_root / relative).read_bytes() == b"new bundled tool"
    assert external.read_bytes() == b"user provided tool"
    assert _persistent_snapshot(install_root) == persistent_before
    _assert_no_transaction_files(install_root)


def test_open_install_directory_fails_cleanly_without_transaction_leftovers(tmp_path, smoke_app):
    package = _release_package(tmp_path, smoke_app)
    install_root = _existing_installation(tmp_path)
    persistent_before = _persistent_snapshot(install_root)
    kernel32, handle = _hold_directory(install_root)
    try:
        completed = _run_installer(package, install_root)
    finally:
        assert kernel32.CloseHandle(handle)

    assert completed.returncode == 2, completed.stdout + completed.stderr
    _assert_output_contains(completed, "Close File Explorer windows showing this folder")
    assert (install_root / "VERSION").read_text(encoding="utf-8").strip() == "0.1.0"
    assert (install_root / "old-app-file.txt").is_file()
    assert not (install_root / "new-app-file.txt").exists()
    assert _persistent_snapshot(install_root) == persistent_before
    _assert_no_transaction_files(install_root)


def test_installed_smoke_failure_restores_previous_installation(tmp_path, smoke_app):
    package = _release_package(tmp_path, smoke_app)
    install_root = _existing_installation(tmp_path)
    persistent_before = _persistent_snapshot(install_root)
    environment = _installer_environment(FAKE_SMOKE_FAIL_ROOT=str(install_root.resolve()))

    completed = _run_installer(
        package,
        install_root,
        environment=environment,
    )

    assert completed.returncode != 0
    _assert_output_contains(completed, "Installed application verification failed")
    assert (install_root / "VERSION").read_text(encoding="utf-8").strip() == "0.1.0"
    assert (install_root / "old-app-file.txt").is_file()
    assert not (install_root / "new-app-file.txt").exists()
    assert _persistent_snapshot(install_root) == persistent_before
    _assert_no_transaction_files(install_root)


def test_staged_smoke_failure_never_changes_existing_installation(tmp_path, smoke_app):
    package = _release_package(tmp_path, smoke_app)
    install_root = _existing_installation(tmp_path)
    persistent_before = _persistent_snapshot(install_root)
    environment = _installer_environment(FAKE_SMOKE_FAIL_ROOT="all")

    completed = _run_installer(
        package,
        install_root,
        environment=environment,
    )

    assert completed.returncode != 0
    _assert_output_contains(completed, "Staged application verification failed")
    assert (install_root / "VERSION").read_text(encoding="utf-8").strip() == "0.1.0"
    assert (install_root / "old-app-file.txt").is_file()
    assert _persistent_snapshot(install_root) == persistent_before
    _assert_no_transaction_files(install_root)


def test_interrupted_directory_swap_is_recovered_before_next_attempt(tmp_path, smoke_app):
    package = _release_package(tmp_path, smoke_app)
    install_root = _existing_installation(tmp_path)
    persistent_before = _persistent_snapshot(install_root)
    backup_root = install_root.parent / f".{install_root.name}.backup-interrupted"
    staging_root = install_root.parent / f".{install_root.name}.install-interrupted"
    transaction_path = install_root.parent / f".{install_root.name}.install-transaction.json"
    install_root.rename(backup_root)
    staging_root.mkdir()
    (staging_root / "partial.txt").write_text("partial update\n", encoding="utf-8")
    transaction_path.write_text(
        json.dumps(
            {
                "InstallRoot": str(install_root.resolve()),
                "StagingRoot": str(staging_root.resolve()),
                "BackupRoot": str(backup_root.resolve()),
            }
        ),
        encoding="utf-8",
    )

    completed = _run_installer(
        package,
        install_root,
        environment=_installer_environment(FAKE_SMOKE_FAIL_ROOT="all"),
    )

    assert completed.returncode != 0
    _assert_output_contains(completed, "Restored the previous installation")
    assert (install_root / "VERSION").read_text(encoding="utf-8").strip() == "0.1.0"
    assert (install_root / "old-app-file.txt").is_file()
    assert _persistent_snapshot(install_root) == persistent_before
    _assert_no_transaction_files(install_root)


def test_blocked_rollback_keeps_backup_and_never_runs_failed_version(tmp_path, smoke_app):
    package = _release_package(tmp_path, smoke_app)
    install_root = _existing_installation(tmp_path)
    persistent_before = _persistent_snapshot(install_root)
    backup_root = install_root.parent / f".{install_root.name}.backup-interrupted"
    staging_root = install_root.parent / f".{install_root.name}.install-interrupted"
    transaction_path = install_root.parent / f".{install_root.name}.install-transaction.json"
    install_root.rename(backup_root)
    install_root.mkdir()
    (install_root / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    (install_root / "new-app-file.txt").write_text("failed version\n", encoding="utf-8")
    staging_root.mkdir()
    transaction_path.write_text(
        json.dumps(
            {
                "InstallRoot": str(install_root.resolve()),
                "StagingRoot": str(staging_root.resolve()),
                "BackupRoot": str(backup_root.resolve()),
            }
        ),
        encoding="utf-8",
    )

    kernel32, handle = _hold_directory(backup_root)
    try:
        blocked = _run_installer(package, install_root)
    finally:
        assert kernel32.CloseHandle(handle)

    assert blocked.returncode != 0
    _assert_output_contains(blocked, "Could not restore the previous installation")
    assert not install_root.exists()
    assert (backup_root / "VERSION").read_text(encoding="utf-8").strip() == "0.1.0"
    assert transaction_path.is_file()

    retry = _run_installer(
        package,
        install_root,
        environment=_installer_environment(FAKE_SMOKE_FAIL_ROOT="all"),
    )
    assert retry.returncode != 0
    _assert_output_contains(retry, "Restored the previous installation")
    assert (install_root / "VERSION").read_text(encoding="utf-8").strip() == "0.1.0"
    assert _persistent_snapshot(install_root) == persistent_before
    _assert_no_transaction_files(install_root)


def test_running_application_blocks_install_before_files_change(tmp_path, smoke_app):
    package = _release_package(tmp_path, smoke_app)
    install_root = _existing_installation(tmp_path)
    running_app = subprocess.Popen([str(smoke_app), "--hold"])
    try:
        completed = _run_installer(package, install_root)
    finally:
        running_app.terminate()
        running_app.wait(timeout=5)

    assert completed.returncode != 0
    _assert_output_contains(completed, "Close Pogled Assist")
    assert (install_root / "VERSION").read_text(encoding="utf-8").strip() == "0.1.0"
    assert (install_root / "old-app-file.txt").is_file()


def test_running_source_application_blocks_install_before_files_change(tmp_path, smoke_app):
    package = _release_package(tmp_path, smoke_app)
    install_root = _existing_installation(tmp_path)
    source_command = f'python.exe "{install_root / "run_gaze_mouse.py"}"'

    completed = _run_installer(
        package,
        install_root,
        environment=_installer_environment(FAKE_SOURCE_PROCESS_COMMAND=source_command),
    )

    assert completed.returncode != 0
    _assert_output_contains(completed, "Close Pogled Assist")
    assert (install_root / "old-app-file.txt").is_file()


def test_process_discovery_failure_never_changes_existing_installation(tmp_path, smoke_app):
    package = _release_package(tmp_path, smoke_app)
    install_root = _existing_installation(tmp_path)

    completed = _run_installer(
        package,
        install_root,
        environment=_installer_environment(FAKE_CIM_ACCESS_DENIED="1"),
    )

    assert completed.returncode != 0
    _assert_output_contains(completed, "Could not check whether the source application is running")
    assert (install_root / "old-app-file.txt").is_file()


def test_expected_version_mismatch_stops_before_staging(tmp_path, smoke_app):
    package = _release_package(tmp_path, smoke_app)
    install_root = _existing_installation(tmp_path)

    completed = _run_installer(package, install_root, expected_version="9.9.9")

    assert completed.returncode != 0
    _assert_output_contains(completed, "does not match expected release")
    assert (install_root / "VERSION").read_text(encoding="utf-8").strip() == "0.1.0"
    assert (install_root / "old-app-file.txt").is_file()


def test_legacy_install_root_is_never_modified(tmp_path, smoke_app):
    package = _release_package(tmp_path, smoke_app)

    completed = _run_installer(package, Path(r"C:\TobiiExec"))

    assert completed.returncode != 0
    _assert_output_contains(
        completed,
        "belongs to the previous application and will not be changed",
    )


def _package_process_case(tmp_path, smoke_app, build_script, outcome):
    app_root = tmp_path / "package with spaces"
    app_root.mkdir()
    executable = app_root / "PogledAssist.exe"
    if outcome == "invalid":
        executable.write_bytes(b"invalid executable")
    else:
        shutil.copy2(smoke_app, executable)
    _mark_downloaded(executable)
    records = tmp_path / "records"
    records.mkdir()
    report = tmp_path / "report.txt"
    environment = {
        "FAKE_PROCESS_RECORD_DIR": str(records),
        "FAKE_APP_ROOT": str(app_root),
        "FAKE_REPORT_PATH": str(report),
        "POGLED_ASSIST_PACKAGE_SMOKE_REPORT": "original report",
        "QT_QPA_PLATFORM": "original platform",
        "FAKE_SMOKE_HOLD": "1" if outcome == "timeout" else "0",
        "FAKE_EXIT_CODE": "" if outcome == "failure" else "0",
        "FAKE_SMOKE_FAIL_ROOT": "all" if outcome == "failure" else "",
    }
    if build_script:
        call = "Invoke-BuiltPackageSmokeTest -PackageRoot $env:FAKE_APP_ROOT -SmokeReportPath $env:FAKE_REPORT_PATH"
    else:
        call = 'Invoke-PackageSmokeTest -Root $env:FAKE_APP_ROOT -Label "probe"'
    return {
        "body": r"""
$beforePath = $env:PATH
$failed = $false
try {
    CALL -TimeoutMilliseconds TIMEOUT
} catch {
    $failed = $true
    Write-Output $_.Exception.Message
}
if ($env:POGLED_ASSIST_PACKAGE_SMOKE_REPORT -ne "original report" -or
    $env:QT_QPA_PLATFORM -ne "original platform" -or $env:PATH -ne $beforePath) {
    throw "Environment was not restored"
}
if ($failed) { throw "Smoke failed" }
""".replace("CALL", call).replace("TIMEOUT", "300" if outcome == "timeout" else "5000"),
        "env": environment,
        "cwd": tmp_path,
        "records": records,
        "report": report,
    }


def _descendant_case(tmp_path, smoke_app, timeout):
    executable = tmp_path / "bootstrap with spaces.exe"
    shutil.copy2(smoke_app, executable)
    _mark_downloaded(executable)
    records = tmp_path / "records"
    records.mkdir()
    child_done = tmp_path / "child done.txt"
    environment = {
        "FAKE_BOOTSTRAP_CHILD": "1",
        "FAKE_CHILD_HOLD": "1" if timeout else "0",
        "FAKE_PROCESS_RECORD_DIR": str(records),
        "FAKE_EXE": str(executable),
        "FAKE_CHILD_DONE": str(child_done),
        "FAKE_INHERITED_VALUE": "value with spaces",
    }
    return {
        "body": "Write-Output (Invoke-InstallerProcess -FilePath $env:FAKE_EXE "
        '-Arguments @("--child", "one argument", \'a"b\', "C:\\trailing space\\", "") '
        f"-TimeoutSeconds {1 if timeout else 10})",
        "env": environment,
        "cwd": tmp_path,
        "records": records,
        "child_done": child_done,
    }


def _python_installer_case(tmp_path, smoke_app, exit_code):
    records = tmp_path / "records"
    records.mkdir()
    return {
        "body": r"""
function Write-Info { param([string]$Message) }
function Write-Success { param([string]$Message) Write-Output $Message }
function Write-WarningLog { param([string]$Message) Write-Output $Message }
Invoke-OfficialPythonInstaller -InstallerPath $env:FAKE_EXE -TargetDir "C:\Python with spaces\" -X86
""",
        "env": {
            "FAKE_EXE": str(smoke_app),
            "FAKE_EXIT_CODE": str(exit_code),
            "FAKE_PROCESS_RECORD_DIR": str(records),
        },
        "cwd": tmp_path,
        "records": records,
    }


def _native_probe_case(tmp_path, smoke_app):
    return {
        "body": r"""
function Write-Info { param([string]$Message) }
Invoke-NativeCommandWithTimeout -Label "flood probe" -FilePath $env:FAKE_EXE -Arguments @(
    "-c", "import sys; sys.stdout.write('o'*200000); sys.stderr.write('e'*200000)"
) -TimeoutSeconds 10
""",
        "env": {"FAKE_EXE": sys.executable},
        "cwd": tmp_path,
    }


def _invalid_executable_case(tmp_path, smoke_app):
    executable = tmp_path / "invalid with spaces.exe"
    executable.write_bytes(b"invalid executable")
    _mark_downloaded(executable)
    return {
        "body": r"""
try {
    Invoke-InstallerProcess -FilePath $env:FAKE_EXE -Arguments @() -TimeoutSeconds 1
} catch {
    $cause = $_.Exception
    while ($null -ne $cause.InnerException) { $cause = $cause.InnerException }
    if ($cause -isnot [ComponentModel.Win32Exception]) { throw }
    Write-Output "NativeErrorCode=$($cause.NativeErrorCode)"
    return
}
throw "Invalid executable unexpectedly started"
""",
        "env": {"FAKE_EXE": str(executable)},
        "cwd": tmp_path,
    }


def _msi_case(tmp_path, exit_code):
    return {
        "body": r"""
function Write-Step { param([string]$Message) }
function Write-Info { param([string]$Message) }
function Write-Success { param([string]$Message) Write-Output $Message }
function Write-WarningLog { param([string]$Message) Write-Output $Message }
function Download-FileWithPowerShell { param($Url, $DestinationPath, $Label) }
function Unblock-File { param($Path, $ErrorAction) }
function Invoke-InstallerProcess {
    param($FilePath, $Arguments)
    if ($FilePath -ne (Join-Path $env:SystemRoot "System32\msiexec.exe") -or
        $Arguments.Count -ne 4 -or $Arguments[0] -ne "/i" -or
        $Arguments[1] -notlike "*PogledAssistSetup\installer with spaces.msi" -or
        $Arguments[1].Contains('"') -or $Arguments[2] -ne "/quiet" -or $Arguments[3] -ne "/norestart") {
        throw "Invalid installer invocation"
    }
    return [int]$env:FAKE_EXIT_CODE
}
$EspeakNgVersion = "1.52.0"
$EspeakNgInstallerFileName = "installer with spaces.msi"
$EspeakNgInstallerUrl = "https://example.invalid/installer"
Install-EspeakNgFromMsi
""",
        "env": {"FAKE_EXIT_CODE": str(exit_code)},
        "cwd": tmp_path,
    }


def _installation_check_case(tmp_path, smoke_app):
    return {
        "body": r"""
$process = Start-ApplicationProcess -FilePath $env:FAKE_EXE -Arguments "--installation-check" -WorkingDirectory $env:FAKE_ROOT
try {
    if ($process.StartInfo.UseShellExecute -or $process.StartInfo.CreateNoWindow -or
        $process.StartInfo.WindowStyle -ne "Normal") { throw "Wrong window configuration" }
    if (-not $process.WaitForExit(5000) -or $process.ExitCode -ne 0) { throw "Launch failed" }
} finally { $process.Dispose() }
""",
        "env": {"FAKE_EXE": str(smoke_app), "FAKE_ROOT": str(tmp_path)},
        "cwd": tmp_path,
    }


def _post_install_case(tmp_path, smoke_app):
    root = tmp_path / "installed with spaces"
    root.mkdir()
    records = tmp_path / "records"
    records.mkdir()
    launcher = root / "start_gaze_mouse.ps1"
    launcher.write_text(
        "param([switch]$NoPause)\nif (-not $NoPause) { exit 4 }\n"
        '& $env:FAKE_EXE "--post-install"\n',
        encoding="utf-8",
    )
    return {
        "body": "Start-InstalledApplication -InstalledRoot $env:FAKE_ROOT",
        "env": {
            "FAKE_EXE": str(smoke_app),
            "FAKE_ROOT": str(root),
            "FAKE_PROCESS_RECORD_DIR": str(records),
        },
        "cwd": tmp_path,
        "root": root,
        "records": records,
    }


def _run_process_batch(root, script, cases):
    # Environment restoration is asserted in each smoke body before driver cleanup.
    results = run_powershell_cases(root, cases, prelude=function_definitions(script))
    return {name: {**case, "result": results[name]} for name, case in cases.items()}


@pytest.fixture(scope="module")
def package_process_results(tmp_path_factory, smoke_app):
    batches = {}
    for build in (False, True):
        root = tmp_path_factory.mktemp(f"package-process-{build}")
        cases = {}
        for outcome in ("success", "failure", "invalid", "timeout"):
            directory = root / f"smoke-{outcome}"
            directory.mkdir()
            cases[directory.name] = _package_process_case(directory, smoke_app, build, outcome)
        if not build:
            for name, prepare in [
                ("installation-check", _installation_check_case),
                ("post-install", _post_install_case),
            ]:
                directory = root / name
                directory.mkdir()
                cases[name] = prepare(directory, smoke_app)
        script = (
            REPO_ROOT / "scripts/release/build_windows_package.ps1" if build else INSTALLER_SCRIPT
        )
        batches[build] = _run_process_batch(root, script, cases)
    return batches


@pytest.fixture(scope="module")
def setup_process_results(tmp_path_factory, smoke_app):
    root = tmp_path_factory.mktemp("setup-processes")
    specs = [(f"descendants-{timeout}", _descendant_case, (timeout,)) for timeout in (False, True)]
    specs += [(f"python-{code}", _python_installer_case, (code,)) for code in (0, 3010, 7)]
    specs += [("native-probe", _native_probe_case, ()), ("invalid", _invalid_executable_case, ())]
    cases = {}
    for name, prepare, args in specs:
        directory = root / name
        directory.mkdir()
        cases[name] = prepare(directory, smoke_app, *args)
    return _run_process_batch(root, REPO_ROOT / "setup_windows.ps1", cases)


@pytest.fixture(scope="module")
def msi_process_results(tmp_path_factory):
    root = tmp_path_factory.mktemp("msi-rules")
    cases = {str(code): _msi_case(root / str(code), code) for code in (0, 3010, 7)}
    return _run_process_batch(root, REPO_ROOT / "setup_windows.ps1", cases)
