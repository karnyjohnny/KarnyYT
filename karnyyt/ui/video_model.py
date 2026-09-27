"""
video_model.py - QAbstractListModel z filmami feedu.

Model trzyma:
  * pełną listę filmów + przefiltrowane „wiersze",
  * miniatury (LRU z limitem - RAM jest na wagę złota),
  * zbiory „obejrzane" i „odtwarzane" (współdzielone między zakładkami).

Delegate czyta role: R_VIDEO / R_THUMB / R_WATCHED / R_PLAYING.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Dict, List, Optional, Set

from PyQt5.QtCore import (
    QAbstractListModel,
    QModelIndex,
    Qt,
    pyqtSignal,
)
from PyQt5.QtGui import QPixmap

from ..yt_feed_py38 import VideoItem

R_VIDEO = Qt.UserRole + 1
R_THUMB = Qt.UserRole + 2
R_WATCHED = Qt.UserRole + 3
R_PLAYING = Qt.UserRole + 4

_THUMB_CAP = 180  # ~30 MB max przy 300×169 RGB32 - twardy limit LRU


class VideoListModel(QAbstractListModel):
    count_changed = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._all: List[VideoItem] = []
        self._rows: List[VideoItem] = []
        self._id_rows: Dict[str, List[int]] = {}
        self._filter = ""
        self._thumbs: "OrderedDict[str, QPixmap]" = OrderedDict()
        self._watched: Set[str] = set()
        self._playing: Set[str] = set()

    # -- dane -----------------------------------------------------------

    def set_videos(self, videos: List[VideoItem]) -> None:
        self.beginResetModel()
        self._all = list(videos)
        self._rebuild_rows_locked()
        self.endResetModel()
        self.count_changed.emit(len(self._rows))

    def append_videos(self, videos: List[VideoItem]) -> int:
        """Dokleja filmy („wczytaj więcej"), deduplikując po video_id.
        Zwraca liczbę faktycznie dodanych wierszy (po filtrze)."""
        known = {v.video_id for v in self._all}
        fresh = [v for v in videos if v.video_id not in known]
        if not fresh:
            return 0
        self._all.extend(fresh)

        matching = [v for v in fresh if self._matches(v)]
        if matching:
            first = len(self._rows)
            self.beginInsertRows(QModelIndex(), first, first + len(matching) - 1)
            self._rows.extend(matching)
            self._rebuild_id_map()
            self.endInsertRows()
        else:
            self._rebuild_id_map()
        self.count_changed.emit(len(self._rows))
        return len(matching)

    def clear(self) -> None:
        self.beginResetModel()
        self._all = []
        self._rows = []
        self._id_rows = {}
        self.endResetModel()
        self.count_changed.emit(0)

    def set_filter(self, text: str) -> None:
        text = (text or "").strip().lower()
        if text == self._filter:
            return
        self.beginResetModel()
        self._filter = text
        self._rebuild_rows_locked()
        self.endResetModel()
        self.count_changed.emit(len(self._rows))

    def _matches(self, video: VideoItem) -> bool:
        if not self._filter:
            return True
        if self._filter in video.title.lower():
            return True
        if video.author and self._filter in video.author.lower():
            return True
        return False

    def _rebuild_rows_locked(self) -> None:
        self._rows = [v for v in self._all if self._matches(v)]
        self._rebuild_id_map()

    def _rebuild_id_map(self) -> None:
        self._id_rows = {}
        for row, video in enumerate(self._rows):
            self._id_rows.setdefault(video.video_id, []).append(row)

    # -- miniatury ---------------------------------------------------------

    def set_thumb(self, video_id: str, pixmap: QPixmap) -> None:
        self._thumbs[video_id] = pixmap
        self._thumbs.move_to_end(video_id)
        while len(self._thumbs) > _THUMB_CAP:
            self._thumbs.popitem(last=False)
        for row in self._id_rows.get(video_id, ()):
            idx = self.index(row)
            self.dataChanged.emit(idx, idx, [R_THUMB])

    def thumb(self, video_id: str) -> Optional[QPixmap]:
        pix = self._thumbs.get(video_id)
        if pix is not None:
            self._thumbs.move_to_end(video_id)
        return pix

    def has_thumb(self, video_id: str) -> bool:
        return video_id in self._thumbs

    def clear_thumbs(self) -> None:
        self._thumbs.clear()

    def request_ids_missing_thumbs(self) -> List[str]:
        return [v.video_id for v in self._rows if v.video_id not in self._thumbs]

    # -- znaczniki ---------------------------------------------------------

    def set_watched(self, ids: Set[str]) -> None:
        changed = ids.symmetric_difference(self._watched)
        self._watched = set(ids)
        self._emit_for_ids(changed, R_WATCHED)

    def set_playing(self, ids: Set[str]) -> None:
        changed = ids.symmetric_difference(self._playing)
        self._playing = set(ids)
        self._emit_for_ids(changed, R_PLAYING)

    def _emit_for_ids(self, ids: Set[str], role: int) -> None:
        for vid in ids:
            for row in self._id_rows.get(vid, ()):
                idx = self.index(row)
                self.dataChanged.emit(idx, idx, [role])

    # -- Qt API -------------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        video = self._rows[index.row()]
        if role == Qt.DisplayRole:
            return video.title
        if role == Qt.ToolTipRole:
            parts = [video.title]
            if video.author:
                parts.append(video.author)
            meta = " • ".join(p for p in (video.views, video.published_time) if p)
            if meta:
                parts.append(meta)
            if video.duration:
                parts.append(video.duration)
            parts.append(video.url)
            return "\n".join(parts)
        if role == R_VIDEO:
            return video
        if role == R_THUMB:
            return self.thumb(video.video_id)
        if role == R_WATCHED:
            return video.video_id in self._watched
        if role == R_PLAYING:
            return video.video_id in self._playing
        return None

    def video_at(self, row: int) -> Optional[VideoItem]:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def all_videos(self) -> List[VideoItem]:
        return list(self._all)

    def total_count(self) -> int:
        return len(self._all)
