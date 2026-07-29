"""QGraphicsItems that make up the editing canvas.

The scene works in PDF points, so one scene unit is one point on the page and
zooming is purely a view transform.  Each page is a :class:`PageItem`; anything
the user can grab (annotations, placed images, form fields) is an
:class:`ObjectItem` parented to its page.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import fitz
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QPainter, QPainterPath, QPen,
                           QPolygonF)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject

HANDLE_PX = 8.0          # on-screen handle size, independent of zoom
FRAME_PX = 1.5
MIN_SIZE = 4.0           # smallest object in points


# --------------------------------------------------------------------- helpers
def qrect(r) -> QRectF:
    r = fitz.Rect(r)
    return QRectF(r.x0, r.y0, r.width, r.height)


def frect(r: QRectF) -> fitz.Rect:
    return fitz.Rect(r.left(), r.top(), r.right(), r.bottom())


def _scale_of(painter: QPainter) -> float:
    t = painter.worldTransform()
    return max(1e-6, (abs(t.m11()) + abs(t.m22())) / 2.0)


# ------------------------------------------------------------------ page item
class PageItem(QGraphicsItem):
    """One rendered page.  Also owns the shadow, border and page label."""

    def __init__(self, index: int, size: QRectF, renderer, palette):
        super().__init__()
        self.index = index
        self._size = QRectF(0, 0, size.width(), size.height())
        self.renderer = renderer
        self.palette = palette
        self.setFlag(QGraphicsItem.ItemUsesExtendedStyleOption, True)
        self.setAcceptHoverEvents(False)
        self.setZValue(0)

    def set_size(self, w: float, h: float):
        self.prepareGeometryChange()
        self._size = QRectF(0, 0, w, h)

    def boundingRect(self) -> QRectF:
        return self._size.adjusted(-1, -1, 5, 5)

    def page_rect(self) -> QRectF:
        return QRectF(self._size)

    def paint(self, painter: QPainter, option, widget=None):
        r = self._size
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # drop shadow
        painter.setPen(Qt.NoPen)
        shadow = QColor(self.palette.shadow)
        shadow.setAlpha(46)
        painter.setBrush(shadow)
        painter.drawRoundedRect(r.adjusted(2.5, 3.0, 4.0, 4.5), 1.5, 1.5)

        painter.setBrush(QColor("#ffffff"))
        painter.drawRect(r)

        lod = option.levelOfDetailFromTransform(painter.worldTransform())
        pm = self.renderer.pixmap(self.index, lod)
        if pm is None or pm.isNull():
            pm = self.renderer.best_available(self.index, lod)
        if pm is not None and not pm.isNull():
            painter.drawPixmap(r, pm, QRectF(pm.rect()))
        else:
            painter.setPen(QPen(QColor(self.palette.page_border), 0))
            painter.setBrush(Qt.NoBrush)
            f = QFont()
            f.setPointSizeF(max(6.0, r.height() / 40))
            painter.setFont(f)
            painter.drawText(r, Qt.AlignCenter, "Loading…")

        pen = QPen(QColor(self.palette.page_border), 0)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(r)


# ---------------------------------------------------------------- overlay item
@dataclass
class Draft:
    """An in-progress drawing the active tool wants painted."""
    kind: str = ""                      # rect | ellipse | line | arrow | ink | marquee | crop | textbox
    points: list = field(default_factory=list)
    color: str = "#2f6fd0"
    fill: str | None = None
    width: float = 2.0
    opacity: float = 1.0
    dashed: bool = False


class OverlayItem(QGraphicsItem):
    """Transient decoration painted above a page: selection, search, drafts."""

    def __init__(self, page_item: PageItem, palette):
        super().__init__(page_item)
        self.palette = palette
        self.setZValue(50)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.selection: list[QRectF] = []
        self.hover: QRectF | None = None
        self.hover_kind = "line"
        self.search: list[QRectF] = []
        self.search_active: QRectF | None = None
        self.draft: Draft | None = None
        self.guides: list[QRectF] = []
        self._bounds = QRectF(page_item.page_rect())

    def boundingRect(self) -> QRectF:
        return self._bounds.adjusted(-40, -40, 40, 40)

    def refresh(self, bounds: QRectF | None = None):
        self.prepareGeometryChange()
        if bounds is not None:
            self._bounds = QRectF(bounds)
        self.update()

    def clear_transient(self):
        self.hover = None
        self.draft = None
        self.update()

    def paint(self, painter: QPainter, option, widget=None):
        scale = _scale_of(painter)
        painter.setRenderHint(QPainter.Antialiasing, True)

        # --- found-text highlights
        if self.search:
            painter.setPen(Qt.NoPen)
            c = QColor(self.palette.warn)
            c.setAlpha(90)
            painter.setBrush(c)
            for r in self.search:
                painter.drawRect(r.adjusted(-0.6, -0.6, 0.6, 0.6))
        if self.search_active is not None:
            c = QColor(self.palette.accent)
            c.setAlpha(120)
            painter.setBrush(c)
            painter.setPen(QPen(QColor(self.palette.accent), 1.2 / scale))
            painter.drawRect(self.search_active.adjusted(-1, -1, 1, 1))

        # --- text selection
        if self.selection:
            painter.setPen(Qt.NoPen)
            c = QColor(self.palette.accent)
            c.setAlpha(78)
            painter.setBrush(c)
            for r in self.selection:
                painter.drawRect(r)

        # --- hovered editable line / block
        if self.hover is not None:
            c = QColor(self.palette.accent)
            pen = QPen(c, 1.2 / scale, Qt.DashLine)
            pen.setDashPattern([4, 3])
            painter.setPen(pen)
            fill = QColor(c)
            fill.setAlpha(26)
            painter.setBrush(fill)
            painter.drawRect(self.hover.adjusted(-1.5, -1.5, 1.5, 1.5))

        for g in self.guides:
            painter.setPen(QPen(QColor(self.palette.accent), 0.8 / scale, Qt.DotLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(g)

        if self.draft is not None:
            self._paint_draft(painter, scale, self.draft)

    # ----------------------------------------------------------- draft shapes
    def _paint_draft(self, painter: QPainter, scale: float, d: Draft):
        pts = d.points
        col = QColor(d.color)
        col.setAlphaF(max(0.05, min(1.0, d.opacity)))
        pen = QPen(col, max(d.width, 0.3))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        if d.dashed:
            pen.setStyle(Qt.DashLine)
            pen.setWidthF(1.4 / scale)
        painter.setPen(pen)
        brush = Qt.NoBrush
        if d.fill:
            fc = QColor(d.fill)
            fc.setAlphaF(max(0.05, min(1.0, d.opacity)))
            brush = QBrush(fc)
        painter.setBrush(brush)

        if d.kind in ("marquee", "crop"):
            if len(pts) < 2:
                return
            r = QRectF(pts[0], pts[-1]).normalized()
            sel = QColor(self.palette.accent)
            painter.setPen(QPen(sel, 1.3 / scale, Qt.DashLine))
            f = QColor(sel)
            f.setAlpha(30)
            painter.setBrush(f)
            painter.drawRect(r)
            if d.kind == "crop":
                painter.setBrush(QColor(0, 0, 0, 90))
                painter.setPen(Qt.NoPen)
                outer = QPainterPath()
                outer.addRect(self._bounds)
                inner = QPainterPath()
                inner.addRect(r)
                painter.drawPath(outer.subtracted(inner))
            return

        if d.kind == "rect" and len(pts) >= 2:
            painter.drawRect(QRectF(pts[0], pts[-1]).normalized())
        elif d.kind == "ellipse" and len(pts) >= 2:
            painter.drawEllipse(QRectF(pts[0], pts[-1]).normalized())
        elif d.kind == "line" and len(pts) >= 2:
            painter.drawLine(pts[0], pts[-1])
        elif d.kind == "arrow" and len(pts) >= 2:
            _draw_arrow(painter, pts[0], pts[-1], d.width)
        elif d.kind == "ink" and len(pts) >= 2:
            path = QPainterPath(pts[0])
            for p in pts[1:]:
                path.lineTo(p)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)
        elif d.kind == "polyline" and len(pts) >= 2:
            painter.setBrush(Qt.NoBrush)
            painter.drawPolyline(QPolygonF(pts))
        elif d.kind == "textbox" and len(pts) >= 2:
            r = QRectF(pts[0], pts[-1]).normalized()
            painter.setPen(QPen(QColor(self.palette.accent), 1.2 / scale, Qt.DashLine))
            painter.setBrush(QColor(255, 255, 255, 40))
            painter.drawRect(r)


def _draw_arrow(painter: QPainter, a: QPointF, b: QPointF, width: float):
    import math
    painter.drawLine(a, b)
    dx, dy = b.x() - a.x(), b.y() - a.y()
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return
    head = max(6.0, width * 3.6)
    ang = math.atan2(dy, dx)
    for side in (-1, 1):
        theta = ang + side * math.radians(152)
        painter.drawLine(b, QPointF(b.x() + head * math.cos(theta),
                                    b.y() + head * math.sin(theta)))


# ----------------------------------------------------------------- object item
@dataclass
class ObjectRef:
    kind: str                 # 'annot' | 'image' | 'widget'
    page: int
    xref: int = 0
    label: str = ""
    subtype: str = ""
    data: dict = field(default_factory=dict)


# handle ids
NONE, MOVE = -1, 8
HANDLES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")
CURSORS = {
    "nw": Qt.SizeFDiagCursor, "se": Qt.SizeFDiagCursor,
    "ne": Qt.SizeBDiagCursor, "sw": Qt.SizeBDiagCursor,
    "n": Qt.SizeVerCursor, "s": Qt.SizeVerCursor,
    "e": Qt.SizeHorCursor, "w": Qt.SizeHorCursor,
}


class ObjectItem(QGraphicsObject):
    """A grabbable PDF object: annotation, embedded image or form widget."""

    moved = Signal(object, QRectF)        # ref, new rect in page coords
    activated = Signal(object)            # double-clicked

    def __init__(self, ref: ObjectRef, rect: QRectF, palette,
                 resizable: bool = True, movable: bool = True):
        super().__init__()
        self.ref = ref
        self.palette = palette
        self.resizable = resizable
        self.movable = movable
        self._rect = QRectF(0, 0, max(rect.width(), MIN_SIZE),
                            max(rect.height(), MIN_SIZE))
        self.setPos(rect.topLeft())
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsFocusable, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(20 if ref.kind != "image" else 15)
        self._drag_handle = NONE
        self._press_scene = QPointF()
        self._press_rect = QRectF()
        self._press_pos = QPointF()
        self._hot = None
        self._scale_hint = 1.0

    # ------------------------------------------------------------- geometry
    def page_rect(self) -> QRectF:
        return QRectF(self.pos(), self._rect.size())

    def set_page_rect(self, r: QRectF):
        self.prepareGeometryChange()
        self.setPos(r.topLeft())
        self._rect = QRectF(0, 0, max(r.width(), MIN_SIZE),
                            max(r.height(), MIN_SIZE))
        self.update()

    def boundingRect(self) -> QRectF:
        m = HANDLE_PX / max(self._scale_hint, 1e-6)
        return self._rect.adjusted(-m, -m, m, m)

    def shape(self) -> QPainterPath:
        p = QPainterPath()
        m = HANDLE_PX / max(self._scale_hint, 1e-6)
        p.addRect(self._rect.adjusted(-m / 2, -m / 2, m / 2, m / 2))
        return p

    # ---------------------------------------------------------------- paint
    def paint(self, painter: QPainter, option, widget=None):
        scale = _scale_of(painter)
        if abs(scale - self._scale_hint) > 0.01:
            self.prepareGeometryChange()
            self._scale_hint = scale
        painter.setRenderHint(QPainter.Antialiasing, True)

        selected = self.isSelected()
        hovered = self._hot is not None or self.isUnderMouse()
        if not (selected or hovered):
            return

        col = QColor(self.palette.accent)
        if self.ref.kind == "widget":
            col = QColor(self.palette.ok)

        pen = QPen(col, (FRAME_PX if selected else 1.0) / scale)
        if not selected:
            pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self._rect)

        if not selected:
            return

        h = HANDLE_PX / scale
        painter.setPen(QPen(col, 1.2 / scale))
        painter.setBrush(QBrush(QColor("#ffffff")))
        for name in (HANDLES if self.resizable else ()):
            c = self._handle_centre(name)
            painter.drawRect(QRectF(c.x() - h / 2, c.y() - h / 2, h, h))

    # --------------------------------------------------------------- handles
    def _handle_centre(self, name: str) -> QPointF:
        r = self._rect
        cx, cy = r.center().x(), r.center().y()
        return {
            "nw": QPointF(r.left(), r.top()), "n": QPointF(cx, r.top()),
            "ne": QPointF(r.right(), r.top()), "e": QPointF(r.right(), cy),
            "se": QPointF(r.right(), r.bottom()), "s": QPointF(cx, r.bottom()),
            "sw": QPointF(r.left(), r.bottom()), "w": QPointF(r.left(), cy),
        }[name]

    def _handle_at(self, pos: QPointF) -> str | None:
        if not self.resizable or not self.isSelected():
            return None
        tol = (HANDLE_PX * 0.85) / max(self._scale_hint, 1e-6)
        for name in HANDLES:
            c = self._handle_centre(name)
            if abs(pos.x() - c.x()) <= tol and abs(pos.y() - c.y()) <= tol:
                return name
        return None

    # ---------------------------------------------------------------- events
    def hoverMoveEvent(self, event):
        name = self._handle_at(event.pos())
        self._hot = name
        if name:
            self.setCursor(CURSORS[name])
        elif self.movable:
            self.setCursor(Qt.SizeAllCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
        self.update()
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self._hot = None
        self.unsetCursor()
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            event.ignore()
            return
        self.setSelected(True)
        self._press_scene = event.scenePos()
        self._press_rect = QRectF(self._rect)
        self._press_pos = QPointF(self.pos())
        name = self._handle_at(event.pos())
        self._drag_handle = name if name else (MOVE if self.movable else NONE)
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_handle == NONE:
            return
        delta = event.scenePos() - self._press_scene
        if self._drag_handle == MOVE:
            self.setPos(self._press_pos + delta)
            self.update()
            return

        r = QRectF(self._press_rect)
        # rect lives at local origin, so translate the delta into local space
        dx, dy = delta.x(), delta.y()
        name = self._drag_handle
        left, top = r.left(), r.top()
        right, bottom = r.right(), r.bottom()
        if "w" in name:
            left += dx
        if "e" in name:
            right += dx
        if "n" in name:
            top += dy
        if "s" in name:
            bottom += dy
        if event.modifiers() & Qt.ShiftModifier and name in ("nw", "ne", "se", "sw"):
            ratio = (self._press_rect.width() /
                     max(self._press_rect.height(), 1e-6))
            w, h = right - left, bottom - top
            if abs(w) / max(abs(h), 1e-6) > ratio:
                h = w / ratio
                bottom = top + h if "s" in name else bottom
                top = bottom - h if "n" in name else top
            else:
                w = h * ratio
                right = left + w if "e" in name else right
                left = right - w if "w" in name else left

        new = QRectF(min(left, right), min(top, bottom),
                     max(abs(right - left), MIN_SIZE),
                     max(abs(bottom - top), MIN_SIZE))
        self.prepareGeometryChange()
        # keep the un-dragged corner anchored in scene space
        shift = new.topLeft()
        self._rect = QRectF(0, 0, new.width(), new.height())
        self.setPos(self._press_pos + shift)
        self.update()

    def mouseReleaseEvent(self, event):
        if self._drag_handle == NONE:
            return
        self._drag_handle = NONE
        moved = (self.pos() != self._press_pos or
                 self._rect.size() != self._press_rect.size())
        if moved:
            self.moved.emit(self.ref, self.page_rect())
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if self.ref.kind == "image":
            # Nothing to open, and an image box often covers a caption or a
            # heading.  Let the click through so double-clicking text still
            # starts editing it.
            event.ignore()
            return
        self.activated.emit(self.ref)
        event.accept()
