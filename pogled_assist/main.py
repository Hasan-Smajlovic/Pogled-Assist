"""Application entry point."""

from __future__ import annotations

import contextlib
import os
import sys
import time
import traceback
from pathlib import Path

from .logging_setup import (
    install_qt_message_handler,
    setup_application_logging,
    shutdown_application_logging,
)
from .tracking.tobii_stream_engine import APP_ROOT_ENV
from .windows.dpi import enable_windows_dpi_awareness

PACKAGE_SMOKE_TEST_ARG = "--package-smoke-test"
PACKAGE_SMOKE_REPORT_ENV = "POGLED_ASSIST_PACKAGE_SMOKE_REPORT"
MOUSE_GAZE_SIMULATION_ARG = "--simulate-gaze"
INSTALLATION_CHECK_ARG = "--installation-check"


def main() -> int:
    frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        os.environ.setdefault(APP_ROOT_ENV, str(Path(sys.executable).resolve().parent))

    if PACKAGE_SMOKE_TEST_ARG in sys.argv[1:]:
        return package_smoke_test()

    if INSTALLATION_CHECK_ARG in sys.argv[1:]:
        from .ui.installation_window import show_installation_check

        return show_installation_check()

    simulate_gaze = MOUSE_GAZE_SIMULATION_ARG in sys.argv[1:]
    if simulate_gaze and frozen:
        print("Mouse gaze simulation is available only from a development checkout.")
        return 2

    lock = application_lock()
    if not lock.tryLock(0):
        from PySide6.QtCore import QLockFile

        if lock.error() == QLockFile.LockError.LockFailedError:
            return 0
        print("Pogled Assist ne može osigurati jedno pokretanje aplikacije.")
        return 1
    try:
        return _run_application(simulate_gaze=simulate_gaze)
    finally:
        shutdown_application_logging()
        lock.unlock()


def application_lock():
    """One interactive app per user; diagnostics never acquire this lock."""
    from PySide6.QtCore import QLockFile, QStandardPaths

    directory = Path(QStandardPaths.writableLocation(QStandardPaths.TempLocation))
    lock = QLockFile(str(directory / "pogled-assist-interactive.lock"))
    # A long-running session is not stale. Qt can still recover a dead owner's lock.
    lock.setStaleLockTime(0)
    return lock


def _run_application(*, simulate_gaze: bool) -> int:
    setup_application_logging()
    enable_windows_dpi_awareness()

    import logging

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from .app_icon import app_icon_path, load_app_icon
    from .toolbar import HotbarWindow

    logger = logging.getLogger(__name__)

    application_arguments = [
        argument for argument in sys.argv if argument != MOUSE_GAZE_SIMULATION_ARG
    ]
    app = QApplication(application_arguments)
    app.setApplicationName("Pogled Assist")
    app.setOrganizationName("Pogled Assist")
    icon = load_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    install_qt_message_handler()
    logger.info("Qt application created.")
    from PySide6 import __version__ as qt_version

    from . import diagnostics

    diagnostics.emit(
        "qt_runtime", priority=True, qt_version=qt_version, simulate_gaze=simulate_gaze
    )
    last_tick = [time.monotonic()]
    heartbeat = QTimer(app)
    heartbeat.setInterval(1000)

    def log_heartbeat() -> None:
        now = time.monotonic()
        diagnostics.emit(
            "ui_heartbeat",
            priority=True,
            interval_s=now - last_tick[0],
            qt_timer_late_ms=max(0.0, (now - last_tick[0]) * 1000 - 1000),
        )
        last_tick[0] = now

    heartbeat.timeout.connect(log_heartbeat)
    heartbeat.start()
    logger.info("Application icon: %s", app_icon_path() or "missing")

    window = HotbarWindow(simulate_gaze=simulate_gaze)
    if not icon.isNull():
        window.setWindowIcon(icon)
    window.show()

    exit_code = app.exec()
    heartbeat.stop()
    logger.info("Application exited with code %s.", exit_code)
    return exit_code


def package_smoke_test() -> int:
    """Check imports and files required by the packaged application."""

    try:
        from .app_icon import app_icon_path
        from .suggestions.model import (
            ISLAMIC_MODEL_METADATA_PATH,
            ISLAMIC_MODEL_PATH,
            MODEL_METADATA_PATH,
            MODEL_PATH,
            load_model,
        )
        from .toolbar import HotbarWindow
        from .tracking.tobii_stream_engine_bridge_backend import bridge_script_path
        from .ui.settings_window import _checkbox_x_image_url
        from .windows.windows_startup import launcher_script_path

        required_paths = (
            app_icon_path(),
            Path(_checkbox_x_image_url()),
            MODEL_PATH,
            MODEL_METADATA_PATH,
            ISLAMIC_MODEL_PATH,
            ISLAMIC_MODEL_METADATA_PATH,
            bridge_script_path(),
            launcher_script_path(),
        )
        imports_loaded = HotbarWindow is not None
        path_results = [(path, bool(path and path.is_file())) for path in required_paths]
        model = load_model()
        suggestions_loaded = "ŽELIM" in model.predict("žel") and "KUR'AN" in model.predict("kur")
        if getattr(sys, "frozen", False):
            from .speech.bundle_check import verify_bundled_speech
            from .tracking.tobii_stream_engine_bridge_backend import verify_bundled_bridge

            verify_bundled_speech(Path(sys.executable).resolve().parent)
            verify_bundled_bridge(Path(sys.executable).resolve().parent)
    except Exception:
        _write_package_smoke_report([traceback.format_exc()])
        return 1

    report_lines = [
        f"imports_loaded={imports_loaded}",
        f"suggestions_loaded={suggestions_loaded}",
    ]
    report_lines.extend(f"{path} exists={exists}" for path, exists in path_results)
    _write_package_smoke_report(report_lines)

    return (
        0
        if imports_loaded and suggestions_loaded and all(exists for _, exists in path_results)
        else 1
    )


def _write_package_smoke_report(lines: list[str]) -> None:
    report_path = os.environ.get(PACKAGE_SMOKE_REPORT_ENV, "").strip()
    if not report_path:
        return

    with contextlib.suppress(OSError):
        Path(report_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
