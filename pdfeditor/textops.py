"""Reading and rewriting the text that already lives inside a PDF.

Two jobs live here:

* **Indexing** - turn a page into lines/characters with geometry, so the UI can
  hover a line, drag-select a character range, and produce highlight quads.
* **Rewriting** - erase an existing line with a redaction (which genuinely drops
  the glyphs from the content stream) and lay the user's new text back down in
  the closest available font.

All public geometry is in *display* space, i.e. the same coordinate system as
``page.rect``, which already accounts for ``page.rotation``.  Mutations
internally flip the page to rotation 0 so insertions land correctly, then put
the rotation back.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field

import fitz

from . import fonts

# Redaction that removes glyphs but leaves images and vector art untouched.
_KEEP_ART = dict(images=fitz.PDF_REDACT_IMAGE_NONE,
                 graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                 text=fitz.PDF_REDACT_TEXT_REMOVE)


# --------------------------------------------------------------- rotation help
@contextmanager
def unrotated(page: fitz.Page):
    """Temporarily present the page at rotation 0 so inserts are predictable."""
    rot = page.rotation
    if rot:
        page.set_rotation(0)
    try:
        yield
    finally:
        if rot:
            page.set_rotation(rot)


def to_pdf_rect(page: fitz.Page, rect) -> fitz.Rect:
    r = fitz.Rect(rect)
    return r * page.derotation_matrix if page.rotation else r


def to_pdf_point(page: fitz.Page, pt) -> fitz.Point:
    p = fitz.Point(pt)
    return p * page.derotation_matrix if page.rotation else p


# --------------------------------------------------------------- data classes
@dataclass
class Span:
    text: str
    bbox: fitz.Rect
    font: str
    size: float
    color: int
    flags: int
    origin: tuple
    ascender: float = 0.8
    descender: float = -0.2


@dataclass
class Char:
    c: str
    bbox: fitz.Rect
    line: int          # index into PageText.lines


@dataclass
class Line:
    index: int
    block: int
    bbox: fitz.Rect
    spans: list
    text: str
    origin: tuple
    first: int = 0     # global char offset of first char
    last: int = 0      # global char offset one past the last char
    chars: list = field(default_factory=list)

    @property
    def style(self) -> Span:
        """The span that dominates the line - used as the rewrite style."""
        if not self.spans:
            return Span("", self.bbox, "Helvetica", 11, 0, 0,
                        (self.bbox.x0, self.bbox.y1))
        return max(self.spans, key=lambda s: len(s.text))

    @property
    def size(self) -> float:
        return self.style.size

    def is_vertical(self) -> bool:
        return self.bbox.height > self.bbox.width * 2 and len(self.text) > 1


@dataclass
class Block:
    index: int
    bbox: fitz.Rect
    lines: list

    @property
    def text(self) -> str:
        return "\n".join(l.text for l in self.lines)


# ------------------------------------------------------------------ page index
class PageText:
    """Line/character index for one page, in display coordinates."""

    def __init__(self, page: fitz.Page):
        self.lines: list[Line] = []
        self.blocks: list[Block] = []
        self.chars: list[Char] = []
        self._build(page)

    def _build(self, page: fitz.Page):
        try:
            raw = page.get_text("rawdict")
        except Exception:
            return
        li = 0
        for bno, block in enumerate(raw.get("blocks", [])):
            if block.get("type", 0) != 0:
                continue                        # image block
            blines = []
            for line in block.get("lines", []):
                spans, text, chars = [], [], []
                for sp in line.get("spans", []):
                    stext = "".join(c["c"] for c in sp.get("chars", []))
                    if not stext:
                        continue
                    spans.append(Span(
                        text=stext,
                        bbox=fitz.Rect(sp["bbox"]),
                        font=sp.get("font", "Helvetica"),
                        size=float(sp.get("size", 11)),
                        color=int(sp.get("color", 0)),
                        flags=int(sp.get("flags", 0)),
                        origin=tuple(sp.get("origin", sp["bbox"][:2])),
                        ascender=float(sp.get("ascender", 0.8)),
                        descender=float(sp.get("descender", -0.2)),
                    ))
                    for ch in sp.get("chars", []):
                        chars.append(Char(ch["c"], fitz.Rect(ch["bbox"]), li))
                    text.append(stext)
                joined = "".join(text)
                if not joined.strip():
                    continue
                obj = Line(
                    index=li, block=bno, bbox=fitz.Rect(line["bbox"]),
                    spans=spans, text=joined,
                    origin=tuple(spans[0].origin) if spans else line["bbox"][:2],
                    first=len(self.chars), chars=chars,
                )
                self.chars.extend(chars)
                obj.last = len(self.chars)
                self.lines.append(obj)
                blines.append(obj)
                li += 1
            if blines:
                self.blocks.append(Block(
                    index=bno, bbox=fitz.Rect(block["bbox"]), lines=blines))

    # ------------------------------------------------------------- lookups
    def __bool__(self):
        return bool(self.lines)

    def line_at(self, pt, slack: float = 1.5) -> Line | None:
        """Line under a point, tolerating a little vertical slop."""
        p = fitz.Point(pt)
        best, best_d = None, 1e9
        for line in self.lines:
            r = line.bbox
            if r.x0 - slack <= p.x <= r.x1 + slack and \
               r.y0 - slack <= p.y <= r.y1 + slack:
                d = abs((r.y0 + r.y1) / 2 - p.y)
                if d < best_d:
                    best, best_d = line, d
        return best

    def block_at(self, pt) -> Block | None:
        p = fitz.Point(pt)
        for blk in self.blocks:
            if blk.bbox.contains(p):
                return blk
        return None

    def offset_at(self, pt, clamp: bool = True) -> int | None:
        """Nearest character boundary to a point, as a global char offset."""
        if not self.chars:
            return None
        p = fitz.Point(pt)
        line = self.line_at(p, slack=3)
        if line is None:
            if not clamp:
                return None
            line = min(self.lines,
                       key=lambda l: abs((l.bbox.y0 + l.bbox.y1) / 2 - p.y))
        if p.x <= line.bbox.x0:
            return line.first
        if p.x >= line.bbox.x1:
            return line.last
        for i in range(line.first, line.last):
            b = self.chars[i].bbox
            if p.x < (b.x0 + b.x1) / 2:
                return i
            if p.x <= b.x1:
                return i + 1
        return line.last

    def text_range(self, a: int, b: int) -> str:
        a, b = sorted((a, b))
        out, prev = [], None
        for i in range(max(0, a), min(len(self.chars), b)):
            ch = self.chars[i]
            if prev is not None and ch.line != prev:
                out.append("\n")
            out.append(ch.c)
            prev = ch.line
        return "".join(out)

    def quads(self, a: int, b: int) -> list[fitz.Rect]:
        """One rectangle per visual line covering the character range."""
        a, b = sorted((a, b))
        a, b = max(0, a), min(len(self.chars), b)
        out: list[fitz.Rect] = []
        cur, cur_line = None, None
        for i in range(a, b):
            ch = self.chars[i]
            if ch.line != cur_line:
                if cur is not None:
                    out.append(cur)
                cur, cur_line = fitz.Rect(ch.bbox), ch.line
            else:
                cur |= ch.bbox
        if cur is not None:
            out.append(cur)
        return [r for r in out if r.width > 0.1 and r.height > 0.1]

    def word_at(self, offset: int) -> tuple[int, int]:
        n = len(self.chars)
        if not n:
            return (0, 0)
        i = max(0, min(n - 1, offset))
        if self.chars[i].c.isspace() and i > 0:
            i -= 1
        line = self.chars[i].line
        a = i
        while a > 0 and self.chars[a - 1].line == line and \
                not self.chars[a - 1].c.isspace():
            a -= 1
        b = i
        while b < n and self.chars[b].line == line and \
                not self.chars[b].c.isspace():
            b += 1
        return (a, b)

    def line_bounds(self, offset: int) -> tuple[int, int]:
        if not self.chars:
            return (0, 0)
        i = max(0, min(len(self.chars) - 1, offset))
        line = self.lines[self.chars[i].line]
        return (line.first, line.last)


# ------------------------------------------------------------ colour sampling
def background_at(page: fitz.Page, rect, margin: float = 4.0) -> tuple:
    """Most common colour in the ring just outside ``rect`` - the paper tone."""
    try:
        probe = (fitz.Rect(rect) + (-margin, -margin, margin, margin)) & page.rect
        if probe.is_empty:
            return (1.0, 1.0, 1.0)
        pix = page.get_pixmap(clip=probe, colorspace=fitz.csRGB, alpha=False)
        if pix.width < 2 or pix.height < 2:
            return (1.0, 1.0, 1.0)
        samples = Counter()
        w, h, n = pix.width, pix.height, pix.n
        data = pix.samples

        def at(x, y):
            o = (y * pix.stride) + x * n
            return data[o], data[o + 1], data[o + 2]

        for x in range(0, w, max(1, w // 24)):
            samples[at(x, 0)] += 1
            samples[at(x, h - 1)] += 1
        for y in range(0, h, max(1, h // 24)):
            samples[at(0, y)] += 1
            samples[at(w - 1, y)] += 1
        r, g, b = samples.most_common(1)[0][0]
        return (r / 255.0, g / 255.0, b / 255.0)
    except Exception:
        return (1.0, 1.0, 1.0)


# ------------------------------------------------------------------ rewriting
def erase(page: fitz.Page, rect, fill=None) -> None:
    """Remove page content inside ``rect``.

    ``fill=None`` removes only the glyphs and leaves whatever was underneath
    (images, rules, background tints) alone.  Pass a colour to paint over the
    area as well, which is what the whiteout tool wants.
    """
    with unrotated(page):
        r = to_pdf_rect(page, rect)
        page.add_redact_annot(r, fill=fill if fill else False, cross_out=False)
        page.apply_redactions(**_KEEP_ART)


def erase_area(page: fitz.Page, rect, fill=(1, 1, 1), drop_images=True) -> None:
    """Hard erase: text, art and optionally images inside ``rect``."""
    with unrotated(page):
        r = to_pdf_rect(page, rect)
        page.add_redact_annot(r, fill=fill if fill else False, cross_out=False)
        page.apply_redactions(
            images=(fitz.PDF_REDACT_IMAGE_REMOVE if drop_images
                    else fitz.PDF_REDACT_IMAGE_NONE),
            graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
            text=fitz.PDF_REDACT_TEXT_REMOVE)


def replace_line(doc: fitz.Document, page: fitz.Page, line: Line, new_text: str,
                 *, color=None, size: float | None = None,
                 fontname: str | None = None, shrink_to_fit: bool = True,
                 pad: float = 0.6) -> None:
    """Swap the text of one line, keeping position, font, size and colour."""
    style = line.style
    new_text = new_text.replace("\n", " ").replace("\r", "")

    size = float(size or style.size)
    rgb = color if color is not None else _rgb(style.color)

    # Erase the old glyphs.  A hair of padding catches antialiased edges without
    # eating into the neighbouring lines.
    box = fitz.Rect(line.bbox) + (-pad, -pad, pad, pad)

    with unrotated(page):
        rect = to_pdf_rect(page, box)
        page.add_redact_annot(rect, fill=False, cross_out=False)
        page.apply_redactions(**_KEEP_ART)

        if not new_text.strip():
            return

        if fontname:
            name, buf = fontname, None
        else:
            name, buf = fonts.resolve(doc, page, style.font, style.flags, new_text)

        # Keep the replacement inside the space the original occupied.
        if shrink_to_fit:
            avail = max(line.bbox.width, 1.0)
            # A line that already ran to the page edge gets the rest of the page.
            avail = max(avail, page.rect.width - line.bbox.x0 - 18)
            width = fonts.text_width(new_text, name, size, buf)
            if width > avail:
                size = max(size * 0.55, size * avail / width)

        origin = to_pdf_point(page, fitz.Point(style.origin))
        page.insert_text(origin, new_text, fontname=name, fontfile=None,
                         fontsize=size, color=rgb, render_mode=0, overlay=True)


def replace_block(doc: fitz.Document, page: fitz.Page, block: Block,
                  new_text: str, *, color=None, size: float | None = None,
                  align: int = 0) -> None:
    """Reflow a whole paragraph into the rectangle it used to occupy."""
    if not block.lines:
        return
    style = block.lines[0].style
    size = float(size or style.size)
    rgb = color if color is not None else _rgb(style.color)

    box = fitz.Rect(block.bbox) + (-1.0, -1.0, 1.0, 1.0)
    with unrotated(page):
        rect = to_pdf_rect(page, box)
        page.add_redact_annot(rect, fill=False, cross_out=False)
        page.apply_redactions(**_KEEP_ART)

        if not new_text.strip():
            return
        name, _buf = fonts.resolve(doc, page, style.font, style.flags, new_text)

        # Grow downward if the new text needs more room than the old block had.
        target = fitz.Rect(rect)
        limit = page.rect.y1 - 12
        for _ in range(48):
            leftover = page.insert_textbox(
                target, new_text, fontname=name, fontsize=size, color=rgb,
                align=align, overlay=True)
            if leftover >= 0:
                return
            if target.y1 < limit:
                target.y1 = min(limit, target.y1 + max(size, -leftover) + 2)
            else:
                size *= 0.94
                if size < 3:
                    return


def insert_text(doc: fitz.Document, page: fitz.Page, point, text: str, *,
                fontname: str = "helv", size: float = 12,
                color=(0, 0, 0)) -> None:
    """Drop a new run of text at a point (baseline of the first line)."""
    with unrotated(page):
        pt = to_pdf_point(page, point)
        lines = text.split("\n")
        for i, ln in enumerate(lines):
            if not ln:
                continue
            page.insert_text(fitz.Point(pt.x, pt.y + i * size * 1.32), ln,
                             fontname=fontname, fontsize=size, color=color,
                             overlay=True)


def insert_textbox(doc: fitz.Document, page: fitz.Page, rect, text: str, *,
                   fontname: str = "helv", size: float = 12,
                   color=(0, 0, 0), align: int = 0) -> float:
    with unrotated(page):
        r = to_pdf_rect(page, rect)
        return page.insert_textbox(r, text, fontname=fontname, fontsize=size,
                                   color=color, align=align, overlay=True)


def _rgb(packed: int):
    v = int(packed) & 0xFFFFFF
    return ((v >> 16 & 255) / 255.0, (v >> 8 & 255) / 255.0, (v & 255) / 255.0)


# ---------------------------------------------------------------------- search
@dataclass
class Hit:
    page: int
    rect: fitz.Rect
    text: str
    context: str


def search_document(doc: fitz.Document, needle: str, *, case: bool = False,
                    whole_words: bool = False, limit: int = 5000) -> list[Hit]:
    if not needle:
        return []
    flags = 0
    if not case:
        # PyMuPDF's search_for is case-insensitive by default.
        pass
    hits: list[Hit] = []
    for pno in range(doc.page_count):
        page = doc[pno]
        try:
            rects = page.search_for(needle, quads=False)
        except Exception:
            continue
        if not rects:
            continue
        plain = page.get_text("text")
        low_plain = plain if case else plain.lower()
        low_needle = needle if case else needle.lower()
        starts, pos = [], 0
        while True:
            k = low_plain.find(low_needle, pos)
            if k < 0:
                break
            starts.append(k)
            pos = k + max(1, len(needle))
        for i, r in enumerate(rects):
            if case:
                # search_for ignores case; drop hits that differ in case.
                found = page.get_textbox(r).strip()
                if needle not in found:
                    continue
            ctx = ""
            if i < len(starts):
                k = starts[i]
                ctx = plain[max(0, k - 34):k + len(needle) + 34]
                ctx = " ".join(ctx.split())
            hits.append(Hit(pno, fitz.Rect(r), needle, ctx))
            if len(hits) >= limit:
                return hits
    return hits
