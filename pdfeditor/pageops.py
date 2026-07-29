"""Whole-page operations: insert, delete, reorder, rotate, crop, watermark…

Every function mutates the ``fitz.Document`` in place and expects the caller to
have opened a :meth:`Document.edit` transaction so undo works.
"""

from __future__ import annotations

import math
import os

import fitz

PAGE_SIZES = {
    "A3":        (841.89, 1190.55),
    "A4":        (595.28, 841.89),
    "A5":        (419.53, 595.28),
    "Letter":    (612.0, 792.0),
    "Legal":     (612.0, 1008.0),
    "Tabloid":   (792.0, 1224.0),
    "Executive": (521.86, 756.0),
}


# ------------------------------------------------------------------ structure
def insert_blank(doc: fitz.Document, index: int, width: float = 595.28,
                 height: float = 841.89, count: int = 1) -> None:
    for i in range(count):
        doc.new_page(pno=index + i, width=width, height=height)


def insert_like(doc: fitz.Document, index: int, template: int = 0,
                count: int = 1) -> None:
    """Insert blank pages matching the size/rotation of an existing page."""
    rect = doc[template].rect
    rot = doc[template].rotation
    for i in range(count):
        p = doc.new_page(pno=index + i, width=rect.width, height=rect.height)
        if rot:
            p.set_rotation(rot)


def delete_pages(doc: fitz.Document, indices) -> None:
    keep = sorted(set(indices), reverse=True)
    if len(keep) >= doc.page_count:
        raise ValueError("A document must keep at least one page")
    for i in keep:
        doc.delete_page(i)


def duplicate_pages(doc: fitz.Document, indices) -> None:
    for offset, i in enumerate(sorted(set(indices))):
        doc.fullcopy_page(i + offset, i + offset + 1)


def move_pages(doc: fitz.Document, indices, destination: int) -> list[int]:
    """Move pages to sit before ``destination``.  Returns their new indices."""
    order = list(range(doc.page_count))
    picked = [i for i in order if i in set(indices)]
    if not picked:
        return []
    before = [i for i in order[:destination] if i not in set(indices)]
    after = [i for i in order[destination:] if i not in set(indices)]
    new_order = before + picked + after
    doc.select(new_order)
    start = len(before)
    return list(range(start, start + len(picked)))


def reorder(doc: fitz.Document, new_order) -> None:
    doc.select(list(new_order))


def rotate_pages(doc: fitz.Document, indices, delta: int) -> None:
    for i in indices:
        page = doc[i]
        page.set_rotation((page.rotation + delta) % 360)


def set_rotation(doc: fitz.Document, indices, value: int) -> None:
    for i in indices:
        doc[i].set_rotation(value % 360)


def crop_page(doc: fitz.Document, index: int, rect: fitz.Rect) -> None:
    page = doc[index]
    r = fitz.Rect(rect)
    if page.rotation:
        r = r * page.derotation_matrix
    r = r & page.mediabox
    page.set_cropbox(r)


def reset_crop(doc: fitz.Document, index: int) -> None:
    doc[index].set_cropbox(doc[index].mediabox)


def resize_pages(doc: fitz.Document, indices, width: float, height: float) -> None:
    """Scale page content onto a new sheet size, preserving aspect ratio."""
    for i in sorted(indices):
        src = doc[i]
        target = fitz.Rect(0, 0, width, height)
        tmp = fitz.open()
        new = tmp.new_page(width=width, height=height)
        scale = min(width / src.rect.width, height / src.rect.height)
        w, h = src.rect.width * scale, src.rect.height * scale
        box = fitz.Rect((width - w) / 2, (height - h) / 2,
                        (width - w) / 2 + w, (height - h) / 2 + h)
        new.show_pdf_page(box, doc, i)
        doc.insert_pdf(tmp, from_page=0, to_page=0, start_at=i + 1)
        doc.delete_page(i)
        tmp.close()


# ------------------------------------------------------------------- combining
def import_pdf(doc: fitz.Document, path: str, at: int,
               from_page: int = 0, to_page: int = -1,
               password: str | None = None) -> int:
    src = fitz.open(path)
    try:
        if src.needs_pass and not src.authenticate(password or ""):
            raise ValueError("Source document is password protected")
        if not src.is_pdf:
            src = fitz.open("pdf", src.convert_to_pdf())
        last = src.page_count - 1 if to_page < 0 else min(to_page, src.page_count - 1)
        n = last - from_page + 1
        doc.insert_pdf(src, from_page=from_page, to_page=last, start_at=at)
        return n
    finally:
        src.close()


def extract_to_bytes(doc: fitz.Document, indices) -> bytes:
    out = fitz.open()
    out.insert_pdf(doc, from_page=0, to_page=doc.page_count - 1)
    out.select(sorted(set(indices)))
    data = out.tobytes(garbage=3, deflate=True)
    out.close()
    return data


def split_to_files(doc: fitz.Document, folder: str, stem: str,
                   every: int = 1) -> list[str]:
    written = []
    for start in range(0, doc.page_count, every):
        end = min(start + every - 1, doc.page_count - 1)
        out = fitz.open()
        out.insert_pdf(doc, from_page=start, to_page=end)
        name = (f"{stem}_{start + 1}.pdf" if every == 1
                else f"{stem}_{start + 1}-{end + 1}.pdf")
        path = os.path.join(folder, name)
        out.save(path, garbage=3, deflate=True)
        out.close()
        written.append(path)
    return written


# ------------------------------------------------------------------ decoration
def add_watermark(doc: fitz.Document, indices, text: str, *,
                  size: float = 48, color=(0.6, 0.6, 0.6), opacity: float = 0.28,
                  angle: float = 45, on_top: bool = True) -> None:
    for i in indices:
        page = doc[i]
        rect = page.rect
        font = fitz.Font("helv")
        width = font.text_length(text, size)
        centre = fitz.Point(rect.width / 2, rect.height / 2)
        # Position so the rotated text is centred on the page.
        rad = math.radians(angle)
        start = fitz.Point(centre.x - width / 2 * math.cos(rad),
                           centre.y + width / 2 * math.sin(rad))
        if page.rotation:
            start = start * page.derotation_matrix
        page.insert_text(start, text, fontname="helv", fontsize=size,
                         color=color, rotate=0, overlay=on_top,
                         fill_opacity=opacity, stroke_opacity=opacity,
                         morph=(start, fitz.Matrix(angle)))


def add_image_watermark(doc: fitz.Document, indices, path: str, *,
                        opacity: float = 0.25, scale: float = 0.55,
                        on_top: bool = False) -> None:
    for i in indices:
        page = doc[i]
        r = page.rect
        w, h = r.width * scale, r.height * scale
        box = fitz.Rect((r.width - w) / 2, (r.height - h) / 2,
                        (r.width + w) / 2, (r.height + h) / 2)
        page.insert_image(box, filename=path, overlay=on_top, alpha=-1,
                          keep_proportion=True)


def add_page_numbers(doc: fitz.Document, *, fmt: str = "{page} / {total}",
                     size: float = 9, color=(0.25, 0.25, 0.25),
                     position: str = "bottom-center", margin: float = 28,
                     start_at: int = 1, skip_first: bool = False) -> None:
    total = doc.page_count
    for i in range(doc.page_count):
        if skip_first and i == 0:
            continue
        page = doc[i]
        label = fmt.format(page=i + start_at, total=total + start_at - 1,
                           roman=_roman(i + start_at))
        width = fitz.get_text_length(label, fontname="helv", fontsize=size)
        r = page.rect
        y = margin if position.startswith("top") else r.height - margin
        if position.endswith("left"):
            x = margin
        elif position.endswith("right"):
            x = r.width - margin - width
        else:
            x = (r.width - width) / 2
        pt = fitz.Point(x, y)
        if page.rotation:
            pt = pt * page.derotation_matrix
        rot = page.rotation
        if rot:
            page.set_rotation(0)
        page.insert_text(pt, label, fontname="helv", fontsize=size, color=color)
        if rot:
            page.set_rotation(rot)


def _roman(n: int) -> str:
    vals = ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"),
            (90, "xc"), (50, "l"), (40, "xl"), (10, "x"), (9, "ix"),
            (5, "v"), (4, "iv"), (1, "i"))
    out = []
    for v, s in vals:
        while n >= v:
            out.append(s)
            n -= v
    return "".join(out)


def flatten_annotations(doc: fitz.Document, indices=None) -> int:
    """Bake annotations into page content so they can no longer be moved."""
    count = 0
    for i in (indices if indices is not None else range(doc.page_count)):
        page = doc[i]
        annots = list(page.annots())
        if not annots:
            continue
        for annot in annots:
            try:
                pix = annot.get_pixmap(alpha=True, dpi=200)
                rect = annot.rect
                page.delete_annot(annot)
                page.insert_image(rect, pixmap=pix, overlay=True)
                count += 1
            except Exception:
                continue
    return count


# --------------------------------------------------------------------- export
def page_to_pixmap(page: fitz.Page, dpi: int = 150, alpha: bool = False):
    return page.get_pixmap(dpi=dpi, alpha=alpha)


def export_images(doc: fitz.Document, indices, folder: str, stem: str,
                  dpi: int = 150, fmt: str = "png") -> list[str]:
    out = []
    for i in sorted(indices):
        pix = doc[i].get_pixmap(dpi=dpi, alpha=False)
        path = os.path.join(folder, f"{stem}_{i + 1}.{fmt}")
        if fmt in ("jpg", "jpeg"):
            pix.save(path, jpg_quality=92)
        else:
            pix.save(path)
        out.append(path)
    return out


def export_text(doc: fitz.Document, indices=None, layout: bool = False) -> str:
    mode = "text" if not layout else "blocks"
    chunks = []
    for i in (indices if indices is not None else range(doc.page_count)):
        if layout:
            blocks = sorted(doc[i].get_text("blocks"), key=lambda b: (b[1], b[0]))
            chunks.append("\n".join(b[4] for b in blocks if b[6] == 0))
        else:
            chunks.append(doc[i].get_text(mode))
    return "\n\n".join(chunks)


def extract_embedded_images(doc: fitz.Document, folder: str) -> list[str]:
    written, seen = [], set()
    for pno in range(doc.page_count):
        for info in doc[pno].get_images(full=True):
            xref = info[0]
            if xref in seen:
                continue
            seen.add(xref)
            try:
                img = doc.extract_image(xref)
            except Exception:
                continue
            path = os.path.join(folder, f"image_{xref}.{img['ext']}")
            with open(path, "wb") as fh:
                fh.write(img["image"])
            written.append(path)
    return written


# ------------------------------------------------------------------- security
def encrypt_bytes(doc: fitz.Document, user_pw: str, owner_pw: str = "",
                  allow_print: bool = True, allow_copy: bool = True,
                  allow_annotate: bool = True, allow_modify: bool = True) -> bytes:
    perm = int(fitz.PDF_PERM_ACCESSIBILITY)
    if allow_print:
        perm |= fitz.PDF_PERM_PRINT | fitz.PDF_PERM_PRINT_HQ
    if allow_copy:
        perm |= fitz.PDF_PERM_COPY
    if allow_annotate:
        perm |= fitz.PDF_PERM_ANNOTATE
    if allow_modify:
        perm |= fitz.PDF_PERM_MODIFY | fitz.PDF_PERM_ASSEMBLE | fitz.PDF_PERM_FORM
    return doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw=owner_pw or user_pw,
                       user_pw=user_pw, permissions=perm, garbage=3, deflate=True)


def decrypt_bytes(doc: fitz.Document) -> bytes:
    return doc.tobytes(encryption=fitz.PDF_ENCRYPT_NONE, garbage=3, deflate=True)
