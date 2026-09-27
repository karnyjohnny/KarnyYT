"""
smoke_test.py - headlessowe testy dymne (QT_QPA_PLATFORM=offscreen).

Uruchamiane lokalnie i w CI PRZED pakowaniem binarek. Nie dotykaja sieci
ani prawdziwych cookies - wszystko na syntetycznych danych.

    python tests/smoke_test.py  
"""

from __future__ import annotations

import os
import sys
import tempfile
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMP = tempfile.mkdtemp(prefix="karnyyt_smoke_")
os.environ["KARNYYT_DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["KARNYYT_CACHE_DIR"] = os.path.join(_TMP, "cache")

FAILURES = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    line = f"[{status}] {name}"
    if detail and not condition:
        line += f"  -> {detail}"
    print(line)
    if not condition:
        FAILURES.append(name)


def make_items(n: int):
    from karnyyt.yt_feed_py38 import VideoItem

    return [
        VideoItem(
            video_id=f"vid{i:08d}x",
            title=(
                f"Test video {i} — tytul na tyle dlugi, zeby zawinal sie "
                f"do drugiej linii i przycial poprawnie…"
            ),
            url=f"https://www.youtube.com/watch?v=vid{i:08d}x",
            thumbnail_url=f"https://i.ytimg.com/vi/vid{i:08d}x/mqdefault.jpg",
            author=f"Kanal Testowy {i}",
            duration="12:34" if i % 5 else None,
            views=f"{i}.2K views",
            published_time=f"{i % 23 + 1} hours ago",
        )
        for i in range(n)
    ]


def main() -> int:
    from PyQt5.QtCore import QSize
    from PyQt5.QtGui import QPixmap
    from PyQt5.QtWidgets import QApplication

    app = QApplication([])

    # -- i18n ---------------------------------------------------------------
    from karnyyt.core import i18n

    pl_keys = set(i18n._STRINGS["pl"])
    en_keys = set(i18n._STRINGS["en"])
    check("i18n: kompletnosc PL/EN", pl_keys == en_keys,
          f"braki EN: {sorted(pl_keys - en_keys)}, braki PL: {sorted(en_keys - pl_keys)}")
    check("i18n: fallback", i18n.tr("tab.home") == "Strona glowna")
    i18n.set_lang("en")
    check("i18n: EN", i18n.tr("tab.home") == "Home")
    i18n.set_lang("pl")

    # -- utils ----------------------------------------------------------------
    from karnyyt.core import utils

    check("utils: id z watch URL",
          utils.extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=5") == "dQw4w9WgXcQ")
    check("utils: id z youtu.be",
          utils.extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ")
    check("utils: id z /live/",
          utils.extract_video_id("https://www.youtube.com/live/dQw4w9WgXcQ") == "dQw4w9WgXcQ")
    check("utils: gole id", utils.extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ")
    check("utils: smieci", utils.extract_video_id("https://example.com/x") is None)
    check("utils: normalize", utils.normalize_play_url("dQw4w9WgXcQ") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    check("utils: localize_meta", utils.localize_meta("4 hours ago", "pl") == "4 godzin temu")
    check("utils: parse_extra_args",
          utils.parse_extra_args('--hwdec=auto-safe --title="moj tytul"') == ["--hwdec=auto-safe", "--title=moj tytul"])

    # -- player ------------------------------------------------------------------
    from karnyyt.core.player import build_ytdl_format

    fmt = build_ytdl_format(360, True, "video")
    check("player: format 360+h264", "height<=?360" in fmt and "vcodec^=avc1" in fmt and "mp4a" in fmt, fmt)
    check("player: fallback lańcuch", fmt.count("/") >= 3, fmt)
    fmt_best = build_ytdl_format("best", True, "video")
    check("player: best bez limitu", "height" not in fmt_best, fmt_best)
    fmt_audio = build_ytdl_format(360, True, "audio")
    check("player: audio", fmt_audio == "ba[acodec^=mp4a]/ba", fmt_audio)
    fmt_noh264 = build_ytdl_format(720, False, "video")
    check("player: bez preferencji h264", "avc1" not in fmt_noh264 and "height<=?720" in fmt_noh264, fmt_noh264)

    # -- settings / watched ----------------------------------------------------------
    from karnyyt.core.settings import Settings, WatchedStore

    s = Settings()
    s.set("resolution", 480)
    s2 = Settings()
    check("settings: roundtrip", s2.get("resolution") == 480)
    check("settings: default extra args", "--demuxer-max-bytes" in s2.get("extra_mpv_args"))

    w = WatchedStore()
    w.add("abcdefghijk")
    w2 = WatchedStore()
    check("watched: roundtrip", "abcdefghijk" in w2)
    w2.clear()
    check("watched: clear", len(WatchedStore()) == 0)

    # -- model --------------------------------------------------------------------
    from karnyyt.ui.video_model import R_THUMB, R_VIDEO, R_WATCHED, VideoListModel

    items = make_items(120)
    model = VideoListModel()
    model.set_videos(items)
    check("model: rowCount", model.rowCount() == 120)
    model.set_filter("Kanal Testowy 7")
    check("model: filtr", 0 < model.rowCount() < 120)
    model.set_filter("")
    added = model.append_videos(items[:5] + make_items(1)[0:0])
    check("model: dedupe przy append", added == 0, f"added={added}")
    pix = QPixmap(320, 180)
    pix.fill()
    model.set_thumb("vid00000000x", pix)
    idx = model.index(0)
    check("model: thumb roundtrip", model.data(idx, R_THUMB) is not None)
    model.set_watched({"vid00000000x"})
    check("model: watched", bool(model.data(idx, R_WATCHED)))
    check("model: video role", model.data(idx, R_VIDEO).title.startswith("Test video 0"))

    # -- okno glowne (pelny wiring) -----------------------------------------------------
    from karnyyt.ui.main_window import MainWindow

    win = MainWindow(Settings(), WatchedStore())
    win.show()
    app.processEvents()

    win.page_home.set_feed(items, "FAKE_CONTINUATION_TOKEN", time.time(), False)
    win.page_subs.set_feed(make_items(30), None, time.time(), False)
    app.processEvents()
    check("window: feed w modelu", win.page_home.model.rowCount() == 120)
    check("window: przycisk wiecej widoczny", win.page_home.more_btn.isVisibleTo(win.page_home))

    # delegate: wymaluj viewport do obrazka (lapie crashe w paint)
    vp = win.page_home.view.viewport()
    size = vp.size()
    if size.width() < 10 or size.height() < 10:
        size = QSize(900, 600)
    canvas = QPixmap(size)
    vp.render(canvas)
    check("delegate: paint bez crasha", not canvas.isNull())

    # hover button geometry
    from karnyyt.ui.video_delegate import CardDelegate
    from PyQt5.QtCore import QRect
    vrect, arect = CardDelegate.button_rects(QRect(0, 0, 300, 169))
    check("delegate: przyciski w miniaturze",
          QRect(0, 0, 300, 169).contains(vrect) and QRect(0, 0, 300, 169).contains(arect))

    # filtr z paska narzedzi
    win.edit_filter.setText("Test video 42")
    app.processEvents()
    check("window: filtr globalny", win.page_home.model.rowCount() == 1)
    win.edit_filter.clear()
    app.processEvents()

    # retranslate na EN
    i18n.set_lang("en")
    win.retranslate()
    app.processEvents()
    check("retranslate: EN tytul okna", "lightweight" in win.windowTitle().lower())
    i18n.set_lang("pl")
    win.retranslate()
    app.processEvents()

    # rozmiar kart
    win._apply_card_size("small")
    app.processEvents()
    check("card size: small", win.metrics.card_w == 240)
    win._apply_card_size("medium")

    # cache feedu (stale-while-revalidate)
    from karnyyt.core import cache as feed_cache
    from karnyyt.yt_feed_py38 import FeedPage

    feed_cache.save_feed_cache(
        __import__("karnyyt.core.paths", fromlist=["feed_cache_path"]).feed_cache_path(),
        {"FEwhat_to_watch": FeedPage(videos=items[:10], continuation="TOK")},
    )
    loaded = feed_cache.load_feed_cache(
        __import__("karnyyt.core.paths", fromlist=["feed_cache_path"]).feed_cache_path()
    )
    check("cache: feed roundtrip",
          len(loaded.get("FEwhat_to_watch", {}).get("videos", [])) == 10
          and loaded["FEwhat_to_watch"]["continuation"] == "TOK")

    win.close()
    app.processEvents()

    print()
    if FAILURES:
        print(f"PRZEGRANE TESTY ({len(FAILURES)}): {FAILURES}")
        return 1
    print("WSZYSTKIE TESTY ZALICZONE ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
