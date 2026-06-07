"""Application entry point."""

from __future__ import annotations

import sys

from .dpi import enable_windows_dpi_awareness
from .logging_setup import install_qt_message_handler, setup_application_logging


def main() -> int:
    setup_application_logging()
    enable_windows_dpi_awareness()

    import logging

    from PySide6.QtWidgets import QApplication

    from .app_icon import app_icon_path, load_app_icon
    from .toolbar import HotbarWindow

    logger = logging.getLogger(__name__)

    app = QApplication(sys.argv)
    app.setApplicationName("Tobii Gaze Mouse")
    app.setOrganizationName("PieLabs")
    icon = load_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    install_qt_message_handler()
    logger.info("Qt application created.")
    logger.info("Application icon: %s", app_icon_path() or "missing")

    window = HotbarWindow()
    if not icon.isNull():
        window.setWindowIcon(icon)
    window.show()

    exit_code = app.exec()
    logger.info("Application exited with code %s.", exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
