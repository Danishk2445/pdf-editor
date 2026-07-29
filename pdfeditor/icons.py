"""Vector icons painted at runtime, so the app ships with no image assets.

Every icon is drawn inside a 24x24 box with round caps and a 1.7pt stroke, which
keeps the set visually consistent.  ``icon(name)`` returns a cached QIcon that
carries a dimmed "disabled" variant too.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap,
                           QPolygonF)

BOX = 24.0
_cache: dict[tuple, QIcon] = {}


# --------------------------------------------------------------------- helpers
def _line(p: QPainterPath, x1, y1, x2, y2):
    p.moveTo(x1, y1)
    p.lineTo(x2, y2)


def _poly(p: QPainterPath, pts, close=False):
    p.moveTo(*pts[0])
    for pt in pts[1:]:
        p.lineTo(*pt)
    if close:
        p.closeSubpath()


def _rect(p: QPainterPath, x, y, w, h, r=0.0):
    if r:
        p.addRoundedRect(QRectF(x, y, w, h), r, r)
    else:
        p.addRect(QRectF(x, y, w, h))


def _ellipse(p: QPainterPath, cx, cy, rx, ry=None):
    p.addEllipse(QPointF(cx, cy), rx, ry if ry is not None else rx)


def _doc_outline(p: QPainterPath, x=5, y=3, w=14, h=18, fold=4.5):
    """The folded-corner page shape shared by the file icons."""
    _poly(p, [(x, y), (x + w - fold, y), (x + w, y + fold),
              (x + w, y + h), (x, y + h)], close=True)
    _poly(p, [(x + w - fold, y), (x + w - fold, y + fold), (x + w, y + fold)])


# ----------------------------------------------------------------- definitions
# Each entry returns (stroke_path, fill_path).  Either may be None.
def _draw(name: str):
    s = QPainterPath()
    f = QPainterPath()

    # ---- file ---------------------------------------------------------------
    if name == "new":
        _doc_outline(s)
        _line(s, 12, 10, 12, 16)
        _line(s, 9, 13, 15, 13)
    elif name == "open":
        _poly(s, [(3, 19), (5.5, 10), (21, 10), (18.5, 19)], close=True)
        _poly(s, [(3, 19), (3, 5), (9, 5), (11, 8), (18, 8), (18, 10)])
    elif name == "save":
        _poly(s, [(4, 4), (17, 4), (20, 7), (20, 20), (4, 20)], close=True)
        _rect(s, 8, 4, 8, 5)
        _rect(s, 7, 13, 10, 7)
    elif name == "save_as":
        _poly(s, [(4, 4), (14, 4), (17, 7), (17, 17), (4, 17)], close=True)
        _rect(s, 7, 4, 6, 4)
        _line(s, 15, 21, 21, 15)
        _poly(s, [(21, 15), (21, 19), (17, 19)])
    elif name == "print":
        _poly(s, [(7, 9), (7, 3), (17, 3), (17, 9)])
        _rect(s, 3, 9, 18, 8, 2)
        _rect(s, 7, 14, 10, 7)
    elif name == "export":
        _doc_outline(s)
        _line(s, 12, 16, 12, 9)
        _poly(s, [(9.5, 11.5), (12, 9), (14.5, 11.5)])
    elif name == "import":
        _doc_outline(s)
        _line(s, 12, 9, 12, 16)
        _poly(s, [(9.5, 13.5), (12, 16), (14.5, 13.5)])

    # ---- history ------------------------------------------------------------
    elif name == "undo":
        s.moveTo(4, 11)
        s.arcTo(QRectF(4, 6, 16, 12), 180, -230)
        _poly(s, [(4, 6), (4, 11.5), (9.5, 11.5)])
    elif name == "redo":
        s.moveTo(20, 11)
        s.arcTo(QRectF(4, 6, 16, 12), 0, 230)
        _poly(s, [(20, 6), (20, 11.5), (14.5, 11.5)])

    # ---- navigation / tools -------------------------------------------------
    elif name == "select":
        _poly(f, [(6, 3), (18, 13), (12.5, 13.6), (15.6, 20), (13, 21.2),
                  (10, 15), (6, 19)], close=True)
    elif name == "hand":
        _poly(s, [(8, 12), (8, 6.5)])
        _poly(s, [(11.3, 11), (11.3, 5)])
        _poly(s, [(14.6, 11), (14.6, 6)])
        _poly(s, [(17.8, 12), (17.8, 9)])
        _poly(s, [(8, 12), (6, 14), (7, 17), (10, 20.5), (14, 21),
                  (17.8, 18), (17.8, 12)])
    elif name == "text_select":
        _poly(s, [(9, 4), (12, 4), (15, 4)])
        _line(s, 12, 4, 12, 20)
        _poly(s, [(9, 20), (12, 20), (15, 20)])
    elif name == "edit_text":
        _poly(s, [(3, 7), (3, 5), (13, 5), (13, 7)])
        _line(s, 8, 5, 8, 15)
        _poly(s, [(6, 15), (8, 15), (10, 15)])
        _poly(s, [(13, 20.5), (20.5, 13), (22, 14.5), (14.5, 22), (12.5, 22.5)],
              close=True)
    elif name == "add_text":
        _poly(s, [(3, 8), (3, 5.5), (15, 5.5), (15, 8)])
        _line(s, 9, 5.5, 9, 18)
        _poly(s, [(6.5, 18), (9, 18), (11.5, 18)])
        _line(s, 18.5, 13, 18.5, 21)
        _line(s, 14.5, 17, 22.5, 17)
    elif name == "note":
        _poly(s, [(4, 4), (20, 4), (20, 14), (13, 14), (8, 19), (8, 14), (4, 14)],
              close=True)
        _line(s, 8, 8, 16, 8)
        _line(s, 8, 11, 13, 11)
    elif name == "ink":
        s.moveTo(4, 17)
        s.cubicTo(7, 8, 10, 20, 13, 12)
        s.cubicTo(15, 6.5, 18, 12, 20, 8)
    elif name == "highlight":
        _poly(s, [(5, 14), (12, 4), (19, 9), (12, 19), (7, 19)], close=True)
        _line(s, 3, 22, 21, 22)
    elif name == "underline":
        _poly(s, [(7, 3), (7, 11)])
        s.arcTo(QRectF(7, 4, 10, 14), 180, 180)
        _line(s, 17, 3, 17, 11)
        _line(s, 5, 21, 19, 21)
    elif name == "strikeout":
        _poly(s, [(7, 4), (7, 10)])
        s.arcTo(QRectF(7, 3, 10, 14), 180, 180)
        _line(s, 17, 4, 17, 10)
        _line(s, 4, 12, 20, 12)
    elif name == "eraser":
        _poly(s, [(9, 20), (3.5, 14.5), (13, 5), (20.5, 12.5), (13, 20)], close=True)
        _line(s, 9, 20, 20.5, 20)
        _line(s, 8.2, 9.8, 15.7, 17.3)
    elif name == "redact":
        _rect(s, 3, 8, 18, 8, 1.5)
        f.addRoundedRect(QRectF(3, 8, 18, 8), 1.5, 1.5)
        _line(s, 5, 4.5, 19, 4.5)
        _line(s, 5, 19.5, 14, 19.5)
    elif name == "whiteout":
        _rect(s, 4, 6, 16, 12, 2)
        _line(s, 4, 18, 20, 6)

    # ---- shapes -------------------------------------------------------------
    elif name == "rect":
        _rect(s, 3.5, 5.5, 17, 13, 1.5)
    elif name == "ellipse":
        _ellipse(s, 12, 12, 8.6, 6.6)
    elif name == "line":
        _line(s, 4, 20, 20, 4)
    elif name == "arrow":
        _line(s, 4, 20, 19, 5)
        _poly(s, [(12, 4.5), (19.5, 4.5), (19.5, 12)])
    elif name == "polygon":
        _poly(s, [(12, 3), (21, 9.5), (17.5, 20), (6.5, 20), (3, 9.5)], close=True)
    elif name == "stamp":
        _poly(s, [(8, 4), (16, 4), (15, 11), (19, 13), (19, 16), (5, 16),
                  (5, 13), (9, 11)], close=True)
        _line(s, 4, 20, 20, 20)
    elif name == "signature":
        s.moveTo(3, 16)
        s.cubicTo(6, 16, 7, 5, 9.5, 5)
        s.cubicTo(12, 5, 9, 17, 12, 17)
        s.cubicTo(14.5, 17, 15, 11, 17, 11)
        s.cubicTo(18.5, 11, 18, 15, 21, 13)
        _line(s, 3, 21, 21, 21)
    elif name == "image":
        _rect(s, 3, 5, 18, 14, 2)
        _ellipse(s, 8.5, 10, 1.9)
        _poly(s, [(4, 17.5), (10, 11.5), (14, 15.5), (16.5, 13), (20, 16.5)])
    elif name == "link":
        s.moveTo(10, 14)
        s.arcTo(QRectF(3.5, 9.5, 9, 9), 130, 180)
        _line(s, 9.5, 14.5, 14.5, 9.5)
        s.moveTo(14, 10)
        s.arcTo(QRectF(11.5, 5.5, 9, 9), -50, 180)
    elif name == "form":
        _rect(s, 3, 5, 18, 14, 2)
        _line(s, 6.5, 10, 11, 10)
        _line(s, 6.5, 14, 15, 14)
    elif name == "check":
        _poly(s, [(4.5, 12.5), (9.5, 18), (19.5, 6)])
    elif name == "measure":
        _rect(s, 2.5, 8, 19, 8, 1.5)
        _line(s, 7, 8, 7, 12)
        _line(s, 12, 8, 12, 13)
        _line(s, 17, 8, 17, 12)

    # ---- view ---------------------------------------------------------------
    elif name == "zoom_in":
        _ellipse(s, 10.5, 10.5, 7)
        _line(s, 15.6, 15.6, 21, 21)
        _line(s, 10.5, 7.5, 10.5, 13.5)
        _line(s, 7.5, 10.5, 13.5, 10.5)
    elif name == "zoom_out":
        _ellipse(s, 10.5, 10.5, 7)
        _line(s, 15.6, 15.6, 21, 21)
        _line(s, 7.5, 10.5, 13.5, 10.5)
    elif name == "fit_width":
        _rect(s, 6, 4, 12, 16, 1.5)
        _line(s, 1.5, 12, 5, 12)
        _poly(s, [(3.5, 10), (1.5, 12), (3.5, 14)])
        _line(s, 19, 12, 22.5, 12)
        _poly(s, [(20.5, 10), (22.5, 12), (20.5, 14)])
    elif name == "fit_page":
        _rect(s, 6.5, 5, 11, 14, 1.5)
        _poly(s, [(2.5, 8), (2.5, 3.5), (7, 3.5)])
        _poly(s, [(21.5, 16), (21.5, 20.5), (17, 20.5)])
    elif name == "rotate_left":
        s.moveTo(5, 9)
        s.arcTo(QRectF(4, 4, 16, 14), 165, -290)
        _poly(s, [(5, 3.5), (5, 9.5), (11, 9.5)])
    elif name == "rotate_right":
        s.moveTo(19, 9)
        s.arcTo(QRectF(4, 4, 16, 14), 15, 290)
        _poly(s, [(19, 3.5), (19, 9.5), (13, 9.5)])
    elif name == "thumbnails":
        for x, y in ((3, 3), (13, 3), (3, 13), (13, 13)):
            _rect(s, x, y, 8, 8, 1.2)
    elif name == "outline":
        for y in (5, 12, 19):
            _ellipse(f, 4.5, y, 1.4)
            _line(s, 8.5, y, 20.5, y)
    elif name == "search":
        _ellipse(s, 10.5, 10.5, 7)
        _line(s, 15.6, 15.6, 21, 21)
    elif name == "properties":
        _ellipse(s, 12, 12, 9)
        _line(s, 12, 11, 12, 17)
        _ellipse(f, 12, 7.6, 1.15)
    elif name == "layers":
        _poly(s, [(12, 3), (21, 8), (12, 13), (3, 8)], close=True)
        _poly(s, [(4.5, 12), (12, 16.2), (19.5, 12)])
        _poly(s, [(4.5, 16), (12, 20.2), (19.5, 16)])
    elif name == "sidebar":
        _rect(s, 3, 4, 18, 16, 2)
        _line(s, 9.5, 4, 9.5, 20)

    # ---- pages --------------------------------------------------------------
    elif name == "page_add":
        _doc_outline(s, 4, 3, 12, 16, 4)
        _line(s, 19, 15, 19, 22)
        _line(s, 15.5, 18.5, 22.5, 18.5)
    elif name == "page_delete":
        _doc_outline(s, 4, 3, 12, 16, 4)
        _line(s, 16, 18.5, 22.5, 18.5)
    elif name == "page_copy":
        _rect(s, 3.5, 3.5, 12, 15, 1.5)
        _rect(s, 8.5, 8.5, 12, 15, 1.5)
    elif name == "page_extract":
        _doc_outline(s, 3, 3, 12, 16, 4)
        _line(s, 15, 12, 22, 12)
        _poly(s, [(19.5, 9.5), (22, 12), (19.5, 14.5)])
    elif name == "trash":
        _poly(s, [(5, 6.5), (6.5, 20.5), (17.5, 20.5), (19, 6.5)])
        _line(s, 3, 6.5, 21, 6.5)
        _poly(s, [(9, 6.5), (9, 3.5), (15, 3.5), (15, 6.5)])
        _line(s, 10, 10, 10, 17)
        _line(s, 14, 10, 14, 17)
    elif name == "reorder":
        for y in (5, 12, 19):
            _line(s, 8, y, 21, y)
            _ellipse(f, 4, y, 1.3)
    elif name == "crop":
        _poly(s, [(6, 2), (6, 18), (22, 18)])
        _poly(s, [(2, 6), (18, 6), (18, 22)])

    # ---- misc ---------------------------------------------------------------
    elif name == "chevron_left":
        _poly(s, [(15, 4), (8, 12), (15, 20)])
    elif name == "chevron_right":
        _poly(s, [(9, 4), (16, 12), (9, 20)])
    elif name == "chevron_down":
        _poly(s, [(5, 9), (12, 16), (19, 9)])
    elif name == "close":
        _line(s, 5.5, 5.5, 18.5, 18.5)
        _line(s, 18.5, 5.5, 5.5, 18.5)
    elif name == "plus":
        _line(s, 12, 5, 12, 19)
        _line(s, 5, 12, 19, 12)
    elif name == "minus":
        _line(s, 5, 12, 19, 12)
    elif name == "settings":
        _ellipse(s, 12, 12, 3.2)
        for i in range(6):
            a = math.radians(i * 60)
            _line(s, 12 + 5.6 * math.cos(a), 12 + 5.6 * math.sin(a),
                  12 + 9.2 * math.cos(a), 12 + 9.2 * math.sin(a))
    elif name == "theme":
        _ellipse(s, 12, 12, 8)
        f.moveTo(12, 4)
        f.arcTo(QRectF(4, 4, 16, 16), 90, -180)
        f.closeSubpath()
    elif name == "lock":
        _rect(s, 4.5, 10, 15, 11, 2)
        s.moveTo(8, 10)
        s.lineTo(8, 7.5)
        s.arcTo(QRectF(8, 2.5, 8, 8), 180, -180)
        s.lineTo(16, 10)
    elif name == "copy":
        _rect(s, 8.5, 3.5, 12, 12, 1.5)
        _poly(s, [(15.5, 18.5), (3.5, 18.5), (3.5, 6.5)])
    elif name == "info":
        _ellipse(s, 12, 12, 9)
        _line(s, 12, 11, 12, 17)
        _ellipse(f, 12, 7.6, 1.15)
    elif name == "warning":
        _poly(s, [(12, 3.5), (22, 20.5), (2, 20.5)], close=True)
        _line(s, 12, 9.5, 12, 15)
        _ellipse(f, 12, 18, 1.1)
    elif name == "grid":
        _rect(s, 3, 3, 18, 18, 2)
        _line(s, 9, 3, 9, 21)
        _line(s, 15, 3, 15, 21)
        _line(s, 3, 9, 21, 9)
        _line(s, 3, 15, 21, 15)
    elif name == "single_page":
        _rect(s, 6, 3, 12, 18, 1.5)
    elif name == "continuous":
        _rect(s, 6, 1, 12, 9, 1.5)
        _rect(s, 6, 12, 12, 9, 1.5)
    elif name == "facing":
        _rect(s, 2, 4, 9.5, 16, 1.5)
        _rect(s, 12.5, 4, 9.5, 16, 1.5)
    return s, f


# ------------------------------------------------------------------ public API
def pixmap(name: str, size: int = 22, color: str = "#1b2330",
           opacity: float = 1.0) -> QPixmap:
    ratio = 2  # render at 2x so icons stay sharp on hidpi screens
    pm = QPixmap(size * ratio, size * ratio)
    pm.setDevicePixelRatio(ratio)
    pm.fill(Qt.transparent)

    stroke, fill = _draw(name)
    if stroke.isEmpty() and fill.isEmpty():
        return pm

    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    # QPainter already applies the pixmap's device pixel ratio, so scale from
    # the 24pt design box into *logical* pixels only.
    painter.scale(size / BOX, size / BOX)
    painter.setOpacity(opacity)

    col = QColor(color)
    if not fill.isEmpty():
        painter.setPen(Qt.NoPen)
        painter.setBrush(col)
        painter.drawPath(fill)
    if not stroke.isEmpty():
        pen = QPen(col, 1.7)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(stroke)
    painter.end()
    return pm


def icon(name: str, color: str = "#1b2330", size: int = 22) -> QIcon:
    key = (name, color, size)
    if key not in _cache:
        ic = QIcon()
        ic.addPixmap(pixmap(name, size, color), QIcon.Normal)
        ic.addPixmap(pixmap(name, size, color, 0.35), QIcon.Disabled)
        _cache[key] = ic
    return _cache[key]


def clear_cache():
    _cache.clear()
