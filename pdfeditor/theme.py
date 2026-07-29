"""Palette + Qt stylesheet.  Light and dark variants of the same design."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str            # window chrome
    panel: str         # docks, toolbars
    panel_alt: str     # grooves, headers
    border: str
    workspace: str     # the area behind the pages
    text: str
    text_muted: str
    accent: str
    accent_hi: str
    accent_soft: str
    hover: str
    danger: str
    ok: str
    warn: str
    page_border: str
    shadow: str


LIGHT = Palette(
    name="light",
    bg="#eef1f5", panel="#f7f8fa", panel_alt="#e6eaf0", border="#ccd3de",
    workspace="#5c6675", text="#1b2330", text_muted="#69727f",
    accent="#2f6fd0", accent_hi="#3b82f6", accent_soft="#dce8fb",
    hover="#e2e8f1", danger="#c0392b", ok="#2e8b57", warn="#c07d16",
    page_border="#9aa3b0", shadow="#39404d",
)

DARK = Palette(
    name="dark",
    bg="#1e2229", panel="#252a33", panel_alt="#2d333d", border="#3a414d",
    workspace="#14171c", text="#e4e8ee", text_muted="#9aa3b2",
    accent="#4a8ee6", accent_hi="#63a2f5", accent_soft="#24354d",
    hover="#323945", danger="#e06c5b", ok="#4cae7a", warn="#d9a441",
    page_border="#4a515e", shadow="#0b0d10",
)

# Colours offered in the annotation colour picker.
SWATCHES = [
    "#000000", "#ffffff", "#c0392b", "#e8590c", "#f2c037",
    "#2f9e44", "#12b886", "#2f6fd0", "#7048e8", "#868e96",
]

HIGHLIGHT_SWATCHES = [
    "#fff35c", "#7bf1a8", "#8fd3ff", "#ffb3d1", "#d0bfff", "#ffc9a0",
]


# --------------------------------------------------------------- colour utils
def hex_to_rgb(value: str) -> tuple[float, float, float]:
    """'#rrggbb' -> (r, g, b) floats in 0..1, the form PyMuPDF expects."""
    if not value:
        return (0.0, 0.0, 0.0)
    value = str(value).lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    try:
        return tuple(int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except (ValueError, IndexError):
        return (0.0, 0.0, 0.0)


def rgb_to_hex(rgb) -> str:
    if rgb is None:
        return "#000000"
    try:
        r, g, b = (max(0.0, min(1.0, float(c))) for c in tuple(rgb)[:3])
    except (TypeError, ValueError):
        return "#000000"
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def srgb_int_to_hex(value: int) -> str:
    """PyMuPDF text spans carry colour as a packed sRGB integer."""
    return "#%06x" % (int(value) & 0xFFFFFF)


def stylesheet(p: Palette) -> str:
    return f"""
* {{ outline: none; }}

QWidget {{
    background: {p.bg};
    color: {p.text};
    font-size: 13px;
}}

QMainWindow::separator {{ background: {p.border}; width: 1px; height: 1px; }}

/* ---- docks -------------------------------------------------------------- */
QDockWidget {{
    titlebar-close-icon: none; titlebar-normal-icon: none;
    font-size: 11px; font-weight: 600;
    color: {p.text_muted};
}}
QDockWidget::title {{
    background: {p.panel_alt};
    padding: 7px 10px;
    border-bottom: 1px solid {p.border};
    text-transform: uppercase;
    letter-spacing: 1px;
}}
QDockWidget > QWidget {{ background: {p.panel}; }}

/* ---- toolbars ----------------------------------------------------------- */
QToolBar {{
    background: {p.panel};
    border: none;
    border-bottom: 1px solid {p.border};
    padding: 4px 6px;
    spacing: 2px;
}}
QToolBar::separator {{
    background: {p.border};
    width: 1px;
    margin: 5px 7px;
}}
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 5px;
    margin: 0px;
    color: {p.text};
}}
QToolButton:hover {{ background: {p.hover}; border-color: {p.border}; }}
QToolButton:pressed {{ background: {p.accent_soft}; }}
QToolButton:checked {{
    background: {p.accent_soft};
    border-color: {p.accent};
    color: {p.accent};
}}
QToolButton:disabled {{ color: {p.text_muted}; }}
QToolButton::menu-indicator {{ image: none; width: 0px; }}

/* ---- menus -------------------------------------------------------------- */
QMenuBar {{ background: {p.panel}; border-bottom: 1px solid {p.border}; }}
QMenuBar::item {{ padding: 6px 10px; background: transparent; border-radius: 5px; }}
QMenuBar::item:selected {{ background: {p.hover}; }}
QMenu {{
    background: {p.panel};
    border: 1px solid {p.border};
    border-radius: 8px;
    padding: 5px;
}}
QMenu::item {{ padding: 6px 26px 6px 22px; border-radius: 5px; }}
QMenu::item:selected {{ background: {p.accent}; color: #ffffff; }}
QMenu::item:disabled {{ color: {p.text_muted}; }}
QMenu::separator {{ height: 1px; background: {p.border}; margin: 5px 8px; }}
QMenu::icon {{ padding-left: 8px; }}

/* ---- inputs ------------------------------------------------------------- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {p.panel_alt};
    border: 1px solid {p.border};
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: {p.accent};
    selection-color: #ffffff;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {p.accent};
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {p.panel};
    border: 1px solid {p.border};
    border-radius: 6px;
    selection-background-color: {p.accent};
    selection-color: #ffffff;
    padding: 4px;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 14px; }}

/* ---- buttons ------------------------------------------------------------ */
QPushButton {{
    background: {p.panel_alt};
    border: 1px solid {p.border};
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 500;
}}
QPushButton:hover {{ background: {p.hover}; }}
QPushButton:pressed {{ background: {p.accent_soft}; }}
QPushButton:disabled {{ color: {p.text_muted}; }}
QPushButton[accent="true"] {{
    background: {p.accent}; color: #ffffff; border-color: {p.accent};
}}
QPushButton[accent="true"]:hover {{ background: {p.accent_hi}; }}

QCheckBox, QRadioButton {{ spacing: 7px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 15px; height: 15px; }}
QCheckBox::indicator {{
    border: 1px solid {p.border}; border-radius: 4px; background: {p.panel_alt};
}}
QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent}; }}

/* ---- lists / trees ------------------------------------------------------ */
QListView, QTreeView, QTreeWidget, QListWidget {{
    background: {p.panel};
    border: none;
    outline: none;
}}
QListView::item, QTreeView::item {{ padding: 3px; border-radius: 5px; }}
QListView::item:hover, QTreeView::item:hover {{ background: {p.hover}; }}
QListView::item:selected, QTreeView::item:selected {{
    background: {p.accent_soft}; color: {p.text};
}}
QHeaderView::section {{
    background: {p.panel_alt}; border: none;
    border-bottom: 1px solid {p.border}; padding: 5px;
}}

/* ---- tabs --------------------------------------------------------------- */
QTabWidget::pane {{ border: none; background: {p.panel}; }}
QTabBar::tab {{
    background: transparent;
    color: {p.text_muted};
    padding: 7px 13px;
    border-bottom: 2px solid transparent;
    font-size: 12px;
}}
QTabBar::tab:hover {{ color: {p.text}; }}
QTabBar::tab:selected {{
    color: {p.accent};
    border-bottom-color: {p.accent};
    font-weight: 600;
}}

/* ---- scrollbars --------------------------------------------------------- */
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0; }}
QScrollBar::handle {{
    background: {p.border}; border-radius: 5px; min-height: 32px; min-width: 32px;
    margin: 2px;
}}
QScrollBar::handle:hover {{ background: {p.text_muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---- misc --------------------------------------------------------------- */
QStatusBar {{
    background: {p.panel};
    border-top: 1px solid {p.border};
    color: {p.text_muted};
}}
QStatusBar::item {{ border: none; }}
QSplitter::handle {{ background: {p.border}; }}
QGroupBox {{
    border: 1px solid {p.border}; border-radius: 8px;
    margin-top: 10px; padding-top: 10px; font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 10px; padding: 0 5px;
    color: {p.text_muted}; font-size: 11px;
}}
QToolTip {{
    background: {p.text}; color: {p.bg};
    border: none; border-radius: 5px; padding: 5px 8px;
}}
QSlider::groove:horizontal {{
    background: {p.panel_alt}; height: 4px; border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {p.accent}; width: 13px; height: 13px;
    margin: -5px 0; border-radius: 7px;
}}
QProgressBar {{
    background: {p.panel_alt}; border: none; border-radius: 4px;
    height: 6px; text-align: center;
}}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 4px; }}
QLabel[muted="true"] {{ color: {p.text_muted}; font-size: 11px; }}
QLabel[heading="true"] {{
    color: {p.text_muted}; font-size: 10px; font-weight: 700;
    letter-spacing: 1px;
}}
QFrame[rule="true"] {{ background: {p.border}; max-height: 1px; border: none; }}
"""
