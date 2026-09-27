"""
app.py - punkt startowy aplikacji: logowanie, motyw, ustawienia, okno.

Trzyma też globalny excepthook - w binarce windowed (--noconsole) każdy
nieobsłużony wyjątek inaczej zabiłby aplikację po cichu.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import traceback
from typing import List, Optional

from . import __version__, yt_feed_py38
from .core import paths
from .core.i18n import set_lang, tr
from .core.settings import Settings, WatchedStore

logger = logging.getLogger("karnyyt")


def setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            str(paths.log_path()),
            maxBytes=1_000_000,
            backupCount=2,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError:
        pass
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)
    root.addHandler(stream_handler)
    # httpx/httpcore są gadatliwe na INFO - nie zaśmiecają logu
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _install_excepthook() -> None:
    def hook(exc_type, exc_value, tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc_value, tb))
        logger.critical("Nieobsłużony wyjątek:\n%s", text)
        try:
            from PyQt5.QtWidgets import QMessageBox

            QMessageBox.critical(None, tr("dlg.error_title"), text[-1800:])
        except Exception:  # noqa: BLE001
            pass

    sys.excepthook = hook


def main(argv: Optional[List[str]] = None) -> int:
    from PyQt5.QtGui import QFont, QIcon
    from PyQt5.QtWidgets import QApplication

    setup_logging()
    logger.info("KarnyYT %s start (Python %s)", __version__, sys.version.split()[0])

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("KarnyYT")
    app.setOrganizationName("KarnyJohnny")
    app.setApplicationVersion(__version__)
    # Segoe UI i tak jest domyślne na Windows; gdzie indziej Qt fallbackuje
    app.setFont(QFont("Segoe UI", 9))

    from .ui import theme

    theme.apply_theme(app)

    icon_path = paths.resource_path("assets/icon.ico")
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    if os.name == "nt":
        # własna ikona/nazwa na pasku zadań Windows zamiast "python.exe"
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "KarnyYT.App"
            )
        except Exception:  # noqa: BLE001
            pass

    settings = Settings()
    set_lang(str(settings.get("language", "pl")))

    def _apply_client_version(key: str, value) -> None:
        if key == "client_version":
            yt_feed_py38.set_client_version(str(value or "") or None)

    _apply_client_version("client_version", settings.get("client_version", ""))
    settings.changed.connect(_apply_client_version)

    watched = WatchedStore()

    _install_excepthook()

    from .ui.main_window import MainWindow

    window = MainWindow(settings, watched)
    window.show()
    logger.info("Okno główne wyświetlone.")
    return app.exec_()
