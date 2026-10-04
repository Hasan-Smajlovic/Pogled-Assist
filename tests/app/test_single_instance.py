from __future__ import annotations

import os
import subprocess
import sys

import pytest
from PySide6.QtCore import QLockFile, QStandardPaths

from pogled_assist import main


@pytest.fixture
def isolated_lock(monkeypatch, tmp_path):
    monkeypatch.setattr(QStandardPaths, "writableLocation", lambda _location: str(tmp_path))
    return main.application_lock()


def test_second_launch_exits_before_logs_services_or_focus_changes(monkeypatch, isolated_lock):
    assert isolated_lock.tryLock(0)
    calls = []
    monkeypatch.setattr(sys, "argv", ["run_gaze_mouse.py"])
    monkeypatch.setattr(main, "setup_application_logging", lambda: calls.append("logging"))
    monkeypatch.setattr(main, "_run_application", lambda **_kwargs: calls.append("app"))
    try:
        assert main.main() == 0
        assert calls == []
    finally:
        isolated_lock.unlock()


def test_lock_is_released_on_normal_exit_and_startup_failure(monkeypatch, isolated_lock):
    monkeypatch.setattr(sys, "argv", ["run_gaze_mouse.py"])
    monkeypatch.setattr(main, "_run_application", lambda **_kwargs: 17)
    assert main.main() == 17
    assert isolated_lock.tryLock(0)
    isolated_lock.unlock()

    def fail(**_kwargs):
        raise RuntimeError("Synthetic startup failure")

    monkeypatch.setattr(main, "_run_application", fail)
    with pytest.raises(RuntimeError):
        main.main()
    assert isolated_lock.tryLock(0)
    isolated_lock.unlock()


def test_lock_permission_failure_does_not_start_app(monkeypatch, isolated_lock, capsys):
    class FailedLock:
        def tryLock(self, _timeout):
            return False

        def error(self):
            return QLockFile.PermissionError

    monkeypatch.setattr(main, "application_lock", FailedLock)
    monkeypatch.setattr(sys, "argv", ["run_gaze_mouse.py"])
    assert main.main() == 1
    assert "jedno pokretanje" in capsys.readouterr().out


def test_diagnostics_bypass_interactive_lock(monkeypatch, isolated_lock):
    from pogled_assist.ui import installation_window

    def unexpected_start(*_args, **_kwargs):
        pytest.fail("Diagnostics must not start the interactive application or its services")

    for name in (
        "_run_application",
        "setup_application_logging",
        "install_qt_message_handler",
        "enable_windows_dpi_awareness",
    ):
        monkeypatch.setattr(main, name, unexpected_start)

    assert isolated_lock.tryLock(0)
    try:
        monkeypatch.setattr(main, "package_smoke_test", lambda: 23)
        monkeypatch.setattr(sys, "argv", ["app", "--package-smoke-test"])
        assert main.main() == 23
        monkeypatch.setattr(installation_window, "show_installation_check", lambda: 24)
        monkeypatch.setattr(sys, "argv", ["app", "--installation-check"])
        assert main.main() == 24
    finally:
        isolated_lock.unlock()


def test_lock_recovers_after_process_exits_without_unlocking(tmp_path):
    path = tmp_path / "abandoned.lock"
    # Deliberately bypass destructors to represent a crash, using synthetic data.
    script = "import os,sys; from PySide6.QtCore import QLockFile; lock=QLockFile(sys.argv[1]); os._exit(0 if lock.tryLock(0) else 1)"
    subprocess.run(
        [sys.executable, "-c", script, str(path)],
        check=True,
        timeout=10,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    assert path.exists()
    lock = QLockFile(str(path))
    lock.setStaleLockTime(0)
    assert lock.tryLock(0)
    lock.unlock()
