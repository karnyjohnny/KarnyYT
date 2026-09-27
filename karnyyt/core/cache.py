"""
cache.py - dyskowy cache ostatniego udanego feedu (stale-while-revalidate).

Dzięki niemu aplikacja na starcie POKAZUJE COŚ OD RAZU (ostatni feed),
a świeże dane dobija w tle. Na starym laptopie różnica w odczuwalnej
szybkości startu jest ogromna.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import yt_feed_py38 as yf

logger = logging.getLogger(__name__)

_VIDEO_FIELDS = {f for f in yf.VideoItem.__dataclass_fields__}  # type: ignore[attr-defined]


def _video_to_dict(video: yf.VideoItem) -> Dict[str, Any]:
    return asdict(video)


def _video_from_dict(data: Dict[str, Any]) -> Optional[yf.VideoItem]:
    if not isinstance(data, dict):
        return None
    kwargs = {k: v for k, v in data.items() if k in _VIDEO_FIELDS}
    required = ("video_id", "title", "url", "thumbnail_url")
    if not all(isinstance(kwargs.get(k), str) and kwargs.get(k) for k in required):
        return None
    try:
        return yf.VideoItem(**kwargs)
    except TypeError:
        return None


def save_feed_cache(path: Path, pages: Dict[str, "yf.FeedPage"]) -> None:
    """Zapisuje tylko UDANE strony feedu (błędy nie nadpisują dobrego cache)."""
    payload: Dict[str, Any] = {}
    for target, page in pages.items():
        if page is None or not page.ok:
            continue
        payload[target] = {
            "ts": time.time(),
            "videos": [_video_to_dict(v) for v in page.videos],
            "continuation": page.continuation,
        }
    if not payload:
        return
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(path))
    except (OSError, TypeError, ValueError) as exc:
        logger.warning("Zapis cache feedu nieudany: %s", exc)


def load_feed_cache(path: Path) -> Dict[str, Dict[str, Any]]:
    """Zwraca {target: {"ts": float, "videos": [VideoItem], "continuation": str|None}}."""
    result: Dict[str, Dict[str, Any]] = {}
    try:
        path = Path(path)
        if not path.is_file():
            return result
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return result
        for target, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            videos: List[yf.VideoItem] = []
            for vdict in entry.get("videos", []) or []:
                video = _video_from_dict(vdict)
                if video is not None:
                    videos.append(video)
            cont = entry.get("continuation")
            result[target] = {
                "ts": float(entry.get("ts") or 0.0),
                "videos": videos,
                "continuation": cont if isinstance(cont, str) else None,
            }
    except (OSError, ValueError) as exc:
        logger.warning("Odczyt cache feedu nieudany: %s", exc)
    return result
