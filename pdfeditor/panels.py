"""Left-hand docks: page thumbnails, bookmarks and search."""

from __future__ import annotations

from PySide6.QtCore import (QEvent, QItemSelectionModel, QRectF, QSize, Qt,
                            QTimer, Signal)
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMenu, QPushButton, QSizePolicy, QSlider,
                               QToolButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from . import icons, textops

THUMB_SIZES = (96, 132, 172, 220)


class _Panel(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.document = window.document
        self.palette_ = window.palette_
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.layout_ = layout

    def _bar(self) -> QHBoxLayout:
        bar = QWidget()
        bar.setStyleSheet(
            f"background:{self.palette_.panel_alt};"
            f"border-bottom:1px solid {self.palette_.border};")
        h = QHBoxLayout(bar)
        h.setContentsMargins(7, 5, 7, 5)
        h.setSpacing(4)
        self.layout_.addWidget(bar)
        return h

    def _tool_button(self, name: str, tip: str, slot) -> QToolButton:
        b = QToolButton()
        b.setIcon(icons.icon(name, self.palette_.text, 17))
        b.setIconSize(QSize(17, 17))
        b.setToolTip(tip)
        b.clicked.connect(slot)
        return b


# ============================================================== thumbnails
class ThumbnailPanel(_Panel):
    """Page grid with drag-to-reorder and a page context menu."""

    def __init__(self, window):
        super().__init__(window)
        self.size_index = 1
        self._pending: list[int] = []

        bar = self._bar()
        bar.addWidget(self._tool_button("page_add", "Insert blank page after",
                                        window.act_insert_page.trigger))
        bar.addWidget(self._tool_button("page_copy", "Duplicate selected pages",
                                        window.act_duplicate_page.trigger))
        bar.addWidget(self._tool_button("rotate_left", "Rotate left",
                                        window.act_rotate_left.trigger))
        bar.addWidget(self._tool_button("rotate_right", "Rotate right",
                                        window.act_rotate_right.trigger))
        bar.addWidget(self._tool_button("trash", "Delete selected pages",
                                        window.act_delete_page.trigger))
        bar.addStretch(1)
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(0, len(THUMB_SIZES) - 1)
        self.zoom_slider.setValue(self.size_index)
        self.zoom_slider.setFixedWidth(64)
        self.zoom_slider.setToolTip("Thumbnail size")
        self.zoom_slider.valueChanged.connect(self._set_size)
        bar.addWidget(self.zoom_slider)

        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setSpacing(7)
        self.list.setUniformItemSizes(False)
        self.list.setWordWrap(True)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.itemSelectionChanged.connect(self._selection_changed)
        self.list.model().rowsMoved.connect(self._rows_moved)
        self.list.setStyleSheet(
            f"QListWidget{{background:{self.palette_.panel};}}"
            f"QListWidget::item{{border-radius:6px;padding:4px;"
            f"color:{self.palette_.text_muted};}}"
            f"QListWidget::item:selected{{background:{self.palette_.accent_soft};"
            f"color:{self.palette_.accent};font-weight:600;}}")
        self.layout_.addWidget(self.list, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._render_batch)
        self.list.verticalScrollBar().valueChanged.connect(self._queue_visible)
        self._suppress = False

    # ------------------------------------------------------------- building
    def rebuild(self):
        self._suppress = True
        self.list.clear()
        width = THUMB_SIZES[self.size_index]
        # Icons are scaled to iconSize, so it has to track the thumbnail width.
        self.list.setIconSize(QSize(width, int(width * 1.45)))
        for i in range(self.document.page_count):
            item = QListWidgetItem(str(i + 1))
            item.setData(Qt.UserRole, i)
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignBottom)
            item.setSizeHint(QSize(width + 18, int(width * 1.45) + 26))
            item.setIcon(self._placeholder(width))
            self.list.addItem(item)
        self._suppress = False
        self._queue_visible()

    def _placeholder(self, width: int) -> QIcon:
        h = int(width * 1.35)
        pm = QPixmap(width, h)
        pm.fill(QColor("#ffffff"))
        p = QPainter(pm)
        p.setPen(QPen(QColor(self.palette_.border), 1))
        p.drawRect(0, 0, width - 1, h - 1)
        p.end()
        return QIcon(pm)

    def _set_size(self, index: int):
        self.size_index = index
        self.rebuild()

    def _queue_visible(self):
        if self._suppress:
            return
        first = self.list.indexAt(self.list.viewport().rect().topLeft())
        last = self.list.indexAt(self.list.viewport().rect().bottomRight())
        lo = max(0, (first.row() if first.isValid() else 0) - 4)
        hi = min(self.list.count(),
                 (last.row() + 6) if last.isValid() else min(self.list.count(), 24))
        self._pending = [r for r in range(lo, hi)]
        if self._pending:
            self._timer.start()

    def _render_batch(self):
        width = THUMB_SIZES[self.size_index]
        done = 0
        while self._pending and done < 3:
            row = self._pending.pop(0)
            item = self.list.item(row)
            if item is None:
                continue
            index = item.data(Qt.UserRole)
            if item.data(Qt.UserRole + 1) == (self.document.revision, width):
                continue
            pm = self.window.renderer.thumbnail(index, width)
            if pm is not None:
                item.setIcon(QIcon(self._framed(pm)))
                item.setData(Qt.UserRole + 1, (self.document.revision, width))
            done += 1
        if not self._pending:
            self._timer.stop()

    def _framed(self, pm: QPixmap) -> QPixmap:
        out = QPixmap(pm.size())
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.drawPixmap(0, 0, pm)
        p.setPen(QPen(QColor(self.palette_.border), 1))
        p.drawRect(0, 0, out.width() - 1, out.height() - 1)
        p.end()
        return out

    def invalidate(self):
        for row in range(self.list.count()):
            self.list.item(row).setData(Qt.UserRole + 1, None)
        self._queue_visible()

    # ------------------------------------------------------------ selection
    def selected_pages(self) -> list[int]:
        return sorted(i.data(Qt.UserRole) for i in self.list.selectedItems())

    def set_current(self, index: int):
        if self._suppress or index >= self.list.count():
            return
        self._suppress = True
        item = self.list.item(index)
        if item is not None:
            self.list.setCurrentItem(item, QItemSelectionModel.ClearAndSelect)
            self.list.scrollToItem(item, QAbstractItemView.EnsureVisible)
        self._suppress = False

    def _selection_changed(self):
        if self._suppress:
            return
        rows = self.selected_pages()
        if rows:
            self.window.view.goto_page(rows[0])
        self.window.update_page_actions()

    def _rows_moved(self, parent, start, end, dest, row):
        if self._suppress:
            return
        order = [self.list.item(r).data(Qt.UserRole)
                 for r in range(self.list.count())]
        self.window.reorder_pages(order)

    def _menu(self, pos):
        item = self.list.itemAt(pos)
        if item is not None and not item.isSelected():
            self.list.setCurrentItem(item)
        w = self.window
        menu = QMenu(self)
        menu.addAction(w.act_insert_page)
        menu.addAction(w.act_insert_page_before)
        menu.addAction(w.act_duplicate_page)
        menu.addSeparator()
        menu.addAction(w.act_rotate_left)
        menu.addAction(w.act_rotate_right)
        menu.addSeparator()
        menu.addAction(w.act_extract_pages)
        menu.addAction(w.act_export_images)
        menu.addSeparator()
        menu.addAction(w.act_delete_page)
        menu.exec(self.list.mapToGlobal(pos))


# ================================================================= outline
class OutlinePanel(_Panel):
    def __init__(self, window):
        super().__init__(window)
        bar = self._bar()
        bar.addWidget(self._tool_button("plus", "Bookmark the current page",
                                        self._add))
        bar.addWidget(self._tool_button("trash", "Delete bookmark", self._remove))
        bar.addStretch(1)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.itemDoubleClicked.connect(self._rename)
        self.layout_.addWidget(self.tree, 1)

        self.empty = QLabel("No bookmarks in this document")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setProperty("muted", True)
        self.empty.setWordWrap(True)
        self.layout_.addWidget(self.empty)
        self.empty.hide()

    def rebuild(self):
        self.tree.clear()
        toc = self.document.outline()
        if not toc:
            self.tree.hide()
            self.empty.show()
            return
        self.tree.show()
        self.empty.hide()
        stack: list[tuple[int, QTreeWidgetItem]] = []
        for level, title, page in toc:
            node = QTreeWidgetItem([title.strip() or "Untitled"])
            node.setData(0, Qt.UserRole, max(0, page - 1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            if stack:
                stack[-1][1].addChild(node)
            else:
                self.tree.addTopLevelItem(node)
            stack.append((level, node))
        self.tree.expandToDepth(1)

    def _clicked(self, item, _col):
        page = item.data(0, Qt.UserRole)
        if page is not None:
            self.window.view.goto_page(int(page))

    def _rename(self, item, _col):
        from PySide6.QtWidgets import QInputDialog
        new, ok = QInputDialog.getText(self, "Rename bookmark", "Title:",
                                       text=item.text(0))
        if ok and new.strip():
            self._write_toc(rename=(item, new.strip()))

    def _add(self):
        if not self.document.is_open:
            return
        from PySide6.QtWidgets import QInputDialog
        page = self.window.view.current_page
        title, ok = QInputDialog.getText(self, "Add bookmark", "Title:",
                                         text=f"Page {page + 1}")
        if not ok or not title.strip():
            return
        toc = self.document.outline()
        toc.append([1, title.strip(), page + 1])
        toc.sort(key=lambda e: e[2])
        with self.document.edit("Add bookmark"):
            self.document.doc.set_toc(toc)
        self.rebuild()

    def _remove(self):
        item = self.tree.currentItem()
        if item is None:
            return
        self._write_toc(delete=item)

    def _write_toc(self, rename=None, delete=None):
        toc = self.document.outline()
        target_title = None
        target_page = None
        item = rename[0] if rename else delete
        if item is not None:
            target_title = item.text(0)
            target_page = item.data(0, Qt.UserRole)
        new_toc = []
        for entry in toc:
            if (entry[1] == target_title and entry[2] - 1 == target_page):
                if delete is not None:
                    continue
                entry = [entry[0], rename[1], entry[2]]
            new_toc.append(entry)
        with self.document.edit("Edit bookmarks"):
            self.document.doc.set_toc(new_toc)
        self.rebuild()


# ================================================================== search
class SearchPanel(_Panel):
    def __init__(self, window):
        super().__init__(window)
        self.hits: list[textops.Hit] = []
        self._scan_page = 0
        self._needle = ""

        top = QWidget()
        v = QVBoxLayout(top)
        v.setContentsMargins(9, 9, 9, 7)
        v.setSpacing(7)
        row = QHBoxLayout()
        row.setSpacing(5)
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("Find in document…")
        self.entry.returnPressed.connect(self.run)
        row.addWidget(self.entry, 1)
        find = QPushButton("Find")
        find.setProperty("accent", True)
        find.clicked.connect(self.run)
        row.addWidget(find)
        v.addLayout(row)

        opts = QHBoxLayout()
        opts.setSpacing(11)
        self.case = QCheckBox("Match case")
        opts.addWidget(self.case)
        opts.addStretch(1)
        self.count = QLabel("")
        self.count.setProperty("muted", True)
        opts.addWidget(self.count)
        v.addLayout(opts)
        top.setStyleSheet(f"background:{self.palette_.panel_alt};"
                          f"border-bottom:1px solid {self.palette_.border};")
        self.layout_.addWidget(top)

        self.list = QListWidget()
        self.list.itemActivated.connect(self._goto)
        self.list.itemClicked.connect(self._goto)
        self.list.setWordWrap(True)
        self.layout_.addWidget(self.list, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._scan_step)

    def focus(self):
        self.entry.setFocus()
        self.entry.selectAll()

    def run(self):
        needle = self.entry.text()
        self.clear_marks()
        self.list.clear()
        self.hits = []
        self._needle = needle
        if not needle or not self.document.is_open:
            self.count.setText("")
            return
        self._scan_page = 0
        self.count.setText("Searching…")
        self._timer.start()

    def _scan_step(self):
        if not self.document.is_open or self._scan_page >= self.document.page_count:
            self._timer.stop()
            n = len(self.hits)
            self.count.setText(f"{n} result{'' if n == 1 else 's'}")
            if n:
                self.window.view.reveal(self.hits[0].page, self.hits[0].rect)
                self.list.setCurrentRow(0)
            return
        for _ in range(4):
            if self._scan_page >= self.document.page_count:
                break
            page = self.document.page(self._scan_page)
            try:
                rects = page.search_for(self._needle)
            except Exception:
                rects = []
            if rects:
                plain = page.get_text("text")
                lower = plain if self.case.isChecked() else plain.lower()
                key = self._needle if self.case.isChecked() else self._needle.lower()
                starts, pos = [], 0
                while True:
                    k = lower.find(key, pos)
                    if k < 0:
                        break
                    starts.append(k)
                    pos = k + max(1, len(key))
                for i, r in enumerate(rects):
                    if self.case.isChecked():
                        try:
                            if self._needle not in page.get_textbox(r):
                                continue
                        except Exception:
                            pass
                    ctx = ""
                    if i < len(starts):
                        k = starts[i]
                        ctx = " ".join(
                            plain[max(0, k - 38):k + len(self._needle) + 38].split())
                    self.hits.append(textops.Hit(self._scan_page, r,
                                                 self._needle, ctx))
            self._scan_page += 1
        self._refresh_list()
        self._mark_pages()
        self.count.setText(f"{len(self.hits)} so far…")

    def _refresh_list(self):
        while self.list.count() < len(self.hits):
            hit = self.hits[self.list.count()]
            item = QListWidgetItem(f"Page {hit.page + 1}   {hit.context}")
            item.setData(Qt.UserRole, self.list.count())
            item.setSizeHint(QSize(10, 40))
            self.list.addItem(item)

    def _mark_pages(self):
        by_page: dict[int, list] = {}
        for hit in self.hits:
            by_page.setdefault(hit.page, []).append(hit.rect)
        for i, ov in enumerate(self.window.view.scene_.overlays):
            rects = by_page.get(i, [])
            ov.search = [QRectF(r.x0, r.y0, r.width, r.height) for r in rects]
            ov.update()

    def clear_marks(self):
        for ov in self.window.view.scene_.overlays:
            if ov.search or ov.search_active:
                ov.search = []
                ov.search_active = None
                ov.update()

    def _goto(self, item):
        index = item.data(Qt.UserRole)
        if index is None or index >= len(self.hits):
            return
        self.select_hit(index)

    def select_hit(self, index: int):
        if not (0 <= index < len(self.hits)):
            return
        hit = self.hits[index]
        for ov in self.window.view.scene_.overlays:
            if ov.search_active is not None:
                ov.search_active = None
                ov.update()
        ov = self.window.view.scene_.overlay(hit.page)
        if ov is not None:
            ov.search_active = QRectF(hit.rect.x0, hit.rect.y0,
                                      hit.rect.width, hit.rect.height)
            ov.update()
        self.window.view.reveal(hit.page, hit.rect)
        self.list.setCurrentRow(index)

    def step(self, delta: int):
        if not self.hits:
            self.run()
            return
        row = self.list.currentRow()
        self.select_hit((row + delta) % len(self.hits))
