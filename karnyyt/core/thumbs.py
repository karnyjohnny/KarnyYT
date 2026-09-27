"""
thumbs.py - pobieranie miniatur: worker-thread (asyncio + httpx) +
dwupoziomowy cache (dysk → RAM po stronie GUI).

Dlaczego httpx w wątku, a nie QNetworkAccessManager:
QNAM na Qt 5.15/Windows wymaga ręcznie dołożonych DLL-i OpenSSL 1.1.1
(klasyczny ból PyInstallera), a `ssl` z Pythona działa out-of-the-box -
httpx korzysta właśnie z niego. Przy okazji jedna biblioteka HTTP w całej
aplikacji.

Strategia URL-i:
  1. https://i.ytimg.com/vi/{id}/mqdefault.jpg  (320×180, ~17 KB, JPEG -
     najlżejsza sensowna do siatki i zawsze dekodowalna),
  2. thumbnail_url z feedu (fallback),
  3. hqdefault.jpg (ostatnia deska ratunku).

Miniatury YT są niemutowalne → cache dyskowy bez rewalidacji: raz
pobrane, nigdy więcej (do ręcznego wyczyszczenia folderu cache).
"""

from __future__ import annotations

import asyncio
import logging
import os
import queue
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

logger = logging.getLogger(__name__)

_THUMB_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)

_MAX_CONCURRENT = 4
_DISK_CAP = 5000          # max plików w cache miniatur
_DISK_TRIM_TO = 4000      # do ilu przycinamy po przekroczeniu


def thumb_candidates(video_id: str, feed_thumb_url: str = "") -> List[str]:
    urls = [f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"]
    if feed_thumb_url and feed_thumb_url not in urls:
        urls.append(feed_thumb_url)
    urls.append(f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg")
    return urls


class ThumbStore:
    """Cache dyskowy: {video_id}.img (surowe bajty odpowiedzi)."""

    def __init__(self, directory: Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._writes = 0
        self._lock = threading.Lock()

    def path(self, video_id: str) -> Path:
        return self._dir / f"{video_id}.img"

    def read(self, video_id: str) -> Optional[bytes]:
        try:
            p = self.path(video_id)
            if p.is_file():
                data = p.read_bytes()
                return data if len(data) > 200 else None
        except OSError:
            pass
        return None

    def write(self, video_id: str, data: bytes) -> None:
        try:
            with self._lock:
                tmp = self.path(video_id).with_suffix(".tmp")
                tmp.write_bytes(data)
                os.replace(str(tmp), str(self.path(video_id)))
                self._writes += 1
                if self._writes % 200 == 0:
                    self._trim()
        except OSError as exc:
            logger.debug("Zapis miniatury %s nieudany: %s", video_id, exc)

    def _trim(self) -> None:
        try:
            files = sorted(
                self._dir.glob("*.img"), key=lambda p: p.stat().st_mtime
            )
            if len(files) > _DISK_CAP:
                for old in files[: len(files) - _DISK_TRIM_TO]:
                    try:
                        old.unlink()
                    except OSError:
                        pass
        except OSError:
            pass


class ThumbWorker(QThread):
    """Sygnał: thumb_ready(video_id, QImage) - QImage.isNull() oznacza fail.

    Dekodowanie i skalowanie dzieje się W TYM wątku (QImage jest thread-safe
    do tworzenia/malowania poza GUI); do QPixmap konwertuje już GUI.
    """

    thumb_ready = pyqtSignal(str, object)

    def __init__(self, store: ThumbStore, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self._q: "queue.Queue[Optional[Tuple[str, List[str], int]]]" = queue.Queue()
        self._pending: Dict[str, bool] = {}
        self._pending_lock = threading.Lock()
        self._stop_flag = threading.Event()

    # -- API z GUI ----------------------------------------------------------

    def request(self, video_id: str, urls: List[str], target_w: int) -> None:
        if not video_id:
            return
        with self._pending_lock:
            if self._pending.get(video_id):
                return
            self._pending[video_id] = True
        self._q.put((video_id, urls, target_w))

    def stop(self) -> None:
        self._stop_flag.set()
        self._q.put(None)

    # -- wątek ---------------------------------------------------------------

    def run(self) -> None:  # noqa: D102
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._main())
        except Exception:  # noqa: BLE001
            logger.exception("ThumbWorker padł")
        finally:
            loop.close()

    async def _main(self) -> None:
        limits = httpx.Limits(
            max_connections=_MAX_CONCURRENT,
            max_keepalive_connections=_MAX_CONCURRENT,
            keepalive_expiry=30.0,
        )
        timeout = httpx.Timeout(connect=8.0, read=12.0, write=12.0, pool=8.0)
        headers = {"User-Agent": _THUMB_UA, "Referer": "https://www.youtube.com/"}
        async with httpx.AsyncClient(
            limits=limits,
            timeout=timeout,
            headers=headers,
            follow_redirects=True,
            trust_env=False,
        ) as client:
            consumers = [
                asyncio.ensure_future(self._consumer(client, i))
                for i in range(_MAX_CONCURRENT)
            ]
            await asyncio.gather(*consumers)

    async def _consumer(self, client: httpx.AsyncClient, idx: int) -> None:
        loop = asyncio.get_event_loop()
        while not self._stop_flag.is_set():
            try:
                req = await loop.run_in_executor(
                    None, self._q.get, True, 0.2
                )
            except queue.Empty:
                continue
            if req is None:
                self._q.put(None)  # niech pozostali konsumenci też wyjdą
                return
            video_id, urls, target_w = req
            try:
                img = await self._fetch_one(client, video_id, urls, target_w)
            except Exception:  # noqa: BLE001
                logger.debug("Miniatura %s: wyjątek", video_id, exc_info=True)
                img = QImage()
            finally:
                with self._pending_lock:
                    self._pending.pop(video_id, None)
            self.thumb_ready.emit(video_id, img)

    async def _fetch_one(
        self, client: httpx.AsyncClient, video_id: str, urls: List[str],
        target_w: int,
    ) -> QImage:
        data = await loop_run_in_executor(self._store.read, video_id)
        if data is None:
            data = await self._download(client, urls)
            if data is None:
                return QImage()
            # zapis do cache dyskowego - miniatura YT jest niemutowalna,
            # więc przy następnym starcie pójdzie z dysku bez sieci
            await loop_run_in_executor(self._store.write, video_id, data)
        img = QImage.fromData(data)
        if img.isNull():
            return QImage()
        if target_w > 0 and img.width() > target_w * 1.05:
            # FastTransformation - na Core 2 Duo smooth scale byłby marnotrawstwem
            h = max(1, round(img.height() * target_w / img.width()))
            img = img.scaled(
                target_w, h,
                1,  # Qt.KeepAspectRatio
                2,  # Qt.FastTransformation
            )
        return img

    async def _download(
        self, client: httpx.AsyncClient, urls: List[str]
    ) -> Optional[bytes]:
        for url in urls:
            try:
                resp = await client.get(url)
                if resp.status_code != 200 or len(resp.content) < 200:
                    continue
                ctype = resp.headers.get("content-type", "")
                if ctype and not ctype.startswith("image/"):
                    continue
                return resp.content
            except httpx.HTTPError:
                continue
        return None


async def loop_run_in_executor(func, *args):
    """Wrapper, żeby czytelnie wywołać sync-IO z asyncio."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, func, *args)
