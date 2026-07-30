"""Modal dialogs: signature pad, metadata, watermark, security, export…"""

from __future__ import annotations

import io
import os

import fitz
from PySide6.QtCore import QBuffer, QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QImage, QPainter, QPainterPath, QPen,
                           QPixmap)
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QRadioButton,
                               QSlider, QSpinBox, QTabWidget, QVBoxLayout,
                               QWidget)

from . import ocr, pageops


# ============================================================== signature pad
class _Pad(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(520, 190)
        self.setCursor(Qt.CrossCursor)
        self.strokes: list[list[QPointF]] = []
        self._active: list[QPointF] | None = None
        self.pen_colour = "#12203a"
        self.pen_width = 2.6

    def clear(self):
        self.strokes.clear()
        self._active = None
        self.update()

    def undo(self):
        if self.strokes:
            self.strokes.pop()
            self.update()

    def is_empty(self) -> bool:
        return not self.strokes

    def mousePressEvent(self, e):
        self._active = [QPointF(e.position())]
        self.strokes.append(self._active)
        self.update()

    def mouseMoveEvent(self, e):
        if self._active is not None:
            self._active.append(QPointF(e.position()))
            self.update()

    def mouseReleaseEvent(self, e):
        self._active = None

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor("#ffffff"))
        p.setPen(QPen(QColor("#c8cfda"), 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        base = self.height() - 42
        p.setPen(QPen(QColor("#dbe1ea"), 1, Qt.DashLine))
        p.drawLine(24, base, self.width() - 24, base)
        p.setPen(QPen(QColor(self.pen_colour), self.pen_width))
        for stroke in self.strokes:
            if len(stroke) < 2:
                if stroke:
                    p.drawPoint(stroke[0])
                continue
            path = QPainterPath(stroke[0])
            for pt in stroke[1:]:
                path.lineTo(pt)
            p.drawPath(path)

    def render_png(self, scale: float = 3.0):
        """Trimmed, transparent PNG of the drawing plus its aspect ratio."""
        if not self.strokes:
            return None, 1.0
        xs = [p.x() for s in self.strokes for p in s]
        ys = [p.y() for s in self.strokes for p in s]
        pad = self.pen_width * 2 + 6
        box = QRectF(min(xs) - pad, min(ys) - pad,
                     max(xs) - min(xs) + pad * 2, max(ys) - min(ys) + pad * 2)
        img = QImage(int(box.width() * scale), int(box.height() * scale),
                     QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.scale(scale, scale)
        p.translate(-box.topLeft())
        pen = QPen(QColor(self.pen_colour), self.pen_width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        for stroke in self.strokes:
            if len(stroke) < 2:
                continue
            path = QPainterPath(stroke[0])
            for pt in stroke[1:]:
                path.lineTo(pt)
            p.drawPath(path)
        p.end()
        buf = QBuffer()
        buf.open(QBuffer.WriteOnly)
        img.save(buf, "PNG")
        return bytes(buf.data()), box.height() / max(box.width(), 1e-6)


class SignatureDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create signature")
        self.png_bytes = None
        self.aspect = 0.35

        v = QVBoxLayout(self)
        v.setSpacing(11)
        self.tabs = QTabWidget()

        # --- draw
        draw = QWidget()
        dv = QVBoxLayout(draw)
        self.pad = _Pad()
        dv.addWidget(self.pad)
        row = QHBoxLayout()
        for label, slot in (("Clear", self.pad.clear), ("Undo", self.pad.undo)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(QLabel("Pen"))
        width = QSlider(Qt.Horizontal)
        width.setRange(1, 8)
        width.setValue(3)
        width.setFixedWidth(96)
        width.valueChanged.connect(
            lambda v_: (setattr(self.pad, "pen_width", v_ * 0.9), self.pad.update()))
        row.addWidget(width)
        dv.addLayout(row)
        self.tabs.addTab(draw, "Draw")

        # --- type
        typed = QWidget()
        tv = QVBoxLayout(typed)
        self.typed_text = QLineEdit()
        self.typed_text.setPlaceholderText("Type your name")
        self.typed_font = QComboBox()
        self.typed_font.addItems(["Segoe Script", "Brush Script MT", "Comic Sans MS",
                                  "Georgia", "Times New Roman", "Helvetica"])
        self.typed_preview = QLabel("")
        self.typed_preview.setMinimumHeight(96)
        self.typed_preview.setAlignment(Qt.AlignCenter)
        self.typed_preview.setStyleSheet(
            "background:#ffffff;border:1px solid #c8cfda;border-radius:6px;"
            "color:#12203a;")
        self.typed_text.textChanged.connect(self._update_typed)
        self.typed_font.currentTextChanged.connect(self._update_typed)
        tv.addWidget(self.typed_text)
        tv.addWidget(self.typed_font)
        tv.addWidget(self.typed_preview, 1)
        self.tabs.addTab(typed, "Type")

        # --- image
        img = QWidget()
        iv = QVBoxLayout(img)
        self.image_path = QLineEdit()
        self.image_path.setPlaceholderText("Choose a PNG with a transparent background")
        self.image_path.setReadOnly(True)
        pick = QPushButton("Browse…")
        pick.clicked.connect(self._pick_image)
        hb = QHBoxLayout()
        hb.addWidget(self.image_path, 1)
        hb.addWidget(pick)
        iv.addLayout(hb)
        self.image_preview = QLabel("No image chosen")
        self.image_preview.setAlignment(Qt.AlignCenter)
        self.image_preview.setMinimumHeight(120)
        self.image_preview.setStyleSheet(
            "background:#ffffff;border:1px solid #c8cfda;border-radius:6px;")
        iv.addWidget(self.image_preview, 1)
        self.tabs.addTab(img, "Image")

        v.addWidget(self.tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Use signature")
        buttons.button(QDialogButtonBox.Ok).setProperty("accent", True)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)
        self._update_typed()

    def _update_typed(self):
        f = QFont(self.typed_font.currentText(), 34)
        f.setItalic(True)
        self.typed_preview.setFont(f)
        self.typed_preview.setText(self.typed_text.text() or "Your signature")

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Signature image", "", "Images (*.png *.jpg *.jpeg *.gif *.bmp)")
        if path:
            self.image_path.setText(path)
            pm = QPixmap(path)
            if not pm.isNull():
                self.image_preview.setPixmap(
                    pm.scaled(360, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _accept(self):
        tab = self.tabs.currentIndex()
        if tab == 0:
            if self.pad.is_empty():
                return
            self.png_bytes, self.aspect = self.pad.render_png()
        elif tab == 1:
            text = self.typed_text.text().strip()
            if not text:
                return
            self.png_bytes, self.aspect = self._render_typed(text)
        else:
            path = self.image_path.text()
            if not path or not os.path.exists(path):
                return
            with open(path, "rb") as fh:
                self.png_bytes = fh.read()
            pm = QPixmap(path)
            self.aspect = pm.height() / max(pm.width(), 1)
        if self.png_bytes:
            self.accept()

    def _render_typed(self, text: str):
        f = QFont(self.typed_font.currentText(), 96)
        f.setItalic(True)
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(f)
        rect = fm.boundingRect(text).adjusted(-18, -18, 18, 18)
        img = QImage(max(rect.width(), 10), max(rect.height(), 10),
                     QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        p.setFont(f)
        p.setPen(QColor("#12203a"))
        p.drawText(img.rect(), Qt.AlignCenter, text)
        p.end()
        buf = QBuffer()
        buf.open(QBuffer.WriteOnly)
        img.save(buf, "PNG")
        return bytes(buf.data()), img.height() / max(img.width(), 1)


# ================================================================= metadata
class MetadataDialog(QDialog):
    FIELDS = [("title", "Title"), ("author", "Author"), ("subject", "Subject"),
              ("keywords", "Keywords"), ("creator", "Creator"),
              ("producer", "Producer")]

    def __init__(self, document, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Document properties")
        self.document = document
        self.setMinimumWidth(460)
        meta = document.metadata()

        v = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(9)
        self.inputs = {}
        for key, label in self.FIELDS:
            edit = QLineEdit(meta.get(key) or "")
            self.inputs[key] = edit
            form.addRow(label, edit)
        v.addLayout(form)

        info = QGroupBox("File")
        iv = QFormLayout(info)
        doc = document.doc
        size = "—"
        if document.path and os.path.exists(document.path):
            size = f"{os.path.getsize(document.path) / 1024:.0f} KB"
        page = doc[0].rect if doc.page_count else fitz.Rect(0, 0, 0, 0)
        iv.addRow("Location", QLabel(document.path or "Not saved yet"))
        iv.addRow("Size", QLabel(size))
        iv.addRow("Pages", QLabel(str(doc.page_count)))
        iv.addRow("Page size", QLabel(
            f"{page.width:.0f} × {page.height:.0f} pt   "
            f"({page.width / 72:.2f} × {page.height / 72:.2f} in)"))
        iv.addRow("PDF version", QLabel(meta.get("format", "—")))
        iv.addRow("Encrypted", QLabel("Yes" if doc.is_encrypted else "No"))
        iv.addRow("Form fields", QLabel("Yes" if doc.is_form_pdf else "No"))
        v.addWidget(info)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

    def values(self) -> dict:
        meta = self.document.metadata()
        for key, _ in self.FIELDS:
            meta[key] = self.inputs[key].text()
        return meta


# ================================================================ watermark
class WatermarkDialog(QDialog):
    def __init__(self, page_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add watermark")
        self.setMinimumWidth(420)
        v = QVBoxLayout(self)

        self.mode_text = QRadioButton("Text")
        self.mode_text.setChecked(True)
        self.mode_image = QRadioButton("Image")
        row = QHBoxLayout()
        row.addWidget(self.mode_text)
        row.addWidget(self.mode_image)
        row.addStretch(1)
        v.addLayout(row)

        form = QFormLayout()
        self.text = QLineEdit("CONFIDENTIAL")
        form.addRow("Text", self.text)
        self.image = QLineEdit()
        pick = QPushButton("Browse…")
        pick.clicked.connect(self._pick)
        hb = QHBoxLayout()
        hb.addWidget(self.image, 1)
        hb.addWidget(pick)
        holder = QWidget()
        holder.setLayout(hb)
        form.addRow("Image", holder)

        self.size = QSpinBox()
        self.size.setRange(6, 300)
        self.size.setValue(54)
        form.addRow("Font size", self.size)
        self.angle = QSpinBox()
        self.angle.setRange(-90, 90)
        self.angle.setValue(45)
        form.addRow("Angle", self.angle)
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(5, 100)
        self.opacity.setValue(25)
        form.addRow("Opacity", self.opacity)
        self.pages = QLineEdit(f"1-{page_count}")
        form.addRow("Pages", self.pages)
        self.on_top = QCheckBox("Draw on top of the content")
        self.on_top.setChecked(True)
        form.addRow("", self.on_top)
        v.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(self, "Watermark image", "",
                                              "Images (*.png *.jpg *.jpeg)")
        if path:
            self.image.setText(path)
            self.mode_image.setChecked(True)


# ============================================================== page numbers
class PageNumberDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add page numbers")
        v = QVBoxLayout(self)
        form = QFormLayout()
        self.fmt = QComboBox()
        self.fmt.setEditable(True)
        self.fmt.addItems(["{page}", "{page} / {total}", "Page {page} of {total}",
                           "- {page} -", "{roman}"])
        self.fmt.setCurrentIndex(1)
        form.addRow("Format", self.fmt)
        self.position = QComboBox()
        self.position.addItems(["bottom-center", "bottom-right", "bottom-left",
                                "top-center", "top-right", "top-left"])
        form.addRow("Position", self.position)
        self.size = QSpinBox()
        self.size.setRange(5, 48)
        self.size.setValue(9)
        form.addRow("Size", self.size)
        self.start = QSpinBox()
        self.start.setRange(0, 9999)
        self.start.setValue(1)
        form.addRow("Start at", self.start)
        self.skip = QCheckBox("Skip the first page")
        form.addRow("", self.skip)
        v.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)


# ================================================================= security
class SecurityDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Password & permissions")
        self.setMinimumWidth(420)
        v = QVBoxLayout(self)

        form = QFormLayout()
        self.user_pw = QLineEdit()
        self.user_pw.setEchoMode(QLineEdit.Password)
        self.user_pw.setPlaceholderText("Required to open the document")
        form.addRow("Open password", self.user_pw)
        self.owner_pw = QLineEdit()
        self.owner_pw.setEchoMode(QLineEdit.Password)
        self.owner_pw.setPlaceholderText("Required to change permissions")
        form.addRow("Owner password", self.owner_pw)
        v.addLayout(form)

        box = QGroupBox("Allow")
        bv = QVBoxLayout(box)
        self.allow_print = QCheckBox("Printing")
        self.allow_copy = QCheckBox("Copying text and images")
        self.allow_annotate = QCheckBox("Commenting and form filling")
        self.allow_modify = QCheckBox("Changing the document")
        for c in (self.allow_print, self.allow_copy, self.allow_annotate,
                  self.allow_modify):
            c.setChecked(True)
            bv.addWidget(c)
        v.addWidget(box)

        note = QLabel("The document is encrypted with AES-256 when you save.")
        note.setWordWrap(True)
        note.setProperty("muted", True)
        v.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)


# ============================================================== insert pages
class InsertPagesDialog(QDialog):
    def __init__(self, page_count: int, current: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Insert pages")
        v = QVBoxLayout(self)

        self.blank = QRadioButton("Blank pages")
        self.blank.setChecked(True)
        self.from_file = QRadioButton("Pages from another PDF")
        v.addWidget(self.blank)
        v.addWidget(self.from_file)

        form = QFormLayout()
        self.count = QSpinBox()
        self.count.setRange(1, 500)
        self.count.setValue(1)
        form.addRow("How many", self.count)
        self.size = QComboBox()
        self.size.addItems(["Match current page"] + list(pageops.PAGE_SIZES))
        form.addRow("Size", self.size)

        self.path = QLineEdit()
        pick = QPushButton("Browse…")
        pick.clicked.connect(self._pick)
        hb = QHBoxLayout()
        hb.addWidget(self.path, 1)
        hb.addWidget(pick)
        holder = QWidget()
        holder.setLayout(hb)
        form.addRow("File", holder)
        self.range_ = QLineEdit()
        self.range_.setPlaceholderText("all, or e.g. 1-5")
        form.addRow("Pages", self.range_)

        self.where = QComboBox()
        self.where.addItems(["After current page", "Before current page",
                             "At the beginning", "At the end"])
        form.addRow("Insert", self.where)
        v.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(self, "Insert from", "",
                                              "PDF files (*.pdf)")
        if path:
            self.path.setText(path)
            self.from_file.setChecked(True)


# =================================================================== export
class ExportDialog(QDialog):
    def __init__(self, page_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export")
        v = QVBoxLayout(self)
        form = QFormLayout()
        self.kind = QComboBox()
        self.kind.addItems(["Images (PNG)", "Images (JPEG)", "Plain text",
                            "Split into single-page PDFs",
                            "Extract embedded images"])
        form.addRow("Export as", self.kind)
        self.pages = QLineEdit(f"1-{page_count}")
        form.addRow("Pages", self.pages)
        self.dpi = QSpinBox()
        self.dpi.setRange(36, 900)
        self.dpi.setValue(150)
        self.dpi.setSuffix(" dpi")
        form.addRow("Resolution", self.dpi)
        v.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)


# ================================================================== password
class PasswordDialog(QDialog):
    def __init__(self, filename: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Password required")
        v = QVBoxLayout(self)
        lab = QLabel(f"“{os.path.basename(filename)}” is protected.")
        lab.setWordWrap(True)
        v.addWidget(lab)
        self.entry = QLineEdit()
        self.entry.setEchoMode(QLineEdit.Password)
        self.entry.setPlaceholderText("Password")
        self.entry.returnPressed.connect(self.accept)
        v.addWidget(self.entry)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

    def password(self) -> str:
        return self.entry.text()


# =============================================================== form fields
class FormFieldDialog(QDialog):
    """Edit one interactive form field's value."""

    def __init__(self, widget, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Form field")
        self.widget = widget
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"<b>{widget.field_name or 'Field'}</b>  "
                           f"<span style='color:#69727f'>"
                           f"({widget.field_type_string})</span>"))

        ftype = widget.field_type
        self.control = None
        if ftype == fitz.PDF_WIDGET_TYPE_CHECKBOX:
            self.control = QCheckBox("Checked")
            self.control.setChecked(bool(widget.field_value))
        elif ftype in (fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX):
            self.control = QComboBox()
            self.control.setEditable(ftype == fitz.PDF_WIDGET_TYPE_COMBOBOX)
            choices = list(widget.choice_values or [])
            flat = [c if isinstance(c, str) else c[-1] for c in choices]
            self.control.addItems(flat)
            if widget.field_value in flat:
                self.control.setCurrentText(str(widget.field_value))
        elif ftype == fitz.PDF_WIDGET_TYPE_RADIOBUTTON:
            self.control = QCheckBox("Selected")
            self.control.setChecked(bool(widget.field_value))
        else:
            multiline = bool(widget.field_flags & 4096)
            if multiline:
                self.control = QPlainTextEdit(str(widget.field_value or ""))
                self.control.setMinimumHeight(110)
            else:
                self.control = QLineEdit(str(widget.field_value or ""))
        v.addWidget(self.control)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

    def value(self):
        if isinstance(self.control, QCheckBox):
            return bool(self.control.isChecked())
        if isinstance(self.control, QComboBox):
            return self.control.currentText()
        if isinstance(self.control, QPlainTextEdit):
            return self.control.toPlainText()
        return self.control.text()


# ============================================================ freetext editor
class TextContentDialog(QDialog):
    def __init__(self, text: str, title: str = "Edit text", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(440, 240)
        v = QVBoxLayout(self)
        self.edit = QPlainTextEdit(text)
        v.addWidget(self.edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

    def text(self) -> str:
        return self.edit.toPlainText()


# ======================================================================= ocr
class OCRDialog(QDialog):
    """Options for recognising the text in scanned pages."""

    def __init__(self, page_count: int, languages: list[str], *,
                 untexted: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Recognise text")
        self.setMinimumWidth(430)
        v = QVBoxLayout(self)
        v.setSpacing(9)

        blurb = QLabel(
            "Reads the text out of scanned pages and stores it invisibly over "
            "the picture, so the page looks the same but can be searched, "
            "selected and edited.")
        blurb.setWordWrap(True)
        v.addWidget(blurb)

        form = QFormLayout()
        self.pages = QLineEdit(f"1-{page_count}")
        form.addRow("Pages", self.pages)

        self.language = QComboBox()
        for code in languages:
            self.language.addItem(ocr.language_label(code), code)
        form.addRow("Language", self.language)

        self.dpi = QSpinBox()
        self.dpi.setRange(72, 600)
        self.dpi.setSingleStep(50)
        self.dpi.setValue(ocr.DEFAULT_DPI)
        self.dpi.setSuffix(" dpi")
        self.dpi.setToolTip("Resolution the page is read at. Higher is slower; "
                            "300 suits most scans, 400+ helps small print.")
        form.addRow("Read at", self.dpi)
        v.addLayout(form)

        self.skip = QCheckBox("Skip pages that already have text")
        self.skip.setChecked(True)
        self.skip.setToolTip("Recognising a page twice gives it two copies of "
                             "every word.")
        v.addWidget(self.skip)

        if untexted:
            note = (f"{untexted} of {page_count} page(s) carry no text and "
                    f"would gain some.")
        else:
            note = ("Every page already carries text - untick the box above to "
                    "recognise them anyway.")
        hint = QLabel(f"<span style='color:#69727f'>{note}</span>")
        hint.setWordWrap(True)
        v.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Recognise")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

    def language_code(self) -> str:
        return self.language.currentData() or ocr.DEFAULT_LANGUAGE


# ==================================================================== about
class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About PDF Studio")
        v = QVBoxLayout(self)
        v.setSpacing(9)
        title = QLabel("<h2 style='margin:0'>PDF Studio</h2>")
        v.addWidget(title)
        v.addWidget(QLabel(
            "An interactive PDF editor: retype existing text in place, "
            "annotate, redact, reorganise pages and fill forms."))
        v.addWidget(QLabel(
            f"<span style='color:#69727f'>PyMuPDF {fitz.VersionBind} · "
            f"MuPDF {fitz.VersionFitz}</span>"))
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        v.addWidget(buttons)


# ------------------------------------------------------------------- helpers
def parse_page_range(text: str, total: int) -> list[int]:
    """'1-3, 7, 9-' -> zero-based page indices."""
    text = (text or "").strip().lower()
    if not text or text in ("all", "*"):
        return list(range(total))
    out: set[int] = set()
    for chunk in text.replace(" ", "").split(","):
        if not chunk:
            continue
        if "-" in chunk:
            a, _, b = chunk.partition("-")
            start = int(a) - 1 if a.isdigit() else 0
            end = int(b) - 1 if b.isdigit() else total - 1
            for i in range(max(0, start), min(total - 1, end) + 1):
                out.add(i)
        elif chunk.isdigit():
            i = int(chunk) - 1
            if 0 <= i < total:
                out.add(i)
    return sorted(out)
