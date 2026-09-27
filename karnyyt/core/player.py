"""
player.py - budowanie komend mpv + zarządzanie uruchomionymi procesami.

Kluczowe optymalizacje pod stare maszyny (Core 2 Duo / GMA 4500MHD):
  * preferencja H.264 (avc1) + AAC (mp4a) w selektorze formatu yt-dlp -
    VP9/AV1 dekodowane programowo dławią stary CPU, a H.264 ma sprzętowe
    DXVA2 już na Windows 7,
  * limit rozdzielczości `height<=?N` (domyślnie 360),
  * `--no-video --force-window` dla trybu audio - okno mpv ZAWSZE widoczne,
  * `--save-position-on-quit` - darmowe „wznów oglądanie" (mpv watch-later),
  * CREATE_NO_WINDOW - mpv.exe to aplikacja konsolowa; bez tej flagi obok
    playera miga czarne okno konsoli,
  * stdin/stdout/stderr odpięte - proces nie trzyma się rodzica.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from PyQt5.QtCore import QObject, pyqtSignal

from . import utils
from .i18n import tr
from .validate import find_tool

logger = logging.getLogger(__name__)

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_POPEN_FLAGS = _CREATE_NO_WINDOW if os.name == "nt" else 0


def build_ytdl_format(
    resolution: Any = 360, prefer_h264: bool = True, mode: str = "video"
) -> str:
    """Selektor formatu dla --ytdl-format z łańcuchem fallbacków.

    video (prefer_h264):
      bv*[h][avc1]+ba[aac] / b[h][avc1] / bv*[h]+ba / b[h] / bv*+ba / b
    audio:
      ba[aac] / ba   (albo samo ba bez preferencji)
    """
    if mode == "audio":
        return "ba[acodec^=mp4a]/ba" if prefer_h264 else "ba"

    if resolution in ("best", 0, None, ""):
        height = ""
        tail = "/bv*+ba/b"
    else:
        try:
            height = f"[height<=?{int(resolution)}]"
        except (TypeError, ValueError):
            height = "[height<=?360]"
        tail = ""

    if prefer_h264:
        return (
            f"bv*{height}[vcodec^=avc1]+ba[acodec^=mp4a]"
            f"/b{height}[vcodec^=avc1]"
            f"/bv*{height}+ba/b{height}{tail}"
        )
    return f"bv*{height}+ba/b{height}{tail}"


@dataclass
class PlayingEntry:
    proc: "subprocess.Popen"
    video_id: Optional[str]
    title: str
    mode: str
    started: float = field(default_factory=lambda: 0.0)


class MpvManager(QObject):
    """Odpala i śledzi procesy mpv wystartowane z aplikacji."""

    changed = pyqtSignal()  # lista „grających" się zmieniła

    def __init__(self, settings, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._entries: List[PlayingEntry] = []

    # -- budowanie komendy -------------------------------------------------

    def build_command(self, url: str, mode: str) -> List[str]:
        s = self._settings
        mpv = find_tool("mpv", s.get("mpv_path", "")) or "mpv"

        args: List[str] = [
            mpv,
            "--no-terminal",
            "--force-window",
            "--save-position-on-quit",
        ]
        if mode == "audio":
            args.append("--no-video")

        fmt = build_ytdl_format(
            s.get("resolution", 360), bool(s.get("prefer_h264", True)), mode
        )
        args += [f"--ytdl-format={fmt}"]

        ytdlp = find_tool("yt-dlp", s.get("ytdlp_path", ""))
        if ytdlp:
            args += [f"--script-opts=ytdl_hook-ytdl_path={ytdlp}"]

        args += utils.parse_extra_args(s.get("extra_mpv_args", ""))
        args.append(url)
        args.append("--profile=fast")
        args.append("--hwdec=auto")
        return args

    # -- uruchamianie -------------------------------------------------------

    def play(
        self, url: str, mode: str = "video", title: str = "",
        video_id: Optional[str] = None,
    ) -> Optional[str]:
        """Zwraca None przy sukcesie albo PRZETŁUMACZONY komunikat błędu."""
        url = utils.normalize_play_url(url)
        if not url:
            return tr("err.empty_url")

        if not find_tool("mpv", self._settings.get("mpv_path", "")):
            return tr("err.no_mpv")

        cmd = self.build_command(url, mode)
        logger.info("mpv [%s]: %s", mode, " ".join(cmd[:6]) + " … " + url)

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_POPEN_FLAGS,
                close_fds=True,
            )
        except OSError as exc:
            logger.warning("Nie udało się uruchomić mpv: %s", exc)
            return tr("err.launch_failed", msg=str(exc))

        import time

        self._entries.append(
            PlayingEntry(proc, video_id, title or url, mode, time.time())
        )
        self.changed.emit()
        return None

    # -- stan ----------------------------------------------------------------

    def poll(self) -> None:
        """Wywoływane z QTimer GUI: sprząta zakończone procesy."""
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.proc.poll() is None]
        if len(self._entries) != before:
            self.changed.emit()

    def playing_ids(self) -> Set[str]:
        return {e.video_id for e in self._entries if e.video_id}

    def has_playing(self) -> bool:
        return bool(self._entries)

    def current_label(self) -> str:
        if not self._entries:
            return ""
        e = self._entries[-1]
        return e.title

    def stop_all(self) -> None:
        for e in self._entries:
            try:
                e.proc.terminate()
            except OSError:
                pass
        for e in self._entries:
            try:
                e.proc.wait(timeout=2.0)
            except Exception:  # noqa: BLE001
                try:
                    e.proc.kill()
                except OSError:
                    pass
        self._entries.clear()
        self.changed.emit()
