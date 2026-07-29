"""Right-hand dock: properties for the active tool and current selection."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox,
                               QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QMenu, QPushButton, QScrollArea,
                               QSizePolicy, QSlider, QToolButton, QVBoxLayout,
                               QWidget, QWidgetAction)

from . import fonts, icons
from .theme import HIGHLIGHT_SWATCHES, SWATCHES


# ------------------------------------------------------------- colour button
class ColorButton(QToolButton):
    changed = Signal(str)

    def __init__(self, colour: str = "#000000", swatches=None,
                 allow_none: bool = False, parent=None):
        super().__init__(parent)
        self._colour = colour
        self.allow_none = allow_none
        self.swatches = swatches or SWATCHES
        self.setFixedSize(30, 26)
        self.setPopupMode(QToolButton.InstantPopup)
        self.setCursor(Qt.PointingHandCursor)
        self._menu = _SwatchMenu(self)
        self.setMenu(self._menu)
        self._refresh()

    def colour(self) -> str | None:
        return self._colour

    def set_colour(self, value: str | None):
        self._colour = value
        self._refresh()

    def _refresh(self):
        pm = QPixmap(24, 20)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        if self._colour is None:
            p.setPen(QPen(QColor("#9aa3b2"), 1.2))
            p.setBrush(QColor("#ffffff"))
            p.drawRoundedRect(1, 1, 22, 18, 3, 3)
            p.setPen(QPen(QColor("#d0453a"), 1.6))
            p.drawLine(3, 17, 21, 3)
        else:
            p.setPen(QPen(QColor("#00000055"), 1))
            p.setBrush(QColor(self._colour))
            p.drawRoundedRect(1, 1, 22, 18, 3, 3)
        p.end()
        self.setIcon(QIcon(pm))
        self.setIconSize(QSize(24, 20))

    def _choose(self, value: str | None):
        self._colour = value
        self._refresh()
        self.changed.emit(value if value is not None else "")

    def _custom(self):
        start = QColor(self._colour or "#ffffff")
        col = QColorDialog.getColor(start, self, "Choose colour")
        if col.isValid():
            self._choose(col.name())


class _SwatchMenu(QMenu):
    """Grid of preset colours shown under a ColorButton."""

    def __init__(self, button: ColorButton):
        super().__init__(button)
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setSpacing(4)
        for i, colour in enumerate(button.swatches):
            b = QToolButton()
            b.setFixedSize(22, 22)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                f"QToolButton{{background:{colour};border:1px solid #00000044;"
                f"border-radius:4px;}}"
                f"QToolButton:hover{{border:2px solid #2f6fd0;}}")
            b.clicked.connect(
                lambda _=False, c=colour: (button._choose(c), self.close()))
            grid.addWidget(b, i // 5, i % 5)
        row = len(button.swatches) // 5 + 1
        if button.allow_none:
            none_btn = QPushButton("None")
            none_btn.clicked.connect(
                lambda: (button._choose(None), self.close()))
            grid.addWidget(none_btn, row, 0, 1, 3)
            more = QPushButton("Custom…")
            more.clicked.connect(lambda: (self.close(), button._custom()))
            grid.addWidget(more, row, 3, 1, 2)
        else:
            more = QPushButton("Custom…")
            more.clicked.connect(lambda: (self.close(), button._custom()))
            grid.addWidget(more, row, 0, 1, 5)

        action = QWidgetAction(self)
        action.setDefaultWidget(holder)
        self.addAction(action)


# --------------------------------------------------------------------- panel
class Inspector(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.style_ = window.ctx.style
        self.pal = window.palette_
        self._building = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.title = QLabel("Select")
        self.title.setStyleSheet(
            f"background:{self.pal.panel_alt};color:{self.pal.text};"
            f"padding:9px 12px;font-weight:600;"
            f"border-bottom:1px solid {self.pal.border};")
        outer.addWidget(self.title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(12, 12, 12, 12)
        self.body.setSpacing(14)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self._build_sections()
        self.body.addStretch(1)

    # ------------------------------------------------------------- builders
    def _heading(self, text: str) -> QLabel:
        lab = QLabel(text.upper())
        lab.setProperty("heading", True)
        return lab

    def _row(self, label: str, widget) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        lab = QLabel(label)
        lab.setMinimumWidth(64)
        lab.setProperty("muted", True)
        h.addWidget(lab)
        if isinstance(widget, list):
            for x in widget:
                h.addWidget(x)
        else:
            h.addWidget(widget, 1)
        return w

    def _section(self, key: str) -> QVBoxLayout:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(7)
        self.body.addWidget(box)
        self.sections[key] = box
        return v

    def _build_sections(self):
        self.sections: dict[str, QWidget] = {}
        s = self.style_

        # ---- stroke ---------------------------------------------------------
        v = self._section("stroke")
        v.addWidget(self._heading("Stroke"))
        self.stroke_colour = ColorButton(s.stroke)
        self.stroke_colour.changed.connect(self._set_stroke)
        v.addWidget(self._row("Colour", self.stroke_colour))
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(0.2, 40.0)
        self.width_spin.setSingleStep(0.5)
        self.width_spin.setValue(s.width)
        self.width_spin.setSuffix(" pt")
        self.width_spin.valueChanged.connect(self._set_width)
        v.addWidget(self._row("Width", self.width_spin))
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(5, 100)
        self.opacity_slider.setValue(int(s.opacity * 100))
        self.opacity_label = QLabel("100%")
        self.opacity_label.setProperty("muted", True)
        self.opacity_label.setFixedWidth(38)
        self.opacity_slider.valueChanged.connect(self._set_opacity)
        v.addWidget(self._row("Opacity",
                              [self.opacity_slider, self.opacity_label]))

        # ---- fill -----------------------------------------------------------
        v = self._section("fill")
        v.addWidget(self._heading("Fill"))
        self.fill_colour = ColorButton(s.fill, allow_none=True)
        self.fill_colour.changed.connect(self._set_fill)
        v.addWidget(self._row("Colour", self.fill_colour))

        # ---- text -----------------------------------------------------------
        v = self._section("text")
        v.addWidget(self._heading("Text"))
        self.font_combo = QComboBox()
        self.font_combo.addItems([label for label, _ in fonts.FAMILIES])
        self.font_combo.setCurrentText(s.font_family)
        self.font_combo.currentTextChanged.connect(self._set_family)
        v.addWidget(self._row("Font", self.font_combo))

        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(3.0, 300.0)
        self.size_spin.setValue(s.font_size)
        self.size_spin.setSuffix(" pt")
        self.size_spin.valueChanged.connect(self._set_size)
        self.bold_btn = self._toggle("B", s.bold, self._set_bold, bold=True)
        self.italic_btn = self._toggle("I", s.italic, self._set_italic,
                                       italic=True)
        v.addWidget(self._row("Size", [self.size_spin, self.bold_btn,
                                       self.italic_btn]))

        self.text_colour = ColorButton(s.text_color)
        self.text_colour.changed.connect(self._set_text_colour)
        v.addWidget(self._row("Colour", self.text_colour))

        align_row = QWidget()
        ah = QHBoxLayout(align_row)
        ah.setContentsMargins(0, 0, 0, 0)
        ah.setSpacing(3)
        self.align_group = QButtonGroup(self)
        for i, name in enumerate(("Left", "Centre", "Right")):
            b = QToolButton()
            b.setText(name)
            b.setCheckable(True)
            b.setChecked(i == s.align)
            b.setCursor(Qt.PointingHandCursor)
            self.align_group.addButton(b, i)
            ah.addWidget(b)
        ah.addStretch(1)
        self.align_group.idClicked.connect(self._set_align)
        v.addWidget(self._row("Align", align_row))

        self.shrink_check = QCheckBox("Shrink to fit original width")
        self.shrink_check.setChecked(s.shrink_text_to_fit)
        self.shrink_check.toggled.connect(self._set_shrink)
        v.addWidget(self.shrink_check)

        self.text_hint = QLabel("")
        self.text_hint.setProperty("muted", True)
        self.text_hint.setWordWrap(True)
        v.addWidget(self.text_hint)

        # ---- markup ---------------------------------------------------------
        v = self._section("markup")
        v.addWidget(self._heading("Markup"))
        self.hl_colour = ColorButton(s.highlight, swatches=HIGHLIGHT_SWATCHES)
        self.hl_colour.changed.connect(self._set_highlight)
        v.addWidget(self._row("Highlight", self.hl_colour))
        self.markup_opacity = QSlider(Qt.Horizontal)
        self.markup_opacity.setRange(10, 100)
        self.markup_opacity.setValue(int(s.opacity * 100))
        self.markup_opacity.valueChanged.connect(self._set_opacity)
        v.addWidget(self._row("Opacity", self.markup_opacity))

        v.addWidget(self._rule())
        grid = QGridLayout()
        grid.setSpacing(5)
        actions = [
            ("highlight", "Highlight", lambda: self._markup("highlight")),
            ("underline", "Underline", lambda: self._markup("underline")),
            ("strikeout", "Strike", lambda: self._markup("strikeout")),
            ("copy", "Copy", self._copy_selection),
            ("redact", "Redact", self._redact_selection),
            ("trash", "Delete", self._delete_selection),
        ]
        for i, (ic, label, slot) in enumerate(actions):
            b = QPushButton(label)
            b.setIcon(icons.icon(ic, self.pal.text, 15))
            b.clicked.connect(slot)
            grid.addWidget(b, i // 2, i % 2)
        holder = QWidget()
        holder.setLayout(grid)
        v.addWidget(holder)

        # ---- redact ---------------------------------------------------------
        v = self._section("redact")
        v.addWidget(self._heading("Redaction"))
        self.redact_colour = ColorButton(s.redact_fill)
        self.redact_colour.changed.connect(self._set_redact_fill)
        v.addWidget(self._row("Fill", self.redact_colour))
        warn = QLabel("Redaction permanently removes the underlying content "
                      "when applied.")
        warn.setWordWrap(True)
        warn.setProperty("muted", True)
        v.addWidget(warn)

        # ---- erase ----------------------------------------------------------
        v = self._section("erase")
        v.addWidget(self._heading("Erase"))
        note = QLabel("Drag a box to wipe text and vector art. The paper colour "
                      "underneath is sampled automatically.")
        note.setWordWrap(True)
        note.setProperty("muted", True)
        v.addWidget(note)

        # ---- object ---------------------------------------------------------
        v = self._section("object")
        v.addWidget(self._heading("Selection"))
        self.obj_kind = QLabel("Nothing selected")
        self.obj_kind.setWordWrap(True)
        v.addWidget(self.obj_kind)

        self.geom = {}
        grid = QGridLayout()
        grid.setSpacing(5)
        grid.setContentsMargins(0, 0, 0, 0)
        for i, key in enumerate(("x", "y", "w", "h")):
            spin = QDoubleSpinBox()
            spin.setRange(-20000, 20000)
            spin.setDecimals(1)
            spin.setSuffix(" pt")
            # Two of these sit side by side in a narrow dock - keep them small
            # enough that the pair never overflows the panel.
            spin.setMinimumWidth(72)
            spin.setMaximumWidth(104)
            spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            spin.valueChanged.connect(self._geometry_changed)
            self.geom[key] = spin
            lab = QLabel(key.upper())
            lab.setProperty("muted", True)
            lab.setFixedWidth(14)
            grid.addWidget(lab, i // 2, (i % 2) * 2)
            grid.addWidget(spin, i // 2, (i % 2) * 2 + 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        holder = QWidget()
        holder.setLayout(grid)
        v.addWidget(holder)

        self.obj_colour = ColorButton("#c0392b")
        self.obj_colour.changed.connect(self._recolour_object)
        self.obj_colour_row = self._row("Colour", self.obj_colour)
        v.addWidget(self.obj_colour_row)

        self.obj_opacity = QSlider(Qt.Horizontal)
        self.obj_opacity.setRange(5, 100)
        self.obj_opacity.setValue(100)
        self.obj_opacity.sliderReleased.connect(self._reopacity_object)
        self.obj_opacity_row = self._row("Opacity", self.obj_opacity)
        v.addWidget(self.obj_opacity_row)

        self.obj_content = QPushButton("Edit contents…")
        self.obj_content.clicked.connect(self._edit_object_content)
        v.addWidget(self.obj_content)

        row = QHBoxLayout()
        dele = QPushButton("Delete")
        dele.setIcon(icons.icon("trash", self.pal.danger, 15))
        dele.clicked.connect(lambda: self.window.delete_selected_objects())
        row.addWidget(dele)
        holder = QWidget()
        holder.setLayout(row)
        v.addWidget(holder)

    def _rule(self) -> QFrame:
        f = QFrame()
        f.setProperty("rule", True)
        f.setFixedHeight(1)
        f.setStyleSheet(f"background:{self.pal.border};")
        return f

    def _toggle(self, text: str, checked: bool, slot, bold=False, italic=False):
        b = QToolButton()
        b.setText(text)
        b.setCheckable(True)
        b.setChecked(checked)
        b.setFixedWidth(30)
        b.setCursor(Qt.PointingHandCursor)
        style = "font-weight:800;" if bold else ""
        style += "font-style:italic;" if italic else ""
        b.setStyleSheet(f"QToolButton{{{style}}}")
        b.toggled.connect(slot)
        return b

    # -------------------------------------------------------------- updates
    def show_for(self, tool):
        self.title.setText(tool.title if tool else "Select")
        wanted = set(getattr(tool, "inspector", ()) or ())
        for key, widget in self.sections.items():
            widget.setVisible(key in wanted)
        if "object" in wanted:
            self.refresh_selection()
        if "text" in wanted:
            self.text_hint.setText(
                "Click a line to retype it, drag it to move it, or "
                "double-click to reflow the whole paragraph."
                if tool and tool.name == "edit_text" else "")

    def refresh_selection(self):
        items = self.window.selected_object_items()
        has = bool(items)
        for key in ("x", "y", "w", "h"):
            self.geom[key].setEnabled(has)
        self.obj_content.setVisible(False)
        self.obj_colour_row.setVisible(False)
        self.obj_opacity_row.setVisible(False)

        if not has:
            self.obj_kind.setText("Nothing selected.\nClick an annotation, "
                                  "image or form field to select it.")
            self._building = True
            for spin in self.geom.values():
                spin.setValue(0)
            self._building = False
            return

        if len(items) > 1:
            self.obj_kind.setText(f"{len(items)} objects selected")
            self._building = True
            for spin in self.geom.values():
                spin.setValue(0)
            self._building = False
            return

        item = items[0]
        ref = item.ref
        kind = {"annot": "Annotation", "image": "Image",
                "widget": "Form field"}.get(ref.kind, ref.kind)
        detail = ref.subtype or ref.label
        self.obj_kind.setText(f"{kind}{(' · ' + detail) if detail else ''}"
                              f"\nPage {ref.page + 1}")

        r = item.page_rect()
        self._building = True
        self.geom["x"].setValue(r.x())
        self.geom["y"].setValue(r.y())
        self.geom["w"].setValue(r.width())
        self.geom["h"].setValue(r.height())
        self._building = False

        if ref.kind == "annot":
            self.obj_colour_row.setVisible(True)
            self.obj_opacity_row.setVisible(True)
            info = self.window.annotation_info(ref)
            if info:
                if info.get("stroke"):
                    self.obj_colour.set_colour(info["stroke"])
                self.obj_opacity.blockSignals(True)
                self.obj_opacity.setValue(int(info.get("opacity", 1.0) * 100))
                self.obj_opacity.blockSignals(False)
                if info.get("editable_text"):
                    self.obj_content.setVisible(True)
        elif ref.kind == "widget":
            self.obj_content.setVisible(True)

    # ------------------------------------------------------------ callbacks
    def _set_stroke(self, value):
        self.style_.stroke = value or "#000000"

    def _set_fill(self, value):
        self.style_.fill = value or None

    def _set_width(self, value):
        self.style_.width = float(value)

    def _set_opacity(self, value):
        self.style_.opacity = value / 100.0
        self.opacity_label.setText(f"{value}%")
        for w in (self.opacity_slider, self.markup_opacity):
            if w.value() != value:
                w.blockSignals(True)
                w.setValue(value)
                w.blockSignals(False)

    def _set_highlight(self, value):
        self.style_.highlight = value or "#fff35c"

    def _set_redact_fill(self, value):
        self.style_.redact_fill = value or "#000000"

    def _set_family(self, value):
        self.style_.font_family = value

    def _set_size(self, value):
        self.style_.font_size = float(value)

    def _set_bold(self, value):
        self.style_.bold = bool(value)

    def _set_italic(self, value):
        self.style_.italic = bool(value)

    def _set_text_colour(self, value):
        self.style_.text_color = value or "#000000"

    def _set_align(self, value):
        self.style_.align = int(value)

    def _set_shrink(self, value):
        self.style_.shrink_text_to_fit = bool(value)

    def report_text_style(self, span):
        """Mirror the style of the line the user just clicked into."""
        family, bold, italic = fonts.classify(span.font, span.flags)
        label = next((name for name, fam in fonts.FAMILIES if fam == family),
                     "Helvetica")
        self._building = True
        self.font_combo.setCurrentText(label)
        self.size_spin.setValue(span.size)
        self.bold_btn.setChecked(bold)
        self.italic_btn.setChecked(italic)
        self.text_colour.set_colour("#%06x" % (span.color & 0xFFFFFF))
        self._building = False
        self.text_hint.setText(
            f"Matched font: {span.font} · {span.size:.1f} pt")

    # --- markup actions
    def _markup(self, kind: str):
        self.window.apply_markup_from_selection(kind)

    def _copy_selection(self):
        self.window.copy_text_selection()

    def _redact_selection(self):
        self.window.redact_text_selection()

    def _delete_selection(self):
        self.window.delete_text_selection()

    # --- object actions
    def _geometry_changed(self, *_):
        if self._building:
            return
        items = self.window.selected_object_items()
        if len(items) != 1:
            return
        from PySide6.QtCore import QRectF
        r = QRectF(self.geom["x"].value(), self.geom["y"].value(),
                   max(1.0, self.geom["w"].value()),
                   max(1.0, self.geom["h"].value()))
        self.window.set_object_rect(items[0], r)

    def _recolour_object(self, value):
        self.window.recolour_selected_object(value)

    def _reopacity_object(self):
        self.window.set_selected_object_opacity(self.obj_opacity.value() / 100.0)

    def _edit_object_content(self):
        self.window.edit_selected_object_content()
