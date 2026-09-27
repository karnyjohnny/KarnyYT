# KarnyYT 🎬

**Lekki klient YouTube dla starych komputerów.** Zero przeglądarki, zero
1 GB RAM — feed (Strona główna + Subskrypcje) pobierany jest lekkim
zapytaniem HTTP, a filmy odpalają się bezpośrednio w **mpv** przez
**yt-dlp**. Cel projektowy: cały interfejs w ~100 MB RAM na Windows 7
z 2 GB na pokładzie.

> Zbudowany z myślą o Dell Latitude E5500 (Core 2 Duo T7250, 2 GB DDR2,
> GMA 4500MHD, Windows 7 SP1) — ale zadziała na każdym Windows z mpv w PATH.

---

## Funkcje

- **3 zakładki**: Strona główna • Subskrypcje • Ustawienia — kompletne
  dark mode, siatka kafelków jak na YouTube (miniatura + czas trwania na
  miniaturze + tytuł + kanał + wyświetlenia/data).
- **„Wczytaj więcej"** — paginacja feedu (continuation) bez odświeżania strony.
- **Odtwarzanie w mpv**:
  - dwuklik / `Enter` / hover-przycisk ▶ / PPM → wideo,
  - hover-przycisk ♪ / klawisz `A` / PPM → **samo audio, ale ze widocznym
    oknem mpv** (`--no-video --force-window`),
  - pasek URL na górze: wklej dowolny link YouTube (albo gołe ID) i odpal
    ▶ / ♪.
- **Optymalizacje pod stary sprzęt** (domyślne):
  - limit rozdzielczości **360p** (konfigurowalny 144p–2160p/best),
  - preferencja **H.264 + AAC** zamiast VP9/Opus (sprzętowe DXVA2 na Win7,
    lekki dekoder na Core 2 Duo),
  - bufor demuxera 64 MiB zamiast domyślnych 150 MiB,
  - `--save-position-on-quit` — mpv pamięta miejsce przerwania (watch-later),
  - proces mpv odpalany bez migającej konsoli (`CREATE_NO_WINDOW`).
- **Cache dwupoziomowy**: miniatury raz pobrane żyją na dysku
  (`mqdefault.jpg`, ~17 KB/szt.), a ostatni feed jest pokazywany **od razu**
  przy starcie, zanim cokolwiek dotknie sieci (stale-while-revalidate).
  Drugi start aplikacji: feed w ~0,02 s, miniatury z dysku w ~0,2 s.
- **Historia „obejrzane"** — przyciemniona miniatura + zielony ✓ (lokalnie,
  bez konta Google; czyszczenie w Ustawieniach).
- **Walidacja narzędzi przy starcie**: mpv / yt-dlp / FFmpeg sprawdzane
  przez `shutil.which` (bez spawnu), wersje dobijane w tle; ostrzeżenie,
  gdy yt-dlp jest starszy niż ~45 dni (YouTube lubi odrzucać stare wersje).
- **Aktualizacja cookies.json jednym kliknięciem**: Ustawienia →
  „Aktualizuj cookies.json" otwiera plik w Notatniku, wklejasz eksport JSON
  z Cookie-Editora, zapisujesz, `F5` — działa.
- **Błędy jako czytelne banery**: wygasła sesja / błąd sieci / zmieniona
  struktura YouTube — każdy z przyciskiem akcji (np. „Aktualizuj cookies").
- **Filtr lokalny** (`Ctrl+F`) po tytułach i kanałach — bez sieci, natychmiast.
- **Skróty**: `F5` odśwież, `Ctrl+F` filtr, `Ctrl+U` pasek URL,
  `Enter`/dwuklik wideo, `A` audio, `V` wideo, `Esc` czyści filtr,
  PPM — menu kontekstowe (kopiuj URL/tytuł, otwórz w przeglądarce…).
- **PL / EN** — przełącznik języka w Ustawieniach, bez restartu.
- **Tryb portable**: utwórz plik `portable.txt` obok exe — wszystkie dane
  (ustawienia, cookies, cache) przeniosą się do `data/` obok programu.
- Log diagnostyczny: `%APPDATA%\KarnyYT\karnyyt.log` (rotowany).

## Wymagania (użytkownik)

| Składnik | Uwagi |
|---|---|
| Windows 7 SP1 x64 lub nowszy | build celuje w 3.8/Win7 |
| **mpv** w `PATH` | bez mpv nie ma odtwarzania (reszta aplikacji działa) |
| **yt-dlp** w `PATH` | mpv woła go sam przez `ytdl_hook` |
| **FFmpeg** w `PATH` | potrzebny yt-dlp do łączenia strumieni |
| cookies z zalogowanej sesji YouTube | patrz niżej |

Ścieżki narzędzi można też podać ręcznie w Ustawieniach (np. gdy mpv leży
poza PATH). Alternatywne yt-dlp przekazujemy mpv przez
`--script-opts=ytdl_hook-ytdl_path=…`.

### Cookies (raz, a dobrze)

1. Zaloguj się na YouTube w przeglądarce.
2. Rozszerzenie **Cookie-Editor** → *Export* → *Export JSON*.
3. KarnyYT: Ustawienia → **Aktualizuj cookies.json** (otworzy Notatnik) →
   wklej → zapisz.
4. `F5`. Wystarczy ciastko `SAPISID` lub `__Secure-3PAPISID`.

> ⚠️ `cookies.json` to Twoja sesja — **nigdy nie commituj go do gita**
> (`.gitignore` już o to dba) i nie wysyłaj nikomu.

## Instalacja (releases)

- **`KarnyYT_win64_onedir.zip`** — zalecany na co dzień: wypakuj, odpal
  `KarnyYT.exe`. Szybszy start i mniej false-positive antywirusów.
- **`KarnyYT_win64_onefile.exe`** — pojedynczy plik „do kieszeni"; przy
  starcie rozpakowuje się do `%TEMP%` (na starym HDD potrwa chwilę dłużej).

## Budowanie (dev / CI)

```bash
# środowisko: Python 3.8.x
pip install -r requirements.txt          # runtime
pip install -r requirements-build.txt    # pyinstaller (tylko do builda)
python KarnyYT.py                        # dev, bez pakowania
python tests/smoke_test.py               # testy dymne (QT_QPA_PLATFORM=offscreen)
pyinstaller --noconfirm --clean KarnyYT.spec   # onedir + onefile naraz
```

CI (GitHub Actions, `windows-2022` + Python 3.8.20 — ostatni obraz z 3.8):
smoke testy → PyInstaller → artefakty. Push taga `v*` dodatkowo tworzy
**GitHub Release** z oboma binarkami:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

## Struktura

```
KarnyYT/
├─ KarnyYT.py                 # punkt wejścia (dev + PyInstaller)
├─ KarnyYT.spec               # onedir + onefile, jedna analiza
├─ karnyyt/
│  ├─ app.py                  # logging, motyw, excepthook, start
│  ├─ yt_feed_py38.py         # moduł feedu (HOME+SUBS, continuation, override CV)
│  ├─ core/
│  │  ├─ paths.py             # %APPDATA% / portable / cache
│  │  ├─ settings.py          # settings.json + watched.json (atomowe zapisy)
│  │  ├─ i18n.py              # PL/EN bez .qm
│  │  ├─ utils.py             # parse URL, formaty, shlex dla mpv-args
│  │  ├─ validate.py          # which() + wersje w tle
│  │  ├─ player.py            # komenda mpv + śledzenie procesów
│  │  ├─ thumbs.py            # worker miniatur: httpx + cache dysk + LRU
│  │  ├─ feed_worker.py       # QThread + asyncio (nigdy w wątku GUI!)
│  │  └─ cache.py             # stale-while-revalidate feedu
│  └─ ui/
│     ├─ theme.py             # paleta + QSS + metryki kart
│     ├─ video_model.py       # QAbstractListModel (miniatury LRU 180 szt.)
│     ├─ video_delegate.py    # CAŁE malowanie kafelka (zero widgetów/film)
│     ├─ feed_page.py         # baner + siatka + „wczytaj więcej" + menu PPM
│     ├─ settings_tab.py      # wszystkie ustawienia, zapis w locie
│     └─ main_window.py       # spinacz: workerzy, mpv, status, skróty
├─ tests/smoke_test.py        # headless (offscreen), też w CI
└─ .github/workflows/build.yml
```

## Dlaczego tak, a nie inaczej (performance notes)

- **QListView + delegate zamiast widgetów per film** — 120 filmów to
  ~12 malowanych komórek, nie ~500 widgetów. Layout i RAM dziękują.
- **httpx w workerze zamiast QNetworkAccessManager** — QNAM na Qt 5.15/Win
  wymaga ręcznego dokładania DLL-i OpenSSL 1.1.1 (ból PyInstallera);
  `ssl` z Pythona działa out-of-the-box.
- **Miniatury `mqdefault.jpg` (320×180, ~17 KB)** — najlżejszy sensowny
  wariant; skalowanie do rozmiaru karty dzieje się w wątku roboczym
  (`FastTransformation`), do GUI trafia gotowy `QPixmap`.
- **Brak `QGraphicsEffect`/cieni/animacji** — na GMA 4500MHD każdy efekt
  to klatki wyrzucone w błoto.
- **Zapięte wersje zależności** (`requirements.txt`) — identyczne jak
  środowisko docelowe; Python 3.8 to ostatnia linia wspierająca Win7.

## Troubleshooting

| Objaw | Przyczyna / akcja |
|---|---|
| Baner „YouTube zmienił strukturę odpowiedzi" | zwykle stary `CLIENT_VERSION`: Ustawienia → Zaawansowane → wpisz `INNERTUBE_CONTEXT_CLIENT_VERSION` ze źródła youtube.com |
| Baner „cookies wygasły" | ponów eksport z Cookie-Editora (krok 3 wyżej) |
| Filmy nie startują, mpv milczy | sprawdź wiek yt-dlp (Ustawienia → Stan narzędzi); YouTube odrzuca stare wersje — zaktualizuj yt-dlp |
| Czarne okno / czkawka przy 720p+ | ustaw niższą rozdzielczość albo zostaw preferencję H.264; VP9 programowo na C2D boli |
| Antywirus krzyczy na onefile | użyj wariantu onedir (zip) — znacznie mniej false-positive |

## Licencja i podziękowania

- **MIT** — patrz `LICENSE`.
- Moduł feedu `yt_feed_py38.py`: koncept i pierwsza implementacja
  **KarnyJohnny** (prywatny endpoint `/youtubei/v1/browse`, SAPISIDHASH).
- **mpv**, **yt-dlp**, **FFmpeg** nie są dołączane ani linkowane — mają
  własne licencje i muszą być zainstalowane osobno.

---

## EN (short)

KarnyYT is a featherweight YouTube client for ancient laptops: it pulls your
HOME + Subscriptions feeds over a private YouTube endpoint and hands every
video straight to **mpv**/**yt-dlp** — no browser, no 1 GB of RAM. Grid UI
with dark mode, duration badges, watch-history dimming, hover play buttons,
audio-only mode with a visible mpv window, resolution cap (default 360p),
H.264+AAC preference for old CPUs, two-level thumbnail cache and
instant-start feed cache. Ships as onedir zip + onefile exe from GitHub
Actions (Python 3.8 / Windows 7 target). MIT licensed.
