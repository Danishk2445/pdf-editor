"""Font resolution for text that we write back into a page.

When the user retypes a line we want the replacement to look like the original.
Best case we reuse the very font that is already embedded in the file; when that
font is subsetted (and therefore missing glyphs for the newly typed characters)
we fall back to whichever base-14 font is the closest match.
"""

from __future__ import annotations

import re

import fitz

# base-14 aliases: (regular, bold, italic, bold-italic)
SANS  = ("helv", "hebo", "heit", "hebi")
SERIF = ("tiro", "tibo", "tiit", "tibi")
MONO  = ("cour", "cobo", "coit", "cobi")

BASE14_LABELS = {
    "helv": "Helvetica", "hebo": "Helvetica Bold",
    "heit": "Helvetica Italic", "hebi": "Helvetica Bold Italic",
    "tiro": "Times", "tibo": "Times Bold",
    "tiit": "Times Italic", "tibi": "Times Bold Italic",
    "cour": "Courier", "cobo": "Courier Bold",
    "coit": "Courier Italic", "cobi": "Courier Bold Italic",
    "symb": "Symbol", "zapf": "Zapf Dingbats",
}

# The family list offered in the inspector when adding brand new text.
FAMILIES = [("Helvetica", SANS), ("Times", SERIF), ("Courier", MONO)]

_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")

_SERIF_HINTS = ("times", "serif", "georgia", "garamond", "roman", "book",
                "minion", "cambria", "palatino", "century", "utopia", "charter")
_MONO_HINTS = ("mono", "courier", "consol", "menlo", "inconsolata", "code")
_BOLD_HINTS = ("bold", "black", "heavy", "semibold", "demibold", "extrabold",
               "-bd", "medi")
_ITALIC_HINTS = ("italic", "oblique", "-it")


def strip_subset(name: str) -> str:
    return _SUBSET_PREFIX.sub("", name or "")


def classify(font_name: str, flags: int = 0) -> tuple[tuple, bool, bool]:
    """Guess (family_tuple, bold, italic) from a PDF font name."""
    name = strip_subset(font_name or "").lower()
    bold = any(h in name for h in _BOLD_HINTS)
    italic = any(h in name for h in _ITALIC_HINTS)
    # PyMuPDF span flags: bit 1 = italic, bit 4 = bold, bit 3 = serif
    if flags:
        italic = italic or bool(flags & 2)
        bold = bold or bool(flags & 16)
    if any(h in name for h in _MONO_HINTS):
        family = MONO
    elif any(h in name for h in _SERIF_HINTS) or (flags and flags & 4):
        family = SERIF
    else:
        family = SANS
    return family, bold, italic


def base14_for(font_name: str, flags: int = 0) -> str:
    family, bold, italic = classify(font_name, flags)
    return pick(family, bold, italic)


def pick(family: tuple, bold: bool, italic: bool) -> str:
    return family[(1 if bold else 0) + (2 if italic else 0)]


def label_for(alias: str) -> str:
    return BASE14_LABELS.get(alias, alias)


def _page_font_buffer(doc: fitz.Document, page: fitz.Page, font_name: str):
    """Find the embedded font file for ``font_name`` as used on ``page``."""
    want = strip_subset(font_name).lower()
    if not want:
        return None
    for entry in page.get_fonts(full=True):
        xref, _ext, _ftype, basefont = entry[0], entry[1], entry[2], entry[3]
        if strip_subset(basefont).lower() != want:
            continue
        try:
            _name, ext, _ftype2, buf = doc.extract_font(xref)
        except Exception:
            continue
        if buf and ext in ("ttf", "otf", "cff", "pfa", "pfb", "type1", "ttc"):
            return buf
    return None


def _covers(buffer: bytes, text: str) -> bool:
    """True when the font buffer has a glyph for every character in text."""
    try:
        font = fitz.Font(fontbuffer=buffer)
    except Exception:
        return False
    for ch in set(text):
        if ch in "\r\n\t":
            continue
        try:
            if not font.has_glyph(ord(ch)):
                return False
        except Exception:
            return False
    return True


_counter = [0]


def resolve(doc: fitz.Document, page: fitz.Page, font_name: str,
            flags: int, text: str) -> tuple[str, bytes | None]:
    """Return ``(fontname, fontbuffer)`` ready for ``page.insert_text``.

    Prefers the file's own embedded font so replacement text is visually
    identical; falls back to a base-14 look-alike when that is impossible.
    """
    buf = _page_font_buffer(doc, page, font_name)
    if buf and _covers(buf, text):
        _counter[0] += 1
        alias = "PSE%d" % _counter[0]
        try:
            page.insert_font(fontname=alias, fontbuffer=buf)
            return alias, buf
        except Exception:
            pass
    return base14_for(font_name, flags), None


def text_width(text: str, fontname: str, fontsize: float,
               fontbuffer: bytes | None = None) -> float:
    """Width of ``text`` in points, for fitting replacement text to a box."""
    if fontbuffer:
        try:
            return fitz.Font(fontbuffer=fontbuffer).text_length(text, fontsize)
        except Exception:
            pass
    try:
        return fitz.get_text_length(text, fontname=fontname, fontsize=fontsize)
    except Exception:
        return fitz.get_text_length(text, fontname="helv", fontsize=fontsize)
