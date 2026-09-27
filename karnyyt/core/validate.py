"""
validate.py - sprawdzanie dostępności mpv / yt-dlp / FFmpeg.

`shutil.which` jest darmowy (bez spawnu procesu), więc leci synchronicznie
przy starcie. Wersje narzędzi (`--version`) dobijamy osobnym wątkiem, żeby
nie blokować GUI - wynik przez sygnał Qt.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from typing import Dict, Optional

from PyQt5.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)

TOOLS = ("mpv", "yt-dlp", "ffmpeg")

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_FLAGS = _CREATE_NO_WINDOW if os.name == "nt" else 0


def find_tool(name: str, custom_path: str = "") -> Optional[str]:
    """Zwraca pełną ścieżkę do narzędzia albo None.

    Priorytet: ścieżka z ustawień (o ile istnieje) > PATH.
    """
    custom = (custom_path or "").strip().strip('"')
    if custom:
        if os.path.isfile(custom):
            return custom
        found = shutil.which(custom)
        if found:
            return found
    return shutil.which(name)


def check_all(settings) -> Dict[str, Optional[str]]:
    """Szybka walidacja przy starcie: {nazwa: ścieżka albo None}."""
    mapping = {
        "mpv": settings.get("mpv_path", ""),
        "yt-dlp": settings.get("ytdlp_path", ""),
        "ffmpeg": settings.get("ffmpeg_path", ""),
    }
    return {name: find_tool(name, mapping.get(name, "")) for name in TOOLS}


def _version_flag(name: str) -> str:
    return "-version" if name == "ffmpeg" else "--version"


def _probe_one(name: str, path: str) -> Optional[str]:
    try:
        proc = subprocess.run(
            [path, _version_flag(name)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=15,
            creationflags=_FLAGS,
        )
        out = proc.stdout.decode("utf-8", errors="replace").strip()
        if out:
            return out.splitlines()[0][:160]
        return None
    except Exception as exc:  # noqa: BLE001 - probe nie może niczego wywrócić
        logger.debug("Probe %s failed: %s", name, exc)
        return None


class VersionProber(QObject):
    """Dobija `--version` wszystkich narzędzi w tle (jedno threading.Thread)."""

    done = pyqtSignal(dict)  # {name: version_string or None}

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._thread: Optional[threading.Thread] = None

    def probe_async(self, found: Dict[str, Optional[str]]) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, args=(dict(found),), daemon=True
        )
        self._thread.start()

    def _run(self, found: Dict[str, Optional[str]]) -> None:
        versions: Dict[str, Optional[str]] = {}
        for name, path in found.items():
            versions[name] = _probe_one(name, path) if path else None
        self.done.emit(versions)
