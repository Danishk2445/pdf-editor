"""The editing canvas: a QGraphicsScene of pages plus the view that drives it.

Scene units are PDF points.  ``PdfView`` owns zoom, panning, page layout modes
and hands raw mouse input to whichever :class:`~pdfeditor.tools.Tool` is active.
"""

from __future__ import annotations

from dataclasses import dataclass

import fitz
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QCursor, QFont, QKeySequence,
                           QPainter, QPen, QTransform)
from PySide6.QtWidgets import (QApplication, QGraphicsScene, QGraphicsView,
                               QPlainTextEdit, QRubberBand)

from . import imageops, textops
from .items import (Draft, ObjectItem, ObjectRef, OverlayItem, PageItem, frect,
                    qrect)

GAP = 16.0            # points between pages
MARGIN = 26.0
ZOOM_MIN, ZOOM_MAX = 0.08, 12.0
ZOOM_STEPS = [0.10, 0.15, 0.25, 0.33, 0.5, 0.667, 0.75, 1.0, 1.25, 1.5,
              1.75, 2.0, 2.5, 3.0, 4.0, 6.0, 8.0]

LAYOUT_CONTINUOUS = "continuous"
LAYOUT_SINGLE = "single"
LAYOUT_FACING = "facing"


@dataclass
class PageEvent:
    """A mouse event already resolved onto a page."""
    page: int
    pos: QPointF            # page coordinates (points)
    scene: QPointF
    screen: QPointF
    modifiers: Qt.KeyboardModifiers
    buttons: Qt.MouseButtons
    count: int = 1

    @property
    def shift(self) -> bool:
        return bool(self.modifiers & Qt.ShiftModifier)

    @property
    def ctrl(self) -> bool:
        return bool(self.modifiers & Qt.ControlModifier)

    @property
    def alt(self) -> bool:
        return bool(self.modifiers & Qt.AltModifier)

    def fpoint(self) -> fitz.Point:
        return fitz.Point(self.pos.x(), self.pos.y())


# ------------------------------------------------------------------ text cache
class TextCache:
    """Per-page :class:`textops.PageText`, dropped when the document changes."""

    def __init__(self, document):
        self.document = document
        self._rev = -1
        self._store: dict[int, textops.PageText] = {}

    def get(self, index: int) -> textops.PageText | None:
        if not self.document.is_open:
            return None
        if self.document.revision != self._rev:
            self._rev = self.document.revision
            self._store.clear()
        if index not in self._store:
            try:
                self._store[index] = textops.PageText(self.document.page(index))
            except Exception:
                return None
        return self._store[index]

    def drop(self, index: int | None = None):
        if index is None:
            self._store.clear()
        else:
            self._store.pop(index, None)


# ----------------------------------------------------------------------- scene
class PdfScene(QGraphicsScene):
    def __init__(self, document, renderer, palette, parent=None):
        super().__init__(parent)
        self.document = document
        self.renderer = renderer
        self.pal = palette
        self.layout_mode = LAYOUT_CONTINUOUS
        self.pages: list[PageItem] = []
        self.overlays: list[OverlayItem] = []
        self._objects: dict[int, list[ObjectItem]] = {}
        self._objects_rev = -1
        self.setBackgroundBrush(QBrush(QColor(palette.workspace)))

    # ---------------------------------------------------------------- build
    def rebuild(self):
        self.clearSelection()
        for item in list(self.items()):
            self.removeItem(item)
        self.pages.clear()
        self.overlays.clear()
        self._objects.clear()
        self._objects_rev = -1

        if not self.document.is_open:
            self.setSceneRect(QRectF(0, 0, 10, 10))
            return

        for i in range(self.document.page_count):
            r = self.document.page_rect(i)
            item = PageItem(i, QRectF(0, 0, r.width, r.height),
                            self.renderer, self.pal)
            self.addItem(item)
            self.pages.append(item)
            self.overlays.append(OverlayItem(item, self.pal))
        self.relayout()

    def relayout(self):
        if not self.pages:
            return
        x = y = MARGIN
        widest = max(p.page_rect().width() for p in self.pages)

        if self.layout_mode == LAYOUT_FACING:
            i = 0
            while i < len(self.pages):
                left = self.pages[i]
                right = self.pages[i + 1] if i + 1 < len(self.pages) else None
                # page 1 sits alone on the right, like a book cover
                if i == 0:
                    total = left.page_rect().width()
                    left.setPos(MARGIN + widest + GAP / 2, y)
                    row_h = left.page_rect().height()
                    i += 1
                else:
                    lw = left.page_rect().width()
                    left.setPos(MARGIN + widest - lw, y)
                    row_h = left.page_rect().height()
                    if right is not None:
                        right.setPos(MARGIN + widest + GAP, y)
                        row_h = max(row_h, right.page_rect().height())
                    i += 2
                y += row_h + GAP
            width = MARGIN * 2 + widest * 2 + GAP
        else:
            for p in self.pages:
                pr = p.page_rect()
                p.setPos(MARGIN + (widest - pr.width()) / 2, y)
                y += pr.height() + GAP
            width = MARGIN * 2 + widest

        for i, ov in enumerate(self.overlays):
            ov.refresh(self.pages[i].page_rect())

        self.setSceneRect(0, 0, width, y - GAP + MARGIN)

    def sync_sizes(self):
        """Page sizes changed (rotation, crop) - resize items and re-lay out."""
        if len(self.pages) != self.document.page_count:
            self.rebuild()
            return
        for i, item in enumerate(self.pages):
            r = self.document.page_rect(i)
            item.set_size(r.width, r.height)
        self.relayout()

    # --------------------------------------------------------------- lookup
    def page_item(self, index: int) -> PageItem | None:
        return self.pages[index] if 0 <= index < len(self.pages) else None

    def overlay(self, index: int) -> OverlayItem | None:
        return self.overlays[index] if 0 <= index < len(self.overlays) else None

    def page_at(self, scene_pos: QPointF):
        """(index, page-local point).  Falls back to the nearest page."""
        for item in self.pages:
            r = QRectF(item.pos(), item.page_rect().size())
            if r.contains(scene_pos):
                return item.index, item.mapFromScene(scene_pos)
        if not self.pages:
            return None, None
        best = min(self.pages,
                   key=lambda it: _dist(QRectF(it.pos(), it.page_rect().size()),
                                        scene_pos))
        return best.index, best.mapFromScene(scene_pos)

    def clear_transient(self):
        for ov in self.overlays:
            ov.clear_transient()

    def clear_selection_marks(self):
        for ov in self.overlays:
            ov.selection = []
            ov.update()

    # -------------------------------------------------------------- objects
    def object_items(self, index: int) -> list[ObjectItem]:
        return self._objects.get(index, [])

    def clear_objects(self, index: int | None = None):
        targets = ([index] if index is not None
                   else list(self._objects.keys()))
        for i in targets:
            for item in self._objects.pop(i, []):
                if item.scene() is self:
                    self.removeItem(item)

    def build_objects(self, index: int, on_moved, on_activated,
                      kinds=("annot", "image", "widget")) -> list[ObjectItem]:
        """Create grab handles for everything editable on one page."""
        if self.document.revision != self._objects_rev:
            self.clear_objects()
            self._objects_rev = self.document.revision
        if index in self._objects:
            return self._objects[index]

        page_item = self.page_item(index)
        if page_item is None:
            return []
        items: list[ObjectItem] = []
        try:
            page = self.document.page(index)
        except Exception:
            return []

        if "annot" in kinds:
            for annot in page.annots():
                try:
                    ref = ObjectRef("annot", index, annot.xref,
                                    _annot_label(annot), annot.type[1] or "")
                    it = ObjectItem(ref, qrect(annot.rect), self.pal)
                    items.append(it)
                except Exception:
                    continue
        if "widget" in kinds:
            for w in page.widgets():
                try:
                    ref = ObjectRef("widget", index, w.xref,
                                    w.field_name or "Field",
                                    w.field_type_string,
                                    {"type": w.field_type})
                    it = ObjectItem(ref, qrect(w.rect), self.pal)
                    items.append(it)
                except Exception:
                    continue
        if "image" in kinds:
            blank = {info[0] for info in page.get_images(full=True)
                     if imageops.is_blank(info)}
            for xref, r, matrix, copies in imageops.placements(page):
                if xref in blank or not imageops.is_grabbable(page, r):
                    continue
                # Carry the composed transform and the number of copies over
                # to the mover: working them out again means decoding every
                # image on the page, which on a big file is seconds.
                ref = ObjectRef("image", index, xref, "Image",
                                data={"rect": tuple(r),
                                      "matrix": tuple(matrix),
                                      "spots": copies})
                items.append(ObjectItem(ref, qrect(r), self.pal))

        for it in items:
            it.setParentItem(page_item)
            it.moved.connect(on_moved)
            it.activated.connect(on_activated)
        self._objects[index] = items
        return items

    def set_objects_interactive(self, enabled: bool):
        for items in self._objects.values():
            for it in items:
                it.setEnabled(enabled)
                it.setVisible(enabled)


def _annot_label(annot) -> str:
    name = (annot.type[1] or "Annotation").replace("Annot", "")
    info = annot.info or {}
    return info.get("title") or name or "Annotation"


def _dist(rect: QRectF, pt: QPointF) -> float:
    dx = max(rect.left() - pt.x(), 0, pt.x() - rect.right())
    dy = max(rect.top() - pt.y(), 0, pt.y() - rect.bottom())
    return dx * dx + dy * dy


# ------------------------------------------------------------------ inline box
class InlineEditor(QPlainTextEdit):
    """Floating text box used to retype a line straight on the page."""

    committed = Signal(str)
    cancelled = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setFrameStyle(0)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.single_line = True
        self.text_px = 12
        self.hide()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
            return
        enter = event.key() in (Qt.Key_Return, Qt.Key_Enter)
        if enter and (self.single_line or event.modifiers() & Qt.ControlModifier):
            self.committed.emit(self.toPlainText())
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        if self.isVisible():
            self.committed.emit(self.toPlainText())


# ------------------------------------------------------------------------ view
class PdfView(QGraphicsView):
    page_changed = Signal(int)
    zoom_changed = Signal(float)
    status = Signal(str)
    selection_changed = Signal()
    context_requested = Signal(object, QPointF)   # PageEvent, global pos

    def __init__(self, document, renderer, palette, parent=None):
        super().__init__(parent)
        self.document = document
        self.renderer = renderer
        self.pal = palette
        self.scene_ = PdfScene(document, renderer, palette, self)
        self.setScene(self.scene_)
        self.text_cache = TextCache(document)

        self.setRenderHints(QPainter.Antialiasing |
                            QPainter.SmoothPixmapTransform |
                            QPainter.TextAntialiasing)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.NoAnchor)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)

        self.tool = None
        self.zoom = 1.0
        self.fit_mode = "width"
        self._current_page = 0
        self._panning = False
        self._pan_origin = QPointF()
        self._space_pan = False
        self._pending_fit = True

        self.editor = InlineEditor(self.viewport())
        self._editor_connected = False
        # Keep the box hugging the text as it is retyped.
        self.editor.textChanged.connect(self._reposition_editor)

        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(40)
        self._scroll_timer.timeout.connect(self._update_current_page)
        self.verticalScrollBar().valueChanged.connect(
            lambda *_: self._scroll_timer.start())

    # ------------------------------------------------------------- document
    def reload(self, keep_view: bool = False):
        anchor = self._current_page
        centre = self._viewport_centre_page_offset() if keep_view else None
        self.scene_.rebuild()
        if self._pending_fit or not keep_view:
            self.apply_fit()
            self._pending_fit = False
        if keep_view and centre is not None:
            self._restore_page_offset(anchor, centre)
        self._update_current_page()

    def refresh_geometry(self):
        self.scene_.sync_sizes()
        if self.fit_mode:
            self.apply_fit()

    # ----------------------------------------------------------------- tools
    def set_tool(self, tool):
        if self.tool is not None:
            self.tool.deactivate()
        self.cancel_inline_edit()
        self.scene_.clear_transient()
        self.tool = tool
        if tool is not None:
            tool.activate()
            self.viewport().setCursor(tool.cursor)
            self.setDragMode(QGraphicsView.RubberBandDrag if tool.rubber_band
                             else QGraphicsView.NoDrag)
            self.scene_.set_objects_interactive(tool.wants_objects)

    # ----------------------------------------------------------------- zoom
    def set_zoom(self, value: float, anchor: QPointF | None = None,
                 remember_fit: bool = False):
        value = max(ZOOM_MIN, min(ZOOM_MAX, value))
        if abs(value - self.zoom) < 1e-6:
            return
        if anchor is None:
            anchor = QPointF(self.viewport().rect().center())
        before = self.mapToScene(anchor.toPoint())
        self.zoom = value
        self.setTransform(QTransform.fromScale(value, value))
        after = self.mapToScene(anchor.toPoint())
        delta = after - before
        self.translate(delta.x(), delta.y())
        if not remember_fit:
            self.fit_mode = None
        self.zoom_changed.emit(value)
        self._reposition_editor()

    def zoom_in(self):
        for s in ZOOM_STEPS:
            if s > self.zoom + 1e-4:
                self.set_zoom(s)
                return
        self.set_zoom(min(ZOOM_MAX, self.zoom * 1.25))

    def zoom_out(self):
        for s in reversed(ZOOM_STEPS):
            if s < self.zoom - 1e-4:
                self.set_zoom(s)
                return
        self.set_zoom(max(ZOOM_MIN, self.zoom / 1.25))

    def set_fit(self, mode: str | None):
        self.fit_mode = mode
        self.apply_fit()

    def apply_fit(self):
        if not self.scene_.pages:
            return
        item = self.scene_.page_item(self._current_page) or self.scene_.pages[0]
        pr = item.page_rect()
        vw = self.viewport().width() - 24
        vh = self.viewport().height() - 24
        if vw <= 0 or vh <= 0:
            return
        if self.fit_mode == "width":
            span = (pr.width() * 2 + GAP if self.scene_.layout_mode == LAYOUT_FACING
                    else pr.width())
            z = vw / max(span + MARGIN, 1)
        elif self.fit_mode == "page":
            z = min(vw / max(pr.width(), 1), vh / max(pr.height(), 1))
        elif self.fit_mode == "actual":
            z = 1.0
        else:
            return
        keep = self.fit_mode
        self.set_zoom(z, remember_fit=True)
        self.fit_mode = keep

    # ------------------------------------------------------------ navigation
    def goto_page(self, index: int, top: bool = True):
        item = self.scene_.page_item(index)
        if item is None:
            return
        if self.scene_.layout_mode == LAYOUT_SINGLE:
            self._show_single(index)
        r = QRectF(item.pos(), item.page_rect().size())
        if top:
            self.centerOn(r.center().x(), r.top() + self.viewport().height()
                          / (2 * self.zoom) - 8)
        else:
            self.centerOn(r.center())
        self._current_page = index
        self.page_changed.emit(index)

    def reveal(self, index: int, rect: fitz.Rect, margin: float = 60.0):
        item = self.scene_.page_item(index)
        if item is None:
            return
        scene_r = QRectF(item.mapToScene(qrect(rect).topLeft()),
                         item.mapToScene(qrect(rect).bottomRight()))
        view_r = self.mapToScene(self.viewport().rect()).boundingRect()
        if not view_r.adjusted(margin, margin, -margin, -margin).contains(scene_r):
            self.centerOn(scene_r.center())
        self._current_page = index
        self.page_changed.emit(index)

    def _show_single(self, index: int):
        for i, p in enumerate(self.scene_.pages):
            p.setVisible(i == index)

    def set_layout_mode(self, mode: str):
        self.scene_.layout_mode = mode
        for p in self.scene_.pages:
            p.setVisible(True)
        self.scene_.relayout()
        if mode == LAYOUT_SINGLE:
            self._show_single(self._current_page)
        self.apply_fit()
        self.goto_page(self._current_page)

    @property
    def current_page(self) -> int:
        return self._current_page

    def _update_current_page(self):
        if not self.scene_.pages:
            return
        centre = self.mapToScene(self.viewport().rect().center())
        best, best_d = self._current_page, 1e18
        for item in self.scene_.pages:
            if not item.isVisible():
                continue
            r = QRectF(item.pos(), item.page_rect().size())
            d = abs(r.center().y() - centre.y())
            if d < best_d:
                best, best_d = item.index, d
        if best != self._current_page:
            self._current_page = best
            self.page_changed.emit(best)

    def _viewport_centre_page_offset(self):
        item = self.scene_.page_item(self._current_page)
        if item is None:
            return None
        centre = self.mapToScene(self.viewport().rect().center())
        return item.mapFromScene(centre)

    def _restore_page_offset(self, index: int, offset: QPointF):
        item = self.scene_.page_item(index)
        if item is None:
            return
        self.centerOn(item.mapToScene(offset))

    # --------------------------------------------------------------- events
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fit_mode:
            QTimer.singleShot(0, self.apply_fit)
        self._reposition_editor()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                factor = 1.0015 ** delta
                self.set_zoom(self.zoom * factor,
                              QPointF(event.position()))
            event.accept()
            return
        if event.modifiers() & Qt.ShiftModifier:
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - event.angleDelta().y())
            event.accept()
            return
        super().wheelEvent(event)

    def _make_event(self, event, count: int = 1) -> PageEvent | None:
        scene_pos = self.mapToScene(event.position().toPoint())
        index, pos = self.scene_.page_at(scene_pos)
        if index is None:
            return None
        return PageEvent(index, pos, scene_pos,
                         QPointF(event.globalPosition()),
                         event.modifiers(), event.buttons(), count)

    def mousePressEvent(self, event):
        self.setFocus()
        if event.button() == Qt.MiddleButton or self._space_pan:
            self._begin_pan(event)
            return
        if event.button() == Qt.RightButton:
            return                      # the menu is raised by contextMenuEvent
        if self.tool is not None:
            pe = self._make_event(event)
            if pe is not None and self.tool.press(pe):
                event.accept()
                return
        super().mousePressEvent(event)

    def contextMenuEvent(self, event):
        """Raise the page menu here rather than off the right-button press.

        Qt makes one of these per right-click and delivers it *after* the press
        handler returns.  A menu opened during the press therefore finishes
        first, and this event then lands on whatever the chosen action put
        under the pointer - the inline editor - which answers with its own
        Undo/Redo menu and takes the focus, so the edit box hides again.
        """
        if self.editor.isVisible() and self.editor.geometry().contains(event.pos()):
            super().contextMenuEvent(event)         # the box keeps its own menu
            return
        scene_pos = self.mapToScene(event.pos())
        index, pos = self.scene_.page_at(scene_pos)
        if index is None:
            return
        where = QPointF(event.globalPos())
        pe = PageEvent(index, pos, scene_pos, where,
                       event.modifiers(), Qt.RightButton, 1)
        event.accept()
        self.context_requested.emit(pe, where)

    def mouseMoveEvent(self, event):
        if self._panning:
            delta = event.position() - self._pan_origin
            self._pan_origin = QPointF(event.position())
            self.horizontalScrollBar().setValue(
                int(self.horizontalScrollBar().value() - delta.x()))
            self.verticalScrollBar().setValue(
                int(self.verticalScrollBar().value() - delta.y()))
            return
        if self.tool is not None:
            pe = self._make_event(event)
            if pe is not None:
                if event.buttons() & Qt.LeftButton:
                    if self.tool.move(pe):
                        event.accept()
                        return
                else:
                    self.tool.hover(pe)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning and event.button() in (Qt.MiddleButton, Qt.LeftButton):
            self._end_pan()
            return
        if self.tool is not None:
            pe = self._make_event(event)
            if pe is not None and self.tool.release(pe):
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.tool is not None:
            pe = self._make_event(event, count=2)
            if pe is not None and self.tool.double(pe):
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_pan = True
            self.viewport().setCursor(Qt.OpenHandCursor)
            event.accept()
            return
        if self.tool is not None and self.tool.key(event):
            event.accept()
            return
        if event.key() == Qt.Key_Escape:
            self.cancel_inline_edit()
            if self.tool is not None:
                self.tool.cancel()
            self.scene_.clearSelection()
            event.accept()
            return
        if event.key() == Qt.Key_PageDown:
            self.goto_page(min(self._current_page + 1,
                               self.document.page_count - 1))
            event.accept()
            return
        if event.key() == Qt.Key_PageUp:
            self.goto_page(max(self._current_page - 1, 0))
            event.accept()
            return
        if event.key() == Qt.Key_Home and event.modifiers() & Qt.ControlModifier:
            self.goto_page(0)
            event.accept()
            return
        if event.key() == Qt.Key_End and event.modifiers() & Qt.ControlModifier:
            self.goto_page(self.document.page_count - 1)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_pan = False
            if not self._panning and self.tool is not None:
                self.viewport().setCursor(self.tool.cursor)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def _begin_pan(self, event):
        self._panning = True
        self._pan_origin = QPointF(event.position())
        self.viewport().setCursor(Qt.ClosedHandCursor)

    def _end_pan(self):
        self._panning = False
        cursor = (Qt.OpenHandCursor if self._space_pan else
                  (self.tool.cursor if self.tool else Qt.ArrowCursor))
        self.viewport().setCursor(cursor)

    # -------------------------------------------------------- inline editing
    def begin_inline_edit(self, index: int, rect: fitz.Rect, text: str,
                          font_size: float, on_commit, on_cancel=None,
                          multiline: bool = False, align: int = 0,
                          color: str = "#111111"):
        item = self.scene_.page_item(index)
        if item is None:
            return
        self.cancel_inline_edit()
        ed = self.editor
        self._edit_anchor = (index, fitz.Rect(rect))
        self._edit_commit = on_commit
        self._edit_cancel = on_cancel
        ed.single_line = not multiline
        ed.blockSignals(True)
        ed.setPlainText(text)
        ed.blockSignals(False)

        # Scene units are PDF points and the view transform is a plain scale,
        # so the on-screen em size is just the point size times the zoom.  It
        # goes in the style sheet rather than through setFont(): a style sheet
        # re-polishes the widget and the application-wide QSS font would win.
        ed.text_px = max(9, round(font_size * self.zoom))
        ed.setStyleSheet(
            f"QPlainTextEdit{{background:{self.pal.panel};color:{color};"
            f"border:2px solid {self.pal.accent};border-radius:3px;"
            f"padding:1px 3px;font-size:{ed.text_px}px;}}")
        ed.show()
        self._reposition_editor()      # needs to be visible to size itself
        ed.setFocus()
        cur = ed.textCursor()
        # A paragraph that overflows its box should still be read from the top;
        # only a single line wants the caret waiting at the end.
        cur.movePosition(cur.MoveOperation.End if multiline is False
                         else cur.MoveOperation.Start)
        ed.setTextCursor(cur)
        ed.ensureCursorVisible()

        self._disconnect_editor()
        ed.committed.connect(self._finish_inline_edit)
        ed.cancelled.connect(self.cancel_inline_edit)
        self._editor_connected = True

    def _reposition_editor(self):
        """Sit the edit box exactly over the text it is replacing."""
        anchor = getattr(self, "_edit_anchor", None)
        if not anchor or not self.editor.isVisible():
            return
        index, rect = anchor
        item = self.scene_.page_item(index)
        if item is None:
            return
        ed = self.editor
        tl = self.mapFromScene(item.mapToScene(QPointF(rect.x0, rect.y0)))
        br = self.mapFromScene(item.mapToScene(QPointF(rect.x1, rect.y1)))

        pad = 10
        # What the widget spends on itself before a glyph is drawn: the 2px
        # border and 1px padding from the style sheet, plus the document's own
        # margin.  Guessing at this leaves a multi-line box a few pixels short,
        # which scrolls the paragraph and hides its first line.
        chrome = 2 * (2 + 1 + ed.document().documentMargin())

        # Wide enough for the replacement, not just for what was there before.
        metrics = ed.fontMetrics()
        lines = ed.toPlainText().split("\n") or [""]
        typed = max(metrics.horizontalAdvance(t) for t in lines) + chrome + pad
        w = max(110.0, br.x() - tl.x() + pad * 2, typed)
        line_h = metrics.lineSpacing()
        if ed.single_line:
            h = max(line_h + chrome, br.y() - tl.y() + pad)
        else:
            h = max(br.y() - tl.y() + pad, min(len(lines), 24) * line_h + chrome)

        vp = self.viewport().rect()
        x = min(max(0.0, tl.x() - pad / 2), max(0.0, vp.width() - w))
        y = min(max(0.0, tl.y() - pad / 2), max(0.0, vp.height() - h))
        ed.setGeometry(int(x), int(y), int(min(w, vp.width())),
                       int(min(h, vp.height())))

    def hideEvent(self, event):
        # On the way out, drop the edit box before it loses focus - committing
        # into a window that is being destroyed goes badly.
        self._hide_editor()
        super().hideEvent(event)

    def _finish_inline_edit(self, text: str):
        cb = getattr(self, "_edit_commit", None)
        self._hide_editor()
        if cb:
            cb(text)

    def cancel_inline_edit(self):
        cb = getattr(self, "_edit_cancel", None)
        was = self.editor.isVisible()
        self._hide_editor()
        if was and cb:
            cb()

    def _disconnect_editor(self):
        if not self._editor_connected:
            return
        try:
            self.editor.committed.disconnect(self._finish_inline_edit)
            self.editor.cancelled.disconnect(self.cancel_inline_edit)
        except (RuntimeError, TypeError):
            pass
        self._editor_connected = False

    def _hide_editor(self):
        self._edit_commit = None
        self._edit_cancel = None
        self._edit_anchor = None
        self._disconnect_editor()
        self.editor.hide()
        self.setFocus()

    # ---------------------------------------------------------------- paint
    def drawBackground(self, painter: QPainter, rect: QRectF):
        painter.fillRect(rect, QColor(self.pal.workspace))
