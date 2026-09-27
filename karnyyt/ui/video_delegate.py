"""
video_delegate.py - rysowanie karty filmu (QStyledItemDelegate).

Jeden delegate maluje WSZYSTKIE kafelki (miniatura, badge czasu, tytuł,
kanał, meta, hover-przyciski ▶/♪, stan obejrzane/odtwarzane). Dzięki temu
siatka 100+ filmów kosztuje tyle, co ~12 widocznych komórek - zero
widgetów per film.

Optymalizacje pod Core 2 Duo / GMA 4500MHD:
  * cache zawijania tytułów (QFontMetrics to najdroższa operacja w paint),
  * brak cieni/blurów (QGraphicsEffect jest drogi na starym GPU),
  * pixmapy miniatur są już przeskalowane przez ThumbWorker - paint tylko
    rysuje, nie skaluje.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Optional, Tuple

from PyQt5.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PyQt5.QtGui import (
    QColor,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPolygon,
)
from PyQt5.QtWidgets import QStyle, QStyleOptionViewItem, QStyledItemDelegate

from ..core.i18n import lang, tr
from . import theme
from .theme import CardMetrics
from .video_model import R_PLAYING, R_THUMB, R_WATCHED, R_VIDEO

_WRAP_CACHE_CAP = 400


def _qcolor(css: str, alpha: Optional[int] = None) -> QColor:
    c = QColor(css)
    if alpha is not None:
        c.setAlpha(alpha)
    return c


class CardDelegate(QStyledItemDelegate):
    """Karta filmu: [miniatura + badge] [tytuł 2 linie] [kanał] [views • data]."""

    BTN_R = 21      # promień hover-przycisków
    BTN_GAP = 14    # odstęp między środkami przycisków (od krawędzi)

    def __init__(self, metrics: CardMetrics, parent=None) -> None:
        super().__init__(parent)
        self._m = metrics
        self._fonts = theme.make_fonts()
        self._wrap_cache: "OrderedDict[Tuple[str, int], Tuple[str, str]]" = OrderedDict()

    # -- geometria -------------------------------------------------------

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return self._m.size()

    @classmethod
    def button_rects(cls, thumb_rect: QRect) -> Tuple[QRect, QRect]:
        """(przycisk wideo, przycisk audio) wyśrodkowane na miniaturze z zachowaniem odstępu."""
        cx = thumb_rect.center().x()
        cy = thumb_rect.center().y()
        r = cls.BTN_R
        gap = cls.BTN_GAP
        
        # Obliczamy przesunięcie środka każdego koła od punktu centralnego (cx)
        # Środek koła musi być odsunięty o swój promień + połowę odstępu
        offset = r + (gap / 2)
        
        # Wyznaczamy środki dla lewego i prawego przycisku
        left_cx = cx - offset
        right_cx = cx + offset
        
        # Tworzymy QRect dla obu przycisków (współrzędne x to środek minus promień, czyli po prostu left_cx - r)
        # int() zabezpiecza przed błędami zaokrągleń, jeśli gap jest liczbą nieparzystą
        left = QRect(int(left_cx - r), int(cy - r), 2 * r, 2 * r)
        right = QRect(int(right_cx - r), int(cy - r), 2 * r, 2 * r)
        
        return left, right

    # @classmethod
    # def button_rects(cls, thumb_rect: QRect) -> Tuple[QRect, QRect]:
    #     """(przycisk wideo, przycisk audio) wyśrodkowane na miniaturze."""
    #     cx = thumb_rect.center().x()
    #     cy = thumb_rect.center().y()
    #     r = cls.BTN_R
    #     gap = cls.BTN_GAP
    #     left = QRect(cx - gap - r, cy - r, 2 * r, 2 * r)
    #     right = QRect(cx + gap - r, cy - r, 2 * r, 2 * r)
    #     return left, right

    def thumb_rect(self, card: QRect) -> QRect:
        return QRect(card.x(), card.y(), self._m.thumb_w, self._m.thumb_h)

    # -- malowanie ---------------------------------------------------------

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        video = index.data(R_VIDEO)
        if video is None:
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)

        m = self._m
        card = option.rect
        hover = bool(option.state & QStyle.State_MouseOver)
        selected = bool(option.state & QStyle.State_Selected)
        watched = bool(index.data(R_WATCHED))
        playing = bool(index.data(R_PLAYING))

        # tło karty (hover/selected)
        if hover or selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(_qcolor(theme.CARD_HOVER))
            painter.drawRoundedRect(card.adjusted(0, 0, -1, -1), m.radius, m.radius)

        thumb_rect = self.thumb_rect(card)
        self._paint_thumb(painter, thumb_rect, index.data(R_THUMB), watched, video)
        self._paint_hover_buttons(painter, thumb_rect, hover)

        if playing:
            pen = painter.pen()
            pen.setColor(_qcolor(theme.ACCENT))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(card.adjusted(1, 1, -2, -2), m.radius, m.radius)
        elif selected:
            pen = painter.pen()
            pen.setColor(_qcolor(theme.CARD_BORDER))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(card.adjusted(0, 0, -1, -1), m.radius, m.radius)

        self._paint_texts(painter, card, thumb_rect, video, watched)
        painter.restore()

    # -- miniatura -----------------------------------------------------------

    def _paint_thumb(self, painter: QPainter, rect: QRect, thumb, watched: bool, video) -> None:
        m = self._m
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), m.thumb_radius, m.thumb_radius)
        painter.save()
        painter.setClipPath(path)

        if thumb is not None and not thumb.isNull():
            painter.drawPixmap(rect, thumb)
        else:
            painter.fillRect(rect, _qcolor(theme.THUMB_PLACEHOLDER))
            # placeholder: subtelny trójkąt play
            c = rect.center()
            s = 16
            tri = QPolygon(
                [QPoint(c.x() - s // 2 + 2, c.y() - s), QPoint(c.x() - s // 2 + 2, c.y() + s),
                 QPoint(c.x() + s, c.y())]
            )
            painter.setPen(Qt.NoPen)
            painter.setBrush(_qcolor(theme.CARD_BORDER))
            painter.drawPolygon(tri)

        if watched:
            painter.fillRect(rect, _qcolor("#08080a", 105))
        painter.restore()

        # badge czasu trwania (prawy dolny róg miniatury)
        duration = video.duration or ""
        if duration:
            is_live = duration.strip().upper() in ("LIVE", "NA ŻYWO", "PREMIERE")
            self._paint_badge(painter, rect, duration, is_live)

        # znacznik obejrzane (lewy górny)
        if watched:
            self._paint_watched_badge(painter, rect)

    def _paint_badge(self, painter: QPainter, thumb_rect: QRect, text: str, is_live: bool) -> None:
        if is_live:
            text = tr("badge.live")
        fm = QFontMetrics(self._fonts["badge"])
        tw = fm.horizontalAdvance(text)
        pad_x, pad_y = 6, 3
        w = tw + 2 * pad_x
        h = fm.height() + 2 * pad_y - 3
        rect = QRect(
            thumb_rect.right() - w - 6,
            thumb_rect.bottom() - h - 6,
            w,
            h,
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(_qcolor(theme.ACCENT if is_live else "#000000", 195))
        painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(_qcolor("#ffffff"))
        painter.setFont(self._fonts["badge"])
        painter.drawText(rect, Qt.AlignCenter, text)

    def _paint_watched_badge(self, painter: QPainter, thumb_rect: QRect) -> None:
        d = 18
        rect = QRect(thumb_rect.left() + 6, thumb_rect.top() + 6, d, d)
        painter.setPen(Qt.NoPen)
        painter.setBrush(_qcolor(theme.OK, 225))
        painter.drawEllipse(rect)
        pen = painter.pen()
        pen.setColor(_qcolor("#0b1f13"))
        pen.setWidthF(2.0)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        pts = [
            QPoint(rect.x() + int(d * 0.28), rect.y() + int(d * 0.52)),
            QPoint(rect.x() + int(d * 0.44), rect.y() + int(d * 0.68)),
            QPoint(rect.x() + int(d * 0.74), rect.y() + int(d * 0.33)),
        ]
        from PyQt5.QtGui import QPainterPath as _QP

        path = _QP()
        path.moveTo(pts[0])
        path.lineTo(pts[1])
        path.lineTo(pts[2])
        painter.drawPath(path)

    # -- hover buttons ---------------------------------------------------------

    def _paint_hover_buttons(self, painter: QPainter, thumb_rect: QRect, hover: bool) -> None:
        if not hover:
            return
        painter.fillRect(thumb_rect, _qcolor("#000000", 46))
        video_rect, audio_rect = self.button_rects(thumb_rect)
        self._paint_circle_button(painter, video_rect, _qcolor(theme.ACCENT), "play")
        self._paint_circle_button(painter, audio_rect, _qcolor("#3f7fd6"), "note")

    def _paint_circle_button(self, painter: QPainter, rect: QRect, bg: QColor, glyph: str) -> None:
        painter.setPen(_qcolor("#000000", 90))
        painter.setBrush(bg)
        painter.drawEllipse(rect)
        cx, cy = rect.center().x(), rect.center().y()
        painter.setPen(Qt.NoPen)
        painter.setBrush(_qcolor("#ffffff"))
        if glyph == "play":
            r = rect.width() // 2
            tri = QPolygon(
                [
                    QPoint(cx - int(r * 0.36) + 2, cy - int(r * 0.55)),
                    QPoint(cx - int(r * 0.36) + 2, cy + int(r * 0.55)),
                    QPoint(cx + int(r * 0.58), cy),
                ]
            )
            painter.drawPolygon(tri)
        else:  # nuta ♪
            head = QRect(cx - 6, cy + 2, 8, 6)
            painter.drawEllipse(head)
            painter.drawRect(QRect(cx + 1, cy - 9, 2, 13))
            painter.drawPolygon(
                QPolygon(
                    [
                        QPoint(cx + 1, cy - 9),
                        QPoint(cx + 8, cy - 6),
                        QPoint(cx + 8, cy - 3),
                        QPoint(cx + 3, cy - 5),
                    ]
                )
            )

    # -- teksty ------------------------------------------------------------------

    def _paint_texts(self, painter: QPainter, card: QRect, thumb_rect: QRect, video, watched: bool) -> None:
        m = self._m
        x = card.x() + m.pad_x
        w = m.text_w
        y = thumb_rect.bottom() + m.title_top

        title_color = _qcolor(theme.TEXT_FADED if watched else theme.TEXT_PRIMARY)
        painter.setFont(self._fonts["title"])
        fm = QFontMetrics(self._fonts["title"])
        line1, line2 = self._wrap_title(video.title, fm, w)
        painter.setPen(title_color)
        painter.drawText(QRect(x, y, w, m.title_line_h), Qt.AlignLeft | Qt.AlignVCenter, line1)
        painter.drawText(
            QRect(x, y + m.title_line_h, w, m.title_line_h),
            Qt.AlignLeft | Qt.AlignVCenter,
            line2,
        )
        y += m.title_lines * m.title_line_h

        painter.setFont(self._fonts["channel"])
        painter.setPen(_qcolor(theme.TEXT_SECONDARY))
        channel = video.author or ""
        fm_c = QFontMetrics(self._fonts["channel"])
        painter.drawText(
            QRect(x, y, w, m.channel_h),
            Qt.AlignLeft | Qt.AlignVCenter,
            fm_c.elidedText(channel, Qt.ElideRight, w),
        )
        y += m.channel_h

        # meta: wyświetlenia • data (zlokalizowane)
        painter.setFont(self._fonts["meta"])
        painter.setPen(_qcolor(theme.TEXT_FADED))
        views = video.views or ""
        pub = video.published_time or ""
        from ..core.utils import localize_meta

        views = localize_meta(views, lang())
        pub = localize_meta(pub, lang())
        if views and pub:
            meta = tr("meta.views_pub", views=views, pub=pub)
        else:
            meta = views or pub
        fm_m = QFontMetrics(self._fonts["meta"])
        painter.drawText(
            QRect(x, y, w, m.meta_h),
            Qt.AlignLeft | Qt.AlignVCenter,
            fm_m.elidedText(meta, Qt.ElideRight, w),
        )

    def _wrap_title(self, title: str, fm: QFontMetrics, width: int) -> Tuple[str, str]:
        """Dwulinijkowe zawijanie tytułu z cache (najdroższa operacja painta)."""
        key = (title, width)
        cached = self._wrap_cache.get(key)
        if cached is not None:
            self._wrap_cache.move_to_end(key)
            return cached

        words = title.split(" ")
        line1_words = []
        idx = 0
        for i, word in enumerate(words):
            candidate = " ".join(line1_words + [word])
            if fm.horizontalAdvance(candidate) > width and line1_words:
                idx = i
                break
            line1_words.append(word)
            idx = len(words)
        line1 = " ".join(line1_words)
        rest = " ".join(words[idx:]) if idx < len(words) else ""
        line2 = fm.elidedText(rest, Qt.ElideRight, width) if rest else ""
        line1 = fm.elidedText(line1, Qt.ElideRight, width)

        result = (line1, line2)
        self._wrap_cache[key] = result
        while len(self._wrap_cache) > _WRAP_CACHE_CAP:
            self._wrap_cache.popitem(last=False)
        return result
