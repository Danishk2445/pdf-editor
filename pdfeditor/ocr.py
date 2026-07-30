"""Optical character recognition: giving a scanned page a text layer.

A page that came out of a scanner or a phone camera holds only a *picture* of
its text, so every text feature in this editor - find, replace, Edit Text, copy,
text export - has nothing to work on.  Recognition fixes that: Tesseract reads
the glyphs out of the image and we write the characters back into the page as an
*invisible* text layer (PDF render mode 3) sitting over the ink.  The page looks
exactly as it did, and is now searchable, selectable and editable.

Nothing about the original page is destroyed - the layer is added on top - so a
recognised page still carries its scan at full quality and OCR is undoable like
any other edit.

The recogniser is a native program the operating system installs, not a Python
package, so it may simply be absent.  :func:`available` reports that up front
and lets the UI disable itself instead of failing halfway through a document.
"""

from __future__ import annotations

import glob
import os
import shutil
from dataclasses import dataclass, field

import fitz

DEFAULT_DPI = 300
DEFAULT_LANGUAGE = "eng"
TESSDATA_ENV = "TESSDATA_PREFIX"

# Base-14 fonts can only encode Latin-1, and MuPDF quietly writes a middle dot
# for anything outside it - which would make the layer look fine and extract as
# gibberish.  The built-in CJK faces cover much more, so try them in turn.
_FONT_CANDIDATES = ("helv", "china-s", "japan", "korea")

# Typography a recogniser hands back readily and Latin-1 has no room for.  Fold
# it to the plain equivalent rather than storing a middle dot: nobody searching
# a document types a curly apostrophe, so "don't" is the more useful spelling of
# "don't" even where the font could manage both.
_FOLD = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "′": "'", "ʼ": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "″": '"', "«": '"', "»": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-",
    "—": "-", "―": "-", "−": "-", "⁃": "-",
    "…": "...", "•": "·", "‧": "·",
    " ": " ", " ": " ", " ": " ", "​": "",
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi",
    "ﬄ": "ffl", "Œ": "OE", "œ": "oe",
}

# Recognition of a stray mark can hand back a box a millimetre wide holding ten
# characters; clamp the size it implies so one artefact cannot produce text the
# rest of the app then has to lay out.
_MIN_SIZE = 1.0
_MAX_SIZE = 400.0

# Recognition wants resolution, but a page is rendered whole and held in memory
# while it runs: 40 megapixels is about 120 MB, and past that the dpi is walked
# back rather than risking the process on a poster-sized page.
_MAX_PIXELS = 40_000_000

# Language codes worth naming; anything else is shown as the bare code.
LANGUAGE_NAMES = {
    "afr": "Afrikaans", "ara": "Arabic", "aze": "Azerbaijani",
    "bel": "Belarusian", "ben": "Bengali", "bul": "Bulgarian",
    "cat": "Catalan", "ces": "Czech", "chi_sim": "Chinese (simplified)",
    "chi_tra": "Chinese (traditional)", "dan": "Danish", "deu": "German",
    "ell": "Greek", "eng": "English", "epo": "Esperanto", "est": "Estonian",
    "eus": "Basque", "fas": "Persian", "fin": "Finnish", "fra": "French",
    "gle": "Irish", "glg": "Galician", "heb": "Hebrew", "hin": "Hindi",
    "hrv": "Croatian", "hun": "Hungarian", "ind": "Indonesian",
    "isl": "Icelandic", "ita": "Italian", "jpn": "Japanese", "kat": "Georgian",
    "kor": "Korean", "lat": "Latin", "lav": "Latvian", "lit": "Lithuanian",
    "mal": "Malayalam", "mkd": "Macedonian", "msa": "Malay", "nld": "Dutch",
    "nor": "Norwegian", "pol": "Polish", "por": "Portuguese",
    "ron": "Romanian", "rus": "Russian", "slk": "Slovak", "slv": "Slovenian",
    "spa": "Spanish", "sqi": "Albanian", "srp": "Serbian", "swa": "Swahili",
    "swe": "Swedish", "tam": "Tamil", "tel": "Telugu", "tha": "Thai",
    "tur": "Turkish", "ukr": "Ukrainian", "urd": "Urdu", "vie": "Vietnamese",
    "yid": "Yiddish",
}

# Not a language: orientation and script detection.
_NOT_A_LANGUAGE = {"osd", "equ"}

INSTALL_HINT = (
    "Recognition needs Tesseract, which the system installs separately:\n\n"
    "    Windows   winget install UB-Mannheim.TesseractOCR\n"
    "    Arch      sudo pacman -S tesseract tesseract-data-eng\n"
    "    Debian    sudo apt install tesseract-ocr tesseract-ocr-eng\n"
    "    macOS     brew install tesseract\n\n"
    "Install it, then restart PDF Studio.\n\n"
    "If it is already installed somewhere unusual, point the "
    "TESSDATA_PREFIX environment variable at the folder holding the "
    "*.traineddata files.")


# ------------------------------------------------------------- availability
def _has_language_data(path: str | None) -> bool:
    """True when ``path`` is a directory actually holding language data."""
    return bool(path) and bool(glob.glob(os.path.join(path, "*.traineddata")))


def _tessdata_candidates():
    """Places Tesseract's language data turns up, best guess first."""
    env = os.environ.get(TESSDATA_ENV)
    if env:
        yield env
        # TESSDATA_PREFIX has meant the *parent* of tessdata for most of
        # Tesseract's life, and plenty of installs still set it that way.
        yield os.path.join(env, "tessdata")
    # Alongside the binary, which is where the Windows installer puts it and
    # where a Homebrew or self-built install can end up too.
    binary = shutil.which("tesseract")
    if binary:
        near = os.path.dirname(os.path.abspath(binary))
        yield os.path.join(near, "tessdata")
        parent = os.path.dirname(near)
        yield os.path.join(parent, "share", "tessdata")
        yield os.path.join(parent, "share", "tesseract-ocr", "tessdata")
    for base in (r"C:\Program Files\Tesseract-OCR",
                 r"C:\Program Files (x86)\Tesseract-OCR",
                 r"C:\Tesseract-OCR"):
        yield os.path.join(base, "tessdata")
    for path in ("/usr/share/tessdata", "/usr/local/share/tessdata",
                 "/usr/share/tesseract-ocr/tessdata",
                 "/opt/homebrew/share/tessdata"):
        yield path


def tessdata() -> str | None:
    """Directory holding Tesseract's language data, or ``None`` if unavailable.

    MuPDF is asked first, so a hit here means the recogniser this editor would
    actually call is present - not merely that a ``tesseract`` binary is
    somewhere on ``PATH``.

    MuPDF only consults ``TESSDATA_PREFIX`` though, and the Windows installer
    does not set it, which would leave recognition looking unavailable on a
    machine where it is installed and working.  So when MuPDF comes up empty we
    go looking, and export what we find for the rest of the process.

    What MuPDF hands back is checked rather than trusted, because it echoes
    ``TESSDATA_PREFIX`` without looking: a stale or misaimed value would
    otherwise be reported as a working install and fail later, mid-document.
    """
    try:
        found = fitz.get_tessdata()          # False when it cannot find them
    except Exception:
        found = None
    if _has_language_data(found):
        return found

    for candidate in _tessdata_candidates():
        if _has_language_data(candidate):
            os.environ[TESSDATA_ENV] = candidate
            return candidate
    return None


def languages(path: str | None = None) -> list[str]:
    """Installed language codes, best guess at useful order, ``eng`` first."""
    path = path or tessdata()
    if not path:
        return []
    found = set()
    for name in glob.glob(os.path.join(path, "*.traineddata")):
        code = os.path.basename(name)[: -len(".traineddata")]
        if code and code not in _NOT_A_LANGUAGE:
            found.add(code)
    codes = sorted(found, key=lambda c: (c != DEFAULT_LANGUAGE, language_label(c)))
    return codes


def language_label(code: str) -> str:
    name = LANGUAGE_NAMES.get(code)
    return f"{name} ({code})" if name else code


def available() -> bool:
    """True when a page can actually be recognised."""
    return bool(languages())


# ------------------------------------------------------------------ probing
def has_text(page: fitz.Page) -> bool:
    """True when the page already carries extractable text.

    The guard against recognising a page twice: a second layer would double
    every word for search and text export.
    """
    try:
        return bool(page.get_text("text").strip())
    except Exception:
        return False


def needs_ocr(doc: fitz.Document, indices=None) -> list[int]:
    """Pages with no text of their own - the ones OCR has something to add to."""
    if indices is None:
        indices = range(doc.page_count)
    return [i for i in indices if not has_text(doc[i])]


# --------------------------------------------------------------- text layer
_INK_CACHE: dict[str, tuple[float, float]] = {}


def ink_span(name: str) -> tuple[float, float]:
    """``(cap_height, descender_depth)`` of a font, in em, both positive.

    How far the *ink* of a normal line of type reaches above and below the
    baseline - which is what Tesseract measures, so it is what the layer has to
    be matched against.  Read from the font's own glyphs rather than assumed,
    because the em box is a good deal taller than the ink and using it would
    undersize every word by a third.
    """
    if name not in _INK_CACHE:
        cap = depth = None
        try:
            font = fitz.Font(name)
            cap = font.glyph_bbox(ord("H")).y1
            depth = -font.glyph_bbox(ord("p")).y0
            if not (0.2 < cap <= 1.5) or not (0.0 <= depth < 0.8):
                cap = depth = None          # implausible; fall back below
        except Exception:
            pass
        if cap is None:
            try:
                font = fitz.Font(name)
                cap, depth = font.ascender, -font.descender
            except Exception:
                cap, depth = 0.73, 0.22     # Helvetica's, near enough
        _INK_CACHE[name] = (float(cap), float(depth))
    return _INK_CACHE[name]


def fold(text: str) -> str:
    """Rewrite typography that no available font can store."""
    return "".join(_FOLD.get(c, c) for c in text)


def _coverage(name: str, chars: str) -> set[str]:
    """Which of ``chars`` survive a round trip through font ``name``.

    Asked by writing them into a scratch page and reading them back, because
    the interesting failure is silent: a base-14 font accepts Cyrillic happily
    and stores a row of middle dots.
    """
    if not chars:
        return set()
    scratch = fitz.open()
    page = scratch.new_page(width=2400, height=30 * (len(chars) // 48 + 2))
    try:
        for row, start in enumerate(range(0, len(chars), 48)):
            page.insert_text((12, 24 + row * 26), chars[start:start + 48],
                             fontname=name, fontsize=11, render_mode=3)
        got = set(page.get_text("text"))
    except Exception:
        return set()
    finally:
        scratch.close()
    return {c for c in chars if c in got}


def choose_font(text: str) -> tuple[str, str]:
    """Pick a font for the layer: ``(fontname, characters_it_cannot_store)``.

    Whichever candidate carries the most of the text wins.  A non-empty second
    element is worth saying out loud - those characters reach the page as middle
    dots, so a search for the words holding them will never match - rather than
    leaving the user to discover it later.
    """
    chars = "".join(sorted({c for c in text if not c.isspace()}))
    best_name, best = _FONT_CANDIDATES[0], set()
    for name in _FONT_CANDIDATES:
        covered = _coverage(name, chars)
        if len(covered) > len(best):
            best_name, best = name, covered
        if len(best) == len(chars):
            break
    return best_name, "".join(c for c in chars if c not in best)


def _place(metrics: tuple[float, float], box) -> tuple[float, float]:
    """``(fontsize, baseline)`` that sit a word on its recognised box.

    Size comes from the box *height*.  Tesseract reports one box per text line,
    so the height is a stable reading of the type size, while the width is the
    ink of this particular word: fitting to that collapses anything narrow, and
    a page number reading "1" would come back at a third of its real size.
    Checked against pages whose real text is known, height gives the true size
    to within a few percent and the baseline to within half a point.
    """
    cap, depth = metrics
    _x0, y0, _x1, y1 = box
    height = max(y1 - y0, 0.01)
    size = min(max(height / (cap + depth), _MIN_SIZE), _MAX_SIZE)
    return size, y1 - depth * size


@dataclass
class PageLayer:
    """What recognition found on one page."""
    page: int
    words: int = 0
    text: str = ""
    fontname: str = ""
    unstorable: str = ""                    # characters no font could carry

    @property
    def empty(self) -> bool:
        return self.words == 0

    @property
    def complete(self) -> bool:
        return not self.unstorable


class OCRError(RuntimeError):
    """Recognition could not run - a missing language, usually."""


class NothingRecognised(Exception):
    """A run that found nothing to add, so it should not cost an undo step."""
    expected = True                        # report it quietly, not as a fault


def render_dpi(page: fitz.Page, dpi: int) -> int:
    """``dpi`` reduced if it would render an unreasonably large image."""
    scale = dpi / 72.0
    pixels = page.rect.width * scale * page.rect.height * scale
    if pixels <= _MAX_PIXELS:
        return dpi
    return max(72, int(dpi * (_MAX_PIXELS / pixels) ** 0.5))


def read_page(page: fitz.Page, *, language: str = DEFAULT_LANGUAGE,
              dpi: int = DEFAULT_DPI) -> list[tuple]:
    """Recognise ``page`` and return word tuples ``(x0, y0, x1, y1, word, …)``.

    Coordinates come back in display space, the same system as ``page.rect``
    and as the rest of this package.

    The page is rendered here and the picture handed to the recogniser, rather
    than going through MuPDF's OCR text page: that route drops the top of a
    rotated page - measured, on a page the same recogniser reads in full from
    an image we render ourselves - and losing a quarter of a scan silently is
    not a trade worth making.  Rendering also fixes the resolution the
    recogniser sees, which is the one knob that matters for accuracy.
    """
    pixmap = page.get_pixmap(dpi=render_dpi(page, dpi))
    try:
        data = pixmap.pdfocr_tobytes(compress=True, language=language,
                                     tessdata=tessdata())
    except Exception as exc:
        raise OCRError(
            f"Recognition failed for language {language!r}: {exc}") from exc
    finally:
        del pixmap

    recognised = fitz.open("pdf", data)
    try:
        box = recognised[0].rect
        words = recognised[0].get_text("words")
        # The rendered page is the page as the reader sees it, so the only
        # difference left is the scale between pixels-at-dpi and points.
        sx = page.rect.width / box.width if box.width else 1.0
        sy = page.rect.height / box.height if box.height else 1.0
    finally:
        recognised.close()
    if sx == 1.0 and sy == 1.0:
        return words
    return [(w[0] * sx, w[1] * sy, w[2] * sx, w[3] * sy) + tuple(w[4:])
            for w in words]


def _same_line(word: tuple, words: list[tuple], index: int) -> bool:
    """True when ``words[index]`` continues the text line ``word`` is on.

    Word tuples carry their block and line number; anything shorter than that
    (a hand-built tuple) is treated as standing alone.
    """
    if index >= len(words) or len(word) < 7:
        return False
    other = words[index]
    return len(other) >= 7 and tuple(other[5:7]) == tuple(word[5:7])


def add_layer(page: fitz.Page, words: list[tuple], *,
              fontname: str | None = None) -> PageLayer:
    """Write ``words`` into ``page`` as an invisible text layer."""
    layer = PageLayer(page=page.number or 0)
    usable = [w for w in words if len(w) >= 5 and w[4].strip()]
    if not usable:
        return layer

    layer.text = fold(" ".join(w[4] for w in usable))
    if fontname:
        name, unstorable = fontname, ""
    else:
        name, unstorable = choose_font(layer.text)
    layer.fontname = name
    layer.unstorable = unstorable
    metrics = ink_span(name)

    # insert_text takes display coordinates and compensates for page rotation
    # itself, so the words go straight back where they were read.  Unlike the
    # text rewriter this needs no flip to rotation 0; measured across all four
    # rotations, flipping changes nothing here.
    for position, word in enumerate(usable):
        # Each word is placed on its own recognised box, so nothing but a gap
        # separates it from the next.  Correctly sized text closes that gap far
        # enough that extraction reads "Revenuegrew", so carry a real space
        # into the layer - except at the end of a line, which already breaks.
        text = fold(word[4]) + (" " if _same_line(word, usable, position + 1)
                                else "")
        size, baseline = _place(metrics, word[:4])
        try:
            page.insert_text(fitz.Point(word[0], baseline), text,
                             fontname=name, fontsize=size,
                             render_mode=3, color=(0, 0, 0), overlay=True)
        except Exception:
            # One unrepresentable word must not cost the whole page.
            continue
        layer.words += 1
    return layer


# ------------------------------------------------------------------ document
@dataclass
class Result:
    """Outcome of a recognition run, for the status line and the undo label."""
    recognised: list[int] = field(default_factory=list)
    skipped: list[int] = field(default_factory=list)
    empty: list[int] = field(default_factory=list)
    incomplete: list[int] = field(default_factory=list)
    failed: list[int] = field(default_factory=list)
    words: int = 0
    unstorable: str = ""
    cancelled: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.recognised)

    def summary(self) -> str:
        if not self.recognised:
            if self.cancelled:
                return "Recognition cancelled"
            if self.skipped and not self.empty:
                return ("Nothing to recognise - "
                        f"{len(self.skipped)} page(s) already carry text")
            return "Found no text to recognise"
        bits = [f"Recognised {self.words} word(s) on "
                f"{len(self.recognised)} page(s)"]
        if self.skipped:
            bits.append(f"{len(self.skipped)} already had text")
        if self.empty:
            bits.append(f"{len(self.empty)} came back empty")
        if self.failed:
            bits.append(f"{len(self.failed)} could not be read")
        if self.incomplete:
            shown = self.unstorable[:8]
            bits.append(f"{len(self.incomplete)} hold characters no available "
                        f"font can store ({shown})")
        if self.cancelled:
            bits.append("cancelled early")
        return "; ".join(bits)


def ocr_pages(doc: fitz.Document, indices, *, language: str = DEFAULT_LANGUAGE,
              dpi: int = DEFAULT_DPI, skip_with_text: bool = True,
              progress=None) -> Result:
    """Add a text layer to each of ``indices``, returning what happened.

    ``progress(done, total, page_index)`` is called before each page and may
    return ``False`` to stop; pages already finished keep their layer, so a
    cancelled run is still a coherent edit.

    The caller is expected to have opened a :meth:`Document.edit` transaction,
    as with everything else that mutates the document.
    """
    wanted = [i for i in dict.fromkeys(indices) if 0 <= i < doc.page_count]
    result = Result()
    total = len(wanted)
    for done, index in enumerate(wanted):
        if progress is not None and progress(done, total, index) is False:
            result.cancelled = True
            break
        page = doc[index]
        if skip_with_text and has_text(page):
            result.skipped.append(index)
            continue
        try:
            words = read_page(page, language=language, dpi=dpi)
        except OCRError:
            # The recogniser itself is unusable, so the next page will fail the
            # same way; let the caller roll the whole run back.
            raise
        except Exception:
            # One page this recogniser cannot render must not discard the work
            # already done on a long document.
            result.failed.append(index)
            continue
        layer = add_layer(page, words)
        if layer.empty:
            result.empty.append(index)
            continue
        result.recognised.append(index)
        result.words += layer.words
        if not layer.complete:
            result.incomplete.append(index)
            for char in layer.unstorable:
                if char not in result.unstorable:
                    result.unstorable += char
    if progress is not None and not result.cancelled:
        progress(total, total, -1)
    return result
