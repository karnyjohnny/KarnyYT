"""
utils.py - drobne helpery współdzielone przez warstwy.

Bez zależności od Qt (poza tym moduł jest czysto pythonowy), żeby dało się
go testować bez wyświetlacza.
"""

from __future__ import annotations

import re
import shlex
from datetime import datetime
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_INLINE_ID_RE = re.compile(
    r"(?:v=|youtu\.be/|/live/|/shorts/|/embed/|/v/)([A-Za-z0-9_-]{11})"
)


def extract_video_id(text: str) -> Optional[str]:
    """Wyciąga video_id z dowolnego popularnego formatu URL YouTube
    (watch?v=, youtu.be, /live/, /shorts/, /embed/) albo z gołego ID."""
    if not text:
        return None
    t = text.strip()
    if _ID_RE.match(t):
        return t
    try:
        parsed = urlparse(t if "://" in t else "https://" + t)
    except ValueError:
        parsed = None
    if parsed is not None:
        host = (parsed.hostname or "").lower()
        if "youtube.com" in host or "youtu.be" in host:
            if host == "youtu.be":
                vid = parsed.path.lstrip("/").split("/")[0]
                if _ID_RE.match(vid or ""):
                    return vid
            if parsed.path.startswith("/watch"):
                v = parse_qs(parsed.query).get("v", [None])[0]
                if v and _ID_RE.match(v):
                    return v
            for prefix in ("/live/", "/shorts/", "/embed/", "/v/"):
                if parsed.path.startswith(prefix):
                    vid = parsed.path[len(prefix):].split("/")[0]
                    if _ID_RE.match(vid or ""):
                        return vid
    m = _INLINE_ID_RE.search(t)
    if m:
        return m.group(1)
    return None


def normalize_play_url(text: str) -> str:
    """Gołe ID zamienia w pełny URL; dokleja https:// gdy brakuje schematu."""
    t = (text or "").strip()
    if not t:
        return ""
    if _ID_RE.match(t):
        return "https://www.youtube.com/watch?v=" + t
    if "://" not in t:
        t = "https://" + t
    return t


# -- lokalizacja metadanych z YouTube (np. "23K views • 4 hours ago") -------

_PL_WORDS = {
    "views": "wyświetleń",
    "view": "wyświetlenie",
    "watching": "ogląda",
    "ago": "temu",
    "Streamed": "Transmisja",
    "streamed": "transmisja",
    "Premiered": "Premiera",
    "premiered": "premiera",
    "seconds": "sekund",
    "second": "sekund",
    "minutes": "minut",
    "minute": "minut",
    "hours": "godzin",
    "hour": "godzin",
    "days": "dni",
    "day": "dni",
    "weeks": "tygodni",
    "week": "tygodni",
    "months": "miesięcy",
    "month": "miesięcy",
    "years": "lat",
    "year": "lat",
}


def localize_meta(text: Optional[str], lang: str) -> str:
    """Tłumaczy angielskie jednostki YouTube na polski (lang == 'pl').
    Nie perfekt gramatycznie, ale czytelnie: "4 hours ago" -> "4 godzin temu"."""
    if not text:
        return ""
    if lang != "pl":
        return text

    def repl(m: "re.Match") -> str:
        return _PL_WORDS.get(m.group(0), m.group(0))

    pattern = r"\b(" + "|".join(re.escape(w) for w in _PL_WORDS) + r")\b"
    return re.sub(pattern, repl, text)


# -- argumenty mpv -----------------------------------------------------------


def parse_extra_args(raw: str) -> List[str]:
    """Dzieli pole „dodatkowe argumenty mpv" na listę argv.

    Backslashe zamieniamy na ukośniki (Windows API i mpv akceptują `/`
    w ścieżkach), dzięki czemu shlex w trybie posix poprawnie zdejmuje
    cudzysłowy i nie traktuje `\\` jako znaku ucieczki:
      --hwdec=auto-safe --title="moj tytul"  ->  ['--hwdec=auto-safe', '--title=moj tytul']
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        return [t for t in shlex.split(raw.replace("\\", "/"), posix=True) if t]
    except ValueError:
        return raw.split()


# -- czas ---------------------------------------------------------------------


def human_time(ts: Optional[float]) -> str:
    if not ts:
        return "--:--"
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def ytdlp_age_days(version: Optional[str]) -> Optional[int]:
    """Wersja yt-dlp to data (np. 2026.09.12) - zwraca wiek w dniach."""
    if not version:
        return None
    m = re.search(r"(\d{4})\.(\d{2})\.(\d{2})", version)
    if not m:
        return None
    try:
        d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    age = (datetime.now() - d).days
    return age if age >= 0 else None
