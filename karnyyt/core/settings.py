"""
settings.py - ustawienia aplikacji (JSON) + lokalna historia „obejrzane".

Plik ustawień jest mały i zapisywany atomowo (tmp + replace). Historia
obejrzanych trzymana jest osobno (watched.json), żeby częste dopiski nie
przepisywały całego pliku konfiguracyjnego.
"""

from __future__ import annotations

import json
import logging
import os
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from PyQt5.QtCore import QObject, pyqtSignal

from . import paths

logger = logging.getLogger(__name__)

RESOLUTION_CHOICES: List[Any] = [144, 240, 360, 480, 720, 1080, 1440, 2160, "best"]
CARD_SIZE_CHOICES = ("small", "medium", "large")
LANGUAGE_CHOICES = ("pl", "en")

DEFAULT_EXTRA_MPV_ARGS = "--hwdec=auto-safe --cache=yes --demuxer-max-bytes=64MiB"

DEFAULTS: Dict[str, Any] = {
    "language": "pl",
    "resolution": 360,
    "prefer_h264": True,
    "extra_mpv_args": DEFAULT_EXTRA_MPV_ARGS,
    "mpv_path": "",
    "ytdlp_path": "",
    "ffmpeg_path": "",
    "card_size": "medium",
    "auto_refresh_min": 0,  # 0 = wyłączone
    "client_version": "",   # puste = domyślna z yt_feed_py38
    "window": {"w": 1240, "h": 780, "x": None, "y": None, "tab": 0},
}


def _sanitize(data: Dict[str, Any]) -> Dict[str, Any]:
    """Odsiewa wartości spoza zakresu, żeby ręcznie uszkodzony JSON
    nie wywrócił aplikacji."""
    out: Dict[str, Any] = {}
    for key, default in DEFAULTS.items():
        value = data.get(key, default)
        if key == "window":
            win = dict(DEFAULTS["window"])
            if isinstance(value, dict):
                for wkey in win:
                    if wkey in value:
                        win[wkey] = value[wkey]
            out[key] = win
        elif key == "resolution":
            out[key] = value if value in RESOLUTION_CHOICES else DEFAULTS[key]
        elif key == "language":
            out[key] = value if value in LANGUAGE_CHOICES else DEFAULTS[key]
        elif key == "card_size":
            out[key] = value if value in CARD_SIZE_CHOICES else DEFAULTS[key]
        elif key == "prefer_h264":
            out[key] = bool(value)
        elif key == "auto_refresh_min":
            try:
                out[key] = max(0, min(240, int(value)))
            except (TypeError, ValueError):
                out[key] = DEFAULTS[key]
        elif isinstance(default, str):
            out[key] = value if isinstance(value, str) else default
        else:
            out[key] = value
    return out


class Settings(QObject):
    """Ustawienia z sygnałem `changed(key, value)` dla GUI."""

    changed = pyqtSignal(str, object)

    def __init__(self, path: Optional[Path] = None) -> None:
        super().__init__()
        self._path = Path(path) if path else paths.settings_path()
        self._data: Dict[str, Any] = json.loads(json.dumps(DEFAULTS))  # deep copy
        self.load()

    # -- IO ---------------------------------------------------------------

    def load(self) -> None:
        try:
            if self._path.is_file():
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._data = _sanitize(raw)
        except (OSError, ValueError) as exc:
            logger.warning("Nie udało się wczytać ustawień (%s) - używam domyślnych.", exc)
            self._data = json.loads(json.dumps(DEFAULTS))

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(str(tmp), str(self._path))
        except OSError as exc:
            logger.warning("Nie udało się zapisać ustawień: %s", exc)

    # -- dostęp -----------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any, save: bool = True) -> None:
        if self._data.get(key) == value:
            return
        self._data[key] = value
        if save:
            self.save()
        self.changed.emit(key, value)

    # -- okno -------------------------------------------------------------

    def window_geom(self) -> Dict[str, Any]:
        return dict(self._data.get("window", DEFAULTS["window"]))

    def save_window_geom(self, x: int, y: int, w: int, h: int, tab: int) -> None:
        self._data["window"] = {"x": x, "y": y, "w": w, "h": h, "tab": tab}
        self.save()


class WatchedStore:
    """Lokalna historia obejrzanych filmów (id → znacznik).

    Kolejność wstawiania jest zachowywana; po przekroczeniu CAP najstarsze
    wpisy wypadają. Zapis synchroniczny - plik jest mały (max ~40 KB).
    """

    CAP = 2000

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path) if path else paths.watched_path()
        self._ids: "OrderedDict[str, None]" = OrderedDict()
        self._load()

    def _load(self) -> None:
        try:
            if self._path.is_file():
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    for vid in raw:
                        if isinstance(vid, str) and vid:
                            self._ids[vid] = None
        except (OSError, ValueError) as exc:
            logger.warning("Nie udało się wczytać historii: %s", exc)

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(list(self._ids.keys())), encoding="utf-8")
            os.replace(str(tmp), str(self._path))
        except OSError as exc:
            logger.warning("Nie udało się zapisać historii: %s", exc)

    def add(self, video_id: str) -> None:
        if not video_id:
            return
        if video_id in self._ids:
            self._ids.move_to_end(video_id)
        else:
            self._ids[video_id] = None
            while len(self._ids) > self.CAP:
                self._ids.popitem(last=False)
        self._save()

    def remove(self, video_id: str) -> None:
        if self._ids.pop(video_id, None) is not None:
            self._save()

    def clear(self) -> None:
        self._ids.clear()
        self._save()

    def ids(self) -> Set[str]:
        return set(self._ids.keys())

    def __contains__(self, video_id: str) -> bool:
        return video_id in self._ids

    def __len__(self) -> int:
        return len(self._ids)
