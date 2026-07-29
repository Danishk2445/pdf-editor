"""Page rasterisation with a size-bounded cache.

Scene coordinates are PDF points, so the view transform alone provides zoom.
``PageRenderer.pixmap`` is asked for a *level of detail* (device pixels per
point) which is bucketed to keep cache churn down while zooming.
"""

from __future__ import annotations

from collections import OrderedDict

import fitz
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap

# Cache ceiling in bytes for full page renders.
CACHE_BUDGET = 320 * 1024 * 1024
MAX_LOD = 4.0
MIN_LOD = 0.15


def bucket(lod: float) -> float:
    """Snap a level of detail onto a coarse ladder so we re-render rarely."""
    lod = max(MIN_LOD, min(MAX_LOD, float(lod)))
    steps = (0.15, 0.25, 0.4, 0.55, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0)
    for s in steps:
        if lod <= s * 1.001:
            return s
    return MAX_LOD


def pixmap_from_fitz(pix: fitz.Pixmap) -> QPixmap:
    fmt = QImage.Format_RGBA8888 if pix.alpha else QImage.Format_RGB888
    img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
    # samples is a temporary buffer - copy before it goes away.
    return QPixmap.fromImage(img.copy())


class PageRenderer:
    def __init__(self, document):
        self.document = document
        self._cache: OrderedDict[tuple, QPixmap] = OrderedDict()
        self._thumbs: OrderedDict[tuple, QPixmap] = OrderedDict()
        self._bytes = 0
        self._revision = -1

    # ------------------------------------------------------------------ cache
    def _check_revision(self):
        rev = self.document.revision
        if rev != self._revision:
            self._revision = rev
            self._cache.clear()
            self._thumbs.clear()
            self._bytes = 0

    def invalidate(self, index: int | None = None):
        if index is None:
            self._cache.clear()
            self._thumbs.clear()
            self._bytes = 0
            return
        for store in (self._cache, self._thumbs):
            for key in [k for k in store if k[0] == index]:
                store.pop(key, None)
        self._bytes = sum(p.width() * p.height() * 4 for p in self._cache.values())

    def _store(self, key, pm: QPixmap):
        self._cache[key] = pm
        self._bytes += pm.width() * pm.height() * 4
        while self._bytes > CACHE_BUDGET and len(self._cache) > 2:
            _k, old = self._cache.popitem(last=False)
            self._bytes -= old.width() * old.height() * 4

    # ----------------------------------------------------------------- render
    def pixmap(self, index: int, lod: float) -> QPixmap | None:
        """Rendered page at the requested detail, or ``None`` if unavailable."""
        self._check_revision()
        if not self.document.is_open or not (0 <= index < self.document.page_count):
            return None
        lod = bucket(lod)
        key = (index, lod)
        hit = self._cache.get(key)
        if hit is not None:
            self._cache.move_to_end(key)
            return hit
        try:
            page = self.document.page(index)
            pix = page.get_pixmap(matrix=fitz.Matrix(lod, lod), alpha=False,
                                  annots=True)
            pm = pixmap_from_fitz(pix)
        except Exception:
            return None
        self._store(key, pm)
        return pm

    def best_available(self, index: int, lod: float) -> QPixmap | None:
        """Any cached render for this page - used as a stand-in while zooming."""
        want = bucket(lod)
        best, best_d = None, 1e9
        for (i, l), pm in self._cache.items():
            if i != index:
                continue
            d = abs(l - want)
            if d < best_d:
                best, best_d = pm, d
        return best

    # -------------------------------------------------------------- thumbnail
    def thumbnail(self, index: int, width: int = 150) -> QPixmap | None:
        self._check_revision()
        if not self.document.is_open or not (0 <= index < self.document.page_count):
            return None
        key = (index, width)
        hit = self._thumbs.get(key)
        if hit is not None:
            self._thumbs.move_to_end(key)
            return hit
        try:
            page = self.document.page(index)
            scale = width / max(1.0, page.rect.width)
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False,
                                  annots=True)
            pm = pixmap_from_fitz(pix)
        except Exception:
            return None
        self._thumbs[key] = pm
        while len(self._thumbs) > 400:
            self._thumbs.popitem(last=False)
        return pm

    def render_region(self, index: int, rect: fitz.Rect, lod: float = 2.0) -> QPixmap | None:
        """Render just part of a page - used by the loupe / colour picker."""
        try:
            page = self.document.page(index)
            pix = page.get_pixmap(matrix=fitz.Matrix(lod, lod), clip=rect,
                                  alpha=False, annots=True)
            return pixmap_from_fitz(pix)
        except Exception:
            return None
