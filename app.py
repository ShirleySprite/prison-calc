# -*- coding: utf-8 -*-

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication

from calculator_window import CalculatorWindow

APPLICATION_DISPLAY_NAME = (
    "The Only Software That Truly Cares When You Get Freed from Your Bullshit Work"
)
APP_ICON_PATH = Path(__file__).resolve().parent / "assets" / "app_icon.png"
WINDOWS_APP_USER_MODEL_ID = "PrisonCalc.TheOnlySoftwareThatTrulyCares"


def _set_windows_app_user_model_id():
    """Give Windows a stable app identity for taskbar grouping and shortcuts."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        set_app_id = (
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID)
        set_app_id.argtypes = [ctypes.c_wchar_p]
        set_app_id.restype = ctypes.c_long
        set_app_id(WINDOWS_APP_USER_MODEL_ID)
    except Exception:
        # The Qt window icon and executable resource remain useful if unsupported.
        pass


def _configure_error_logging():
    logger = logging.getLogger("prison_calc")
    if logger.handlers:
        return

    logger.setLevel(logging.WARNING)
    try:
        log_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppLocalDataLocation)
        if not log_dir:
            raise OSError("Qt returned no application data directory")
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_dir / "errors.log", maxBytes=1_000_000,
            backupCount=3, encoding="utf-8")
    except OSError:
        # Keep diagnostics available even if the per-user data directory is unwritable.
        handler = logging.StreamHandler()

    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False


def main():
    _set_windows_app_user_model_id()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.Floor)
    qt_app = QApplication(sys.argv)
    qt_app.setOrganizationName("PrisonCalc")
    # Keep the internal ID stable so existing settings and log locations persist.
    qt_app.setApplicationName("WorkdayCalculator")
    qt_app.setApplicationDisplayName(APPLICATION_DISPLAY_NAME)
    app_icon = QIcon(str(APP_ICON_PATH))
    qt_app.setWindowIcon(app_icon)
    _configure_error_logging()
    window = CalculatorWindow()
    window.setWindowTitle(APPLICATION_DISPLAY_NAME)
    window.setWindowIcon(app_icon)
    window.show()
    sys.exit(qt_app.exec())


if __name__ == "__main__":
    main()
