"""Editing tools.

A tool receives already page-resolved mouse events from :class:`PdfView` and
mutates the document through :meth:`ToolContext.edit`, which wraps
``Document.edit`` so every action lands on the undo stack as one step.
"""

from __future__ import annotations

import math
from contextlib import contextmanager
from dataclasses import dataclass, field

import fitz
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog

from . import fonts, textops
from .items import Draft, ObjectRef, qrect
from .theme import hex_to_rgb
from .view import PageEvent

DRAG_SLOP = 3.0          # scene points before a click becomes a drag


# ------------------------------------------------------------------ tool style
@dataclass
class Style:
    """Everything the inspector can tune, shared by all tools."""
    stroke: str = "#c0392b"
    fill: str | None = None
    width: float = 2.0
    opacity: float = 1.0
    highlight: str = "#fff35c"
    text_color: str = "#000000"
    font_family: str = "Helvetica"
    font_size: float = 12.0
    bold: bool = False
    italic: bool = False
    align: int = 0
    arrow_start: bool = False
    arrow_end: bool = True
    author: str = "PDF Studio"
    redact_fill: str = "#000000"
    shrink_text_to_fit: bool = True

    def font_alias(self) -> str:
        for label, family in fonts.FAMILIES:
            if label == self.font_family:
                return fonts.pick(family, self.bold, self.italic)
        return fonts.pick(fonts.SANS, self.bold, self.italic)

    def stroke_rgb(self):
        return hex_to_rgb(self.stroke)

    def fill_rgb(self):
        return hex_to_rgb(self.fill) if self.fill else None

    def text_rgb(self):
        return hex_to_rgb(self.text_color)


# ---------------------------------------------------------------- tool context
class ToolContext:
    """Services a tool needs, handed to it by the main window."""

    def __init__(self, window):
        self.window = window
        self.style = Style()

    # -- shortcuts -----------------------------------------------------------
    @property
    def document(self):
        return self.window.document

    @property
    def view(self):
        return self.window.view

    @property
    def scene(self):
        return self.window.view.scene_

    @property
    def text_cache(self):
        return self.window.view.text_cache

    def page(self, index: int) -> fitz.Page:
        return self.document.page(index)

    def page_text(self, index: int):
        return self.text_cache.get(index)

    def overlay(self, index: int):
        return self.scene.overlay(index)

    def status(self, message: str, msecs: int = 4000):
        self.window.show_status(message, msecs)

    def set_tool(self, name: str):
        self.window.activate_tool(name)

    # -- mutation ------------------------------------------------------------
    @contextmanager
    def edit(self, label: str, *, geometry: bool = False, page: int | None = None):
        """Run a mutation as one undo step.

        A failure inside the block rolls the document back and surfaces the
        error to the user rather than tearing down the app mid-edit.  An edit
        that declines itself - something this editor knows it cannot do to
        this file - says so in the status bar instead: it is a limitation the
        user just met, not a fault, and a dialog for every attempt grates.
        """
        try:
            with self.document.edit(label):
                yield
        except Exception as exc:
            if getattr(exc, "expected", False):
                self.status(f"{label}: {exc}", 7000)
            else:
                self.window.report_error(label, exc)
            self.after_edit(geometry=geometry, page=page)
            return
        self.after_edit(geometry=geometry, page=page)
        self.status(label)

    def after_edit(self, *, geometry: bool = False, page: int | None = None):
        self.text_cache.drop()
        self.scene.clear_objects()
        if geometry:
            self.view.refresh_geometry()
        self.scene.update()
        self.window.refresh_after_edit()


# ------------------------------------------------------------------ base class
class Tool:
    name = "tool"
    title = "Tool"
    cursor = Qt.ArrowCursor
    wants_objects = False
    rubber_band = False
    inspector = ()          # which inspector sections to show

    def __init__(self, ctx: ToolContext):
        self.ctx = ctx
        self._anchor: QPointF | None = None
        self._page: int | None = None
        self._dragging = False

    # lifecycle
    def activate(self):
        pass

    def deactivate(self):
        self.cancel()

    def cancel(self):
        self._clear_draft()
        self._anchor = None
        self._page = None
        self._dragging = False

    # events - return True to consume
    def press(self, e: PageEvent) -> bool:
        return False

    def move(self, e: PageEvent) -> bool:
        return False

    def release(self, e: PageEvent) -> bool:
        return False

    def hover(self, e: PageEvent):
        pass

    def double(self, e: PageEvent) -> bool:
        return False

    def key(self, event) -> bool:
        return False

    # helpers
    def _draft(self, page: int, **kw):
        ov = self.ctx.overlay(page)
        if ov is not None:
            ov.draft = Draft(**kw)
            ov.update()

    def _clear_draft(self):
        for ov in self.ctx.scene.overlays:
            if ov.draft is not None:
                ov.draft = None
                ov.update()

    def _clear_hover(self):
        for ov in self.ctx.scene.overlays:
            if ov.hover is not None:
                ov.hover = None
                ov.update()

    def _rect(self, a: QPointF, b: QPointF) -> fitz.Rect:
        return fitz.Rect(min(a.x(), b.x()), min(a.y(), b.y()),
                         max(a.x(), b.x()), max(a.y(), b.y()))

    def _moved_enough(self, e: PageEvent) -> bool:
        if self._anchor is None:
            return False
        return (abs(e.pos.x() - self._anchor.x()) > DRAG_SLOP or
                abs(e.pos.y() - self._anchor.y()) > DRAG_SLOP)

    def _finish_annot(self, annot, *, stroke=True, fill=False, border=True):
        s = self.ctx.style
        try:
            colors = {}
            if stroke:
                colors["stroke"] = s.stroke_rgb()
            if fill and s.fill:
                colors["fill"] = s.fill_rgb()
            if colors:
                annot.set_colors(**colors)
            if border:
                annot.set_border(width=s.width)
            annot.set_info(title=s.author)
            annot.set_opacity(s.opacity)
            annot.update(opacity=s.opacity)
        except Exception:
            try:
                annot.update()
            except Exception:
                pass


# ===========================================================================
# Select / move / resize
# ===========================================================================
class SelectTool(Tool):
    name = "select"
    title = "Select"
    cursor = Qt.ArrowCursor
    wants_objects = True
    rubber_band = True
    inspector = ("object",)

    def activate(self):
        self.ctx.window.ensure_objects_for_view()

    def press(self, e: PageEvent) -> bool:
        self.ctx.window.ensure_objects_for_view()
        return False        # let the scene items handle it

    def key(self, event) -> bool:
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            return self.ctx.window.delete_selected_objects()
        if event.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            step = 1.0 if not (event.modifiers() & Qt.ShiftModifier) else 10.0
            dx = -step if event.key() == Qt.Key_Left else (
                step if event.key() == Qt.Key_Right else 0)
            dy = -step if event.key() == Qt.Key_Up else (
                step if event.key() == Qt.Key_Down else 0)
            return self.ctx.window.nudge_selected_objects(dx, dy)
        return False

    def double(self, e: PageEvent) -> bool:
        # double-clicking bare text jumps into the text editor
        pt = self.ctx.page_text(e.page)
        if pt and pt.line_at(e.fpoint()):
            self.ctx.set_tool("edit_text")
            self.ctx.window.tool.begin_edit(e)
            return True
        return False


class HandTool(Tool):
    name = "hand"
    title = "Pan"
    cursor = Qt.OpenHandCursor

    def press(self, e: PageEvent) -> bool:
        view = self.ctx.view
        view._panning = True
        view._pan_origin = view.mapFromGlobal(QCursor.pos()).toPointF()
        view.viewport().setCursor(Qt.ClosedHandCursor)
        return True


# ===========================================================================
# Text selection (copy + markup)
# ===========================================================================
class TextSelectTool(Tool):
    name = "text_select"
    title = "Select Text"
    cursor = Qt.IBeamCursor
    inspector = ("markup",)

    def __init__(self, ctx):
        super().__init__(ctx)
        self.page_index: int | None = None
        self.start = self.end = 0

    def cancel(self):
        super().cancel()
        self.ctx.scene.clear_selection_marks()
        self.page_index = None

    def selection_text(self) -> str:
        if self.page_index is None:
            return ""
        pt = self.ctx.page_text(self.page_index)
        return pt.text_range(self.start, self.end) if pt else ""

    def selection_quads(self) -> list[fitz.Rect]:
        if self.page_index is None:
            return []
        pt = self.ctx.page_text(self.page_index)
        return pt.quads(self.start, self.end) if pt else []

    def press(self, e: PageEvent) -> bool:
        pt = self.ctx.page_text(e.page)
        if not pt:
            return False
        if self.page_index is not None and self.page_index != e.page:
            self.ctx.scene.clear_selection_marks()
        off = pt.offset_at(e.fpoint())
        if off is None:
            return False
        self.page_index = e.page
        self.start = self.end = off
        self._dragging = True
        self._paint()
        return True

    def move(self, e: PageEvent) -> bool:
        if not self._dragging or e.page != self.page_index:
            return False
        pt = self.ctx.page_text(e.page)
        off = pt.offset_at(e.fpoint()) if pt else None
        if off is None:
            return True
        self.end = off
        self._paint()
        return True

    def release(self, e: PageEvent) -> bool:
        if not self._dragging:
            return False
        self._dragging = False
        n = abs(self.end - self.start)
        if n:
            self.ctx.status(f"{n} characters selected  ·  Ctrl+C to copy")
        self.ctx.window.update_inspector()
        return True

    def double(self, e: PageEvent) -> bool:
        pt = self.ctx.page_text(e.page)
        if not pt:
            return False
        off = pt.offset_at(e.fpoint())
        if off is None:
            return False
        self.page_index = e.page
        self.start, self.end = pt.word_at(off)
        self._paint()
        return True

    def key(self, event) -> bool:
        if event.matches(Qt.Key_Copy) or (
                event.key() == Qt.Key_C and event.modifiers() & Qt.ControlModifier):
            text = self.selection_text()
            if text:
                QApplication.clipboard().setText(text)
                self.ctx.status(f"Copied {len(text)} characters")
                return True
        if event.key() == Qt.Key_A and event.modifiers() & Qt.ControlModifier:
            idx = self.page_index if self.page_index is not None \
                else self.ctx.view.current_page
            pt = self.ctx.page_text(idx)
            if pt:
                self.page_index = idx
                self.start, self.end = 0, len(pt.chars)
                self._paint()
                return True
        return False

    def _paint(self):
        self.ctx.scene.clear_selection_marks()
        ov = self.ctx.overlay(self.page_index)
        if ov is None:
            return
        ov.selection = [QRectF(r.x0, r.y0, r.width, r.height)
                        for r in self.selection_quads()]
        ov.update()

    # --- actions offered by the inspector / context menu
    def apply_markup(self, kind: str):
        quads = self.selection_quads()
        if not quads or self.page_index is None:
            self.ctx.status("Select some text first")
            return
        s = self.ctx.style
        colour = hex_to_rgb(s.highlight if kind == "highlight" else s.stroke)
        labels = {"highlight": "Highlight text", "underline": "Underline text",
                  "strikeout": "Strike out text", "squiggly": "Squiggly underline"}
        with self.ctx.edit(labels.get(kind, "Mark up text"), page=self.page_index):
            page = self.ctx.page(self.page_index)
            adder = {"highlight": page.add_highlight_annot,
                     "underline": page.add_underline_annot,
                     "strikeout": page.add_strikeout_annot,
                     "squiggly": page.add_squiggly_annot}[kind]
            annot = adder(quads)
            annot.set_colors(stroke=colour)
            annot.set_info(title=s.author)
            annot.set_opacity(s.opacity)
            annot.update(opacity=s.opacity)

    def redact_selection(self):
        quads = self.selection_quads()
        if not quads or self.page_index is None:
            self.ctx.status("Select some text first")
            return
        fill = hex_to_rgb(self.ctx.style.redact_fill)
        with self.ctx.edit("Redact selected text", page=self.page_index):
            page = self.ctx.page(self.page_index)
            for r in quads:
                page.add_redact_annot(r, fill=fill, cross_out=False)
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                                  graphics=fitz.PDF_REDACT_LINE_ART_NONE)
        self.cancel()

    def delete_selection(self):
        quads = self.selection_quads()
        if not quads or self.page_index is None:
            return
        with self.ctx.edit("Delete selected text", page=self.page_index):
            page = self.ctx.page(self.page_index)
            for r in quads:
                page.add_redact_annot(r, fill=False, cross_out=False)
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                                  graphics=fitz.PDF_REDACT_LINE_ART_NONE)
        self.cancel()


# ===========================================================================
# Edit existing text
# ===========================================================================
class EditTextTool(Tool):
    name = "edit_text"
    title = "Edit Text"
    cursor = Qt.IBeamCursor
    inspector = ("text",)

    def __init__(self, ctx):
        super().__init__(ctx)
        self._hover_line = None
        self._hover_page = None
        self._drag_line = None
        self._drag_page = None

    def cancel(self):
        super().cancel()
        self._clear_hover()
        self._drag_line = None
        self._drag_page = None

    def _clear_hover(self):
        super()._clear_hover()
        self._hover_line = None
        self._hover_page = None

    def hover(self, e: PageEvent):
        pt = self.ctx.page_text(e.page)
        line = pt.line_at(e.fpoint()) if pt else None
        self._hover_line = line
        # Remember which page it came from: in continuous scroll the hovered
        # page is often not the one the status bar calls "current".
        self._hover_page = e.page if line is not None else None
        for i, ov in enumerate(self.ctx.scene.overlays):
            want = qrect(line.bbox) if (line and i == e.page) else None
            if ov.hover != want:
                ov.hover = want
                ov.update()

    def press(self, e: PageEvent) -> bool:
        pt = self.ctx.page_text(e.page)
        line = pt.line_at(e.fpoint()) if pt else None
        if line is None:
            return False
        self._anchor = QPointF(e.pos)
        self._drag_line = line
        self._drag_page = e.page
        self._dragging = False
        return True

    def move(self, e: PageEvent) -> bool:
        if self._drag_line is None or e.page != self._drag_page:
            return False
        if not self._dragging and not self._moved_enough(e):
            return True
        self._dragging = True
        dx = e.pos.x() - self._anchor.x()
        dy = e.pos.y() - self._anchor.y()
        r = self._drag_line.bbox
        ghost = QRectF(r.x0 + dx, r.y0 + dy, r.width, r.height)
        ov = self.ctx.overlay(e.page)
        if ov is not None:
            ov.hover = ghost
            ov.update()
        self.ctx.status("Release to move this line")
        return True

    def release(self, e: PageEvent) -> bool:
        if self._drag_line is None:
            return False
        line, page_index = self._drag_line, self._drag_page
        dragged = self._dragging
        dx = e.pos.x() - self._anchor.x() if self._anchor else 0
        dy = e.pos.y() - self._anchor.y() if self._anchor else 0
        self._drag_line = None
        self._dragging = False
        self._clear_hover()

        if dragged:
            self._move_line(page_index, line, dx, dy)
        else:
            self._open_editor(page_index, line)
        return True

    def double(self, e: PageEvent) -> bool:
        """Double-click edits the line under the pointer.

        It used to open the whole surrounding block, which is unhelpful in two
        common cases: a heading is a block of one line, so nothing happened at
        all, and a table row is a block of cells, so the three columns got
        merged into one run of text.  Editing the paragraph is still on the
        context menu, where it is asked for deliberately.
        """
        return self.begin_edit(e)

    def begin_edit(self, e: PageEvent) -> bool:
        pt = self.ctx.page_text(e.page)
        line = pt.line_at(e.fpoint()) if pt else None
        if line is None:
            return False
        self._clear_hover()
        self._open_editor(e.page, line)
        return True

    def begin_block_edit(self, e: PageEvent) -> bool:
        pt = self.ctx.page_text(e.page)
        block = pt.block_at(e.fpoint()) if pt else None
        if block is None or not block.lines:
            return False
        self._clear_hover()
        self._open_block_editor(e.page, block)
        return True

    def key(self, event) -> bool:
        if event.key() == Qt.Key_Delete:
            return self.delete_hovered()
        return False

    def delete_hovered(self) -> bool:
        """Erase the line currently under the pointer.  Used by Edit ▸ Delete."""
        if self._hover_line is None or self._hover_page is None:
            return False
        page, line = self._hover_page, self._hover_line
        with self.ctx.edit("Delete line of text", page=page):
            textops.erase(self.ctx.page(page), line.bbox)
        self._clear_hover()
        return True

    # ------------------------------------------------------------- editing
    def _open_editor(self, page_index: int, line):
        style = line.style
        colour = "#%06x" % (style.color & 0xFFFFFF)
        self.ctx.window.report_text_style(style)

        def commit(text: str):
            if text == line.text:
                self.ctx.status("No change")
                return
            with self.ctx.edit("Edit text", page=page_index):
                textops.replace_line(
                    self.ctx.document.doc, self.ctx.page(page_index), line, text,
                    shrink_to_fit=self.ctx.style.shrink_text_to_fit)

        self.ctx.view.begin_inline_edit(
            page_index, line.bbox, line.text, style.size, commit,
            multiline=False, color=colour)
        self.ctx.status("Type to replace this line · Enter to apply · Esc to cancel")

    def _open_block_editor(self, page_index: int, block):
        text = "\n".join(l.text for l in block.lines)
        size = block.lines[0].style.size

        def commit(new: str):
            if new == text:
                return
            with self.ctx.edit("Edit paragraph", page=page_index):
                textops.replace_block(self.ctx.document.doc,
                                      self.ctx.page(page_index), block, new)

        self.ctx.view.begin_inline_edit(
            page_index, block.bbox, text, size, commit, multiline=True)
        self.ctx.status("Editing paragraph · Ctrl+Enter to apply · Esc to cancel")

    def _move_line(self, page_index: int, line, dx: float, dy: float):
        if abs(dx) < 0.5 and abs(dy) < 0.5:
            return
        style = line.style
        with self.ctx.edit("Move text", page=page_index):
            doc = self.ctx.document.doc
            page = self.ctx.page(page_index)
            with textops.unrotated(page):
                box = fitz.Rect(line.bbox) + (-0.6, -0.6, 0.6, 0.6)
                page.add_redact_annot(textops.to_pdf_rect(page, box),
                                      fill=False, cross_out=False)
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                                      graphics=fitz.PDF_REDACT_LINE_ART_NONE)
                name, _buf = fonts.resolve(doc, page, style.font, style.flags,
                                           line.text)
                origin = textops.to_pdf_point(
                    page, fitz.Point(style.origin[0] + dx, style.origin[1] + dy))
                rgb = tuple(((style.color >> s) & 255) / 255 for s in (16, 8, 0))
                page.insert_text(origin, line.text, fontname=name,
                                 fontsize=style.size, color=rgb)


# ===========================================================================
# Add new text
# ===========================================================================
class AddTextTool(Tool):
    name = "add_text"
    title = "Add Text"
    cursor = Qt.CrossCursor
    inspector = ("text",)

    def press(self, e: PageEvent) -> bool:
        self._anchor = QPointF(e.pos)
        self._page = e.page
        self._dragging = False
        return True

    def move(self, e: PageEvent) -> bool:
        if self._anchor is None or e.page != self._page:
            return False
        if not self._dragging and not self._moved_enough(e):
            return True
        self._dragging = True
        self._draft(e.page, kind="textbox",
                    points=[self._anchor, QPointF(e.pos)])
        return True

    def release(self, e: PageEvent) -> bool:
        if self._anchor is None:
            return False
        anchor, page_index = self._anchor, self._page
        dragging = self._dragging
        self._clear_draft()
        self._anchor = None
        self._dragging = False

        s = self.ctx.style
        if dragging:
            rect = self._rect(anchor, QPointF(e.pos))
            if rect.width < 12 or rect.height < 10:
                return True
            self._edit_box(page_index, rect)
        else:
            size = s.font_size
            rect = fitz.Rect(anchor.x(), anchor.y() - size * 0.86,
                             anchor.x() + max(190, size * 12),
                             anchor.y() + size * 0.35)
            self._edit_point(page_index, rect, anchor, size)
        return True

    def _edit_point(self, page_index: int, rect, anchor: QPointF, size: float):
        s = self.ctx.style

        def commit(text: str):
            if not text.strip():
                return
            with self.ctx.edit("Add text", page=page_index):
                textops.insert_text(
                    self.ctx.document.doc, self.ctx.page(page_index),
                    fitz.Point(anchor.x(), anchor.y()), text,
                    fontname=s.font_alias(), size=size, color=s.text_rgb())

        self.ctx.view.begin_inline_edit(page_index, rect, "", size, commit,
                                        multiline=False, color=s.text_color)
        self.ctx.status("Type your text · Enter to place · Esc to cancel")

    def _edit_box(self, page_index: int, rect: fitz.Rect):
        s = self.ctx.style

        def commit(text: str):
            if not text.strip():
                return
            with self.ctx.edit("Add text box", page=page_index):
                textops.insert_textbox(
                    self.ctx.document.doc, self.ctx.page(page_index), rect, text,
                    fontname=s.font_alias(), size=s.font_size,
                    color=s.text_rgb(), align=s.align)

        self.ctx.view.begin_inline_edit(page_index, rect, "", s.font_size, commit,
                                        multiline=True, color=s.text_color)
        self.ctx.status("Type your text · Ctrl+Enter to place · Esc to cancel")


# ===========================================================================
# Freehand ink
# ===========================================================================
class InkTool(Tool):
    name = "ink"
    title = "Draw"
    cursor = Qt.CrossCursor
    inspector = ("stroke",)

    def __init__(self, ctx):
        super().__init__(ctx)
        self._points: list[QPointF] = []

    def press(self, e: PageEvent) -> bool:
        self._page = e.page
        self._points = [QPointF(e.pos)]
        return True

    def move(self, e: PageEvent) -> bool:
        if not self._points or e.page != self._page:
            return False
        last = self._points[-1]
        if abs(e.pos.x() - last.x()) + abs(e.pos.y() - last.y()) < 0.7:
            return True
        self._points.append(QPointF(e.pos))
        s = self.ctx.style
        self._draft(self._page, kind="ink", points=list(self._points),
                    color=s.stroke, width=s.width, opacity=s.opacity)
        return True

    def release(self, e: PageEvent) -> bool:
        pts, page_index = self._points, self._page
        self._points = []
        self._clear_draft()
        if len(pts) < 2 or page_index is None:
            return True
        # add_ink_annot wants plain float pairs, not fitz.Point objects
        stroke = [[(float(p.x()), float(p.y())) for p in _smooth(pts)]]
        with self.ctx.edit("Draw", page=page_index):
            annot = self.ctx.page(page_index).add_ink_annot(stroke)
            self._finish_annot(annot)
        return True


def _smooth(points: list[QPointF], window: int = 3) -> list[QPointF]:
    if len(points) <= window:
        return points
    out = [points[0]]
    for i in range(1, len(points) - 1):
        lo = max(0, i - window // 2)
        hi = min(len(points), i + window // 2 + 1)
        chunk = points[lo:hi]
        out.append(QPointF(sum(p.x() for p in chunk) / len(chunk),
                           sum(p.y() for p in chunk) / len(chunk)))
    out.append(points[-1])
    return out


# ===========================================================================
# Shapes
# ===========================================================================
class ShapeTool(Tool):
    cursor = Qt.CrossCursor
    inspector = ("stroke", "fill")
    kind = "rect"

    def press(self, e: PageEvent) -> bool:
        self._anchor = QPointF(e.pos)
        self._page = e.page
        return True

    def move(self, e: PageEvent) -> bool:
        if self._anchor is None or e.page != self._page:
            return False
        end = QPointF(e.pos)
        if e.shift:
            end = self._constrain(self._anchor, end)
        s = self.ctx.style
        self._draft(e.page, kind=self.kind, points=[self._anchor, end],
                    color=s.stroke, fill=s.fill, width=s.width,
                    opacity=s.opacity)
        return True

    def _constrain(self, a: QPointF, b: QPointF) -> QPointF:
        if self.kind in ("line", "arrow"):
            dx, dy = b.x() - a.x(), b.y() - a.y()
            ang = math.degrees(math.atan2(dy, dx))
            snap = round(ang / 45.0) * 45.0
            r = math.hypot(dx, dy)
            return QPointF(a.x() + r * math.cos(math.radians(snap)),
                           a.y() + r * math.sin(math.radians(snap)))
        side = max(abs(b.x() - a.x()), abs(b.y() - a.y()))
        return QPointF(a.x() + math.copysign(side, b.x() - a.x()),
                       a.y() + math.copysign(side, b.y() - a.y()))

    def release(self, e: PageEvent) -> bool:
        if self._anchor is None:
            return False
        a, page_index = self._anchor, self._page
        b = QPointF(e.pos)
        if e.shift:
            b = self._constrain(a, b)
        self._anchor = None
        self._clear_draft()
        if page_index is None:
            return True
        if abs(b.x() - a.x()) < 2 and abs(b.y() - a.y()) < 2:
            return True
        self._create(page_index, a, b)
        return True

    def _create(self, page_index: int, a: QPointF, b: QPointF):
        rect = self._rect(a, b)
        page = self.ctx.page(page_index)
        labels = {"rect": "Draw rectangle", "ellipse": "Draw ellipse",
                  "line": "Draw line", "arrow": "Draw arrow"}
        with self.ctx.edit(labels.get(self.kind, "Draw shape"), page=page_index):
            page = self.ctx.page(page_index)
            if self.kind == "rect":
                annot = page.add_rect_annot(rect)
                self._finish_annot(annot, fill=True)
            elif self.kind == "ellipse":
                annot = page.add_circle_annot(rect)
                self._finish_annot(annot, fill=True)
            else:
                p1 = fitz.Point(a.x(), a.y())
                p2 = fitz.Point(b.x(), b.y())
                annot = page.add_line_annot(p1, p2)
                if self.kind == "arrow":
                    s = self.ctx.style
                    start = (fitz.PDF_ANNOT_LE_CLOSED_ARROW if s.arrow_start
                             else fitz.PDF_ANNOT_LE_NONE)
                    end = (fitz.PDF_ANNOT_LE_CLOSED_ARROW if s.arrow_end
                           else fitz.PDF_ANNOT_LE_NONE)
                    try:
                        annot.set_line_ends(start, end)
                    except Exception:
                        pass
                self._finish_annot(annot)


class RectTool(ShapeTool):
    name, title, kind = "rect", "Rectangle", "rect"


class EllipseTool(ShapeTool):
    name, title, kind = "ellipse", "Ellipse", "ellipse"


class LineTool(ShapeTool):
    name, title, kind = "line", "Line", "line"


class ArrowTool(ShapeTool):
    name, title, kind = "arrow", "Arrow", "arrow"


# ===========================================================================
# Markup by dragging across text
# ===========================================================================
class MarkupTool(Tool):
    cursor = Qt.IBeamCursor
    inspector = ("markup",)
    kind = "highlight"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.page_index = None
        self.start = self.end = 0

    def cancel(self):
        super().cancel()
        self.ctx.scene.clear_selection_marks()
        self.page_index = None

    def press(self, e: PageEvent) -> bool:
        pt = self.ctx.page_text(e.page)
        off = pt.offset_at(e.fpoint()) if pt else None
        if off is None:
            return False
        self.ctx.scene.clear_selection_marks()
        self.page_index = e.page
        self.start = self.end = off
        self._dragging = True
        return True

    def move(self, e: PageEvent) -> bool:
        if not self._dragging or e.page != self.page_index:
            return False
        pt = self.ctx.page_text(e.page)
        off = pt.offset_at(e.fpoint()) if pt else None
        if off is None:
            return True
        self.end = off
        ov = self.ctx.overlay(e.page)
        if ov is not None:
            ov.selection = [QRectF(r.x0, r.y0, r.width, r.height)
                            for r in pt.quads(self.start, self.end)]
            ov.update()
        return True

    def release(self, e: PageEvent) -> bool:
        if not self._dragging:
            return False
        self._dragging = False
        pt = self.ctx.page_text(self.page_index)
        quads = pt.quads(self.start, self.end) if pt else []
        self.ctx.scene.clear_selection_marks()
        if not quads:
            return True
        s = self.ctx.style
        colour = hex_to_rgb(s.highlight if self.kind == "highlight" else s.stroke)
        labels = {"highlight": "Highlight", "underline": "Underline",
                  "strikeout": "Strike out", "squiggly": "Squiggly underline"}
        with self.ctx.edit(labels[self.kind], page=self.page_index):
            page = self.ctx.page(self.page_index)
            adder = {"highlight": page.add_highlight_annot,
                     "underline": page.add_underline_annot,
                     "strikeout": page.add_strikeout_annot,
                     "squiggly": page.add_squiggly_annot}[self.kind]
            annot = adder(quads)
            annot.set_colors(stroke=colour)
            annot.set_info(title=s.author)
            annot.set_opacity(s.opacity)
            annot.update(opacity=s.opacity)
        return True


class HighlightTool(MarkupTool):
    name, title, kind = "highlight", "Highlight", "highlight"


class UnderlineTool(MarkupTool):
    name, title, kind = "underline", "Underline", "underline"


class StrikeoutTool(MarkupTool):
    name, title, kind = "strikeout", "Strike Out", "strikeout"


# ===========================================================================
# Erase / redact / crop
# ===========================================================================
class RectDragTool(Tool):
    """Shared behaviour for tools that act on a dragged rectangle."""
    cursor = Qt.CrossCursor
    draft_kind = "marquee"

    def press(self, e: PageEvent) -> bool:
        self._anchor = QPointF(e.pos)
        self._page = e.page
        return True

    def move(self, e: PageEvent) -> bool:
        if self._anchor is None or e.page != self._page:
            return False
        self._draft(e.page, kind=self.draft_kind,
                    points=[self._anchor, QPointF(e.pos)], dashed=True)
        return True

    def release(self, e: PageEvent) -> bool:
        if self._anchor is None:
            return False
        rect = self._rect(self._anchor, QPointF(e.pos))
        page_index = self._page
        self._anchor = None
        self._clear_draft()
        if rect.width < 2 or rect.height < 2 or page_index is None:
            return True
        self.apply(page_index, rect)
        return True

    def apply(self, page_index: int, rect: fitz.Rect):
        raise NotImplementedError


class EraseTool(RectDragTool):
    name, title = "erase", "Erase"
    inspector = ("erase",)

    def apply(self, page_index: int, rect: fitz.Rect):
        page = self.ctx.page(page_index)
        fill = textops.background_at(page, rect)
        with self.ctx.edit("Erase area", page=page_index):
            textops.erase_area(self.ctx.page(page_index), rect, fill=fill,
                               drop_images=False)


class RedactTool(RectDragTool):
    name, title = "redact", "Redact"
    inspector = ("redact",)

    def apply(self, page_index: int, rect: fitz.Rect):
        fill = hex_to_rgb(self.ctx.style.redact_fill)
        with self.ctx.edit("Redact area", page=page_index):
            page = self.ctx.page(page_index)
            page.add_redact_annot(rect, fill=fill, cross_out=False)
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE,
                                  graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED)


class CropTool(RectDragTool):
    name, title = "crop", "Crop"
    draft_kind = "crop"

    def apply(self, page_index: int, rect: fitz.Rect):
        from . import pageops
        with self.ctx.edit("Crop page", geometry=True, page=page_index):
            pageops.crop_page(self.ctx.document.doc, page_index, rect)


# ===========================================================================
# Images, notes, stamps, links
# ===========================================================================
class ImageTool(Tool):
    name, title = "image", "Insert Image"
    cursor = Qt.CrossCursor

    def __init__(self, ctx):
        super().__init__(ctx)
        self.path: str | None = None

    def activate(self):
        self.path = None
        self._pick()

    def _pick(self) -> bool:
        path, _ = QFileDialog.getOpenFileName(
            self.ctx.window, "Choose an image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp *.svg)")
        if path:
            self.path = path
            self.ctx.status("Now drag on the page to place the image")
            return True
        self.ctx.set_tool("select")
        return False

    def press(self, e: PageEvent) -> bool:
        if not self.path and not self._pick():
            return True
        self._anchor = QPointF(e.pos)
        self._page = e.page
        return True

    def move(self, e: PageEvent) -> bool:
        if self._anchor is None:
            return False
        self._draft(e.page, kind="marquee",
                    points=[self._anchor, QPointF(e.pos)], dashed=True)
        return True

    def release(self, e: PageEvent) -> bool:
        if self._anchor is None or not self.path:
            return False
        rect = self._rect(self._anchor, QPointF(e.pos))
        page_index = self._page
        self._anchor = None
        self._clear_draft()

        if rect.width < 6 or rect.height < 6:
            # a plain click drops the image at a sensible default size
            rect = self._default_rect(page_index, QPointF(e.pos))
        with self.ctx.edit("Insert image", page=page_index):
            self.ctx.page(page_index).insert_image(
                rect, filename=self.path, keep_proportion=True, overlay=True)
        self.ctx.set_tool("select")
        return True

    def _default_rect(self, page_index: int, at: QPointF) -> fitz.Rect:
        try:
            from PIL import Image
            with Image.open(self.path) as im:
                w, h = im.size
            ratio = h / max(w, 1)
        except Exception:
            ratio = 0.75
        page = self.ctx.page(page_index)
        w = min(260.0, page.rect.width * 0.5)
        return fitz.Rect(at.x(), at.y(), at.x() + w, at.y() + w * ratio)


class NoteTool(Tool):
    name, title = "note", "Sticky Note"
    cursor = Qt.CrossCursor
    inspector = ("stroke",)

    def press(self, e: PageEvent) -> bool:
        text, ok = QInputDialog.getMultiLineText(
            self.ctx.window, "Sticky note", "Note text:", "")
        if not ok or not text.strip():
            return True
        s = self.ctx.style
        with self.ctx.edit("Add note", page=e.page):
            annot = self.ctx.page(e.page).add_text_annot(
                fitz.Point(e.pos.x(), e.pos.y()), text, icon="Note")
            annot.set_colors(stroke=s.stroke_rgb())
            annot.set_info(title=s.author, content=text)
            annot.update()
        return True


class LinkTool(RectDragTool):
    name, title = "link", "Add Link"

    def apply(self, page_index: int, rect: fitz.Rect):
        target, ok = QInputDialog.getText(
            self.ctx.window, "Add link",
            "URL (https://…) or page number:")
        if not ok or not target.strip():
            return
        target = target.strip()
        with self.ctx.edit("Add link", page=page_index):
            page = self.ctx.page(page_index)
            if target.isdigit():
                page.insert_link({"kind": fitz.LINK_GOTO, "from": rect,
                                  "page": max(0, int(target) - 1),
                                  "to": fitz.Point(0, 0)})
            else:
                if "://" not in target:
                    target = "https://" + target
                page.insert_link({"kind": fitz.LINK_URI, "from": rect,
                                  "uri": target})


class StampTool(Tool):
    name, title = "stamp", "Stamp"
    cursor = Qt.CrossCursor

    STAMPS = [
        ("Approved", fitz.STAMP_Approved),
        ("Draft", fitz.STAMP_Draft),
        ("Confidential", fitz.STAMP_Confidential),
        ("Final", fitz.STAMP_Final),
        ("For Comment", fitz.STAMP_ForComment),
        ("Not Approved", fitz.STAMP_NotApproved),
        ("Experimental", fitz.STAMP_Experimental),
        ("Expired", fitz.STAMP_Expired),
        ("Sold", fitz.STAMP_Sold),
        ("Top Secret", fitz.STAMP_TopSecret),
    ]

    def __init__(self, ctx):
        super().__init__(ctx)
        self.choice = fitz.STAMP_Approved

    def press(self, e: PageEvent) -> bool:
        names = [n for n, _ in self.STAMPS]
        name, ok = QInputDialog.getItem(self.ctx.window, "Stamp", "Choose:",
                                        names, 0, False)
        if not ok:
            return True
        value = dict(self.STAMPS)[name]
        rect = fitz.Rect(e.pos.x(), e.pos.y(), e.pos.x() + 170, e.pos.y() + 52)
        with self.ctx.edit(f"Stamp: {name}", page=e.page):
            annot = self.ctx.page(e.page).add_stamp_annot(rect, stamp=value)
            annot.set_opacity(self.ctx.style.opacity)
            annot.update()
        self.ctx.set_tool("select")
        return True


class SignatureTool(Tool):
    """Places a signature the user drew in the signature dialog."""
    name, title = "signature", "Signature"
    cursor = Qt.CrossCursor

    def __init__(self, ctx):
        super().__init__(ctx)
        self.png: bytes | None = None
        self.ratio = 0.35

    def activate(self):
        if self.png is None:
            self._capture()

    def _capture(self) -> bool:
        from .dialogs import SignatureDialog
        dlg = SignatureDialog(self.ctx.window)
        if dlg.exec() and dlg.png_bytes:
            self.png = dlg.png_bytes
            self.ratio = dlg.aspect
            self.ctx.status("Click or drag on the page to place your signature")
            return True
        self.ctx.set_tool("select")
        return False

    def press(self, e: PageEvent) -> bool:
        if self.png is None and not self._capture():
            return True
        self._anchor = QPointF(e.pos)
        self._page = e.page
        return True

    def move(self, e: PageEvent) -> bool:
        if self._anchor is None:
            return False
        self._draft(e.page, kind="marquee",
                    points=[self._anchor, QPointF(e.pos)], dashed=True)
        return True

    def release(self, e: PageEvent) -> bool:
        if self._anchor is None or self.png is None:
            return False
        rect = self._rect(self._anchor, QPointF(e.pos))
        page_index = self._page
        self._anchor = None
        self._clear_draft()
        if rect.width < 12:
            w = 190.0
            rect = fitz.Rect(e.pos.x(), e.pos.y(),
                             e.pos.x() + w, e.pos.y() + w * self.ratio)
        with self.ctx.edit("Add signature", page=page_index):
            self.ctx.page(page_index).insert_image(
                rect, stream=self.png, keep_proportion=True, overlay=True)
        self.ctx.set_tool("select")
        return True


# ------------------------------------------------------------------- registry
TOOL_CLASSES = [
    SelectTool, HandTool, TextSelectTool, EditTextTool, AddTextTool,
    HighlightTool, UnderlineTool, StrikeoutTool, InkTool,
    RectTool, EllipseTool, LineTool, ArrowTool,
    EraseTool, RedactTool, CropTool,
    ImageTool, NoteTool, StampTool, SignatureTool, LinkTool,
]

TOOLS = {cls.name: cls for cls in TOOL_CLASSES}
