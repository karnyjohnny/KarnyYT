"""
feed_worker.py - QThread z własną pętlą asyncio wołający yt_feed_py38.

Kontrakt modułu feedu mówi wprost: NIE wolno odpalać go w wątku GUI.
Worker dostaje komendy przez queue.Queue (thread-safe), wykonuje je
sekwencyjnie w swojej pętli asyncio i odsyła wyniki sygnałami Qt:

  pages_ready(dict)      - {"FEwhat_to_watch": FeedPage, "FEsubscriptions": FeedPage}
  more_ready(str, page)  - wynik „wczytaj więcej" dla jednego targetu

Cookies i client_version są przechwytywane w momencie kolejkowania komendy
(na wątku GUI), więc aktualizacja cookies.json działa bez restartu apki.
"""

from __future__ import annotations

import asyncio
import logging
import queue
from typing import Any, Dict, Optional, Tuple

from PyQt5.QtCore import QThread, pyqtSignal

from .. import yt_feed_py38 as yf

logger = logging.getLogger(__name__)

# Komendy: ("all", cookies, client_version)
#          ("more", target, token, cookies, client_version)
Command = Tuple[Any, ...]


class FeedWorker(QThread):
    pages_ready = pyqtSignal(dict)
    more_ready = pyqtSignal(str, object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._q: "queue.Queue[Optional[Command]]" = queue.Queue()
        self._stop = False

    # -- API z GUI -----------------------------------------------------------

    def refresh_all(self, cookies_input: str, client_version: str = "") -> None:
        self._q.put(("all", cookies_input, client_version))

    def load_more(
        self, target: str, token: str, cookies_input: str,
        client_version: str = "",
    ) -> None:
        self._q.put(("more", target, token, cookies_input, client_version))

    def stop(self) -> None:
        self._stop = True
        self._q.put(None)

    @property
    def busy(self) -> bool:
        return not self._q.empty()

    # -- wątek ----------------------------------------------------------------

    def run(self) -> None:  # noqa: D102
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            while True:
                try:
                    cmd = self._q.get(timeout=0.1)
                except queue.Empty:
                    if self._stop:
                        break
                    continue
                if cmd is None:
                    break
                try:
                    loop.run_until_complete(self._handle(cmd))
                except Exception as exc:  # noqa: BLE001
                    logger.exception("FeedWorker: nieobsłużony wyjątek")
                    self._emit_unexpected(cmd, exc)
        finally:
            try:
                loop.close()
            except Exception:  # noqa: BLE001
                pass

    async def _handle(self, cmd: Command) -> None:
        kind = cmd[0]
        if kind == "all":
            _, cookies, cv = cmd
            pages = await yf.fetch_all_pages(cookies, cv or None)
            self.pages_ready.emit(pages)
        elif kind == "more":
            _, target, token, cookies, cv = cmd
            page = await yf.fetch_page(cookies, target, token, cv or None)
            self.more_ready.emit(target, page)

    def _emit_unexpected(self, cmd: Command, exc: Exception) -> None:
        page = yf.FeedPage(
            error=yf.FeedError(
                yf.FeedErrorCode.NETWORK_ERROR,
                f"Wewnętrzny błąd workera: {exc.__class__.__name__}: {exc}",
            )
        )
        if cmd and cmd[0] == "more":
            self.more_ready.emit(cmd[1], page)
        else:
            self.pages_ready.emit(
                {"FEwhat_to_watch": page, "FEsubscriptions": page}
            )
