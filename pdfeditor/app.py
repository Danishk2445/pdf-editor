"""Main window: menus, toolbars, docks and all the action handlers."""

from __future__ import annotations

import os
import sys

import fitz
from PySide6.QtCore import (QPoint, QPointF, QRectF, QSettings, QSize, Qt,
                            QTimer, Slot)
from PySide6.QtGui import (QAction, QActionGroup, QColor, QDesktopServices,
                           QGuiApplication, QIcon, QKeySequence, QPixmap)
from PySide6.QtWidgets import (QApplication, QComboBox, QDockWidget,
                               QFileDialog, QHBoxLayout, QLabel, QMainWindow,
                               QMenu, QMessageBox, QSizePolicy, QSpinBox,
                               QStatusBar, QTabWidget, QToolBar, QToolButton,
                               QVBoxLayout, QWidget)

from . import __version__, dialogs, icons, imageops, pageops, textops, theme
from .document import Document, PasswordRequired
from .inspector import Inspector
from .items import ObjectItem, qrect
from .panels import OutlinePanel, SearchPanel, ThumbnailPanel
from .render import PageRenderer
from .theme import DARK, LIGHT
from .tools import TOOLS, ToolContext
from .view import (LAYOUT_CONTINUOUS, LAYOUT_FACING, LAYOUT_SINGLE, PdfView)

APP_TITLE = "PDF Studio"
MAX_RECENT = 10

# Which tools appear in the left rail, in order.  ``None`` inserts a separator.
TOOL_RAIL = [
    ("select", "select", "Select and move objects", "V"),
    ("hand", "hand", "Pan the page", "H"),
    ("text_select", "text_select", "Select text", "T"),
    None,
    ("edit_text", "edit_text", "Edit existing text", "E"),
    ("add_text", "add_text", "Add new text", "A"),
    None,
    ("highlight", "highlight", "Highlight text", "U"),
    ("underline", "underline", "Underline text", None),
    ("strikeout", "strikeout", "Strike out text", None),
    ("note", "note", "Sticky note", "N"),
    None,
    ("ink", "ink", "Draw freehand", "D"),
    ("rect", "rect", "Rectangle", "R"),
    ("ellipse", "ellipse", "Ellipse", "O"),
    ("line", "line", "Line", "L"),
    ("arrow", "arrow", "Arrow", None),
    None,
    ("image", "image", "Insert an image", "I"),
    ("signature", "signature", "Sign the document", "G"),
    ("stamp", "stamp", "Stamp", None),
    ("link", "link", "Add a link", "K"),
    None,
    ("erase", "eraser", "Erase an area", "X"),
    ("redact", "redact", "Redact an area", None),
    ("crop", "crop", "Crop the page", "C"),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("PDFStudio", "PDFStudio")
        self.palette_ = DARK if self.settings.value("dark", False, bool) else LIGHT

        self.document = Document()
        self.renderer = PageRenderer(self.document)
        self.ctx = ToolContext(self)
        self.tools = {name: cls(self.ctx) for name, cls in TOOLS.items()}
        self.tool = None
        self._recent: list[str] = list(
            self.settings.value("recent", [], list) or [])

        self.setWindowTitle(APP_TITLE)
        self.resize(1500, 960)
        self.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowTabbedDocks)

        self.view = PdfView(self.document, self.renderer, self.palette_, self)
        self.setCentralWidget(self.view)

        self._build_actions()
        self._build_menus()
        self._build_toolbars()
        self._build_docks()
        self._build_statusbar()
        self._connect()

        self.apply_theme(self.palette_)
        self.activate_tool("select")
        self._update_enabled()
        self.restoreGeometry(self.settings.value("geometry", b""))
        self.restoreState(self.settings.value("windowstate", b""))

    # =====================================================================
    # construction
    # =====================================================================
    def _act(self, text, icon=None, shortcut=None, slot=None, tip=None,
             checkable=False):
        action = QAction(text, self)
        if icon:
            action.setIcon(icons.icon(icon, self.palette_.text, 20))
            action.setProperty("iconName", icon)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        if slot:
            action.triggered.connect(slot)
        if tip:
            action.setStatusTip(tip)
            action.setToolTip(f"{tip}  ({action.shortcut().toString()})"
                              if shortcut else tip)
        action.setCheckable(checkable)
        return action

    def _build_actions(self):
        A = self._act
        # ---- file
        self.act_new = A("&New", "new", QKeySequence.New, self.file_new,
                         "Create an empty document")
        self.act_open = A("&Open…", "open", QKeySequence.Open, self.file_open,
                          "Open a PDF")
        self.act_save = A("&Save", "save", QKeySequence.Save, self.file_save,
                          "Save the document")
        self.act_save_as = A("Save &As…", "save_as", QKeySequence.SaveAs,
                             self.file_save_as, "Save to a new file")
        self.act_export = A("&Export…", "export", "Ctrl+Shift+E", self.file_export,
                            "Export pages as images or text")
        self.act_print = A("&Print…", "print", QKeySequence.Print, self.file_print,
                           "Print the document")
        self.act_close = A("&Close", None, QKeySequence.Close, self.file_close)
        self.act_quit = A("&Quit", None, QKeySequence.Quit, self.close)
        self.act_properties = A("Document &Properties…", "properties",
                                "Ctrl+D", self.show_properties)

        # ---- edit
        self.act_undo = A("&Undo", "undo", QKeySequence.Undo, self.do_undo)
        self.act_redo = A("&Redo", "redo", QKeySequence.Redo, self.do_redo)
        self.act_copy = A("&Copy", "copy", QKeySequence.Copy,
                          self.copy_text_selection)
        self.act_select_all = A("Select &All Text", None, QKeySequence.SelectAll,
                                self.select_all_text)
        self.act_delete_sel = A("&Delete Selection", "trash", "Delete",
                                self.delete_current_selection)
        self.act_find = A("&Find…", "search", QKeySequence.Find, self.focus_search)
        self.act_find_next = A("Find &Next", None, QKeySequence.FindNext,
                               lambda: self.search_panel.step(1))
        self.act_find_prev = A("Find &Previous", None, QKeySequence.FindPrevious,
                               lambda: self.search_panel.step(-1))

        # ---- view
        self.act_zoom_in = A("Zoom &In", "zoom_in", QKeySequence.ZoomIn,
                             lambda: self.view.zoom_in())
        self.act_zoom_out = A("Zoom &Out", "zoom_out", QKeySequence.ZoomOut,
                              lambda: self.view.zoom_out())
        self.act_fit_width = A("Fit &Width", "fit_width", "Ctrl+1",
                               lambda: self.view.set_fit("width"))
        self.act_fit_page = A("Fit &Page", "fit_page", "Ctrl+0",
                              lambda: self.view.set_fit("page"))
        self.act_actual = A("&Actual Size", None, "Ctrl+2",
                            lambda: self.view.set_fit("actual"))
        self.act_theme = A("Toggle &Dark Mode", "theme", "Ctrl+Shift+D",
                           self.toggle_theme)
        self.act_fullscreen = A("&Full Screen", None, "F11", self.toggle_fullscreen,
                                checkable=True)

        self.layout_group = QActionGroup(self)
        self.act_layout_single = A("&Single Page", "single_page", None,
                                   lambda: self.set_layout(LAYOUT_SINGLE),
                                   checkable=True)
        self.act_layout_cont = A("&Continuous", "continuous", None,
                                 lambda: self.set_layout(LAYOUT_CONTINUOUS),
                                 checkable=True)
        self.act_layout_facing = A("&Facing Pages", "facing", None,
                                   lambda: self.set_layout(LAYOUT_FACING),
                                   checkable=True)
        self.act_layout_cont.setChecked(True)
        for a in (self.act_layout_single, self.act_layout_cont,
                  self.act_layout_facing):
            self.layout_group.addAction(a)

        # ---- pages
        self.act_insert_page = A("Insert Page &After", "page_add", None,
                                 lambda: self.insert_pages(after=True))
        self.act_insert_page_before = A("Insert Page &Before", None, None,
                                        lambda: self.insert_pages(after=False))
        self.act_insert_dialog = A("&Insert Pages…", "import", "Ctrl+Shift+I",
                                   self.insert_pages_dialog)
        self.act_duplicate_page = A("&Duplicate Page", "page_copy", None,
                                    self.duplicate_pages)
        self.act_delete_page = A("De&lete Page", "page_delete", None,
                                 self.delete_pages)
        self.act_rotate_left = A("Rotate &Left", "rotate_left", "Ctrl+[",
                                 lambda: self.rotate_pages(-90))
        self.act_rotate_right = A("Rotate &Right", "rotate_right", "Ctrl+]",
                                  lambda: self.rotate_pages(90))
        self.act_extract_pages = A("&Extract Pages…", "page_extract", None,
                                   self.extract_pages)
        self.act_export_images = A("Export Pages as &Images…", "image", None,
                                   lambda: self.file_export(preset=0))
        self.act_reset_crop = A("&Reset Crop", None, None, self.reset_crop)
        self.act_page_numbers = A("Add Page &Numbers…", None, None,
                                  self.add_page_numbers)
        self.act_watermark = A("Add &Watermark…", "layers", None, self.add_watermark)
        self.act_flatten = A("&Flatten Annotations", None, None,
                             self.flatten_annotations)
        self.act_resize_pages = A("Resi&ze Pages…", None, None, self.resize_pages)

        # ---- protect / forms
        self.act_security = A("Password && &Permissions…", "lock", None,
                              self.set_security)
        self.act_remove_security = A("&Remove Password", None, None,
                                     self.remove_security)
        self.act_form_flatten = A("Flatten &Form Fields", None, None,
                                  self.flatten_forms)

        # ---- panels
        self.act_toggle_sidebar = A("Show &Sidebar", "sidebar", "F9",
                                    self.toggle_sidebar, checkable=True)
        self.act_toggle_inspector = A("Show &Properties Panel", "properties", "F10",
                                      self.toggle_inspector, checkable=True)
        self.act_toggle_sidebar.setChecked(True)
        self.act_toggle_inspector.setChecked(True)

        self.act_about = A("&About PDF Studio", "info", None, self.show_about)
        self.act_shortcuts = A("&Keyboard Shortcuts", None, "F1",
                               self.show_shortcuts)

        # ---- tools
        self.tool_actions = {}
        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusive(True)
        for entry in TOOL_RAIL:
            if entry is None:
                continue
            name, icon, tip, key = entry
            action = A(self.tools[name].title, icon, key,
                       lambda _=False, n=name: self.activate_tool(n),
                       tip, checkable=True)
            self.tool_actions[name] = action
            self.tool_group.addAction(action)

    def _build_menus(self):
        bar = self.menuBar()

        m = bar.addMenu("&File")
        m.addAction(self.act_new)
        m.addAction(self.act_open)
        self.recent_menu = m.addMenu("Open &Recent")
        m.addSeparator()
        m.addAction(self.act_save)
        m.addAction(self.act_save_as)
        m.addAction(self.act_export)
        m.addSeparator()
        m.addAction(self.act_print)
        m.addAction(self.act_properties)
        m.addSeparator()
        m.addAction(self.act_close)
        m.addAction(self.act_quit)

        m = bar.addMenu("&Edit")
        m.addAction(self.act_undo)
        m.addAction(self.act_redo)
        m.addSeparator()
        m.addAction(self.act_copy)
        m.addAction(self.act_select_all)
        m.addAction(self.act_delete_sel)
        m.addSeparator()
        m.addAction(self.act_find)
        m.addAction(self.act_find_next)
        m.addAction(self.act_find_prev)

        m = bar.addMenu("&View")
        m.addAction(self.act_zoom_in)
        m.addAction(self.act_zoom_out)
        m.addAction(self.act_fit_width)
        m.addAction(self.act_fit_page)
        m.addAction(self.act_actual)
        m.addSeparator()
        m.addAction(self.act_layout_single)
        m.addAction(self.act_layout_cont)
        m.addAction(self.act_layout_facing)
        m.addSeparator()
        m.addAction(self.act_toggle_sidebar)
        m.addAction(self.act_toggle_inspector)
        m.addAction(self.act_theme)
        m.addAction(self.act_fullscreen)

        m = bar.addMenu("&Tools")
        for entry in TOOL_RAIL:
            if entry is None:
                m.addSeparator()
            else:
                m.addAction(self.tool_actions[entry[0]])

        m = bar.addMenu("&Pages")
        m.addAction(self.act_insert_dialog)
        m.addAction(self.act_insert_page)
        m.addAction(self.act_insert_page_before)
        m.addAction(self.act_duplicate_page)
        m.addAction(self.act_delete_page)
        m.addSeparator()
        m.addAction(self.act_rotate_left)
        m.addAction(self.act_rotate_right)
        m.addAction(self.act_resize_pages)
        m.addAction(self.act_reset_crop)
        m.addSeparator()
        m.addAction(self.act_extract_pages)
        m.addAction(self.act_export_images)
        m.addSeparator()
        m.addAction(self.act_page_numbers)
        m.addAction(self.act_watermark)
        m.addAction(self.act_flatten)

        m = bar.addMenu("&Protect")
        m.addAction(self.act_security)
        m.addAction(self.act_remove_security)
        m.addSeparator()
        m.addAction(self.tool_actions["redact"])
        m.addAction(self.act_form_flatten)

        m = bar.addMenu("&Help")
        m.addAction(self.act_shortcuts)
        m.addAction(self.act_about)

        self._refresh_recent_menu()

    def _build_toolbars(self):
        tb = QToolBar("Main")
        tb.setObjectName("mainToolbar")
        tb.setIconSize(QSize(20, 20))
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonIconOnly)
        for a in (self.act_open, self.act_save, self.act_print):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.act_undo)
        tb.addAction(self.act_redo)
        tb.addSeparator()
        tb.addAction(self.act_zoom_out)

        self.zoom_box = QComboBox()
        self.zoom_box.setEditable(True)
        self.zoom_box.setFixedWidth(94)
        self.zoom_box.addItems(["Fit width", "Fit page", "25%", "50%", "75%",
                                "100%", "125%", "150%", "200%", "400%"])
        self.zoom_box.setCurrentText("Fit width")
        self.zoom_box.lineEdit().returnPressed.connect(self._zoom_entered)
        self.zoom_box.activated.connect(self._zoom_picked)
        tb.addWidget(self.zoom_box)

        tb.addAction(self.act_zoom_in)
        tb.addAction(self.act_fit_width)
        tb.addAction(self.act_fit_page)
        tb.addSeparator()
        tb.addAction(self.act_layout_single)
        tb.addAction(self.act_layout_cont)
        tb.addAction(self.act_layout_facing)
        tb.addSeparator()
        tb.addAction(self.act_rotate_left)
        tb.addAction(self.act_rotate_right)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        tb.addAction(self.act_find)
        tb.addAction(self.act_toggle_sidebar)
        tb.addAction(self.act_toggle_inspector)
        tb.addAction(self.act_theme)
        self.addToolBar(Qt.TopToolBarArea, tb)
        self.main_toolbar = tb

        # ---- vertical tool rail
        rail = QToolBar("Tools")
        rail.setObjectName("toolRail")
        rail.setIconSize(QSize(21, 21))
        rail.setMovable(False)
        rail.setOrientation(Qt.Vertical)
        for entry in TOOL_RAIL:
            if entry is None:
                rail.addSeparator()
            else:
                rail.addAction(self.tool_actions[entry[0]])
        self.addToolBar(Qt.LeftToolBarArea, rail)
        self.tool_rail = rail

    def _build_docks(self):
        # ---- left: pages / bookmarks / search
        self.thumbnails = ThumbnailPanel(self)
        self.outline = OutlinePanel(self)
        self.search_panel = SearchPanel(self)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.addTab(self.thumbnails, "Pages")
        tabs.addTab(self.outline, "Bookmarks")
        tabs.addTab(self.search_panel, "Search")
        self.side_tabs = tabs

        dock = QDockWidget("Navigation", self)
        dock.setObjectName("navigationDock")
        dock.setWidget(tabs)
        dock.setFeatures(QDockWidget.DockWidgetMovable |
                         QDockWidget.DockWidgetClosable)
        dock.setMinimumWidth(212)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self.nav_dock = dock
        dock.visibilityChanged.connect(self.act_toggle_sidebar.setChecked)

        # ---- right: properties
        self.inspector = Inspector(self)
        dock = QDockWidget("Properties", self)
        dock.setObjectName("propertiesDock")
        dock.setWidget(self.inspector)
        dock.setFeatures(QDockWidget.DockWidgetMovable |
                         QDockWidget.DockWidgetClosable)
        dock.setMinimumWidth(238)
        dock.setMaximumWidth(360)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self.inspector_dock = dock
        dock.visibilityChanged.connect(self.act_toggle_inspector.setChecked)

    def _build_statusbar(self):
        bar = QStatusBar()
        self.setStatusBar(bar)

        self.message = QLabel("")
        bar.addWidget(self.message, 1)

        self.page_spin = QSpinBox()
        self.page_spin.setRange(1, 1)
        self.page_spin.setFixedWidth(64)
        self.page_spin.setToolTip("Go to page")
        self.page_spin.valueChanged.connect(
            lambda v: self.view.goto_page(v - 1))
        self.page_total = QLabel("of 0")
        self.page_total.setProperty("muted", True)

        prev_btn = QToolButton()
        prev_btn.setIcon(icons.icon("chevron_left", self.palette_.text, 16))
        prev_btn.setToolTip("Previous page")
        prev_btn.clicked.connect(
            lambda: self.view.goto_page(max(0, self.view.current_page - 1)))
        next_btn = QToolButton()
        next_btn.setIcon(icons.icon("chevron_right", self.palette_.text, 16))
        next_btn.setToolTip("Next page")
        next_btn.clicked.connect(
            lambda: self.view.goto_page(min(self.document.page_count - 1,
                                            self.view.current_page + 1)))
        self._nav_buttons = (prev_btn, next_btn)

        for w in (prev_btn, self.page_spin, self.page_total, next_btn):
            bar.addPermanentWidget(w)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setProperty("muted", True)
        self.zoom_label.setFixedWidth(48)
        self.zoom_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bar.addPermanentWidget(self.zoom_label)

    def _connect(self):
        self.view.page_changed.connect(self.on_page_changed)
        self.view.zoom_changed.connect(self.on_zoom_changed)
        self.view.status.connect(self.show_status)
        self.view.context_requested.connect(self.show_context_menu)
        self.view.scene_.selectionChanged.connect(self.update_inspector)
        self.view.verticalScrollBar().valueChanged.connect(
            self._schedule_object_sync)
        self.document.subscribe(self.on_document_changed)

        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.setInterval(90)
        self._sync_timer.timeout.connect(self.ensure_objects_for_view)

    # =====================================================================
    # theme
    # =====================================================================
    def apply_theme(self, palette):
        self.palette_ = palette
        icons.clear_cache()
        QApplication.instance().setStyleSheet(theme.stylesheet(palette))
        self.view.pal = palette
        self.view.scene_.pal = palette
        self.view.scene_.setBackgroundBrush(QColor(palette.workspace))
        for item in self.view.scene_.pages:
            item.palette = palette
        for ov in self.view.scene_.overlays:
            ov.palette = palette
        for action in self.findChildren(QAction):
            name = action.property("iconName")
            if name:
                action.setIcon(icons.icon(name, palette.text, 20))
        self.view.viewport().update()

    def toggle_theme(self):
        new = LIGHT if self.palette_.name == "dark" else DARK
        self.settings.setValue("dark", new.name == "dark")
        # Panels bake palette colours into their stylesheets, so rebuild them.
        self.apply_theme(new)
        self._rebuild_panels()
        self.show_status(f"{new.name.title()} theme")

    def _rebuild_panels(self):
        current = self.side_tabs.currentIndex()
        self.thumbnails = ThumbnailPanel(self)
        self.outline = OutlinePanel(self)
        self.search_panel = SearchPanel(self)
        self.side_tabs.clear()
        self.side_tabs.addTab(self.thumbnails, "Pages")
        self.side_tabs.addTab(self.outline, "Bookmarks")
        self.side_tabs.addTab(self.search_panel, "Search")
        self.side_tabs.setCurrentIndex(current)
        self.inspector = Inspector(self)
        self.inspector_dock.setWidget(self.inspector)
        if self.document.is_open:
            self.thumbnails.rebuild()
            self.outline.rebuild()
        self.inspector.show_for(self.tool)

    # =====================================================================
    # document lifecycle
    # =====================================================================
    def file_new(self):
        if not self._confirm_discard():
            return
        self.document.new()
        self.view._pending_fit = True
        self.after_open()

    def file_open(self, path: str | None = None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "Open document", self._start_dir(),
                "Documents (*.pdf *.xps *.epub *.cbz *.fb2 *.svg "
                "*.png *.jpg *.jpeg *.tif *.tiff);;PDF files (*.pdf);;All files (*)")
        if not path:
            return
        if not self._confirm_discard():
            return
        password = None
        while True:
            try:
                self.document.open(path, password)
                break
            except PasswordRequired:
                dlg = dialogs.PasswordDialog(path, self)
                if not dlg.exec():
                    return
                password = dlg.password()
            except Exception as exc:
                QMessageBox.critical(self, "Could not open",
                                     f"{os.path.basename(path)}\n\n{exc}")
                return
        self._remember_recent(path)
        self.view._pending_fit = True
        self.after_open()

    def after_open(self):
        self.view.reload()
        self.thumbnails.rebuild()
        self.outline.rebuild()
        self.search_panel.list.clear()
        self.search_panel.hits = []
        self._update_title()
        self._update_enabled()
        self.page_spin.setRange(1, max(1, self.document.page_count))
        self.page_total.setText(f"of {self.document.page_count}")
        self.ensure_objects_for_view()
        if self.document.is_open:
            self.show_status(
                f"{self.document.title} · {self.document.page_count} pages")

    def file_save(self):
        if not self.document.is_open:
            return
        if not self.document.path:
            return self.file_save_as()
        try:
            self.document.save()
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        # Saving over the open file swaps in a freshly parsed document, so any
        # cached page/annotation handles have to go.
        self.view.text_cache.drop()
        self.view.scene_.clear_objects()
        self.view.scene_.update()
        self.ensure_objects_for_view()
        self._update_title()
        self.show_status(f"Saved {self.document.title}")

    def file_save_as(self):
        if not self.document.is_open:
            return
        start = self.document.path or os.path.join(self._start_dir(),
                                                   "Untitled.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "Save as", start,
                                              "PDF files (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            self.document.save(path)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self._remember_recent(path)
        self._update_title()
        self.show_status(f"Saved {self.document.title}")

    def file_close(self):
        if not self._confirm_discard():
            return
        self.document.close()
        self.view.reload()
        self.thumbnails.rebuild()
        self.outline.rebuild()
        self._update_title()
        self._update_enabled()

    def file_print(self):
        if not self.document.is_open:
            return
        try:
            from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        except ImportError:
            QMessageBox.warning(self, "Printing unavailable",
                                "Qt print support is not installed.")
            return
        printer = QPrinter(QPrinter.HighResolution)
        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle("Print document")
        if not dlg.exec():
            return
        from PySide6.QtGui import QPainter
        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.warning(self, "Printing failed",
                                "Could not start the print job.")
            return
        first = printer.fromPage() - 1 if printer.fromPage() else 0
        last = printer.toPage() - 1 if printer.toPage() else self.document.page_count - 1
        dpi = printer.resolution()
        for i in range(first, last + 1):
            if i > first:
                printer.newPage()
            page = self.document.page(i)
            pix = page.get_pixmap(dpi=min(dpi, 300), alpha=False)
            from .render import pixmap_from_fitz
            pm = pixmap_from_fitz(pix)
            target = painter.viewport()
            scaled = pm.size().scaled(target.size(), Qt.KeepAspectRatio)
            painter.drawPixmap(
                QRectF((target.width() - scaled.width()) / 2,
                       (target.height() - scaled.height()) / 2,
                       scaled.width(), scaled.height()),
                pm, QRectF(pm.rect()))
        painter.end()
        self.show_status("Sent to printer")

    def file_export(self, preset: int | None = None):
        if not self.document.is_open:
            return
        dlg = dialogs.ExportDialog(self.document.page_count, self)
        if preset is not None:
            dlg.kind.setCurrentIndex(preset)
        if not dlg.exec():
            return
        kind = dlg.kind.currentIndex()
        pages = dialogs.parse_page_range(dlg.pages.text(), self.document.page_count)
        if not pages:
            self.show_status("No pages matched that range")
            return
        stem = os.path.splitext(self.document.title)[0] or "document"

        if kind == 2:      # plain text
            path, _ = QFileDialog.getSaveFileName(
                self, "Save text", os.path.join(self._start_dir(), stem + ".txt"),
                "Text files (*.txt)")
            if not path:
                return
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(pageops.export_text(self.document.doc, pages))
            self.show_status(f"Exported text to {os.path.basename(path)}")
            return

        folder = QFileDialog.getExistingDirectory(self, "Export into",
                                                  self._start_dir())
        if not folder:
            return
        try:
            if kind in (0, 1):
                fmt = "png" if kind == 0 else "jpg"
                written = pageops.export_images(self.document.doc, pages, folder,
                                                stem, dlg.dpi.value(), fmt)
            elif kind == 3:
                written = pageops.split_to_files(self.document.doc, folder, stem)
            else:
                written = pageops.extract_embedded_images(self.document.doc, folder)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self.show_status(f"Wrote {len(written)} file(s) to {folder}")

    # =====================================================================
    # undo / status plumbing
    # =====================================================================
    def do_undo(self):
        label = self.document.undo()
        if label:
            self.after_history(f"Undid: {label}")

    def do_redo(self):
        label = self.document.redo()
        if label:
            self.after_history(f"Redid: {label}")

    def after_history(self, message: str):
        self.view.text_cache.drop()
        self.view.scene_.clear_objects()
        self.view.refresh_geometry()
        self.view.scene_.update()
        self.thumbnails.rebuild()
        self.outline.rebuild()
        self.page_spin.setRange(1, max(1, self.document.page_count))
        self.page_total.setText(f"of {self.document.page_count}")
        self.ensure_objects_for_view()
        self._update_enabled()
        self._update_title()
        self.show_status(message)

    def refresh_after_edit(self):
        """Called by ToolContext after every mutation."""
        self.thumbnails.invalidate()
        self.outline.rebuild()
        self.page_spin.setRange(1, max(1, self.document.page_count))
        self.page_total.setText(f"of {self.document.page_count}")
        self.ensure_objects_for_view()
        self._update_enabled()
        self._update_title()

    def on_document_changed(self, kind: str):
        if kind == "document":
            self.page_spin.setRange(1, max(1, self.document.page_count))
            self.page_total.setText(f"of {self.document.page_count}")

    def report_error(self, label: str, exc: Exception):
        """An edit failed and was rolled back - tell the user, keep running."""
        self.show_status(f"{label} failed: {exc}", 8000)
        QMessageBox.warning(self, "Could not complete that edit",
                            f"{label} failed and no changes were made.\n\n"
                            f"{type(exc).__name__}: {exc}")

    def show_status(self, message: str, msecs: int = 4000):
        self.message.setText(message)
        if msecs:
            QTimer.singleShot(msecs, lambda: (
                self.message.setText("")
                if self.message.text() == message else None))

    def _update_title(self):
        if not self.document.is_open:
            self.setWindowTitle(APP_TITLE)
            return
        mark = "•  " if self.document.dirty else ""
        self.setWindowTitle(f"{mark}{self.document.title} — {APP_TITLE}")

    def _update_enabled(self):
        has = self.document.is_open
        for a in (self.act_save, self.act_save_as, self.act_export, self.act_print,
                  self.act_properties, self.act_close, self.act_find,
                  self.act_insert_dialog, self.act_insert_page,
                  self.act_insert_page_before, self.act_duplicate_page,
                  self.act_rotate_left, self.act_rotate_right,
                  self.act_extract_pages, self.act_export_images,
                  self.act_page_numbers, self.act_watermark, self.act_flatten,
                  self.act_security, self.act_remove_security,
                  self.act_resize_pages, self.act_reset_crop,
                  self.act_select_all, self.act_copy, self.act_form_flatten,
                  self.act_zoom_in, self.act_zoom_out, self.act_fit_width,
                  self.act_fit_page, self.act_actual):
            a.setEnabled(has)
        for action in self.tool_actions.values():
            action.setEnabled(has)
        self.act_undo.setEnabled(self.document.can_undo)
        self.act_redo.setEnabled(self.document.can_redo)
        self.act_undo.setText(f"Undo {self.document.undo_label}".strip()
                              if self.document.can_undo else "Undo")
        self.act_redo.setText(f"Redo {self.document.redo_label}".strip()
                              if self.document.can_redo else "Redo")
        self.update_page_actions()

    def update_page_actions(self):
        multi = self.document.page_count > 1
        self.act_delete_page.setEnabled(self.document.is_open and multi)

    # =====================================================================
    # navigation
    # =====================================================================
    @Slot(int)
    def on_page_changed(self, index: int):
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(index + 1)
        self.page_spin.blockSignals(False)
        self.thumbnails.set_current(index)
        self._schedule_object_sync()

    @Slot(float)
    def on_zoom_changed(self, value: float):
        self.zoom_label.setText(f"{value * 100:.0f}%")
        if self.view.fit_mode == "width":
            text = "Fit width"
        elif self.view.fit_mode == "page":
            text = "Fit page"
        else:
            text = f"{value * 100:.0f}%"
        self.zoom_box.blockSignals(True)
        self.zoom_box.setCurrentText(text)
        self.zoom_box.blockSignals(False)
        self._schedule_object_sync()

    def _zoom_entered(self):
        text = self.zoom_box.currentText().strip().rstrip("%")
        try:
            self.view.set_zoom(float(text) / 100.0)
        except ValueError:
            self._zoom_picked(self.zoom_box.currentIndex())

    def _zoom_picked(self, index: int):
        text = self.zoom_box.itemText(index)
        if text == "Fit width":
            self.view.set_fit("width")
        elif text == "Fit page":
            self.view.set_fit("page")
        else:
            try:
                self.view.set_zoom(float(text.rstrip("%")) / 100.0)
            except ValueError:
                pass

    def set_layout(self, mode: str):
        self.view.set_layout_mode(mode)
        self._schedule_object_sync()

    def toggle_sidebar(self):
        self.nav_dock.setVisible(not self.nav_dock.isVisible())

    def toggle_inspector(self):
        self.inspector_dock.setVisible(not self.inspector_dock.isVisible())

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def focus_search(self):
        self.nav_dock.setVisible(True)
        self.side_tabs.setCurrentWidget(self.search_panel)
        self.search_panel.focus()

    # =====================================================================
    # tools
    # =====================================================================
    def activate_tool(self, name: str):
        tool = self.tools.get(name)
        if tool is None:
            return
        self.tool = tool
        action = self.tool_actions.get(name)
        if action is not None and not action.isChecked():
            action.setChecked(True)
        self.view.set_tool(tool)
        self.inspector.show_for(tool)
        if tool.wants_objects:
            self.ensure_objects_for_view()
        self.show_status(tool.title)

    def report_text_style(self, span):
        self.inspector.report_text_style(span)

    def update_inspector(self):
        self.inspector.refresh_selection()

    # =====================================================================
    # object handling
    # =====================================================================
    def visible_page_indices(self) -> list[int]:
        rect = self.view.mapToScene(self.view.viewport().rect()).boundingRect()
        out = []
        for item in self.view.scene_.pages:
            if not item.isVisible():
                continue
            r = QRectF(item.pos(), item.page_rect().size())
            if r.intersects(rect):
                out.append(item.index)
        return out or [self.view.current_page]

    def _schedule_object_sync(self):
        self._sync_timer.start()

    def ensure_objects_for_view(self):
        if self.tool is None or not self.tool.wants_objects:
            return
        if not self.document.is_open:
            return
        for index in self.visible_page_indices():
            self.view.scene_.build_objects(index, self.on_object_moved,
                                           self.on_object_activated)

    def selected_object_items(self) -> list[ObjectItem]:
        return [i for i in self.view.scene_.selectedItems()
                if isinstance(i, ObjectItem)]

    @Slot(object, QRectF)
    def on_object_moved(self, ref, rect: QRectF):
        label = {"annot": "Move annotation", "image": "Move image",
                 "widget": "Move form field"}.get(ref.kind, "Move object")
        try:
            with self.ctx.edit(label, page=ref.page):
                self._apply_object_rect(ref, rect)
        except Exception as exc:
            QMessageBox.warning(self, "Could not move", str(exc))
            self.view.scene_.clear_objects()
            self.ensure_objects_for_view()

    def _apply_object_rect(self, ref, rect: QRectF):
        page = self.document.page(ref.page)
        target = fitz.Rect(rect.left(), rect.top(), rect.right(), rect.bottom())
        if ref.kind == "annot":
            annot = self._find_annot(page, ref.xref)
            if annot is not None:
                annot.set_rect(target)
                annot.update()
        elif ref.kind == "widget":
            for w in page.widgets():
                if w.xref == ref.xref:
                    w.rect = target
                    w.update()
                    break
        elif ref.kind == "image":
            old = fitz.Rect(*ref.data.get("rect", tuple(target)))
            matrix = ref.data.get("matrix")
            hint = (matrix, ref.data.get("spots", 1)) if matrix else None
            # The move may have to re-stamp the image, which mints a new xref.
            # Follow it, or the next drag edits an object that no longer exists.
            ref.xref = imageops.move_image(page, ref.xref, old, target, hint)
            ref.data["rect"] = tuple(target)
            # The composed transform has moved with it; the rebuild that
            # follows this edit will supply a fresh one.
            ref.data.pop("matrix", None)

    def _find_annot(self, page, xref: int):
        for annot in page.annots():
            if annot.xref == xref:
                return annot
        return None

    @Slot(object)
    def on_object_activated(self, ref):
        if ref.kind == "widget":
            self.edit_form_field(ref)
        elif ref.kind == "annot":
            self.edit_annotation_content(ref)

    def set_object_rect(self, item: ObjectItem, rect: QRectF):
        item.set_page_rect(rect)
        self.on_object_moved(item.ref, rect)

    def nudge_selected_objects(self, dx: float, dy: float) -> bool:
        items = self.selected_object_items()
        if not items:
            return False
        for item in items:
            r = item.page_rect()
            r.translate(dx, dy)
            item.set_page_rect(r)
            self.on_object_moved(item.ref, r)
        return True

    def delete_selected_objects(self) -> bool:
        items = self.selected_object_items()
        if not items:
            return False
        by_page: dict[int, list] = {}
        for item in items:
            by_page.setdefault(item.ref.page, []).append(item.ref)
        try:
            with self.ctx.edit(f"Delete {len(items)} object(s)"):
                for pno, refs in by_page.items():
                    page = self.document.page(pno)
                    for ref in refs:
                        if ref.kind == "annot":
                            annot = self._find_annot(page, ref.xref)
                            if annot is not None:
                                page.delete_annot(annot)
                        elif ref.kind == "image":
                            imageops.delete_image(
                                page, ref.xref,
                                fitz.Rect(*ref.data.get("rect",
                                                        tuple(page.rect))))
                        elif ref.kind == "widget":
                            for w in page.widgets():
                                if w.xref == ref.xref:
                                    page.delete_widget(w)
                                    break
        except Exception as exc:
            QMessageBox.warning(self, "Could not delete", str(exc))
        return True

    def annotation_info(self, ref) -> dict | None:
        try:
            page = self.document.page(ref.page)
            annot = self._find_annot(page, ref.xref)
            if annot is None:
                return None
            colors = annot.colors or {}
            stroke = colors.get("stroke")
            editable = annot.type[0] in (fitz.PDF_ANNOT_FREE_TEXT,
                                         fitz.PDF_ANNOT_TEXT)
            return {
                "stroke": theme.rgb_to_hex(stroke) if stroke else None,
                "opacity": annot.opacity if annot.opacity >= 0 else 1.0,
                "editable_text": editable,
                "content": annot.info.get("content", ""),
            }
        except Exception:
            return None

    def recolour_selected_object(self, colour: str):
        items = self.selected_object_items()
        annots = [i for i in items if i.ref.kind == "annot"]
        if not annots or not colour:
            return
        rgb = theme.hex_to_rgb(colour)
        with self.ctx.edit("Change colour"):
            for item in annots:
                page = self.document.page(item.ref.page)
                annot = self._find_annot(page, item.ref.xref)
                if annot is None:
                    continue
                try:
                    annot.set_colors(stroke=rgb)
                    annot.update()
                except Exception:
                    pass

    def set_selected_object_opacity(self, value: float):
        items = [i for i in self.selected_object_items() if i.ref.kind == "annot"]
        if not items:
            return
        with self.ctx.edit("Change opacity"):
            for item in items:
                page = self.document.page(item.ref.page)
                annot = self._find_annot(page, item.ref.xref)
                if annot is None:
                    continue
                try:
                    annot.set_opacity(value)
                    annot.update(opacity=value)
                except Exception:
                    pass

    def edit_selected_object_content(self):
        items = self.selected_object_items()
        if len(items) != 1:
            return
        ref = items[0].ref
        if ref.kind == "widget":
            self.edit_form_field(ref)
        else:
            self.edit_annotation_content(ref)

    def edit_annotation_content(self, ref):
        page = self.document.page(ref.page)
        annot = self._find_annot(page, ref.xref)
        if annot is None:
            return
        current = annot.info.get("content", "")
        dlg = dialogs.TextContentDialog(current, "Edit annotation text", self)
        if not dlg.exec():
            return
        text = dlg.text()
        with self.ctx.edit("Edit annotation text", page=ref.page):
            page = self.document.page(ref.page)
            annot = self._find_annot(page, ref.xref)
            if annot is None:
                return
            if annot.type[0] == fitz.PDF_ANNOT_FREE_TEXT:
                rect = annot.rect
                colors = annot.colors or {}
                page.delete_annot(annot)
                new = page.add_freetext_annot(
                    rect, text, fontsize=self.ctx.style.font_size,
                    text_color=colors.get("stroke") or (0, 0, 0),
                    fill_color=colors.get("fill"))
                new.update()
            else:
                info = annot.info
                info["content"] = text
                annot.set_info(info)
                annot.update()

    def edit_form_field(self, ref):
        page = self.document.page(ref.page)
        target = None
        for w in page.widgets():
            if w.xref == ref.xref:
                target = w
                break
        if target is None:
            return
        dlg = dialogs.FormFieldDialog(target, self)
        if not dlg.exec():
            return
        value = dlg.value()
        with self.ctx.edit(f"Fill “{target.field_name or 'field'}”", page=ref.page):
            page = self.document.page(ref.page)
            for w in page.widgets():
                if w.xref == ref.xref:
                    w.field_value = value
                    w.update()
                    break

    def flatten_forms(self):
        if not self.document.is_open:
            return
        if QMessageBox.question(
                self, "Flatten form fields",
                "Form fields become ordinary page content and can no longer "
                "be filled in. Continue?") != QMessageBox.Yes:
            return
        with self.ctx.edit("Flatten form fields"):
            doc = self.document.doc
            for pno in range(doc.page_count):
                page = doc[pno]
                # page.annots() deliberately skips widgets, so go through
                # page.widgets() and bake in each field's rendered appearance.
                for widget in list(page.widgets()):
                    rect = fitz.Rect(widget.rect)
                    pix = None
                    annot = getattr(widget, "_annot", None)
                    if annot is not None:
                        try:
                            pix = annot.get_pixmap(alpha=True, dpi=200)
                        except Exception:
                            pix = None
                    if pix is None:
                        # Fall back to rasterising that patch of the page.
                        try:
                            pix = page.get_pixmap(clip=rect, dpi=200, annots=True)
                        except Exception:
                            continue
                    try:
                        page.delete_widget(widget)
                        page.insert_image(rect, pixmap=pix, overlay=True)
                    except Exception:
                        continue

    # =====================================================================
    # text selection actions
    # =====================================================================
    def _text_tool(self):
        tool = self.tool
        if tool is not None and hasattr(tool, "selection_quads"):
            return tool
        return self.tools["text_select"]

    def copy_text_selection(self):
        tool = self._text_tool()
        text = tool.selection_text() if hasattr(tool, "selection_text") else ""
        if text:
            QApplication.clipboard().setText(text)
            self.show_status(f"Copied {len(text)} characters")
        else:
            self.show_status("Nothing selected — use the text tool to select first")

    def select_all_text(self):
        self.activate_tool("text_select")
        tool = self.tools["text_select"]
        index = self.view.current_page
        pt = self.view.text_cache.get(index)
        if not pt:
            return
        tool.page_index = index
        tool.start, tool.end = 0, len(pt.chars)
        tool._paint()
        self.show_status(f"Selected all text on page {index + 1}")

    def apply_markup_from_selection(self, kind: str):
        tool = self._text_tool()
        if hasattr(tool, "apply_markup"):
            tool.apply_markup(kind)

    def redact_text_selection(self):
        tool = self._text_tool()
        if hasattr(tool, "redact_selection"):
            tool.redact_selection()

    def delete_text_selection(self):
        tool = self._text_tool()
        if hasattr(tool, "delete_selection"):
            tool.delete_selection()

    def delete_current_selection(self):
        if self.selected_object_items():
            self.delete_selected_objects()
            return
        # The Delete shortcut is owned by this action, so the text tools never
        # see the key themselves - dispatch to whichever one is active.
        tool = self.tool
        if tool is not None and hasattr(tool, "delete_hovered") and \
                tool.delete_hovered():
            return
        self.delete_text_selection()

    # =====================================================================
    # page operations
    # =====================================================================
    def target_pages(self) -> list[int]:
        picked = self.thumbnails.selected_pages()
        return picked or [self.view.current_page]

    def insert_pages(self, after: bool = True):
        if not self.document.is_open:
            return
        index = self.view.current_page + (1 if after else 0)
        with self.ctx.edit("Insert page", geometry=True):
            pageops.insert_like(self.document.doc, index,
                                template=self.view.current_page)
        self.after_structure_change(index)

    def insert_pages_dialog(self):
        if not self.document.is_open:
            return
        dlg = dialogs.InsertPagesDialog(self.document.page_count,
                                        self.view.current_page, self)
        if not dlg.exec():
            return
        where = dlg.where.currentIndex()
        current = self.view.current_page
        index = {0: current + 1, 1: current, 2: 0,
                 3: self.document.page_count}[where]
        try:
            if dlg.blank.isChecked():
                choice = dlg.size.currentText()
                with self.ctx.edit("Insert pages", geometry=True):
                    if choice == "Match current page":
                        pageops.insert_like(self.document.doc, index,
                                            template=current,
                                            count=dlg.count.value())
                    else:
                        w, h = pageops.PAGE_SIZES[choice]
                        pageops.insert_blank(self.document.doc, index, w, h,
                                             dlg.count.value())
            else:
                path = dlg.path.text()
                if not path or not os.path.exists(path):
                    QMessageBox.warning(self, "Insert pages",
                                        "Choose a PDF to insert.")
                    return
                src = fitz.open(path)
                total = src.page_count
                src.close()
                rng = dialogs.parse_page_range(dlg.range_.text(), total)
                with self.ctx.edit("Insert pages", geometry=True):
                    if rng and len(rng) < total:
                        tmp = fitz.open(path)
                        tmp.select(rng)
                        self.document.doc.insert_pdf(tmp, start_at=index)
                        tmp.close()
                    else:
                        pageops.import_pdf(self.document.doc, path, index)
        except Exception as exc:
            QMessageBox.critical(self, "Insert failed", str(exc))
            return
        self.after_structure_change(index)

    def duplicate_pages(self):
        if not self.document.is_open:
            return
        pages = self.target_pages()
        with self.ctx.edit("Duplicate page", geometry=True):
            pageops.duplicate_pages(self.document.doc, pages)
        self.after_structure_change(pages[0] + 1)

    def delete_pages(self):
        if not self.document.is_open:
            return
        pages = self.target_pages()
        if len(pages) >= self.document.page_count:
            QMessageBox.warning(self, "Delete pages",
                                "A document must keep at least one page.")
            return
        word = "page" if len(pages) == 1 else f"{len(pages)} pages"
        if QMessageBox.question(self, "Delete pages",
                                f"Delete {word}?") != QMessageBox.Yes:
            return
        with self.ctx.edit("Delete page", geometry=True):
            pageops.delete_pages(self.document.doc, pages)
        self.after_structure_change(max(0, pages[0] - 1))

    def rotate_pages(self, delta: int):
        if not self.document.is_open:
            return
        pages = self.target_pages()
        with self.ctx.edit("Rotate page", geometry=True):
            pageops.rotate_pages(self.document.doc, pages, delta)
        self.thumbnails.invalidate()

    def reorder_pages(self, order: list[int]):
        if not self.document.is_open or len(order) != self.document.page_count:
            return
        if order == list(range(self.document.page_count)):
            return
        try:
            with self.ctx.edit("Reorder pages", geometry=True):
                pageops.reorder(self.document.doc, order)
        except Exception as exc:
            QMessageBox.warning(self, "Reorder failed", str(exc))
        self.thumbnails.rebuild()
        self.outline.rebuild()

    def extract_pages(self):
        if not self.document.is_open:
            return
        pages = self.target_pages()
        stem = os.path.splitext(self.document.title)[0]
        path, _ = QFileDialog.getSaveFileName(
            self, "Extract pages to",
            os.path.join(self._start_dir(), f"{stem}_extract.pdf"),
            "PDF files (*.pdf)")
        if not path:
            return
        try:
            data = pageops.extract_to_bytes(self.document.doc, pages)
            with open(path, "wb") as fh:
                fh.write(data)
        except Exception as exc:
            QMessageBox.critical(self, "Extract failed", str(exc))
            return
        self.show_status(f"Extracted {len(pages)} page(s) to "
                         f"{os.path.basename(path)}")

    def reset_crop(self):
        if not self.document.is_open:
            return
        with self.ctx.edit("Reset crop", geometry=True):
            for i in self.target_pages():
                pageops.reset_crop(self.document.doc, i)

    def resize_pages(self):
        if not self.document.is_open:
            return
        from PySide6.QtWidgets import QInputDialog
        names = list(pageops.PAGE_SIZES)
        name, ok = QInputDialog.getItem(self, "Resize pages", "New page size:",
                                        names, names.index("A4"), False)
        if not ok:
            return
        w, h = pageops.PAGE_SIZES[name]
        pages = self.target_pages()
        with self.ctx.edit(f"Resize to {name}", geometry=True):
            pageops.resize_pages(self.document.doc, pages, w, h)
        self.thumbnails.rebuild()

    def add_page_numbers(self):
        if not self.document.is_open:
            return
        dlg = dialogs.PageNumberDialog(self)
        if not dlg.exec():
            return
        with self.ctx.edit("Add page numbers"):
            pageops.add_page_numbers(
                self.document.doc, fmt=dlg.fmt.currentText(),
                size=dlg.size.value(), position=dlg.position.currentText(),
                start_at=dlg.start.value(), skip_first=dlg.skip.isChecked())

    def add_watermark(self):
        if not self.document.is_open:
            return
        dlg = dialogs.WatermarkDialog(self.document.page_count, self)
        if not dlg.exec():
            return
        pages = dialogs.parse_page_range(dlg.pages.text(), self.document.page_count)
        if not pages:
            return
        opacity = dlg.opacity.value() / 100.0
        try:
            with self.ctx.edit("Add watermark"):
                if dlg.mode_image.isChecked():
                    path = dlg.image.text()
                    if not path:
                        raise ValueError("Choose an image first")
                    pageops.add_image_watermark(self.document.doc, pages, path,
                                                opacity=opacity,
                                                on_top=dlg.on_top.isChecked())
                else:
                    pageops.add_watermark(
                        self.document.doc, pages, dlg.text.text(),
                        size=dlg.size.value(), opacity=opacity,
                        angle=dlg.angle.value(), on_top=dlg.on_top.isChecked())
        except Exception as exc:
            QMessageBox.critical(self, "Watermark failed", str(exc))

    def flatten_annotations(self):
        if not self.document.is_open:
            return
        if QMessageBox.question(
                self, "Flatten annotations",
                "Annotations become part of the page and can no longer be "
                "edited. Continue?") != QMessageBox.Yes:
            return
        with self.ctx.edit("Flatten annotations"):
            n = pageops.flatten_annotations(self.document.doc)
        self.show_status(f"Flattened {n} annotation(s)")

    def after_structure_change(self, goto: int | None = None):
        self.view.reload(keep_view=False)
        self.thumbnails.rebuild()
        self.outline.rebuild()
        self.page_spin.setRange(1, max(1, self.document.page_count))
        self.page_total.setText(f"of {self.document.page_count}")
        if goto is not None:
            self.view.goto_page(max(0, min(goto, self.document.page_count - 1)))
        self._update_enabled()

    # =====================================================================
    # security & properties
    # =====================================================================
    def show_properties(self):
        if not self.document.is_open:
            return
        dlg = dialogs.MetadataDialog(self.document, self)
        if dlg.exec():
            self.document.set_metadata(dlg.values())
            self.refresh_after_edit()
            self.show_status("Document properties updated")

    def set_security(self):
        if not self.document.is_open:
            return
        dlg = dialogs.SecurityDialog(self)
        if not dlg.exec():
            return
        if not dlg.user_pw.text() and not dlg.owner_pw.text():
            QMessageBox.warning(self, "Password", "Enter at least one password.")
            return
        stem = os.path.splitext(self.document.path or "document.pdf")[0]
        path, _ = QFileDialog.getSaveFileName(
            self, "Save protected copy", stem + "_protected.pdf",
            "PDF files (*.pdf)")
        if not path:
            return
        try:
            data = pageops.encrypt_bytes(
                self.document.doc, dlg.user_pw.text(), dlg.owner_pw.text(),
                dlg.allow_print.isChecked(), dlg.allow_copy.isChecked(),
                dlg.allow_annotate.isChecked(), dlg.allow_modify.isChecked())
            with open(path, "wb") as fh:
                fh.write(data)
        except Exception as exc:
            QMessageBox.critical(self, "Encryption failed", str(exc))
            return
        self.show_status(f"Protected copy saved to {os.path.basename(path)}")

    def remove_security(self):
        if not self.document.is_open:
            return
        stem = os.path.splitext(self.document.path or "document.pdf")[0]
        path, _ = QFileDialog.getSaveFileName(
            self, "Save unprotected copy", stem + "_open.pdf", "PDF files (*.pdf)")
        if not path:
            return
        try:
            with open(path, "wb") as fh:
                fh.write(pageops.decrypt_bytes(self.document.doc))
        except Exception as exc:
            QMessageBox.critical(self, "Failed", str(exc))
            return
        self.show_status(f"Unprotected copy saved to {os.path.basename(path)}")

    # =====================================================================
    # context menu
    # =====================================================================
    @Slot(object, QPointF)
    def show_context_menu(self, event, global_pos):
        menu = QMenu(self)
        items = self.selected_object_items()
        if items:
            menu.addAction(f"Delete {len(items)} object(s)",
                           self.delete_selected_objects)
            if len(items) == 1 and items[0].ref.kind in ("annot", "widget"):
                menu.addAction("Edit contents…", self.edit_selected_object_content)
            menu.addSeparator()

        pt = self.view.text_cache.get(event.page)
        line = pt.line_at(event.fpoint()) if pt else None
        if line is not None:
            menu.addAction("Edit this line", lambda: (
                self.activate_tool("edit_text"),
                self.tools["edit_text"].begin_edit(event)))
            block = pt.block_at(event.fpoint())
            if block is not None and len(block.lines) > 1:
                menu.addAction("Edit this paragraph", lambda: (
                    self.activate_tool("edit_text"),
                    self.tools["edit_text"].begin_block_edit(event)))
            menu.addAction("Copy line", lambda: (
                QApplication.clipboard().setText(line.text),
                self.show_status("Line copied")))
            menu.addSeparator()

        tool = self._text_tool()
        if hasattr(tool, "selection_quads") and tool.selection_quads():
            menu.addAction("Copy", self.copy_text_selection)
            menu.addAction("Highlight",
                           lambda: self.apply_markup_from_selection("highlight"))
            menu.addAction("Strike out",
                           lambda: self.apply_markup_from_selection("strikeout"))
            menu.addAction("Redact", self.redact_text_selection)
            menu.addSeparator()

        menu.addAction(self.act_insert_page)
        menu.addAction(self.act_duplicate_page)
        menu.addAction(self.act_delete_page)
        menu.addSeparator()
        menu.addAction(self.act_rotate_left)
        menu.addAction(self.act_rotate_right)
        menu.addSeparator()
        menu.addAction(self.act_fit_width)
        menu.addAction(self.act_fit_page)
        menu.exec(global_pos.toPoint())

    # =====================================================================
    # help / misc
    # =====================================================================
    def show_about(self):
        dialogs.AboutDialog(self).exec()

    def show_shortcuts(self):
        rows = [
            ("Ctrl+O / Ctrl+S", "Open / Save"),
            ("Ctrl+Z / Ctrl+Shift+Z", "Undo / Redo"),
            ("Ctrl+F / F3", "Find / Find next"),
            ("Ctrl++ / Ctrl+-", "Zoom in / out"),
            ("Ctrl+1 / Ctrl+0", "Fit width / Fit page"),
            ("Ctrl+scroll", "Zoom at the pointer"),
            ("Space + drag", "Pan"),
            ("V / H / T", "Select / Pan / Text tools"),
            ("E / A", "Edit text / Add text"),
            ("U / D / R", "Highlight / Draw / Rectangle"),
            ("X / C", "Erase / Crop"),
            ("Delete", "Delete selection"),
            ("Arrows", "Nudge selected object (Shift = 10pt)"),
            ("F9 / F10", "Toggle sidebar / properties"),
        ]
        body = "".join(
            f"<tr><td style='padding:3px 18px 3px 0'><b>{k}</b></td>"
            f"<td style='padding:3px 0'>{v}</td></tr>" for k, v in rows)
        QMessageBox.information(self, "Keyboard shortcuts",
                                f"<table>{body}</table>")

    def _start_dir(self) -> str:
        if self.document.path:
            return os.path.dirname(self.document.path)
        if self._recent:
            return os.path.dirname(self._recent[0])
        return os.path.expanduser("~")

    def _remember_recent(self, path: str):
        path = os.path.abspath(path)
        if path in self._recent:
            self._recent.remove(path)
        self._recent.insert(0, path)
        del self._recent[MAX_RECENT:]
        self.settings.setValue("recent", self._recent)
        self._refresh_recent_menu()

    def _refresh_recent_menu(self):
        self.recent_menu.clear()
        existing = [p for p in self._recent if os.path.exists(p)]
        if not existing:
            action = self.recent_menu.addAction("Nothing yet")
            action.setEnabled(False)
            return
        for path in existing:
            action = self.recent_menu.addAction(os.path.basename(path))
            action.setStatusTip(path)
            action.triggered.connect(lambda _=False, p=path: self.file_open(p))
        self.recent_menu.addSeparator()
        self.recent_menu.addAction("Clear list", self._clear_recent)

    def _clear_recent(self):
        self._recent = []
        self.settings.setValue("recent", [])
        self._refresh_recent_menu()

    def _confirm_discard(self) -> bool:
        if not self.document.is_open or not self.document.dirty:
            return True
        answer = QMessageBox.question(
            self, "Unsaved changes",
            f"Save changes to {self.document.title}?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if answer == QMessageBox.Cancel:
            return False
        if answer == QMessageBox.Save:
            self.file_save()
            return not self.document.dirty
        return True

    # ---- drag & drop
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path:
                self.file_open(path)
                break

    def closeEvent(self, event):
        if not self._confirm_discard():
            event.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowstate", self.saveState())
        event.accept()


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    app = QApplication(argv)
    app.setApplicationName(APP_TITLE)
    app.setApplicationDisplayName(APP_TITLE)
    app.setOrganizationName("PDFStudio")

    window = MainWindow()
    window.setAcceptDrops(True)
    window.show()

    for arg in argv[1:]:
        if os.path.exists(arg):
            window.file_open(arg)
            break
    return app.exec()
