"""
feed_page.py - pojedyncza zakładka feedu (HOME / SUBSKRYPCJE).

Zawiera: baner błędu/info, siatkę kafelków (CardListView + delegate),
przycisk „wczytaj więcej" i stan pusty. Komunikacja z resztą aplikacji
wyłącznie sygnałami - strona nie wie nic o workerach ani mpv.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PyQt5.QtCore import QPoint, Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QMenu,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.i18n import tr
from ..yt_feed_py38 import VideoItem
from . import theme
from .theme import CardMetrics
from .video_delegate import CardDelegate
from .video_model import R_VIDEO, VideoListModel


class CardListView(QListView):
    """Siatka kafelków: hover-przyciski ▶/♪, dwuklik/Enter = wideo,
    A/V z klawiatury, PPM = menu kontekstowe."""

    req_play_video = pyqtSignal(object)  # VideoItem
    req_play_audio = pyqtSignal(object)
    req_context = pyqtSignal(object, QPoint)

    def __init__(self, metrics: CardMetrics, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("CardList")
        self._metrics = metrics
        self._delegate = CardDelegate(metrics, self)
        self.setItemDelegate(self._delegate)

        self.setViewMode(QListView.IconMode)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.Adjust)
        self.setUniformItemSizes(True)
        self.setSpacing(6)
        self.setMouseTracking(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWordWrap(False)
        self.setFrameShape(QFrame.NoFrame)

        self.activated.connect(self._on_activated)

    # -- pomocnicze ---------------------------------------------------------

    def _button_hit(self, pos: QPoint) -> Optional[Tuple[object, str]]:
        index = self.indexAt(pos)
        if not index.isValid():
            return None
        thumb = self._delegate.thumb_rect(self.visualRect(index))
        video_rect, audio_rect = CardDelegate.button_rects(thumb)
        if video_rect.contains(pos):
            return index.data(R_VIDEO), "video"
        if audio_rect.contains(pos):
            return index.data(R_VIDEO), "audio"
        return None

    # -- zdarzenia ------------------------------------------------------------

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            hit = self._button_hit(event.pos())
            if hit is not None:
                video, mode = hit
                if video is not None:
                    if mode == "video":
                        self.req_play_video.emit(video)
                    else:
                        self.req_play_audio.emit(video)
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        over = self._button_hit(event.pos()) is not None
        self.viewport().setCursor(
            Qt.PointingHandCursor if over else Qt.ArrowCursor
        )
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.viewport().setCursor(Qt.ArrowCursor)
        super().leaveEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        mods = event.modifiers()
        if key in (Qt.Key_A, Qt.Key_V) and not (
            mods & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)
        ):
            index = self.currentIndex()
            if index.isValid():
                video = index.data(R_VIDEO)
                if video is not None:
                    if key == Qt.Key_A:
                        self.req_play_audio.emit(video)
                    else:
                        self.req_play_video.emit(video)
                    event.accept()
                    return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        index = self.indexAt(event.pos())
        if index.isValid():
            video = index.data(R_VIDEO)
            if video is not None:
                self.req_context.emit(video, event.globalPos())
                event.accept()
                return
        super().contextMenuEvent(event)

    def _on_activated(self, index) -> None:
        if index.isValid():
            video = index.data(R_VIDEO)
            if video is not None:
                self.req_play_video.emit(video)


class FeedTabPage(QWidget):
    """Zakładka z feedem: baner + siatka + „wczytaj więcej"."""

    play_requested = pyqtSignal(object, str)    # VideoItem, "video"/"audio"
    more_requested = pyqtSignal(str)            # target
    cookies_requested = pyqtSignal()
    retry_requested = pyqtSignal()
    unwatched_requested = pyqtSignal(object)    # VideoItem

    # code -> (rodzaj banera, klucz i18n, akcja)
    _ERROR_MAP = {
        "session_invalid": ("error", "banner.session_invalid", "cookies"),
        "cookies_load_failed": ("error", "banner.cookies_load", "cookies"),
        "network_error": ("warn", "banner.network", "retry"),
        "json_decode_error": ("warn", "banner.json_decode", "retry"),
        "unexpected_response": ("error", "banner.unexpected", None),
        "invalid_target": ("error", "banner.unexpected", None),
    }

    def __init__(
        self, target: str, metrics: CardMetrics, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.target = target
        self.metrics = metrics
        self.model = VideoListModel(self)
        self.continuation: Optional[str] = None
        self.last_ts: float = 0.0
        self.from_cache: bool = False
        self.busy: bool = False
        self._banner_state: Optional[tuple] = None  # (kind, text, action)
        self._filter_text = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(8)

        # -- baner -----------------------------------------------------------
        self._banner = QFrame()
        self._banner.setObjectName("Banner")
        self._banner.setProperty("kind", "info")
        self._banner.setVisible(False)
        blay = QHBoxLayout(self._banner)
        blay.setContentsMargins(12, 8, 8, 8)
        blay.setSpacing(8)
        self._banner_dot = QLabel("●")
        self._banner_msg = QLabel()
        self._banner_msg.setObjectName("BannerMsg")
        self._banner_msg.setWordWrap(True)
        self._banner_action = QPushButton()
        self._banner_action.setVisible(False)
        self._banner_action.clicked.connect(self._on_banner_action)
        self._banner_close = QToolButton()
        self._banner_close.setText("×")
        self._banner_close.setCursor(Qt.PointingHandCursor)
        self._banner_close.clicked.connect(self.clear_banner)
        blay.addWidget(self._banner_dot, 0, Qt.AlignTop)
        blay.addWidget(self._banner_msg, 1)
        blay.addWidget(self._banner_action, 0, Qt.AlignVCenter)
        blay.addWidget(self._banner_close, 0, Qt.AlignTop)
        root.addWidget(self._banner)

        # -- siatka / stan pusty ------------------------------------------------
        self.view = CardListView(metrics, self)
        self.view.setModel(self.model)
        self._empty_label = QLabel()
        self._empty_label.setObjectName("EmptyLabel")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._stack = QStackedWidget()
        self._stack.addWidget(self.view)       # 0
        self._stack.addWidget(self._empty_label)  # 1
        root.addWidget(self._stack, 1)

        # -- wczytaj więcej ------------------------------------------------------
        self.more_btn = QPushButton()
        self.more_btn.setCursor(Qt.PointingHandCursor)
        self.more_btn.setVisible(False)
        self.more_btn.clicked.connect(lambda: self.more_requested.emit(self.target))
        root.addWidget(self.more_btn)

        # -- sygnały widoku ---------------------------------------------------------
        self.view.req_play_video.connect(lambda v: self.play_requested.emit(v, "video"))
        self.view.req_play_audio.connect(lambda v: self.play_requested.emit(v, "audio"))
        self.view.req_context.connect(self._show_context)
        self.model.count_changed.connect(lambda _n: self._update_empty())

        self.retranslate()

    # -- API -------------------------------------------------------------------

    def set_feed(
        self,
        videos: List[VideoItem],
        continuation: Optional[str],
        ts: float,
        cached: bool,
    ) -> None:
        self.model.set_videos(videos)
        self.continuation = continuation
        self.last_ts = ts
        self.from_cache = cached
        self._update_more_btn()
        self._update_empty()

    def append_feed(
        self, videos: List[VideoItem], continuation: Optional[str]
    ) -> int:
        added = self.model.append_videos(videos)
        self.continuation = continuation
        self._update_more_btn()
        self._update_empty()
        return added

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.more_btn.setEnabled(not busy)
        self.more_btn.setText(
            tr("btn.more_loading") if busy else tr("btn.more")
        )
        self._update_empty()

    def show_error(self, code: str, message: str) -> None:
        kind, key, action = self._ERROR_MAP.get(
            code, ("error", "banner.generic", None)
        )
        text = tr(key, msg=message) if key == "banner.generic" else tr(key)
        self.show_banner(kind, text, action, raw_state=(kind, text, action))

    def show_banner(
        self,
        kind: str,
        text: str,
        action: Optional[str] = None,
        raw_state: Optional[tuple] = None,
    ) -> None:
        self._banner_state = raw_state or (kind, text, action)
        self._banner.setProperty("kind", kind)
        # odśwież styl po zmianie właściwości dynamicznej
        style = self._banner.style()
        style.unpolish(self._banner)
        style.polish(self._banner)
        color = {"error": theme.ERR, "warn": theme.WARN, "info": "#5aa7ff"}.get(
            kind, theme.WARN
        )
        self._banner_dot.setStyleSheet(f"color: {color}; background: transparent;")
        self._banner_msg.setText(text)
        if action:
            self._banner_action.setText(
                tr("btn.update_cookies") if action == "cookies" else tr("btn.retry")
            )
            self._banner_action.setVisible(True)
        else:
            self._banner_action.setVisible(False)
        self._banner.setVisible(True)
        self._update_empty()

    def clear_banner(self) -> None:
        self._banner_state = None
        self._banner.setVisible(False)
        self._update_empty()

    def has_error_banner(self) -> bool:
        return bool(self._banner_state) and self._banner.isVisible()

    def set_filter(self, text: str) -> None:
        self._filter_text = text or ""
        self.model.set_filter(self._filter_text)
        self._update_empty()

    def apply_marks(self, watched_ids, playing_ids) -> None:
        self.model.set_watched(watched_ids)
        self.model.set_playing(playing_ids)

    def save_scroll(self) -> int:
        return self.view.verticalScrollBar().value()

    def restore_scroll(self, value: int) -> None:
        bar = self.view.verticalScrollBar()
        bar.setValue(min(value, bar.maximum()))

    def retranslate(self) -> None:
        self.more_btn.setText(
            tr("btn.more_loading") if self.busy else tr("btn.more")
        )
        if self._banner_state:
            kind, text, action = self._banner_state
            if action:
                self._banner_action.setText(
                    tr("btn.update_cookies") if action == "cookies" else tr("btn.retry")
                )
        self._update_empty()

    # -- wnętrze ------------------------------------------------------------------

    def _on_banner_action(self) -> None:
        if not self._banner_state:
            return
        action = self._banner_state[2]
        if action == "cookies":
            self.cookies_requested.emit()
        elif action == "retry":
            self.retry_requested.emit()

    def _update_more_btn(self) -> None:
        visible = bool(self.continuation) and self.model.rowCount() > 0
        self.more_btn.setVisible(visible)
        self.more_btn.setEnabled(visible and not self.busy)

    def _update_empty(self) -> None:
        if self.model.rowCount() > 0:
            self._stack.setCurrentWidget(self.view)
            self._update_more_btn()
            return
        self._stack.setCurrentWidget(self._empty_label)
        self.more_btn.setVisible(False)
        if self.busy:
            text = tr("empty.loading")
        elif self._filter_text:
            text = tr("empty.filter")
        else:
            text = tr("empty.feed")
        self._empty_label.setText(text)

    def _show_context(self, video: VideoItem, global_pos: QPoint) -> None:
        menu = QMenu(self)
        act_video = menu.addAction(tr("ctx.play_video"))
        act_audio = menu.addAction(tr("ctx.play_audio"))
        menu.addSeparator()
        act_copy_url = menu.addAction(tr("ctx.copy_url"))
        act_copy_title = menu.addAction(tr("ctx.copy_title"))
        act_browser = menu.addAction(tr("ctx.open_browser"))
        menu.addSeparator()
        act_unwatch = menu.addAction(tr("ctx.unwatched"))

        chosen = menu.exec_(global_pos)
        if chosen is None:
            return
        if chosen is act_video:
            self.play_requested.emit(video, "video")
        elif chosen is act_audio:
            self.play_requested.emit(video, "audio")
        elif chosen is act_copy_url:
            QApplication.clipboard().setText(video.url)
        elif chosen is act_copy_title:
            QApplication.clipboard().setText(video.title)
        elif chosen is act_browser:
            QDesktopServices.openUrl(QUrl(video.url))
        elif chosen is act_unwatch:
            self.unwatched_requested.emit(video)
