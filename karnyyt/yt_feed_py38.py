"""
yt_feed_py38.py - klient nieoficjalnego (prywatnego) API YouTube ("browse"),
zwraca feed "Co obejrzeć" i "Subskrypcje" na podstawie cookies z sesji
przeglądarki. Zaprojektowany do użycia w aplikacji GUI (PyQt5).

WAŻNE (kruchość podejścia):
To NIE jest oficjalne API. Endpoint, payload i sposób parsowania mogą się
zmienić bez ostrzeżenia po stronie YouTube. Kod jest odporny na typowe
przyczyny awarii (wygasła sesja, zmieniona struktura odpowiedzi, błąd
sieci), ale nie ma gwarancji długoterminowej stabilności.

Użycie z PyQt5:
Ten moduł jest w 100% async (httpx.AsyncClient) i NIE wolno go wołać
bezpośrednio z wątku GUI (zablokuje UI / rzuci błędem braku event loopa).
Zalecany wzorzec: własny QThread z pętlą asyncio uruchamianą przez
asyncio.run(), komunikacja z GUI przez sygnały Qt. Patrz YT_FEED_AGENT.md.

--------------------------------------------------------------------------
ROZSZERZENIA KarnyYT (addatywne - stare API bez zmian):
  * FeedPage            - wynik "strony" feedu: filmy + token continuation + błąd
  * fetch_page()        - jednorazowy fetch z opcjonalnym continuation ("wczytaj więcej")
  * fetch_all_pages()   - HOME + SUBSKRYPCJE równolegle jako FeedPage
  * set_client_version() / parametr client_version - override CLIENT_VERSION
                          bez edycji pliku (np. z ustawień aplikacji)
Stare funkcje (fetch_youtube_feed, fetch_youtube_feeds, YouTubeFeedClient)
działają dokładnie tak jak wcześniej i korzystają z tego samego rdzenia.
--------------------------------------------------------------------------
"""

from __future__ import annotations

import asyncio
import enum
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Final, FrozenSet, List, Literal, Optional, Tuple, Union

import httpx

logger = logging.getLogger(__name__)

YOUTUBE_BROWSE_URL: Final = "https://www.youtube.com/youtubei/v1/browse"
YOUTUBE_ORIGIN: Final = "https://www.youtube.com"

# Chrome 151 / Windows 10-11 (stan na wrzesień 2026).
# Chrome robi "UA reduction" - realna wersja systemu i tak nie jest
# ujawniana w headerze, więc "Windows NT 10.0" jest poprawne również dla Win11.
USER_AGENT: Final = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

# UWAGA: YouTube rotuje ten string mniej więcej co tydzień (format
# 2.<YYYYMMDD>.<build>.00, data = dzień builda strony, nie dzisiejsza data).
# Stały string prędzej czy później się "zestarzeje" - YT zwykle to toleruje
# (endpoint browse nie jest tak czuły jak player), ale jeśli zaczniesz
# dostawać puste/błędne odpowiedzi mimo poprawnych cookies, to pierwsze
# podejrzane miejsce. Najpewniejsze źródło prawdy: otwórz youtube.com
# zalogowany, w źródle strony poszukaj "INNERTUBE_CONTEXT_CLIENT_VERSION".
# W KarnyYT można nadpisać tę wartość przez set_client_version() /
# parametr client_version (Ustawienia -> Zaawansowane) bez edycji pliku.
CLIENT_VERSION: Final = "2.20260904.01.00"

BrowseTarget = Literal["FEwhat_to_watch", "FEsubscriptions"]
CookieDict = Dict[str, str]

TARGETS: Final[FrozenSet[str]] = frozenset(("FEwhat_to_watch", "FEsubscriptions"))

# Globalny override CLIENT_VERSION (None = użyj stałej powyżej).
_CLIENT_VERSION_OVERRIDE: Optional[str] = None


class FeedErrorCode(enum.Enum):
    """Maszynowo-rozróżnialna przyczyna błędu - GUI/agent ma po tym branchować,
    nie po treści komunikatu (message jest tylko do wyświetlenia/logów)."""

    INVALID_TARGET = "invalid_target"
    COOKIES_LOAD_FAILED = "cookies_load_failed"
    MISSING_SAPISID = "missing_sapisid"
    NOT_STARTED = "not_started"
    NETWORK_ERROR = "network_error"
    SESSION_INVALID = "session_invalid"  # cookies wygasłe/nieprawidłowe
    UNEXPECTED_RESPONSE = "unexpected_response"  # zmieniona struktura odpowiedzi YT
    JSON_DECODE_ERROR = "json_decode_error"


@dataclass(frozen=True)
class FeedError:
    """Wynik błędu - zamiast dict {"error": str}, żeby GUI mogło
    switchować po `code` zamiast parsować tekst."""

    code: FeedErrorCode
    message: str


@dataclass(frozen=True)
class VideoItem:
    """Pojedynczy wpis w feedzie. Pola tekstowe, których YT nie zwrócił,
    to None (nie polski placeholder) - decyzję o tym, co pokazać w UI
    przy braku danych, podejmuje warstwa GUI."""

    video_id: str
    title: str
    url: str
    thumbnail_url: str
    author: Optional[str] = None
    duration: Optional[str] = None  # None = brak overlaya (może być LIVE bez odznaki)
    views: Optional[str] = None
    published_time: Optional[str] = None


# Wynik pojedynczego fetcha: albo lista wideo (może być pusta - to nie błąd,
# tylko pusty feed), albo FeedError.
FetchResult = Union[List[VideoItem], FeedError]


@dataclass(frozen=True)
class FeedPage:
    """ROZSZERZENIE KarnyYT: jedna "strona" feedu.

    videos       - rozpoznane filmy (może być pusta lista - to nie błąd),
    continuation - token do pobrania kolejnej porcji ("wczytaj więcej") albo None,
    error        - FeedError gdy wystąpił problem, inaczej None.
    """

    videos: List[VideoItem] = field(default_factory=list)
    continuation: Optional[str] = None
    error: Optional[FeedError] = None

    @property
    def ok(self) -> bool:
        return self.error is None


def is_error(result: FetchResult) -> bool:
    """Helper dla GUI/agenta: `if is_error(result): ...` zamiast isinstance."""
    return isinstance(result, FeedError)


def set_client_version(version: Optional[str]) -> None:
    """ROZSZERZENIE KarnyYT: globalny override CLIENT_VERSION.

    Przekaż None, aby wrócić do wartości domyślnej z tego pliku.
    Używane przez GUI (Ustawienia -> Zaawansowane), gdy YouTube zmieni
    wersję klienta, a aplikacja nie została jeszcze zaktualizowana.
    """
    global _CLIENT_VERSION_OVERRIDE
    version = (version or "").strip() or None
    if version == CLIENT_VERSION:
        version = None
    _CLIENT_VERSION_OVERRIDE = version


def _resolve_client_version(override: Optional[str] = None) -> str:
    """Kolejność: jawny parametr > globalny override > stała CLIENT_VERSION."""
    override = (override or "").strip()
    if override:
        return override
    if _CLIENT_VERSION_OVERRIDE:
        return _CLIENT_VERSION_OVERRIDE
    return CLIENT_VERSION


def _safe_get(data: Any, *keys: Any, default: Any = None) -> Any:
    """Bezpieczne pobieranie zagnieżdżonych wartości z dict/list."""
    for key in keys:
        if isinstance(data, dict):
            data = data.get(key, default)
        elif isinstance(data, list) and isinstance(key, int) and 0 <= key < len(data):
            data = data[key]
        else:
            return default

        if data is None:
            return default

    return data


def _get_sapisid_hash(sapisid: str, origin: str = YOUTUBE_ORIGIN) -> str:
    """Generuje nagłówek Authorization SAPISIDHASH."""
    now = str(int(time.time()))
    sha1 = hashlib.sha1(f"{now} {sapisid} {origin}".encode()).hexdigest()
    return f"SAPISIDHASH {now}_{sha1}"


def _load_cookies(cookies_input: str) -> CookieDict:
    """
    Wczytuje cookies ze ścieżki do pliku albo bezpośrednio z JSON.
    Obsługuje listę Cookie-Editora oraz zwykły dict.
    Rzuca ValueError przy błędnym formacie (celowo - warstwa wywołująca
    łapie to i mapuje na FeedError).
    """
    if not isinstance(cookies_input, str):
        raise ValueError("Cookies muszą być podane jako string (ścieżka lub JSON).")

    path = Path(cookies_input)
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        try:
            data = json.loads(cookies_input)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "Podany ciąg nie jest ani prawidłową ścieżką do pliku, "
                "ani poprawnym JSON-em."
            ) from exc

    if isinstance(data, list):
        return {
            item["name"]: item["value"]
            for item in data
            if isinstance(item, dict) and "name" in item and "value" in item
        }

    if isinstance(data, dict):
        return data

    raise ValueError(
        "Nieobsługiwany format pliku cookies. Oczekiwano listy lub słownika."
    )


def _resolve_sapisid(cookies: CookieDict) -> str:
    sapisid = cookies.get("SAPISID") or cookies.get("__Secure-3PAPISID")
    if not sapisid:
        raise ValueError(
            "Brak ciasteczka SAPISID lub __Secure-3PAPISID. "
            "Zaloguj się i wyeksportuj cookies."
        )
    return sapisid


def _build_headers(sapisid: str) -> Dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        "Origin": YOUTUBE_ORIGIN,
        "Referer": f"{YOUTUBE_ORIGIN}/",
        "Authorization": _get_sapisid_hash(sapisid),
        "X-Origin": YOUTUBE_ORIGIN,
    }


def _build_payload(
    target: str,
    continuation: Optional[str] = None,
    client_version: Optional[str] = None,
) -> Dict[str, Any]:
    if continuation:
        # Żądanie "wczytaj więcej" - ten sam endpoint, zamiast browseId
        # wysyłamy token continuation z poprzedniej odpowiedzi.
        return {
            "context": {
                "client": {
                    "clientName": "WEB",
                    "clientVersion": _resolve_client_version(client_version),
                }
            },
            "continuation": continuation,
        }
    return {
        "context": {
            "client": {
                "clientName": "WEB",
                "clientVersion": _resolve_client_version(client_version),
            }
        },
        "browseId": target,
    }


def _check_response_markers(response_text: str) -> None:
    """Wspólne wykrywanie nieważnej sesji / zmienionej struktury odpowiedzi.
    Rzuca RuntimeError("session_invalid" | "unexpected_response")."""
    if (
        "feedNudgeRenderer" in response_text
        or "Your YouTube history is off" in response_text
    ):
        raise RuntimeError("session_invalid")

    if (
        "richItemRenderer" not in response_text
        and "lockupViewModel" not in response_text
    ):
        raise RuntimeError("unexpected_response")


def _extract_initial_items(raw_data: Dict[str, Any], response_text: str) -> List[Any]:
    """Ścieżka do listy elementów feedu z PIERWSZEJ odpowiedzi browse."""
    _check_response_markers(response_text)

    items = (
        raw_data.get("contents", {})
        .get("twoColumnBrowseResultsRenderer", {})
        .get("tabs", [{}])[0]
        .get("tabRenderer", {})
        .get("content", {})
        .get("richGridRenderer", {})
        .get("contents", [])
    ) or []

    if not isinstance(items, list):
        items = []
    return items


def _extract_continuation_items(
    raw_data: Dict[str, Any], response_text: str
) -> List[Any]:
    """ROZSZERZENIE KarnyYT: elementy z odpowiedzi na żądanie continuation."""
    _check_response_markers(response_text)

    actions = raw_data.get("onResponseReceivedActions")
    if not isinstance(actions, list):
        raise RuntimeError("unexpected_response")

    items: List[Any] = []
    for action in actions:
        appended = _safe_get(
            action, "appendContinuationItemsAction", "continuationItems", default=[]
        )
        if isinstance(appended, list):
            items.extend(appended)

    if not items:
        raise RuntimeError("unexpected_response")
    return items


def _extract_continuation_token(items: List[Any]) -> Optional[str]:
    """ROZSZERZENIE KarnyYT: token kolejnej strony (zwykle ostatni element listy)."""
    if not isinstance(items, list):
        return None
    for item in reversed(items):
        if not isinstance(item, dict):
            continue
        token = _safe_get(
            item,
            "continuationItemRenderer",
            "continuationEndpoint",
            "continuationCommand",
            "token",
        )
        if token:
            return str(token)
    return None


def _items_to_videos(items: List[Any]) -> List[VideoItem]:
    """Pętla parsująca elementy feedu (richItemRenderer -> lockupViewModel)
    na listę VideoItem. Wspólna dla pierwszej strony i continuation."""
    clean_list: List[VideoItem] = []

    for item in items:
        vm = _safe_get(item, "richItemRenderer", "content", "lockupViewModel")
        if not vm:
            continue

        video_id = _safe_get(vm, "contentId")
        if not video_id:
            continue

        title = (
            _safe_get(vm, "metadata", "lockupMetadataViewModel", "title", "content")
            or "Untitled"
        )

        rows = (
            _safe_get(
                vm,
                "metadata",
                "lockupMetadataViewModel",
                "metadata",
                "contentMetadataViewModel",
                "metadataRows",
                default=[],
            )
            or []
        )

        author = _safe_get(rows, 0, "metadataParts", 0, "text", "content")

        views: Optional[str] = None
        published: Optional[str] = None

        if len(rows) > 1:
            parts = _safe_get(rows, 1, "metadataParts", default=[]) or []
            if len(parts) > 0:
                views = _safe_get(parts, 0, "text", "content")
            if len(parts) > 1:
                published = _safe_get(parts, 1, "text", "content")

        duration: Optional[str] = None
        overlays = (
            _safe_get(vm, "contentImage", "thumbnailViewModel", "overlays", default=[])
            or []
        )

        for overlay in overlays:
            badge = _safe_get(
                overlay,
                "thumbnailBottomOverlayViewModel",
                "badges",
                0,
                "thumbnailBadgeViewModel",
                "text",
            )
            if badge:
                duration = badge
                break

        thumb_url = ""
        sources = (
            _safe_get(
                vm, "contentImage", "thumbnailViewModel", "image", "sources", default=[]
            )
            or []
        )

        for source in sources:
            if isinstance(source, dict) and "url" in source:
                thumb_url = source["url"]
                if thumb_url.startswith("//"):
                    thumb_url = "https:" + thumb_url
                if 160 <= source.get("width", 0) <= 480:
                    break

        if not thumb_url and sources:
            last_source = sources[-1]
            if isinstance(last_source, dict):
                thumb_url = last_source.get("url", "")
                if thumb_url.startswith("//"):
                    thumb_url = "https:" + thumb_url

        if not thumb_url:
            continue

        clean_list.append(
            VideoItem(
                video_id=video_id,
                title=title,
                author=author,
                duration=duration,
                views=views,
                published_time=published,
                thumbnail_url=thumb_url,
                url=f"https://www.youtube.com/watch?v={video_id}",
            )
        )

    return clean_list


def _extract_videos(raw_data: Dict[str, Any], response_text: str) -> List[VideoItem]:
    """Parsowanie PIERWSZEJ odpowiedzi (stare API). Rzuca RuntimeError przy
    rozpoznanych sygnałach nieprawidłowej sesji lub nierozznanej strukturze -
    wywołujący mapuje to na FeedError z odpowiednim kodem."""
    return _items_to_videos(_extract_initial_items(raw_data, response_text))


def _build_client(*, max_connections: int, max_keepalive: int) -> httpx.AsyncClient:
    """Wspólna fabryka klienta - używana zarówno przez klasę, jak i funkcje-wrappery."""
    limits = httpx.Limits(
        max_connections=max_connections,
        max_keepalive_connections=max_keepalive,
        keepalive_expiry=30.0,
    )
    timeout = httpx.Timeout(connect=10.0, read=25.0, write=25.0, pool=10.0)
    # retries=2 na transporcie łapie błędy na poziomie połączenia
    # (RST, timeout handshake'u) - nie dotyczy błędów HTTP (4xx/5xx),
    # więc nie ryzykujemy powtórzenia requestu z nieprawidłowymi danymi.
    transport = httpx.AsyncHTTPTransport(retries=2)

    return httpx.AsyncClient(
        timeout=timeout,
        limits=limits,
        follow_redirects=False,
        trust_env=False,
        transport=transport,
    )


def _map_runtime_error(exc: RuntimeError) -> FeedError:
    if str(exc) == "session_invalid":
        return FeedError(
            FeedErrorCode.SESSION_INVALID,
            "Sesja YouTube jest nieprawidłowa lub historia oglądania jest wyłączona.",
        )
    return FeedError(
        FeedErrorCode.UNEXPECTED_RESPONSE,
        "Odpowiedź nie zawiera oczekiwanych danych wideo. Struktura mogła się zmienić.",
    )


async def _fetch_one_page(
    client: httpx.AsyncClient,
    cookies: CookieDict,
    sapisid: str,
    target: str,
    continuation: Optional[str] = None,
    client_version: Optional[str] = None,
) -> FeedPage:
    """ROZSZERZENIE KarnyYT: jedno żądanie browse (pierwsza strona LUB
    continuation) wykonane przez współdzielony connection pool.
    Zawsze zwraca FeedPage - rdzeń dla starego i nowego API."""
    headers = _build_headers(sapisid)
    payload = _build_payload(target, continuation, client_version)

    try:
        response = await client.post(
            YOUTUBE_BROWSE_URL, headers=headers, cookies=cookies, json=payload
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 403):
            logger.warning(
                "YouTube feed: %s -> HTTP %s (sesja nieważna)", target, status
            )
            return FeedPage(
                error=FeedError(
                    FeedErrorCode.SESSION_INVALID,
                    f"YouTube odrzucił żądanie (HTTP {status}) - sesja wygasła lub cookies są nieprawidłowe.",
                )
            )
        logger.warning("YouTube feed: %s -> HTTP %s", target, status)
        return FeedPage(
            error=FeedError(
                FeedErrorCode.NETWORK_ERROR,
                f"Błąd HTTP {status} przy pobieraniu feedu.",
            )
        )
    except httpx.HTTPError as exc:
        logger.warning("YouTube feed: %s -> błąd sieciowy: %s", target, exc)
        return FeedPage(
            error=FeedError(FeedErrorCode.NETWORK_ERROR, f"Błąd sieciowy YouTube: {exc}")
        )

    response_text = response.text

    try:
        raw_data = response.json()
    except (json.JSONDecodeError, ValueError):
        logger.warning("YouTube feed: %s -> nie udało się sparsować JSON", target)
        return FeedPage(
            error=FeedError(
                FeedErrorCode.JSON_DECODE_ERROR,
                "Nie udało się sparsować odpowiedzi JSON z YouTube.",
            )
        )

    try:
        if continuation:
            items = _extract_continuation_items(raw_data, response_text)
        else:
            items = _extract_initial_items(raw_data, response_text)
    except RuntimeError as exc:
        return FeedPage(error=_map_runtime_error(exc))

    return FeedPage(
        videos=_items_to_videos(items),
        continuation=_extract_continuation_token(items),
    )


async def _fetch_one(
    client: httpx.AsyncClient,
    cookies: CookieDict,
    sapisid: str,
    target: str,
) -> FetchResult:
    """Jedno żądanie browse - STARY kontrakt: lista VideoItem albo FeedError."""
    page = await _fetch_one_page(client, cookies, sapisid, target)
    if page.error is not None:
        return page.error
    return page.videos


class YouTubeFeedClient:
    """
    Trwały klient do wielokrotnego odpytywania feedu (np. cykliczny
    refresh w GUI). W przeciwieństwie do fetch_youtube_feed/-s poniżej,
    NIE otwiera nowego połączenia TCP+TLS przy każdym wywołaniu -
    handshake robimy raz w __aenter__, dalej lecimy po keep-alive.
    Przy pollingu co kilka/kilkadziesiąt sekund to realna różnica
    w czasie odpowiedzi.

    Użycie (wewnątrz wątku roboczego, NIE w wątku GUI):
        async with YouTubeFeedClient("cookies.json") as yt:
            while running:
                feed = await yt.fetch_all()
                ...
                await asyncio.sleep(60)
    """

    def __init__(
        self, cookies_input: str, client_version: Optional[str] = None
    ) -> None:
        self._cookies_input = cookies_input
        self._client_version = client_version
        self._cookies: Optional[CookieDict] = None
        self._sapisid: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> YouTubeFeedClient:
        self._cookies = _load_cookies(self._cookies_input)
        self._sapisid = _resolve_sapisid(self._cookies)
        self._client = _build_client(max_connections=4, max_keepalive=2)
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _require_started(self) -> Tuple[httpx.AsyncClient, CookieDict, str]:
        if self._client is None or self._cookies is None or self._sapisid is None:
            raise RuntimeError(
                "YouTubeFeedClient musi być używany jako `async with YouTubeFeedClient(...) as yt:`."
            )
        return self._client, self._cookies, self._sapisid

    async def fetch(self, target: BrowseTarget = "FEwhat_to_watch") -> FetchResult:
        if target not in TARGETS:
            return FeedError(
                FeedErrorCode.INVALID_TARGET,
                "Nieprawidłowy target. Dozwolone: 'FEwhat_to_watch' lub 'FEsubscriptions'.",
            )
        client, cookies, sapisid = self._require_started()
        return await _fetch_one(client, cookies, sapisid, target)

    async def fetch_all(self) -> Dict[BrowseTarget, FetchResult]:
        """HOME + SUBSKRYPCJE równolegle."""
        client, cookies, sapisid = self._require_started()

        home_result, subs_result = await asyncio.gather(
            _fetch_one(client, cookies, sapisid, "FEwhat_to_watch"),
            _fetch_one(client, cookies, sapisid, "FEsubscriptions"),
        )

        return {
            "FEwhat_to_watch": home_result,
            "FEsubscriptions": subs_result,
        }

    # -- ROZSZERZENIE KarnyYT: wersje zwracające FeedPage (z continuation) --

    async def fetch_page(
        self,
        target: BrowseTarget = "FEwhat_to_watch",
        continuation: Optional[str] = None,
    ) -> FeedPage:
        if target not in TARGETS:
            return FeedPage(
                error=FeedError(
                    FeedErrorCode.INVALID_TARGET,
                    "Nieprawidłowy target. Dozwolone: 'FEwhat_to_watch' lub 'FEsubscriptions'.",
                )
            )
        client, cookies, sapisid = self._require_started()
        return await _fetch_one_page(
            client, cookies, sapisid, target, continuation, self._client_version
        )


# ---------------------------------------------------------------------------
# Proste funkcje jednorazowe - wygodne do skryptów/testów. Do pollingu
# w GUI używaj YouTubeFeedClient powyżej (jedno połączenie, wiele fetchy).
# ---------------------------------------------------------------------------


async def fetch_youtube_feeds(
    cookies_input: str,
) -> Dict[BrowseTarget, FetchResult]:
    """Pobiera HOME + SUBSKRYPCJE równolegle, jednorazowe połączenie."""
    try:
        cookies = _load_cookies(cookies_input)
        sapisid = _resolve_sapisid(cookies)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        error = FeedError(
            FeedErrorCode.COOKIES_LOAD_FAILED, f"Błąd wczytywania cookies: {exc}"
        )
        return {"FEwhat_to_watch": error, "FEsubscriptions": error}

    async with _build_client(max_connections=4, max_keepalive=2) as client:
        home_result, subs_result = await asyncio.gather(
            _fetch_one(client, cookies, sapisid, "FEwhat_to_watch"),
            _fetch_one(client, cookies, sapisid, "FEsubscriptions"),
        )

    return {
        "FEwhat_to_watch": home_result,
        "FEsubscriptions": subs_result,
    }


async def fetch_youtube_feed(
    cookies_input: str,
    target: BrowseTarget = "FEwhat_to_watch",
) -> FetchResult:
    """Odpowiednik pojedynczego fetcha - jednorazowe połączenie."""
    if target not in TARGETS:
        return FeedError(
            FeedErrorCode.INVALID_TARGET,
            "Nieprawidłowy target. Dozwolone: 'FEwhat_to_watch' lub 'FEsubscriptions'.",
        )

    try:
        cookies = _load_cookies(cookies_input)
        sapisid = _resolve_sapisid(cookies)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        return FeedError(FeedErrorCode.COOKIES_LOAD_FAILED, f"Błąd wczytywania cookies: {exc}")

    async with _build_client(max_connections=2, max_keepalive=1) as client:
        return await _fetch_one(client, cookies, sapisid, target)


async def fetch_page(
    cookies_input: str,
    target: BrowseTarget = "FEwhat_to_watch",
    continuation: Optional[str] = None,
    client_version: Optional[str] = None,
) -> FeedPage:
    """ROZSZERZENIE KarnyYT: jednorazowy fetch zwracający FeedPage.

    Obsługuje continuation ("wczytaj więcej") i override client_version.
    Błędy cookies mapowane na FeedPage(error=COOKIES_LOAD_FAILED) -
    ta funkcja NIE rzuca wyjątków dla typowych problemów wejściowych.
    """
    if target not in TARGETS:
        return FeedPage(
            error=FeedError(
                FeedErrorCode.INVALID_TARGET,
                "Nieprawidłowy target. Dozwolone: 'FEwhat_to_watch' lub 'FEsubscriptions'.",
            )
        )

    try:
        cookies = _load_cookies(cookies_input)
        sapisid = _resolve_sapisid(cookies)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        return FeedPage(
            error=FeedError(
                FeedErrorCode.COOKIES_LOAD_FAILED, f"Błąd wczytywania cookies: {exc}"
            )
        )

    async with _build_client(max_connections=2, max_keepalive=1) as client:
        return await _fetch_one_page(
            client, cookies, sapisid, target, continuation, client_version
        )


async def fetch_all_pages(
    cookies_input: str,
    client_version: Optional[str] = None,
) -> Dict[BrowseTarget, FeedPage]:
    """ROZSZERZENIE KarnyYT: HOME + SUBSKRYPCJE równolegle jako FeedPage,
    jedno współdzielone połączenie (keep-alive między requestami)."""
    try:
        cookies = _load_cookies(cookies_input)
        sapisid = _resolve_sapisid(cookies)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        error = FeedError(
            FeedErrorCode.COOKIES_LOAD_FAILED, f"Błąd wczytywania cookies: {exc}"
        )
        return {
            "FEwhat_to_watch": FeedPage(error=error),
            "FEsubscriptions": FeedPage(error=error),
        }

    async with _build_client(max_connections=4, max_keepalive=2) as client:
        home_page, subs_page = await asyncio.gather(
            _fetch_one_page(
                client, cookies, sapisid, "FEwhat_to_watch", None, client_version
            ),
            _fetch_one_page(
                client, cookies, sapisid, "FEsubscriptions", None, client_version
            ),
        )

    return {"FEwhat_to_watch": home_page, "FEsubscriptions": subs_page}


def ns_to_ms(value_ns: int) -> float:
    return value_ns / 1_000_000


async def _demo() -> None:
    logging.basicConfig(level=logging.INFO)
    async with YouTubeFeedClient("cookies.json") as yt:
        result = await yt.fetch_all()

    for target, videos in result.items():
        if isinstance(videos, FeedError):
            print(f"{target}: [{videos.code.value}] {videos.message}")
        else:
            print(f"{target}: {len(videos)} filmów")


if __name__ == "__main__":
    started_ns = time.perf_counter_ns()
    asyncio.run(_demo())
    elapsed_ns = time.perf_counter_ns() - started_ns
    print(f"   Czas zapytania: {ns_to_ms(elapsed_ns):,.3f} ms")
