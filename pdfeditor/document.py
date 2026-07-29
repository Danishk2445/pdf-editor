"""Document model: a PyMuPDF document plus snapshot based undo/redo.

Every mutation goes through :meth:`Document.edit`, which takes a snapshot of the
file *before* the change.  Snapshots are whole-document byte images, which is a
blunt instrument but makes undo bulletproof for operations that are otherwise
awkward to reverse (applying redactions, deleting pages, re-embedding fonts).
History is capped so memory stays bounded.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

import fitz

MAX_HISTORY = 40
# Snapshots are whole-file images, so a big PDF eats memory fast.  Keep the
# combined history under a budget and drop the oldest steps to stay inside it.
HISTORY_BUDGET = 512 * 1024 * 1024
DEFAULT_PAGE = (595.0, 842.0)          # A4 in points


class DocumentError(Exception):
    pass


class PasswordRequired(DocumentError):
    pass


class Document:
    """Owns the ``fitz.Document`` and the undo stacks."""

    def __init__(self):
        self.doc: fitz.Document | None = None
        self.path: str | None = None
        self.revision = 0            # bumped on every change; caches key off it
        self.dirty = False
        self._undo: list[tuple[str, bytes]] = []
        self._redo: list[tuple[str, bytes]] = []
        self._listeners: list = []

    # ------------------------------------------------------------------ state
    @property
    def is_open(self) -> bool:
        return self.doc is not None and not self.doc.is_closed

    @property
    def page_count(self) -> int:
        return self.doc.page_count if self.is_open else 0

    @property
    def title(self) -> str:
        if self.path:
            return os.path.basename(self.path)
        return "Untitled.pdf" if self.is_open else "No document"

    def page(self, index: int) -> fitz.Page:
        return self.doc[index]

    def page_rect(self, index: int) -> fitz.Rect:
        return self.doc[index].rect

    # -------------------------------------------------------------- listeners
    def subscribe(self, callback):
        """callback(kind) where kind is 'document' | 'content' | 'meta'."""
        self._listeners.append(callback)

    def notify(self, kind: str = "content"):
        for cb in list(self._listeners):
            cb(kind)

    # ------------------------------------------------------------- open/close
    def new(self, width: float = DEFAULT_PAGE[0], height: float = DEFAULT_PAGE[1]):
        self.close()
        self.doc = fitz.open()
        self.doc.new_page(width=width, height=height)
        self.path = None
        self._reset_history()
        self.dirty = True
        self.revision += 1
        self.notify("document")

    def open(self, path: str, password: str | None = None):
        doc = fitz.open(path)
        if doc.needs_pass:
            if password is None or not doc.authenticate(password):
                doc.close()
                raise PasswordRequired(path)
        if not doc.is_pdf:
            # Convert images / XPS / EPUB etc. into a PDF we can actually edit.
            try:
                pdf_bytes = doc.convert_to_pdf()
                doc.close()
                doc = fitz.open("pdf", pdf_bytes)
            except Exception as exc:                    # pragma: no cover
                doc.close()
                raise DocumentError(f"Cannot convert {path!r} to PDF: {exc}")
        self.close()
        self.doc = doc
        self.path = path if doc.is_pdf else None
        self._reset_history()
        self.dirty = False
        self.revision += 1
        self.notify("document")

    def close(self):
        if self.doc is not None and not self.doc.is_closed:
            self.doc.close()
        self.doc = None
        self.path = None
        self._reset_history()
        self.dirty = False

    # ------------------------------------------------------------------ save
    def save(self, path: str | None = None, *, incremental: bool = False, **opts):
        if not self.is_open:
            raise DocumentError("No document to save")
        target = path or self.path
        if not target:
            raise DocumentError("No destination path")

        same_file = (self.path is not None and
                     os.path.abspath(target) == os.path.abspath(self.path))
        kwargs = dict(garbage=3, deflate=True, clean=True)
        kwargs.update(opts)
        if incremental and same_file:
            kwargs = dict(incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)

        if same_file and not kwargs.get("incremental"):
            # Saving over the open file needs an atomic dance: MuPDF still has
            # the original mapped, so write beside it and swap.
            tmp = target + ".pdfstudio.tmp"
            self.doc.save(tmp, **kwargs)
            os.replace(tmp, target)
            data = open(target, "rb").read()
            self.doc.close()
            self.doc = fitz.open("pdf", data)
        else:
            self.doc.save(target, **kwargs)

        self.path = target
        self.dirty = False
        self.revision += 1
        self.notify("document")

    def to_bytes(self) -> bytes:
        return self.doc.tobytes(garbage=3, deflate=True)

    # --------------------------------------------------------------- editing
    @contextmanager
    def edit(self, label: str):
        """Snapshot, then run the mutation.  Rolls back if it raises."""
        if not self.is_open:
            raise DocumentError("No document open")
        snapshot = self._serialise()
        try:
            yield self.doc
        except Exception:
            self._restore(snapshot)          # leave the document untouched
            raise
        self._undo.append((label, snapshot))
        self._trim_history()
        self._redo.clear()
        self.dirty = True
        self.revision += 1
        self.notify("content")

    def _trim_history(self):
        while len(self._undo) > MAX_HISTORY:
            self._undo.pop(0)
        total = sum(len(data) for _label, data in self._undo)
        # Always keep at least one step so undo never becomes a no-op.
        while total > HISTORY_BUDGET and len(self._undo) > 1:
            total -= len(self._undo.pop(0)[1])

    def history_bytes(self) -> int:
        return sum(len(d) for _l, d in self._undo) + \
               sum(len(d) for _l, d in self._redo)

    def touch(self, kind: str = "content"):
        """Mark changed without a snapshot (for edits made in place)."""
        self.dirty = True
        self.revision += 1
        self.notify(kind)

    # ------------------------------------------------------------ undo / redo
    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_label(self) -> str:
        return self._undo[-1][0] if self._undo else ""

    @property
    def redo_label(self) -> str:
        return self._redo[-1][0] if self._redo else ""

    def undo(self) -> str | None:
        if not self._undo:
            return None
        label, data = self._undo.pop()
        self._redo.append((label, self._serialise()))
        self._restore(data)
        self.dirty = True
        self.revision += 1
        self.notify("document")
        return label

    def redo(self) -> str | None:
        if not self._redo:
            return None
        label, data = self._redo.pop()
        self._undo.append((label, self._serialise()))
        self._restore(data)
        self.dirty = True
        self.revision += 1
        self.notify("document")
        return label

    # ---------------------------------------------------------------- private
    def _reset_history(self):
        self._undo.clear()
        self._redo.clear()

    def _serialise(self) -> bytes:
        return self.doc.tobytes(garbage=0, deflate=True)

    def _restore(self, data: bytes):
        old = self.doc
        self.doc = fitz.open("pdf", data)
        if old is not None and not old.is_closed:
            old.close()

    # ------------------------------------------------------------- metadata
    def metadata(self) -> dict:
        return dict(self.doc.metadata or {}) if self.is_open else {}

    def set_metadata(self, meta: dict):
        with self.edit("Change document properties"):
            self.doc.set_metadata(meta)

    def outline(self):
        return self.doc.get_toc(simple=True) if self.is_open else []
