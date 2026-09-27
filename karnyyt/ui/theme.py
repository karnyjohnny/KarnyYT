"""
theme.py - kompletny ciemny motyw (Fusion + paleta + QSS) i metryki kafelków.

Kolory są współdzielone między QSS a delegate'em (jedno źródło prawdy).
Styl: głęboki, lekko zniebieszczony charcoal + czerwony akcent.
"""

from __future__ import annotations

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QColor, QFont, QPalette
from PyQt5.QtWidgets import QApplication

# -- paleta -------------------------------------------------------------------

WINDOW_BG = "#131316"
PANEL_BG = "#1a1a1f"
CARD_BG = "#212126"
CARD_HOVER = "#2a2a31"
CARD_BORDER = "#2e2e36"
INPUT_BG = "#0f0f13"
INPUT_BORDER = "#33333c"
TEXT_PRIMARY = "#f2f2f2"
TEXT_SECONDARY = "#a5a5ae"
TEXT_FADED = "#71717a"

ACCENT = "#ff4444"
ACCENT_HOVER = "#ff6a6a"
ACCENT_DOWN = "#d92b2b"
AUDIO_BG = "#1e3350"
AUDIO_BORDER = "#2a4a75"
AUDIO_TEXT = "#cfe4ff"
AUDIO_HOVER = "#27436b"

OK = "#3ddc84"
WARN = "#ffc857"
ERR = "#ff5c5c"

BANNER_ERROR_BG = "#331c20"
BANNER_ERROR_BORDER = "#6e2b31"
BANNER_WARN_BG = "#332b18"
BANNER_WARN_BORDER = "#6e5a26"
BANNER_INFO_BG = "#1a2836"
BANNER_INFO_BORDER = "#2c527a"

THUMB_PLACEHOLDER = "#1c1c22"

# -- metryki karty -------------------------------------------------------------

CARD_WIDTHS = {"small": 240, "medium": 300, "large": 364}


class CardMetrics:
    """Wymiary karty dla delegate'a; przeliczane przy zmianie rozmiaru."""

    def __init__(self, size_key: str = "medium") -> None:
        self.apply(size_key)

    def apply(self, size_key: str) -> None:
        self.size_key = size_key if size_key in CARD_WIDTHS else "medium"
        self.card_w = CARD_WIDTHS[self.size_key]
        self.thumb_w = self.card_w
        self.thumb_h = int(round(self.thumb_w * 9 / 16))
        self.radius = 10
        self.thumb_radius = 8
        self.pad_x = 10
        self.title_top = 8
        self.title_lines = 2
        self.title_line_h = 18
        self.channel_h = 17
        self.meta_h = 15
        self.pad_bottom = 10
        self.text_w = self.card_w - 2 * self.pad_x
        self.card_h = (
            self.thumb_h
            + self.title_top
            + self.title_lines * self.title_line_h
            + self.channel_h
            + self.meta_h
            + self.pad_bottom
        )

    def size(self) -> QSize:
        return QSize(self.card_w, self.card_h)

    def thumb_width_px(self) -> int:
        """Szerokość miniatury, do której skaluje worker (lekki zapas na DPI)."""
        return int(self.thumb_w * 1.25)


# -- fonty ---------------------------------------------------------------------


def make_fonts():
    base = QFont("Segoe UI")
    title = QFont(base)
    title.setPointSizeF(10.0)
    title.setWeight(QFont.DemiBold)
    channel = QFont(base)
    channel.setPointSizeF(9.0)
    meta = QFont(base)
    meta.setPointSizeF(8.0)
    badge = QFont(base)
    badge.setPointSizeF(8.5)
    badge.setBold(True)
    return {"title": title, "channel": channel, "meta": meta, "badge": badge}


# -- QSS -------------------------------------------------------------------------

QSS = f"""
* {{
    outline: none;
}}
QMainWindow, QDialog {{
    background: {WINDOW_BG};
}}
QWidget {{
    color: {TEXT_PRIMARY};
    font-family: "Segoe UI", "Arial", sans-serif;
    font-size: 9pt;
}}
QStatusBar {{
    background: {PANEL_BG};
    color: {TEXT_SECONDARY};
    border-top: 1px solid #26262c;
}}
QStatusBar::item {{ border: none; }}

/* --- zakładki --- */
QTabWidget::pane {{
    border: none;
    border-top: 1px solid #26262c;
    background: {WINDOW_BG};
}}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_SECONDARY};
    padding: 9px 20px 8px 20px;
    border: none;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:hover {{ color: {TEXT_PRIMARY}; }}
QTabBar::tab:selected {{
    color: {TEXT_PRIMARY};
    border-bottom: 2px solid {ACCENT};
}}

/* --- przyciski --- */
QPushButton, QToolButton[flat="false"] {{
    background: #26262c;
    border: 1px solid #35353e;
    border-radius: 6px;
    padding: 6px 14px;
    color: {TEXT_PRIMARY};
}}
QPushButton:hover, QToolButton[flat="false"]:hover {{ background: #30303a; }}
QPushButton:pressed {{ background: #1e1e24; }}
QPushButton:disabled {{ color: {TEXT_FADED}; background: #1e1e22; border-color: #2a2a30; }}
QPushButton[class="accent"] {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton[class="accent"]:hover {{ background: {ACCENT_HOVER}; }}
QPushButton[class="accent"]:pressed {{ background: {ACCENT_DOWN}; }}
QPushButton[class="audio"] {{
    background: {AUDIO_BG};
    border: 1px solid {AUDIO_BORDER};
    color: {AUDIO_TEXT};
    font-weight: 600;
}}
QPushButton[class="audio"]:hover {{ background: {AUDIO_HOVER}; }}
QPushButton[class="audio"]:pressed {{ background: #16273d; }}

QToolButton {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 5px 10px;
    color: {TEXT_SECONDARY};
}}
QToolButton:hover {{ background: #26262c; color: {TEXT_PRIMARY}; }}
QToolButton:pressed {{ background: #1e1e24; }}
QToolButton:disabled {{ color: {TEXT_FADED}; }}
QToolButton[class="accent"] {{
    background: {ACCENT};
    color: #ffffff;
    font-weight: 600;
    padding: 6px 14px;
}}
QToolButton[class="accent"]:hover {{ background: {ACCENT_HOVER}; }}
QToolButton[class="audio"] {{
    background: {AUDIO_BG};
    border: 1px solid {AUDIO_BORDER};
    color: {AUDIO_TEXT};
    font-weight: 600;
    padding: 6px 14px;
}}
QToolButton[class="audio"]:hover {{ background: {AUDIO_HOVER}; }}

/* --- pola tekstowe --- */
QLineEdit, QSpinBox, QComboBox {{
    background: {INPUT_BG};
    border: 1px solid {INPUT_BORDER};
    border-radius: 6px;
    padding: 6px 8px;
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1px solid {ACCENT};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {TEXT_FADED}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {TEXT_SECONDARY};
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: {PANEL_BG};
    border: 1px solid {INPUT_BORDER};
    border-radius: 6px;
    selection-background-color: #30303a;
    selection-color: {TEXT_PRIMARY};
    color: {TEXT_PRIMARY};
    outline: none;
}}

/* --- checkbox --- */
QCheckBox {{ spacing: 8px; color: {TEXT_PRIMARY}; }}
QCheckBox::indicator {{
    width: 17px; height: 17px;
    border: 1px solid {INPUT_BORDER};
    border-radius: 4px;
    background: {INPUT_BG};
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}

/* --- lista kafelków --- */
QListView#CardList {{
    background: transparent;
    border: none;
}}
QListView#CardList::item {{ background: transparent; border: none; }}

/* --- baner --- */
QFrame#Banner {{ border-radius: 8px; }}
QFrame#Banner[kind="error"] {{
    background: {BANNER_ERROR_BG};
    border: 1px solid {BANNER_ERROR_BORDER};
}}
QFrame#Banner[kind="warn"] {{
    background: {BANNER_WARN_BG};
    border: 1px solid {BANNER_WARN_BORDER};
}}
QFrame#Banner[kind="info"] {{
    background: {BANNER_INFO_BG};
    border: 1px solid {BANNER_INFO_BORDER};
}}
QLabel#BannerMsg {{ color: {TEXT_PRIMARY}; background: transparent; }}
QLabel#EmptyLabel {{
    color: {TEXT_SECONDARY};
    background: transparent;
    font-size: 11pt;
}}

/* --- ustawienia --- */
QScrollArea {{ border: none; background: transparent; }}
QGroupBox {{
    border: 1px solid #2a2a32;
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 10px;
    background: {PANEL_BG};
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 4px;
    color: {TEXT_SECONDARY};
}}
QLabel#Hint {{
    color: {TEXT_FADED};
    font-size: 8pt;
    background: transparent;
}}
QLabel#ToolOk {{ color: {OK}; background: transparent; }}
QLabel#ToolMissing {{ color: {ERR}; background: transparent; }}
QLabel#AboutText {{
    color: {TEXT_SECONDARY};
    background: transparent;
}}

/* --- scrollbary --- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px 2px 2px 0;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: #3a3a44;
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #4a4a55; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ height: 0; }}

/* --- reszta --- */
QMenu {{
    background: {PANEL_BG};
    border: 1px solid {INPUT_BORDER};
    border-radius: 8px;
    padding: 5px;
}}
QMenu::item {{
    padding: 6px 22px;
    border-radius: 5px;
    color: {TEXT_PRIMARY};
}}
QMenu::item:selected {{ background: #30303a; }}
QMenu::separator {{ height: 1px; background: #2e2e36; margin: 4px 8px; }}
QToolTip {{
    background: #26262c;
    color: {TEXT_PRIMARY};
    border: 1px solid #3a3a44;
    border-radius: 4px;
    padding: 5px 7px;
}}
"""


def apply_theme(app: QApplication) -> None:
    """Fusion + ciemna paleta bazowa + QSS. Wywołać raz, przed show()."""
    app.setStyle("Fusion")

    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(WINDOW_BG))
    pal.setColor(QPalette.WindowText, QColor(TEXT_PRIMARY))
    pal.setColor(QPalette.Base, QColor(INPUT_BG))
    pal.setColor(QPalette.AlternateBase, QColor(PANEL_BG))
    pal.setColor(QPalette.Text, QColor(TEXT_PRIMARY))
    pal.setColor(QPalette.Button, QColor(CARD_BG))
    pal.setColor(QPalette.ButtonText, QColor(TEXT_PRIMARY))
    pal.setColor(QPalette.BrightText, QColor(ACCENT))
    pal.setColor(QPalette.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, QColor("#26262c"))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT_PRIMARY))
    pal.setColor(QPalette.PlaceholderText, QColor(TEXT_FADED))
    pal.setColor(QPalette.Link, QColor("#5aa7ff"))
    for role in (QPalette.Disabled,):
        pal.setColor(role, QPalette.Text, QColor(TEXT_FADED))
        pal.setColor(role, QPalette.ButtonText, QColor(TEXT_FADED))
        pal.setColor(role, QPalette.WindowText, QColor(TEXT_FADED))
    app.setPalette(pal)
    app.setStyleSheet(QSS)
