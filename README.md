# PDF Studio

An interactive PDF editor in Python — retype text that is already in the file,
read the text out of scanned pages, move and resize the things on the page,
annotate, redact, reorganise pages and fill forms. Built on **PySide6** (Qt 6)
and **PyMuPDF**.

![tools](https://img.shields.io/badge/tools-21-2f6fd0) ![python](https://img.shields.io/badge/python-3.9%2B-3776ab)

---

## Run it

```bash
./pdf-studio                 # uses the bundled .venv
./pdf-studio sample.pdf      # or open a file straight away
```

First time on a fresh machine:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python make_sample.py     # writes sample.pdf to play with
./pdf-studio sample.pdf
```

On Windows, same thing with the launcher and paths Windows uses:

```bat
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python make_sample.py
pdf-studio.cmd sample.pdf
```

`pdf-studio.cmd` keeps a console window open alongside the app, which is where
errors go; swap `python.exe` for `pythonw.exe` in it if you would rather it ran
without one.

`sample.pdf` is a four-page report with real text, an embedded chart, a
landscape appendix and a working form — handy for trying every tool.

Reading scanned pages needs **Tesseract**, which is a system package rather than
a pip one — everything else comes from `requirements.txt`. Without it the editor
works as normal and the OCR menu entry explains what to install:

```bash
winget install UB-Mannheim.TesseractOCR          # Windows
sudo pacman -S tesseract tesseract-data-eng      # Arch
sudo apt install tesseract-ocr tesseract-ocr-eng # Debian/Ubuntu
brew install tesseract                           # macOS
```

You do not need to add it to `PATH` or set `TESSDATA_PREFIX` — the editor looks
in the usual install locations, including the ones the Windows installer uses,
and exports what it finds. If you keep the language data somewhere unusual, set
`TESSDATA_PREFIX` to the folder holding the `*.traineddata` files.

---

## What it can actually do

### Editing text that is already in the PDF

This is the part most Python PDF tools skip. Pick the **Edit Text** tool (`E`)
and hover the page — the line under the pointer is outlined.

| Action | Result |
| --- | --- |
| Click or double-click a line | Retype it in place. Enter applies, Esc cancels. |
| Drag a line | Move it to a new spot on the page. |
| Delete | Erase the hovered line. |
| Right-click ▸ Edit this paragraph | Reflow a whole block in a multi-line box. |
| … then clear the box and apply | Delete the whole paragraph in one step. |

Double-click works from the Select tool too — it switches to Edit Text for you.

The original glyphs are genuinely removed from the content stream with a
redaction, then the new text is written back. Position, size, colour and font
are matched: if the file embeds the font and it has the glyphs you typed, that
exact font is reused, otherwise the closest base-14 face is substituted.
Images, rules and background tints under the text are left untouched, and
rotated pages are handled by editing in unrotated space and restoring the
rotation afterwards.

### Find and replace

The Search tab in the sidebar (`Ctrl+F`) finds text across the document and
marks every hit on the page. Type into the second box and it becomes a
find-and-replace (`Ctrl+H` jumps straight there):

| Action | Result |
| --- | --- |
| **Replace** | Rewrites the highlighted hit, then lands on the next one. |
| **Replace all** | Rewrites every hit in the document as one undo step. |
| Empty replacement box | Deletes the matched text instead. |

Replacements go through the same rewriter as the Edit Text tool, so each hit
keeps the position, font, size and colour of the line it came from — the whole
line is re-laid, not patched. `Match case` applies to replacing as well as
finding. Leaving something that still matches (`cat` → `cats`) is fine:
Replace steps past what it just wrote instead of chewing through it, and
Replace all makes one pass.

A page with several hits is erased and re-laid in a single pass, so the hit
count you press Replace all on is the count you get. The result list refreshes
afterwards, which is also how you see anything that could not be rewritten.

### Scanned pages

A page that came from a scanner or a phone holds only a *picture* of its text,
so none of the above has anything to work on: search finds nothing, Edit Text
never outlines a line, text export comes back blank. **Pages ▸ Recognise Text
(OCR)** fixes that — it reads the glyphs out of the image and stores the
characters invisibly over the ink, so the page looks exactly as it did and is
now searchable, selectable and editable.

| | |
| --- | --- |
| Pages | Which pages to read, as a range. |
| Language | Whichever Tesseract language data you have installed. |
| Read at | Resolution to read at. 300 dpi suits most scans; 400+ helps small print, slowly. |
| Skip pages that already have text | On by default — reading a page twice gives it two copies of every word. |

The whole run is one undo step, and Cancel keeps the pages already done. The
page is rendered here and handed to the recogniser rather than going through
MuPDF's own OCR path, which drops the top of a rotated page.

Each word is placed on its own recognised box, at the size the box implies, so
selection and search highlights land on the ink they belong to — measured
against pages whose real text is known, word boxes overlap the true ones by 93%
on average at every page rotation. Typography the base fonts cannot hold is
folded to a plain equivalent (curly quotes, em dashes, `…`, `ﬁ`), which is also
what people actually type into the search box; text outside Latin-1 moves to a
font that covers it, and anything no available font can store is reported rather
than silently written as a middle dot.

### Moving objects around

The **Select** tool (`V`) puts grab handles on annotations, embedded images and
form fields. Drag to move, pull a corner to resize (Shift keeps the aspect
ratio), arrow keys nudge by 1 pt (Shift = 10 pt), Delete removes. The
Properties panel shows exact X/Y/W/H that you can type into, plus colour and
opacity for annotations.

Moving an image rewrites the placement matrix in the content stream rather than
re-inserting the picture, so the pixels are never re-encoded, the image keeps
its position in the drawing order, and you can drag it as many times as you
like without it degrading.

### The rest of the toolbox

- **Text** — select and copy (`T`), add new text at a point or in a wrapped box (`A`)
- **Markup** — highlight (`U`), underline, strike out, sticky notes (`N`)
- **Draw** — freehand ink (`D`), rectangle (`R`), ellipse (`O`), line (`L`), arrow
- **Insert** — images (`I`), signatures (`G`), stamps, hyperlinks (`K`)
- **Remove** — erase an area (`X`, samples the paper colour), true redaction, crop (`C`)
- **Pages** — insert, duplicate, delete, rotate, resize, reorder by dragging
  thumbnails, extract, split, import from another PDF
- **Document** — watermarks, page numbers, metadata, bookmarks, AES-256
  passwords and permissions, flatten annotations or form fields
- **Forms** — fill text fields, checkboxes, radio buttons and dropdowns
- **Export** — PNG/JPEG at any DPI, plain text, single-page PDFs, embedded images

Everything is one undo step. `Ctrl+Z` / `Ctrl+Shift+Z` walk the history, and the
Edit menu names the step it will reverse.

---

## Getting around

| | |
| --- | --- |
| `Ctrl+O` / `Ctrl+S` | Open / Save |
| `Ctrl+F`, `F3` | Find, find next |
| `Ctrl+H` | Find and replace |
| `Ctrl` + scroll | Zoom at the pointer |
| Space + drag | Pan |
| `Ctrl+1` / `Ctrl+0` | Fit width / fit page |
| `F9` / `F10` | Toggle sidebar / properties |
| `F1` | Full shortcut list |

Continuous, single-page and facing-page layouts; light and dark themes
(`Ctrl+Shift+D`). The sidebar carries page thumbnails, bookmarks and search
results. Drop a file on the window to open it.

The tool rail wraps into two or three columns when the window is too short for
one, so every tool stays on screen rather than disappearing into an overflow
chevron — which is what a single column of 21 tools does on a laptop screen, or
on any display running at 125% or 150% scaling.

Non-PDF inputs (XPS, EPUB, CBZ, PNG, JPEG…) are converted to PDF on open so you
can edit them, then saved as PDF.

---

## How it fits together

```
pdfeditor/
  document.py   PyMuPDF document + snapshot undo/redo
  textops.py    line/character index, in-place text rewriting, search
  ocr.py        recognising scanned pages into an invisible text layer
  pageops.py    page-level operations, watermarks, export, encryption
  imageops.py   moving/removing placed images by rewriting the content stream
  fonts.py      font matching, embedded-font reuse
  render.py     page rasterisation with a bounded cache
  items.py      QGraphicsItems: pages, overlays, resize handles
  view.py       the canvas — layout, zoom, panning, tool dispatch
  tools.py      21 tools, all sharing one ToolContext
  inspector.py  properties panel
  panels.py     thumbnails, bookmarks, search
  dialogs.py    signature pad, metadata, watermark, security, export
  icons.py      icons drawn with QPainter (no image assets)
  app.py        main window, menus, actions
```

The canvas is a `QGraphicsScene` whose units *are* PDF points, so zooming is
just a view transform and hit-testing needs no coordinate maths. Pages render
on demand at the level of detail the current zoom asks for, and the cache is
keyed on a document revision counter that every edit bumps.

Undo works by snapshotting the whole file before each change. That is blunt,
but it reverses operations that are otherwise very hard to invert — applied
redactions, page deletions, re-embedded fonts — with no special cases. History
is capped at 40 steps and 512 MB, whichever comes first.

---

## Known limits

- A line with mixed styling (bold word inside a sentence) is rewritten in the
  dominant style of that line; the mix is not preserved.
- Replacement text does not reflow into following lines. Overflow shrinks to
  fit the original width by default — turn that off in the Properties panel.
- Find and replace works a line at a time, so a hit split across a line break
  is found but not replaceable; Replace says which page it gave up on.
- Some files hold text the redactor cannot lift out — glyphs drawn by a Type3
  font are the usual case. There the new text lands on top of the old instead
  of over it. The result list still showing hits after Replace all is the
  tell-tale, and it is the same limit the Edit Text tool has on those files.
- Recognition is only as good as the scan. Clean printed text reads well;
  handwriting, tight photocopies and heavy skew do not, and no amount of dpi
  rescues them. Nothing claims otherwise — reread a page and the result list
  shows you what it found.
- Editing recognised text lays the new words *over* the scan rather than
  replacing them, because the visible text is part of a picture and only the
  invisible layer can be lifted out. Erase or Redact the area first if you need
  the old words gone.
- A page that genuinely displays sideways is read sideways, because that is what
  it looks like. Rotate it upright first, then recognise.
- A picture that a design tool draws through a Form XObject moves fine, but
  only while that form is used once. Where the same form is stamped down
  several times the copies share one matrix, so the editor declines the move
  and says so in the status bar rather than dragging all of them at once.
- Full-bleed backgrounds get no grab handles. Their placement is often many
  times the size of the page and only visible through a window their container
  clips, so a handle drawn on it would cover the page and grab the wrong
  thing. Use Erase or Redact on the area instead.
- Very heavy pages are slow, not broken: a single-page brief with a 2.6 MB
  content stream takes a couple of seconds to redraw after each edit, because
  every change re-renders the page.
- Undo snapshots make each edit O(file size); very large PDFs will feel it.
