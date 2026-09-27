"""
paths.py - wszystkie lokalizacje plików aplikacji w jednym miejscu.

Dwa tryby:
  * standardowy: %APPDATA%\\KarnyYT (dane) + %LOCALAPPDATA%\\KarnyYT (cache),
  * portable:    jeśli obok exe istnieje plik `portable.txt`, wszystko
                 (dane + cache) ląduje w katalogu `data` obok exe.

Zmienne środowiskowe KARNYYT_DATA_DIR / KARNYYT_CACHE_DIR nadpisują
lokalizacje (używane m.in. w testach).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "KarnyYT"


def app_dir() -> Path:
    """Katalog aplikacji: obok exe (frozen) albo root repozytorium (dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # karnyyt/core/paths.py -> repo root to dwa poziomy wyżej niż package
    return Path(__file__).resolve().parent.parent.parent


def is_portable() -> bool:
    return (app_dir() / "portable.txt").is_file()


def _env_dir(name: str) -> "Path | None":
    value = os.environ.get(name)
    if value:
        return Path(value)
    return None


def data_dir() -> Path:
    """Ustawienia, cookies, historia, logi."""
    override = _env_dir("KARNYYT_DATA_DIR")
    if override is not None:
        p = override
    elif is_portable():
        p = app_dir() / "data"
    else:
        base = os.environ.get("APPDATA")
        if base:
            p = Path(base) / APP_NAME
        else:
            p = Path.home() / ".config" / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir() -> Path:
    """Cache miniatur (dużo plików, nadaje się do czyszczenia)."""
    override = _env_dir("KARNYYT_CACHE_DIR")
    if override is not None:
        p = override
    elif is_portable():
        p = app_dir() / "data" / "cache"
    else:
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            p = Path(base) / APP_NAME / "cache"
        else:
            p = Path.home() / ".cache" / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def thumbs_dir() -> Path:
    p = cache_dir() / "thumbs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def cookies_path() -> Path:
    return data_dir() / "cookies.json"


def settings_path() -> Path:
    return data_dir() / "settings.json"


def watched_path() -> Path:
    return data_dir() / "watched.json"


def feed_cache_path() -> Path:
    return data_dir() / "feed_cache.json"


def log_path() -> Path:
    return data_dir() / "karnyyt.log"


def resource_path(rel: str) -> Path:
    """Zasób dołączony do binarki (PyInstaller _MEIPASS) albo z repo (dev)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / rel
    return app_dir() / rel
