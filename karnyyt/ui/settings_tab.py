"""
settings_tab.py - zakładka Ustawienia.

Sekcje: Odtwarzanie (mpv) / Ścieżki narzędzi / Wygląd / Dane i cookies /
Zaawansowane / Stan narzędzi / O programie.

Każda zmiana ląduje natychmiast w settings.json (nie ma przycisku „Zapisz"
- mniej klikania, zero stanów „niezapisanych").
"""

from __future__ import annotations

import os
from typing import Dict, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, yt_feed_py38
from ..core.i18n import set_lang, tr
from ..core.settings import (
    CARD_SIZE_CHOICES,
    RESOLUTION_CHOICES,
    Settings,
    WatchedStore,
)


class SettingsTab(QWidget):
    retranslate_all = pyqtSignal()
    cookies_edit_requested = pyqtSignal()
    open_dir_requested = pyqtSignal(str)          # "data" | "cache"
    tools_recheck_requested = pyqtSignal()
    watched_cleared = pyqtSignal()
    card_size_changed = pyqtSignal(str)

    def __init__(
        self, settings: Settings, watched: WatchedStore,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._watched = watched

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        inner = QWidget()
        scroll.setWidget(inner)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(16, 12, 16, 24)
        lay.setSpacing(14)

        # == Odtwarzanie =====================================================
        self.grp_playback = QGroupBox()
        form = QFormLayout(self.grp_playback)
        form.setContentsMargins(12, 18, 12, 12)
        form.setSpacing(8)

        self.cmb_resolution = QComboBox()
        for value in RESOLUTION_CHOICES:
            if value == "best":
                self.cmb_resolution.addItem(tr("res.best"), value)
            else:
                self.cmb_resolution.addItem(f"{value}p", value)
        idx = self.cmb_resolution.findData(settings.get("resolution", 360))
        self.cmb_resolution.setCurrentIndex(max(0, idx))
        self.cmb_resolution.currentIndexChanged.connect(self._on_resolution)
        self.lbl_resolution = QLabel()
        form.addRow(self.lbl_resolution, self.cmb_resolution)

        self.chk_h264 = QCheckBox()
        self.chk_h264.setChecked(bool(settings.get("prefer_h264", True)))
        self.chk_h264.toggled.connect(
            lambda v: settings.set("prefer_h264", bool(v))
        )
        form.addRow("", self.chk_h264)
        self.lbl_h264_hint = QLabel()
        self.lbl_h264_hint.setObjectName("Hint")
        self.lbl_h264_hint.setWordWrap(True)
        form.addRow("", self.lbl_h264_hint)

        self.edit_extra = QLineEdit(settings.get("extra_mpv_args", ""))
        self.edit_extra.editingFinished.connect(
            lambda: settings.set("extra_mpv_args", self.edit_extra.text().strip())
        )
        self.lbl_extra = QLabel()
        form.addRow(self.lbl_extra, self.edit_extra)
        self.lbl_extra_hint = QLabel()
        self.lbl_extra_hint.setObjectName("Hint")
        self.lbl_extra_hint.setWordWrap(True)
        form.addRow("", self.lbl_extra_hint)
        lay.addWidget(self.grp_playback)

        # == Ścieżki narzędzi ==================================================
        self.grp_paths = QGroupBox()
        pform = QFormLayout(self.grp_paths)
        pform.setContentsMargins(12, 18, 12, 12)
        pform.setSpacing(8)

        self.lbl_mpv_path = QLabel()
        self.lbl_ytdlp_path = QLabel()
        self.lbl_ffmpeg_path = QLabel()
        self.edit_mpv = self._path_row(pform, self.lbl_mpv_path, "mpv_path")
        self.edit_ytdlp = self._path_row(pform, self.lbl_ytdlp_path, "ytdlp_path")
        self.edit_ffmpeg = self._path_row(pform, self.lbl_ffmpeg_path, "ffmpeg_path")
        lay.addWidget(self.grp_paths)

        # == Wygląd ============================================================
        self.grp_look = QGroupBox()
        lform = QFormLayout(self.grp_look)
        lform.setContentsMargins(12, 18, 12, 12)
        lform.setSpacing(8)

        self.cmb_card = QComboBox()
        for key in CARD_SIZE_CHOICES:
            self.cmb_card.addItem(tr(f"card.{key}"), key)
        self.cmb_card.setCurrentIndex(
            max(0, self.cmb_card.findData(settings.get("card_size", "medium")))
        )
        self.cmb_card.currentIndexChanged.connect(self._on_card_size)
        self.lbl_card = QLabel()
        lform.addRow(self.lbl_card, self.cmb_card)

        self.cmb_lang = QComboBox()
        self.cmb_lang.addItem("Polski", "pl")
        self.cmb_lang.addItem("English", "en")
        self.cmb_lang.setCurrentIndex(
            max(0, self.cmb_lang.findData(settings.get("language", "pl")))
        )
        self.cmb_lang.currentIndexChanged.connect(self._on_language)
        self.lbl_lang = QLabel()
        lform.addRow(self.lbl_lang, self.cmb_lang)

        self.spin_refresh = QSpinBox()
        self.spin_refresh.setRange(0, 240)
        self.spin_refresh.setValue(int(settings.get("auto_refresh_min", 0)))
        self.spin_refresh.valueChanged.connect(
            lambda v: settings.set("auto_refresh_min", int(v))
        )
        self.lbl_refresh = QLabel()
        lform.addRow(self.lbl_refresh, self.spin_refresh)
        lay.addWidget(self.grp_look)

        # == Dane i cookies =====================================================
        self.grp_data = QGroupBox()
        dlay = QVBoxLayout(self.grp_data)
        dlay.setContentsMargins(12, 18, 12, 12)
        dlay.setSpacing(8)

        self.btn_cookies = QPushButton()
        self.btn_cookies.setProperty("class", "accent")
        self.btn_cookies.setCursor(Qt.PointingHandCursor)
        self.btn_cookies.clicked.connect(self.cookies_edit_requested.emit)
        dlay.addWidget(self.btn_cookies)
        self.lbl_cookies_hint = QLabel()
        self.lbl_cookies_hint.setObjectName("Hint")
        self.lbl_cookies_hint.setWordWrap(True)
        dlay.addWidget(self.lbl_cookies_hint)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_open_data = QPushButton()
        self.btn_open_data.clicked.connect(
            lambda: self.open_dir_requested.emit("data")
        )
        self.btn_open_cache = QPushButton()
        self.btn_open_cache.clicked.connect(
            lambda: self.open_dir_requested.emit("cache")
        )
        row.addWidget(self.btn_open_data)
        row.addWidget(self.btn_open_cache)
        row.addStretch(1)
        dlay.addLayout(row)

        self.btn_clear_watched = QPushButton()
        self.btn_clear_watched.clicked.connect(self._on_clear_watched)
        dlay.addWidget(self.btn_clear_watched)
        lay.addWidget(self.grp_data)

        # == Zaawansowane =========================================================
        self.grp_adv = QGroupBox()
        aform = QFormLayout(self.grp_adv)
        aform.setContentsMargins(12, 18, 12, 12)
        aform.setSpacing(8)

        self.edit_cv = QLineEdit(settings.get("client_version", ""))
        self.edit_cv.editingFinished.connect(
            lambda: settings.set("client_version", self.edit_cv.text().strip())
        )
        self.lbl_cv = QLabel()
        aform.addRow(self.lbl_cv, self.edit_cv)
        self.lbl_cv_hint = QLabel()
        self.lbl_cv_hint.setObjectName("Hint")
        self.lbl_cv_hint.setWordWrap(True)
        aform.addRow("", self.lbl_cv_hint)
        lay.addWidget(self.grp_adv)

        # == Stan narzędzi ==========================================================
        self.grp_tools = QGroupBox()
        tlay = QVBoxLayout(self.grp_tools)
        tlay.setContentsMargins(12, 18, 12, 12)
        tlay.setSpacing(6)
        self.tool_labels: Dict[str, QLabel] = {}
        for name in ("mpv", "yt-dlp", "ffmpeg"):
            lbl = QLabel()
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            tlay.addWidget(lbl)
            self.tool_labels[name] = lbl
        self.btn_recheck = QPushButton()
        self.btn_recheck.clicked.connect(self.tools_recheck_requested.emit)
        tlay.addWidget(self.btn_recheck, 0, Qt.AlignLeft)
        lay.addWidget(self.grp_tools)

        # == O programie ==============================================================
        self.grp_about = QGroupBox()
        ablay = QVBoxLayout(self.grp_about)
        ablay.setContentsMargins(12, 18, 12, 12)
        self.lbl_about = QLabel()
        self.lbl_about.setObjectName("AboutText")
        self.lbl_about.setWordWrap(True)
        self.lbl_about.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ablay.addWidget(self.lbl_about)
        lay.addWidget(self.grp_about)
        lay.addStretch(1)

        self.retranslate()

    # -- budowa wiersza ścieżki -------------------------------------------------

    def _path_row(self, form: QFormLayout, label: QLabel, key: str) -> QLineEdit:
        edit = QLineEdit(self._settings.get(key, ""))
        edit.setPlaceholderText("PATH")
        edit.editingFinished.connect(
            lambda k=key, e=edit: self._settings.set(k, e.text().strip())
        )
        btn = QPushButton(tr("set.browse"))
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda _=False, e=edit, k=key: self._browse(e, k))
        box = QHBoxLayout()
        box.setSpacing(6)
        box.addWidget(edit, 1)
        box.addWidget(btn)
        wrap = QWidget()
        wrap.setLayout(box)
        form.addRow(label, wrap)
        return edit

    def _browse(self, edit: QLineEdit, key: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("filter.file_dialog_title"), edit.text() or "",
            "*.exe" if os.name == "nt" else "",
        )
        if path:
            edit.setText(path)
            self._settings.set(key, path)

    # -- reakcje --------------------------------------------------------------------

    def _on_resolution(self, index: int) -> None:
        value = self.cmb_resolution.itemData(index)
        if value is not None:
            self._settings.set("resolution", value)

    def _on_card_size(self, index: int) -> None:
        key = self.cmb_card.itemData(index)
        if key:
            self._settings.set("card_size", key)
            self.card_size_changed.emit(key)

    def _on_language(self, index: int) -> None:
        code = self.cmb_lang.itemData(index)
        if code:
            self._settings.set("language", code)
            set_lang(code)
            self.retranslate_all.emit()

    def _on_clear_watched(self) -> None:
        n = len(self._watched)
        answer = QMessageBox.question(
            self,
            "KarnyYT",
            tr("set.clear_watched_confirm", n=n),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._watched.clear()
            self.refresh_watched_count()
            self.watched_cleared.emit()

    # -- stan narzędzi ----------------------------------------------------------------

    def set_tools_status(
        self, found: Dict[str, Optional[str]], versions: Dict[str, Optional[str]]
    ) -> None:
        for name, lbl in self.tool_labels.items():
            path = found.get(name)
            version = versions.get(name)
            if path:
                lbl.setObjectName("ToolOk")
                text = f"{name}: {tr('tool.found', path=path)}"
                if version:
                    text += f"  —  {version}"
            else:
                lbl.setObjectName("ToolMissing")
                text = f"{name}: {tr('tool.missing')}"
            # zmiana objectName wymaga odświeżenia stylu
            lbl.style().unpolish(lbl)
            lbl.setText(text)
            lbl.style().polish(lbl)

    def refresh_watched_count(self) -> None:
        self.btn_clear_watched.setText(
            tr("set.clear_watched", n=len(self._watched))
        )

    # -- tłumaczenia ---------------------------------------------------------------------

    def retranslate(self) -> None:
        self.grp_playback.setTitle(tr("set.playback"))
        self.lbl_resolution.setText(tr("set.resolution"))
        self.cmb_resolution.setItemText(
            self.cmb_resolution.count() - 1, tr("res.best")
        )
        self.chk_h264.setText(tr("set.prefer_h264"))
        self.lbl_h264_hint.setText(tr("set.prefer_h264_hint"))
        self.lbl_extra.setText(tr("set.extra_args"))
        self.lbl_extra_hint.setText(tr("set.extra_args_hint"))

        self.grp_paths.setTitle(tr("set.paths"))
        self.lbl_mpv_path.setText(tr("set.mpv_path"))
        self.lbl_ytdlp_path.setText(tr("set.ytdlp_path"))
        self.lbl_ffmpeg_path.setText(tr("set.ffmpeg_path"))

        self.grp_look.setTitle(tr("set.appearance"))
        self.lbl_card.setText(tr("set.card_size"))
        for i, key in enumerate(CARD_SIZE_CHOICES):
            self.cmb_card.setItemText(i, tr(f"card.{key}"))
        self.lbl_lang.setText(tr("set.language"))
        self.lbl_refresh.setText(tr("set.auto_refresh"))
        self.spin_refresh.setSuffix(" min")

        self.grp_data.setTitle(tr("set.data"))
        self.btn_cookies.setText(tr("set.update_cookies"))
        self.lbl_cookies_hint.setText(tr("set.update_cookies_hint"))
        self.btn_open_data.setText(tr("set.open_data"))
        self.btn_open_cache.setText(tr("set.open_cache"))
        self.refresh_watched_count()

        self.grp_adv.setTitle(tr("set.advanced"))
        self.lbl_cv.setText(
            tr("set.client_version", cv=yt_feed_py38.CLIENT_VERSION)
        )
        self.lbl_cv_hint.setText(tr("set.client_version_hint"))

        self.grp_tools.setTitle(tr("set.tools"))
        self.btn_recheck.setText(tr("set.recheck"))

        self.grp_about.setTitle(tr("set.about"))
        self.lbl_about.setText(tr("set.about_text", version=__version__))
