"""Moving and resizing images that are already placed on a page.

A PDF draws an image by setting a matrix and invoking the XObject::

    q  499 0 0 288 48 450 cm  /fzImg0 Do  Q

The ``cm`` matrix maps the image's unit square onto wherever it lands, so
moving or resizing the image is a matter of rewriting six numbers.  Nothing is
re-encoded, the image object is untouched, and the operation is repeatable.

The obvious alternative - ``delete_image`` then ``insert_image`` - is a trap.
``Page.delete_image`` does not remove anything: it overwrites the image
*object* with a 1x1 transparent pixmap.  The placement stays, so the page keeps
a phantom the size of the original, and a second move re-extracts the blank and
stamps it down as an opaque black rectangle.  Hence the matrix rewrite, with a
redaction-based fallback that leaves the image object intact.
"""

from __future__ import annotations

import re
from typing import NamedTuple

import fitz

# A page content stream can run to megabytes, so every scan is anchored to a
# small window just behind the draw call rather than run over the whole thing.
_WINDOW = 256
# ``<n> <n> <n> <n> <n> <n> cm`` at the very end of that window.
_CM_TAIL = re.compile(rb"(?:[-+0-9.eE]+[ \t\r\n]+){6}cm$")
# What may sit between the matrix and the ``Do``: whitespace and graphics
# state selections.  Anything else and we are not looking at the placement.
_GS_TAIL = re.compile(rb"/[^\s/\[\]<>()]+\s+gs\s*$")
# Image space is y-down with a top-left origin; PDF space is y-up.  This turns
# one into the other over the unit square, and is its own inverse.
_FLIP = fitz.Matrix(1, 0, 0, -1, 0, 1)
# ``q`` just before the matrix and ``Q`` just after the ``Do``.
_ENDS_WITH_Q = re.compile(rb"(?:^|\s)q\s*$")
_STARTS_WITH_Q = re.compile(rb"^\s*Q(?:\s|$)")


class Unsupported(Exception):
    """A move this editor declines to make rather than get wrong."""
    expected = True                        # report it quietly, not as a fault


def _num(value: float) -> bytes:
    text = f"{value:.5f}".rstrip("0").rstrip(".")
    return (text if text not in ("", "-", "-0") else "0").encode()


def _matrix_rect(page: fitz.Page, m: fitz.Matrix) -> fitz.Rect:
    """Where the unit square lands, in the page's displayed coordinates."""
    tm = page.transformation_matrix
    pts = [fitz.Point(x, y) * m * tm for x, y in ((0, 0), (1, 0), (0, 1), (1, 1))]
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    return fitz.Rect(min(xs), min(ys), max(xs), max(ys))


def _unit_rect(m: fitz.Matrix) -> fitz.Rect:
    """Where the unit square lands under `m`."""
    pts = [fitz.Point(x, y) * m for x, y in ((0, 0), (1, 0), (0, 1), (1, 1))]
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    return fitz.Rect(min(xs), min(ys), max(xs), max(ys))


def _containers(page: fitz.Page, xref: int) -> list[tuple[str, list[int]]]:
    """Where to look for the draw call, as ``(resource name, stream xrefs)``.

    An image is usually invoked by the page's own content, but plenty of
    real documents - anything exported from a design tool - wrap it in a Form
    XObject instead.  ``get_images(full=True)`` reports that container in the
    last field, and its stream is where the matrix actually lives.
    """
    out = []
    for info in page.get_images(full=True):
        if info[0] != xref:
            continue
        referencer = info[9]
        out.append((info[7], [referencer] if referencer else page.get_contents()))
    return out


class Placement(NamedTuple):
    """One ``cm … Do`` pair, wherever it lives."""
    content_xref: int
    data: bytes
    cm: tuple[int, int]        # byte span of the matrix and its operator
    do: tuple[int, int]        # byte span of the ``/Name Do``
    matrix: fitz.Matrix        # in the coordinates of whatever stream holds it
    rect: fitz.Rect            # where it puts the image, in page coordinates


def _placements(page: fitz.Page, xref: int) -> list[Placement]:
    """Every ``cm … Do`` that draws `xref`, in the page or in a Form XObject."""
    doc = page.parent
    found = []
    for name, streams in _containers(page, xref):
        do_re = re.compile(rb"/" + re.escape(name.encode()) + rb"\s*Do\b")
        for content_xref in streams:
            try:
                data = doc.xref_stream(content_xref)
            except Exception:
                continue
            for do in do_re.finditer(data):
                span = _matrix_before(data, do.start())
                if span is None:
                    continue
                start, end = span
                try:
                    m = fitz.Matrix(*[float(n) for n in data[start:end - 2].split()])
                except Exception:
                    continue
                found.append(Placement(content_xref, data, span,
                                       (do.start(), do.end()), m,
                                       _matrix_rect(page, m)))
    return found


def _matrix_before(data: bytes, pos: int) -> tuple[int, int] | None:
    """Byte span of the ``cm`` that sets up the draw call at `pos`."""
    base = max(0, pos - _WINDOW)
    tail = data[base:pos].rstrip()
    while True:                            # skip any `/GS0 gs` in between
        gs = _GS_TAIL.search(tail)
        if gs is None:
            break
        tail = tail[:gs.start()].rstrip()
    hit = _CM_TAIL.search(tail)
    if hit is None:
        return None
    return base + hit.start(), base + hit.end()


def _operands(m: fitz.Matrix) -> bytes:
    return b" ".join(_num(v) for v in (m.a, m.b, m.c, m.d, m.e, m.f))


def _isolated(place: Placement) -> bool:
    """True when the matrix serves this image and nothing else."""
    before = place.data[max(0, place.cm[0] - 16):place.cm[0]]
    after = place.data[place.do[1]:place.do[1] + 16]
    return (_ENDS_WITH_Q.search(before) is not None and
            _STARTS_WITH_Q.match(after) is not None)


def _closest(places: list[Placement], rect: fitz.Rect) -> Placement | None:
    """The placement the user is pointing at, when an image is drawn twice."""
    if not places:
        return None
    place = min(places, key=lambda p: abs(p.rect.x0 - rect.x0) +
                abs(p.rect.y0 - rect.y0) + abs(p.rect.x1 - rect.x1) +
                abs(p.rect.y1 - rect.y1))
    if len(places) > 1 and not place.rect.intersects(rect):
        return None
    return place


def _digest_map(page: fitz.Page) -> dict:
    """Fingerprint -> xref for the images on this page, cached on the document.

    PyMuPDF attaches xrefs to placements by decoding every image on the page
    and matching digests, and it redoes that on each call - so asking about
    sixty images costs sixty full decodes, sixty times over.  The mapping only
    depends on which image objects exist, which moving one does not change, so
    it is worth keeping.
    """
    doc = page.parent
    xrefs = tuple(sorted({info[0] for info in page.get_images()}))
    cached = getattr(doc, "_pdfstudio_digests", None)
    if cached is not None and cached[0] == xrefs:
        return cached[1]
    mapping = {}
    for xref in xrefs:
        try:
            pix = fitz.Pixmap(doc, xref)
        except Exception:
            continue
        mapping[pix.digest] = xref
        del pix
    try:
        doc._pdfstudio_digests = (xrefs, mapping)
    except Exception:                      # pragma: no cover - exotic build
        pass
    return mapping


def placements(page: fitz.Page) -> list[tuple[int, fitz.Rect, fitz.Matrix, int]]:
    """Every image on the page as ``(xref, rect, composed matrix, copies)``.

    Unlike the raw ``cm``, the transform has any enclosing Form XObject already
    folded in, so it speaks the same coordinates as the grab handles.
    """
    try:
        spots = page.get_image_info(hashes=True)
    except Exception:
        return []
    digests = _digest_map(page)
    found = []
    for spot in spots:
        xref = digests.get(spot.get("digest"), 0)
        if not xref:
            continue
        found.append([xref, fitz.Rect(spot["bbox"]), fitz.Matrix(spot["transform"])])
    counts: dict[int, int] = {}
    for xref, _r, _m in found:
        counts[xref] = counts.get(xref, 0) + 1
    return [(x, r, m, counts[x]) for x, r, m in found]


def _occurrences(page: fitz.Page, xref: int) -> list[tuple[fitz.Rect, fitz.Matrix]]:
    """Every spot one particular image appears."""
    return [(r, m) for x, r, m, _n in placements(page) if x == xref]


def _pick(page: fitz.Page, xref: int, old: fitz.Rect, hint=None):
    """The one draw call to rewrite, or ``None`` if it cannot be identified."""
    if hint is not None:
        rect, composed, copies = old, fitz.Matrix(hint[0]), hint[1]
    else:
        spots = _occurrences(page, xref)
        if not spots:
            return None
        rect, composed = min(spots, key=lambda s: abs(s[0].x0 - old.x0) +
                             abs(s[0].y0 - old.y0) + abs(s[0].x1 - old.x1) +
                             abs(s[0].y1 - old.y1))
        copies = len(spots)
        if copies > 1 and not rect.intersects(old):
            return None

    places = _placements(page, xref)
    if not places:
        return None
    own = page.get_contents()
    if len(places) == 1:
        place = places[0]
    else:
        # Several draw calls: match on where each one puts the image.  That
        # comparison only works for a matrix in page coordinates; inside a
        # Form XObject the numbers are in the form's own space, so rather than
        # guess we decline and leave the file alone.
        if any(p.content_xref not in own for p in places):
            return None
        place = min(places, key=lambda p: abs(p.rect.x0 - rect.x0) +
                    abs(p.rect.y0 - rect.y0) + abs(p.rect.x1 - rect.x1) +
                    abs(p.rect.y1 - rect.y1))
        if not place.rect.intersects(rect):
            return None

    if place.content_xref not in own and copies > 1:
        # The matrix lives in a Form XObject that the page draws more than
        # once - every copy shares it, so editing it here would drag them all.
        return None
    return place, rect, composed


def _retarget(page: fitz.Page, xref: int, old: fitz.Rect,
              new: fitz.Rect, hint=None) -> bool:
    """Rewrite the placement matrix so the image lands on `new`.

    Everything happens in page coordinates: `composed` maps the image's unit
    square onto the page, so scaling that composition and unwinding it again
    gives the matrix to write back, whichever stream it lives in.
    """
    picked = _pick(page, xref, old, hint)
    if picked is None:
        return False
    place, rect, composed = picked
    if (rect.width < 1e-6 or rect.height < 1e-6 or
            new.width < 1e-6 or new.height < 1e-6):
        return False
    try:
        undo = ~composed
    except Exception:
        return False                       # singular: nothing sane to write

    sx = new.width / rect.width
    sy = new.height / rect.height
    fit = fitz.Matrix(sx, 0, 0, sy,
                      new.x0 - sx * rect.x0, new.y0 - sy * rect.y0)
    # `composed` speaks image space, where the origin is top-left and y runs
    # down; the `cm` in the stream speaks PDF space, where y runs up.  Flip on
    # the way in and back out so the two agree.
    updated = _FLIP * composed * fit * undo * _FLIP * place.matrix

    # Check the arithmetic before touching the file.  Everything between the
    # matrix and the page - a Form XObject's own placement, the page flip -
    # is whatever turns `place.matrix` into `composed`, and it does not change
    # here, so re-composing with the new matrix says exactly where it lands.
    container = ~(_FLIP * place.matrix) * composed
    landed = _unit_rect(_FLIP * updated * container)
    if (abs(landed.x0 - new.x0) > 0.05 or abs(landed.y0 - new.y0) > 0.05 or
            abs(landed.x1 - new.x1) > 0.05 or abs(landed.y1 - new.y1) > 0.05):
        return False

    operands = _operands(updated)
    data = place.data
    start, end = place.cm
    if _isolated(place):
        # The usual `q … cm /Im Do … Q`: the matrix is the image's alone, so
        # swapping the six numbers is enough.
        patched = data[:start] + operands + b" cm" + data[end:]
    else:
        # The matrix is shared with whatever is drawn after it.  Give the image
        # its own graphics state and restore the original matrix on the way
        # out, so the rest of the block sees exactly what it saw before.  The
        # placement is isolated afterwards, so further moves take the cheap
        # path above.
        patched = (data[:start] + b"q " + operands + b" cm " +
                   data[place.do[0]:place.do[1]] + b" Q " +
                   _operands(place.matrix) + b" cm" + data[place.do[1]:])

    page.parent.update_stream(place.content_xref, patched)
    return True


def _safe_to_reinsert(page: fitz.Page, xref: int, old: fitz.Rect) -> bool:
    """Whether re-stamping this image can be done without collateral damage.

    The fallback clears the old spot with a redaction, and a redaction takes
    out *every* image it overlaps.  That is tolerable over a small picture
    sitting on its own, and catastrophic over a full-bleed background: one
    drag would strip the rest of the page.  It also cannot reproduce the clip
    a Form XObject imposes, so a background that is only visible through a
    small window would come back at its full size.
    """
    if any(info[9] for info in page.get_images(full=True) if info[0] == xref):
        return False                       # lives inside a Form: keep out
    bounds = page.rect
    if not old.intersects(bounds):
        return False
    return old.width <= bounds.width * 1.05 and old.height <= bounds.height * 1.05


def _reinsert(page: fitz.Page, xref: int, old: fitz.Rect,
              new: fitz.Rect) -> int:
    """Fallback: strip the old placement and stamp the image down again.

    The redaction removes the *invocation* from the content stream and leaves
    the image object alone, so this stays repeatable.  The pixmap is rebuilt
    through ``fitz.Pixmap(doc, xref)`` rather than ``extract_image`` so a soft
    mask survives - extracting the base stream alone is what turns a
    transparent image into a black slab.
    """
    doc = page.parent
    try:
        pix = fitz.Pixmap(doc, xref)
    except Exception as exc:
        raise RuntimeError(f"this image cannot be read back ({exc})")
    if pix.colorspace is not None and pix.colorspace.n > 3:
        pix = fitz.Pixmap(fitz.csRGB, pix)

    page.add_redact_annot(old, fill=False, cross_out=False)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE,
                          graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                          text=fitz.PDF_REDACT_TEXT_NONE)
    before = {i[0] for i in page.get_images()}
    page.insert_image(new, pixmap=pix, keep_proportion=False, overlay=True)
    added = {i[0] for i in page.get_images()} - before
    return added.pop() if len(added) == 1 else xref


def move_image(page: fitz.Page, xref: int, old: fitz.Rect,
               new: fitz.Rect, hint=None) -> int:
    """Put the image drawn at `old` at `new` instead.

    `hint` is ``(composed matrix, number of copies on the page)`` if the caller
    already knows them - working them out here costs a full page parse.

    Returns the xref that holds the image afterwards - the same one on the
    matrix path, possibly a new one if we had to fall back.  Raises rather
    than damage the page when neither route is safe.
    """
    if _retarget(page, xref, old, new, hint):
        return xref
    if hint is not None and _retarget(page, xref, old, new):
        return xref                        # the hint was stale; do it properly
    if not _safe_to_reinsert(page, xref, old):
        raise Unsupported(
            "this picture is shared or clipped by the page's layout, so it "
            "has been left where it is")
    return _reinsert(page, xref, old, new)


def delete_image(page: fitz.Page, xref: int, rect: fitz.Rect) -> None:
    """Take the image off the page.

    Cuts the invocation out of the content stream.  ``Page.delete_image``
    would instead blank the shared image object - which also empties it
    everywhere else it is used, and leaves a same-sized phantom behind here.
    """
    place = _closest(_placements(page, xref), rect)
    if place is not None:
        # Drop the draw call only.  The matrix that precedes it may still be
        # wanted by whatever comes next, and a matrix on its own draws nothing.
        start, end = place.do
        page.parent.update_stream(place.content_xref,
                                  place.data[:start] + place.data[end:])
        return
    page.add_redact_annot(rect, fill=False, cross_out=False)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE,
                          graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                          text=fitz.PDF_REDACT_TEXT_NONE)


def is_grabbable(page: fitz.Page, rect: fitz.Rect) -> bool:
    """Whether an image placed at `rect` should get a set of grab handles.

    Design-tool exports are full of full-bleed backgrounds placed at absurd
    sizes - one in a real brief measured 9000 x 6200 pt - and shown through a
    small window cut by the Form XObject that holds them.  Their placement
    rectangle is not what you see, so a handle drawn on it is a trap: it
    covers the page, and dragging it moves something you were not pointing at.
    """
    if rect.width < 3 or rect.height < 3:
        return False
    bounds = page.rect
    if not rect.intersects(bounds):
        return False
    return rect.width <= bounds.width * 1.05 or rect.height <= bounds.height * 1.05


def is_blank(info) -> bool:
    """True for the 1x1 corpses left behind by ``Page.delete_image``.

    Documents edited by an earlier build of this program still contain them;
    without this they show up as empty grab boxes with nothing inside.
    Takes a tuple from ``Page.get_images(full=True)``.
    """
    return info[2] <= 1 and info[3] <= 1
