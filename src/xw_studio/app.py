"""Application factory: config, DI, theme, main window."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from xw_studio.core.config import load_config
from xw_studio.core.container import Container
from xw_studio.core.logging_setup import setup_logging
from xw_studio.core.signals import AppSignals
from xw_studio.core.updater import check_and_update

logger = logging.getLogger(__name__)


def _handle_exception(exc_type, exc_value, exc_tb):  # type: ignore[no-untyped-def]
    """Global exception handler — log and show dialog."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))
    QMessageBox.critical(
        None,
        "Unerwarteter Fehler",
        f"Ein unerwarteter Fehler ist aufgetreten:\n\n{exc_value}\n\n"
        "Bitte die Log-Datei pruefen.",
    )


def create_application() -> QApplication:
    """Build and return the fully wired QApplication."""
    setup_logging(log_dir=Path("logs"))
    logger.info("Starting XeisWorks Studio...")

    update_result = check_and_update(enabled=False)
    if update_result.updated:
        logger.info("Code updated from remote. Restart recommended.")

    config = load_config()
    app = QApplication(sys.argv)
    app.setApplicationName(config.app.name)
    app.setApplicationVersion("0.1.0")

    try:
        from qt_material import apply_stylesheet
        apply_stylesheet(app, theme=f"{config.app.theme}.xml")
    except Exception as exc:
        logger.warning("Could not apply qt-material theme: %s", exc)

    sys.excepthook = _handle_exception

    container = Container(config)
    container.register(AppSignals, lambda _: AppSignals())

    from xw_studio.ui.main_window import MainWindow
    window = MainWindow(container)
    window.show()

    return app
