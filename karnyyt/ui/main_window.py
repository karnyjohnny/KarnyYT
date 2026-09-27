"""
main_window.py - okno główne KarnyYT.

Spina wszystko: pasek narzędzi (odśwież / filtr / URL + ▶ / ♪), trzy
zakładki (HOME, SUBSKRYPCJE, Ustawienia), pasek stanu (narzędzia, liczniki,
„teraz gra" + stop) oraz workery (feed, miniatury, wersje narzędzi).
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import Dict, List, Optional

from PyQt5.QtCore import Qt, QTimer, QUrl
from PyQt5.QtGui import QDesktopServices, QIcon, QKeySequence
from PyQt5.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QShortcut,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, yt_feed_py38
from ..core import cache, paths, utils, validate
from ..core.feed_worker import FeedWorker
from ..core.i18n import tr
from ..core.player import MpvManager
from ..core.settings import Settings, WatchedStore
from ..core.thumbs import ThumbStore, ThumbWorker, thumb_candidates
from ..core.validate import VersionProber
from ..yt_feed_py38 import VideoItem
from . import theme
from .feed_page import FeedTabPage
from .settings_tab import SettingsTab
from .theme import CardMetrics

logger = logging.getLogger(__name__)

HOME = "FEwhat_to_watch"
SUBS = "FEsubscriptions"


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, watched: WatchedStore) -> None:
        super().__init__()
        self._settings = settings
        self._watched = watched
        self._busy = False
        self._tool_paths: Dict[str, Optional[str]] = {}
        self._versions: Dict[str, Optional[str]] = {}

        self.setWindowTitle(tr("app.window_title"))
        icon_path = paths.resource_path("assets/icon.ico")
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.metrics = CardMetrics(settings.get("card_size", "medium"))

        # -- workerzy ------------------------------------------------------------
        self._feed_worker = FeedWorker(self)
        self._feed_worker.pages_ready.connect(self._on_pages_ready)
        self._feed_worker.more_ready.connect(self._on_more_ready)

        self._thumb_store = ThumbStore(paths.thumbs_dir())
        self._thumb_worker = ThumbWorker(self._thumb_store, self)
        self._thumb_worker.thumb_ready.connect(self._on_thumb)

        self._mpv = MpvManager(settings, self)
        self._mpv.changed.connect(self._on_playing_changed)

        self._prober = VersionProber(self)
        self._prober.done.connect(self._on_versions)

        # -- UI -------------------------------------------------------------------
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 0)
        root.setSpacing(6)
        root.addLayout(self._build_topbar())

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.page_home = FeedTabPage(HOME, self.metrics)
        self.page_subs = FeedTabPage(SUBS, self.metrics)
        self.settings_tab = SettingsTab(settings, watched)
        self.tabs.addTab(self.page_home, tr("tab.home"))
        self.tabs.addTab(self.page_subs, tr("tab.subs"))
        self.tabs.addTab(self.settings_tab, tr("tab.settings"))
        root.addWidget(self.tabs, 1)

        self._build_statusbar()
        self._wire_signals()
        self._wire_shortcuts()

        # -- timery ------------------------------------------------------------------
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(2000)
        self._poll_timer.timeout.connect(self._mpv.poll)
        self._poll_timer.start()

        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(60_000)
        self._auto_timer.timeout.connect(self._auto_tick)
        self._auto_timer.start()

        # -- start -------------------------------------------------------------------
        self._restore_geometry()
        self._check_tools()
        self.settings_tab.set_tools_status(self._tool_paths, self._versions)
        cached_any = self._load_cached_feeds()
        if not cached_any:
            self.page_home.set_busy(True)
            self.page_subs.set_busy(True)
        if paths.cookies_path().is_file():
            self.refresh()
        else:
            self.page_home.show_error("cookies_load_failed", "")
            self.page_subs.show_error("cookies_load_failed", "")

        # workerzy startują po pierwszym wyświetleniu okna
        QTimer.singleShot(0, self._start_workers)

    # -- budowa UI ---------------------------------------------------------------

    def _build_topbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(8)

        self.btn_refresh = QToolButton()
        self.btn_refresh.setProperty("flat", "false")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.refresh)
        bar.addWidget(self.btn_refresh)

        self.edit_filter = QLineEdit()
        self.edit_filter.setClearButtonEnabled(True)
        self.edit_filter.setMaximumWidth(320)
        self.edit_filter.textChanged.connect(self._on_filter)
        bar.addWidget(self.edit_filter)

        bar.addStretch(1)

        self.edit_url = QLineEdit()
        self.edit_url.setMinimumWidth(240)
        self.edit_url.returnPressed.connect(lambda: self._play_url("video"))
        bar.addWidget(self.edit_url, 1)

        self.btn_url_audio = QPushButton()
        self.btn_url_audio.setProperty("class", "audio")
        self.btn_url_audio.setCursor(Qt.PointingHandCursor)
        self.btn_url_audio.clicked.connect(lambda: self._play_url("audio"))
        bar.addWidget(self.btn_url_audio)

        self.btn_url_video = QPushButton()
        self.btn_url_video.setProperty("class", "accent")
        self.btn_url_video.setCursor(Qt.PointingHandCursor)
        self.btn_url_video.clicked.connect(lambda: self._play_url("video"))
        bar.addWidget(self.btn_url_video)
        return bar

    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        self.lbl_tools = QLabel()
        self.lbl_counts = QLabel()
        self.lbl_playing = QLabel()
        self.lbl_playing.setMaximumWidth(430)
        self.btn_stop = QToolButton()
        self.btn_stop.setProperty("class", "accent")
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        self.btn_stop.setVisible(False)
        self.btn_stop.clicked.connect(self._mpv.stop_all)
        self.lbl_updated = QLabel()

        sb.addWidget(self.lbl_tools)
        sb.addWidget(self._status_sep())
        sb.addWidget(self.lbl_counts)
        sb.addWidget(self._status_sep())
        sb.addWidget(self.lbl_playing, 1)
        sb.addWidget(self.btn_stop)
        sb.addPermanentWidget(self.lbl_updated)

    @staticmethod
    def _status_sep() -> QLabel:
        sep = QLabel("•")
        sep.setStyleSheet("color: #4a4a55; background: transparent;")
        return sep

    def _wire_signals(self) -> None:
        for page in (self.page_home, self.page_subs):
            page.play_requested.connect(self._play)
            page.more_requested.connect(self._load_more)
            page.cookies_requested.connect(self._open_cookies)
            page.retry_requested.connect(self.refresh)
            page.unwatched_requested.connect(self._mark_unwatched)

        self.settings_tab.retranslate_all.connect(self.retranslate)
        self.settings_tab.cookies_edit_requested.connect(self._open_cookies)
        self.settings_tab.open_dir_requested.connect(self._open_dir)
        self.settings_tab.tools_recheck_requested.connect(self._recheck_tools)
        self.settings_tab.watched_cleared.connect(self._apply_marks)
        self.settings_tab.card_size_changed.connect(self._apply_card_size)
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _wire_shortcuts(self) -> None:
        QShortcut(QKeySequence("F5"), self, activated=self.refresh)
        QShortcut(
            QKeySequence("Ctrl+F"), self,
            activated=lambda: (self.edit_filter.setFocus(),
                               self.edit_filter.selectAll()),
        )
        QShortcut(
            QKeySequence("Ctrl+U"), self, activated=self.edit_url.setFocus
        )
        QShortcut(QKeySequence("Escape"), self, activated=self._on_escape)

    def _on_escape(self) -> None:
        if self.edit_filter.text():
            self.edit_filter.clear()

    # -- workerzy / dane ------------------------------------------------------

    def _start_workers(self) -> None:
        self._feed_worker.start()
        self._thumb_worker.start()
        self._prober.probe_async(self._tool_paths)

    def refresh(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.btn_refresh.setEnabled(False)
        self.page_home.set_busy(True)
        self.page_subs.set_busy(True)
        self.lbl_updated.setText(tr("status.fetching"))
        self._feed_worker.refresh_all(
            str(paths.cookies_path()),
            str(self._settings.get("client_version", "") or ""),
        )

    def _on_pages_ready(self, pages: dict) -> None:
        self._busy = False
        self.btn_refresh.setEnabled(True)
        now = time.time()
        cache_pages = {}
        for target, widget in ((HOME, self.page_home), (SUBS, self.page_subs)):
            page = pages.get(target)
            widget.set_busy(False)
            if page is None:
                continue
            if page.ok:
                scroll = widget.save_scroll()
                widget.set_feed(page.videos, page.continuation, now, False)
                widget.restore_scroll(scroll)
                widget.clear_banner()
                cache_pages[target] = page
                self._request_thumbs(page.videos)
            else:
                widget.show_error(page.error.code.value, page.error.message)
        if cache_pages:
            cache.save_feed_cache(paths.feed_cache_path(), cache_pages)
        self._apply_marks()
        self._update_status()

    def _on_more_ready(self, target: str, page) -> None:
        widget = self.page_home if target == HOME else self.page_subs
        widget.set_busy(False)
        if page.ok:
            widget.append_feed(page.videos, page.continuation)
            self._request_thumbs(page.videos)
            self._apply_marks()
        else:
            widget.show_error(page.error.code.value, page.error.message)
        self._update_status()

    def _load_more(self, target: str) -> None:
        widget = self.page_home if target == HOME else self.page_subs
        if widget.busy or not widget.continuation:
            return
        widget.set_busy(True)
        self._feed_worker.load_more(
            target,
            widget.continuation,
            str(paths.cookies_path()),
            str(self._settings.get("client_version", "") or ""),
        )

    def _load_cached_feeds(self) -> bool:
        data = cache.load_feed_cache(paths.feed_cache_path())
        if not data:
            return False
        any_ok = False
        for target, entry in data.items():
            widget = self.page_home if target == HOME else (
                self.page_subs if target == SUBS else None
            )
            if widget is None:
                continue
            widget.set_feed(
                entry.get("videos", []),
                entry.get("continuation"),
                float(entry.get("ts") or 0.0),
                True,
            )
            self._request_thumbs(entry.get("videos", []))
            any_ok = True
        if any_ok:
            self._apply_marks()
            self._update_status()
        return any_ok

    # -- miniatury ---------------------------------------------------------------

    def _request_thumbs(self, videos: List[VideoItem]) -> None:
        width = self.metrics.thumb_width_px()
        for video in videos:
            vid = video.video_id
            if self.page_home.model.has_thumb(vid) or self.page_subs.model.has_thumb(vid):
                continue
            self._thumb_worker.request(
                vid, thumb_candidates(vid, video.thumbnail_url), width
            )

    def _on_thumb(self, video_id: str, image) -> None:
        try:
            if image is None or image.isNull():
                return
        except RuntimeError:
            return
        from PyQt5.QtGui import QPixmap

        pix = QPixmap.fromImage(image)
        if pix.isNull():
            return
        self.page_home.model.set_thumb(video_id, pix)
        self.page_subs.model.set_thumb(video_id, pix)

    # -- odtwarzanie -----------------------------------------------------------------

    def _play(self, video: VideoItem, mode: str) -> None:
        err = self._mpv.play(video.url, mode, video.title, video.video_id)
        if err:
            self._flash(err)
            return
        if video.video_id:
            self._watched.add(video.video_id)
            self._apply_marks()

    def _play_url(self, mode: str) -> None:
        text = self.edit_url.text().strip()
        if not text:
            self._flash(tr("err.empty_url"))
            return
        url = utils.normalize_play_url(text)
        vid = utils.extract_video_id(text)
        err = self._mpv.play(url, mode, url[:90], vid)
        if err:
            self._flash(err)
            return
        if vid:
            self._watched.add(vid)
            self._apply_marks()

    def _on_playing_changed(self) -> None:
        ids = self._mpv.playing_ids()
        self.page_home.model.set_playing(ids)
        self.page_subs.model.set_playing(ids)
        if self._mpv.has_playing():
            title = self._mpv.current_label() or "mpv"
            if len(title) > 56:
                title = title[:55] + "…"
            self.lbl_playing.setText(tr("status.playing", title=title))
            self.btn_stop.setVisible(True)
        else:
            self.lbl_playing.setText("")
            self.btn_stop.setVisible(False)

    def _mark_unwatched(self, video: VideoItem) -> None:
        self._watched.remove(video.video_id)
        self._apply_marks()

    def _apply_marks(self) -> None:
        watched_ids = self._watched.ids()
        playing_ids = self._mpv.playing_ids()
        self.page_home.apply_marks(watched_ids, playing_ids)
        self.page_subs.apply_marks(watched_ids, playing_ids)
        self.settings_tab.refresh_watched_count()

    # -- narzędzia --------------------------------------------------------------------

    def _check_tools(self) -> None:
        self._tool_paths = validate.check_all(self._settings)
        missing = [n for n, p in self._tool_paths.items() if not p]
        if missing:
            self.lbl_tools.setText(
                f'<span style="color:{theme.ERR}">●</span> '
                + tr("status.tools_missing", tools=", ".join(missing))
            )
            if not self._tool_paths.get("mpv") and not self.page_home.has_error_banner():
                self.page_home.show_banner(
                    "warn", tr("banner.tools_missing", tools=", ".join(missing))
                )
        else:
            self.lbl_tools.setText(
                f'<span style="color:{theme.OK}">●</span> {tr("status.tools_ok")}'
            )
        self.lbl_tools.setToolTip(
            "\n".join(
                f"{n}: {p or '-'}" for n, p in self._tool_paths.items()
            )
        )
        self.settings_tab.set_tools_status(self._tool_paths, self._versions)

    def _recheck_tools(self) -> None:
        self._check_tools()
        self._prober.probe_async(self._tool_paths)

    def _on_versions(self, versions: dict) -> None:
        self._versions = versions or {}
        self.settings_tab.set_tools_status(self._tool_paths, self._versions)
        age = utils.ytdlp_age_days(self._versions.get("yt-dlp"))
        if (
            age is not None
            and age > 45
            and not self.page_home.has_error_banner()
        ):
            self.page_home.show_banner("info", tr("banner.ytdlp_old", days=age))

    # -- cookies / katalogi ----------------------------------------------------------------

    def _open_cookies(self) -> None:
        p = paths.cookies_path()
        try:
            if not p.exists():
                content = "[]"
                example = paths.resource_path("cookies.example.json")
                try:
                    if example.is_file():
                        content = example.read_text(encoding="utf-8")
                except OSError:
                    pass
                p.write_text(content, encoding="utf-8")
        except OSError as exc:
            logger.warning("Nie udało się utworzyć cookies.json: %s", exc)
            self._flash(str(exc))
            return
        if os.name == "nt":
            try:
                subprocess.Popen(["notepad.exe", str(p)])
                return
            except OSError:
                pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def _open_dir(self, which: str) -> None:
        directory = paths.data_dir() if which == "data" else paths.cache_dir()
        if os.name == "nt":
            try:
                os.startfile(str(directory))  # type: ignore[attr-defined]
                return
            except OSError:
                pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    # -- wygląd -------------------------------------------------------------------------

    def _apply_card_size(self, key: str) -> None:
        self.metrics.apply(key)
        for page in (self.page_home, self.page_subs):
            page.model.clear_thumbs()
            page.view.scheduleDelayedItemsLayout()
            page.view.viewport().update()
            self._request_thumbs(page.model.all_videos())

    def _on_filter(self, text: str) -> None:
        self.page_home.set_filter(text)
        self.page_subs.set_filter(text)

    def _update_status(self) -> None:
        home_n = self.page_home.model.total_count()
        subs_n = self.page_subs.model.total_count()
        self.lbl_counts.setText(tr("status.counts", home=home_n, subs=subs_n))
        ts = max(self.page_home.last_ts, self.page_subs.last_ts)
        if ts:
            cached = self.page_home.from_cache or self.page_subs.from_cache
            text = tr("status.updated", time=utils.human_time(ts))
            if cached:
                text += tr("status.cached")
            self.lbl_updated.setText(text)

    def _flash(self, message: str) -> None:
        logger.warning("UI: %s", message)
        self.statusBar().showMessage(message, 6000)

    # -- auto refresh ----------------------------------------------------------------------

    def _auto_tick(self) -> None:
        mins = int(self._settings.get("auto_refresh_min", 0) or 0)
        if not mins or self._busy:
            return
        newest = max(self.page_home.last_ts, self.page_subs.last_ts)
        if newest and (time.time() - newest) > mins * 60:
            self.refresh()

    def _on_tab_changed(self, index: int) -> None:
        if index in (0, 1):
            self._auto_tick()

    # -- tłumaczenia -------------------------------------------------------------------------

    def retranslate(self) -> None:
        self.setWindowTitle(tr("app.window_title"))
        self.btn_refresh.setText(tr("btn.refresh"))
        self.btn_refresh.setToolTip(tr("tooltip.refresh"))
        self.edit_filter.setPlaceholderText(tr("filter.placeholder"))
        self.edit_url.setPlaceholderText(tr("url.placeholder"))
        self.btn_url_audio.setText(tr("btn.audio"))
        self.btn_url_audio.setToolTip(tr("tooltip.play_audio"))
        self.btn_url_video.setText(tr("btn.video"))
        self.btn_url_video.setToolTip(tr("tooltip.play_video"))
        self.tabs.setTabText(0, tr("tab.home"))
        self.tabs.setTabText(1, tr("tab.subs"))
        self.tabs.setTabText(2, tr("tab.settings"))
        self.btn_stop.setText(tr("btn.stop"))
        self.page_home.retranslate()
        self.page_subs.retranslate()
        self.settings_tab.retranslate()
        self._check_tools()
        self._on_playing_changed()
        self._update_status()

    # -- geometria / zamknięcie ------------------------------------------------------------------

    def _restore_geometry(self) -> None:
        win = self._settings.window_geom()
        try:
            w = max(640, int(win.get("w") or 1240))
            h = max(420, int(win.get("h") or 780))
        except (TypeError, ValueError):
            w, h = 1240, 780
        self.resize(w, h)
        x, y = win.get("x"), win.get("y")
        if isinstance(x, int) and isinstance(y, int) and x >= 0 and y >= 0:
            self.move(x, y)
        else:
            screen = QApplication.desktop().availableGeometry(self)
            self.move(
                max(0, (screen.width() - w) // 2 + screen.x()),
                max(0, (screen.height() - h) // 2 + screen.y()),
            )
        tab = win.get("tab", 0)
        try:
            self.tabs.setCurrentIndex(int(tab) if int(tab) in (0, 1, 2) else 0)
        except (TypeError, ValueError):
            self.tabs.setCurrentIndex(0)
        # teksty startowe
        self.retranslate()

    def closeEvent(self, event) -> None:  # noqa: N802
        geom = self.geometry()
        win = self._settings.window_geom()
        win.update(
            {
                "x": geom.x(),
                "y": geom.y(),
                "w": geom.width(),
                "h": geom.height(),
                "tab": self.tabs.currentIndex(),
            }
        )
        self._settings.set("window", win)

        self._poll_timer.stop()
        self._auto_timer.stop()
        try:
            self._feed_worker.stop()
            self._feed_worker.wait(3000)
        except RuntimeError:
            pass
        try:
            self._thumb_worker.stop()
            self._thumb_worker.wait(3000)
        except RuntimeError:
            pass
        super().closeEvent(event)
