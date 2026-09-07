"""Main window: Viewer / TODO / Wire Numbers / Component Labels / PDF Tools
panes (tabified, floatable dock widgets), toolbar, comment + navigation docks.

The dialogs it opens are NOT here, and neither is printing. They were, along
with everything else, and that is what this module is being unwound from --
`app/settings_dialog.py` holds the preferences dialog, `app/dialogs.py` the
annotation and audit ones, and `app/printing.py` the printer, the two print
dialogs and the page raster.

What is left is named rather than glossed, and one clause of it was WRONG:
the five panes are already their own modules under `app/panels/`, so what the
window holds is their DOCKING rather than the panes -- measured, and the
sentence that said otherwise had been carried forward unread. The rest is the
toolbar, the menus, the file lifecycle and the document itself."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QColor
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QToolBar, QFileDialog, QMessageBox, QDockWidget,
    QSpinBox, QLabel, QWidget, QDialog, QCheckBox, QComboBox, QColorDialog,
    QDoubleSpinBox, QPushButton, QStatusBar, QApplication,
)

from . import __app_name__, __version__, __copyright__, app_icon
from .config import AppConfig
from .dialogs import (
    FillDialog, TextEditDialog, WaiveDialog, _apply_font, _fill_swatch, _swatch,
)
from .settings_dialog import SettingsDialog
from . import printing
from .model.document import Document
from .model.annotations import Annotation
from .viewer.pdf_view import PdfView
from .viewer import tools as T
from .viewer.command_stack import ModifyAnnotationCommand, RemoveAnnotationCommand, capture
from .panels.comment_panel import CommentPanel
from .panels.todo_panel import TodoPanel
from .panels.wire_panel import WirePanel
from .panels.component_panel import ComponentPanel
from .panels.tools_panel import ToolsPanel, pdf_path_from_mime
from .panels.audit_panel import AuditPanel
from .panels.nav_panel import NavPanel


# --- main window ------------------------------------------------------------


# Bumped whenever the dock set/layout handling changes so QMainWindow
# .restoreState() rejects (and we fall back to the default arrangement) layouts
# saved by an older build — e.g. the earlier QTabWidget central widget, or a
# pre-fix build whose saved layout left the main panes un-tabbed.
_UI_STATE_VERSION = 3


class _MainDocks:
    """A thin ``QTabWidget``-compatible facade over the tabified main dock
    widgets (Viewer / TODO / Wire Numbers / Component Labels / PDF Tools).

    The five main panes used to live in a ``QTabWidget`` central widget. They
    now live in floatable, dockable ``QDockWidget``s — like the Comments /
    Navigation panels — so any tab can be pulled into its own window or docked
    elsewhere. This shim lets the rest of the window keep calling
    ``tabs.setCurrentWidget(w)`` / ``tabs.currentWidget()`` unchanged, and
    tracks which pane is "current" by watching the docks' visibility.
    """

    def __init__(self, window):
        self._window = window
        self._docks = {}          # panel widget -> QDockWidget
        self._order = []          # panel widgets, in tab order
        self._current = None

    def add(self, widget, title, object_name):
        dock = QDockWidget(title, self._window)
        dock.setObjectName(object_name)
        dock.setWidget(widget)
        dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        dock.visibilityChanged.connect(
            lambda vis, w=widget: self._on_visibility(w, vis))
        self._docks[widget] = dock
        self._order.append(widget)
        if self._current is None:
            self._current = widget
        return dock

    def _on_visibility(self, widget, visible):
        # A dock reports visible when it becomes the raised tab (or is floated /
        # revealed). Track that as the "current" pane so currentWidget() follows
        # the user clicking between tabs, not just explicit setCurrentWidget().
        if visible:
            self._current = widget

    def dock_for(self, widget):
        return self._docks.get(widget)

    def setCurrentWidget(self, widget):
        dock = self._docks.get(widget)
        if dock is None:
            return
        self._current = widget
        dock.show()
        dock.raise_()

    def currentWidget(self):
        # Return the tracked pane unless it's been closed/hidden (e.g. a floated
        # pane the user closed with its ✕) — then fall back to a live pane so
        # callers never treat a closed pane as the active one. isHidden() is used
        # rather than isVisible() so this is correct before the window is shown
        # (headless, nothing is "visible" yet) as well as after.
        cur = self._current
        dock = self._docks.get(cur)
        if dock is not None and not dock.isHidden():
            return cur
        for w in self._order:
            d = self._docks.get(w)
            if d is not None and not d.isHidden():
                return w
        return self._order[0] if self._order else None


class MainWindow(QMainWindow):
    def __init__(self, on_progress=None):
        super().__init__()
        self._progress = on_progress or (lambda *a, **k: None)
        self.setWindowTitle(__app_name__)
        self.setWindowIcon(app_icon())
        self.resize(1320, 880)
        self.setAcceptDrops(True)   # drop a PDF anywhere to open it
        # Visual-Studio-style dockable panels: drag a pane's title bar to snap it
        # to any edge (left/right/top/bottom), split panes side-by-side, tab them
        # together, or float a pane out into its own window (and drag it back).
        # GroupedDragging is deliberately OFF: it enables Qt's floating tab-group
        # windows, and dragging one floating window onto another to merge them is
        # a known Qt hang. Without it, panes tab in the main window and float out
        # individually, but two floating windows won't merge — so no hang.
        self.setDockOptions(
            QMainWindow.AnimatedDocks | QMainWindow.AllowNestedDocks
            | QMainWindow.AllowTabbedDocks)
        # Put the pane tabs on TOP (like the old QTabWidget) instead of Qt's
        # default bottom position for tabified docks.
        self.setTabPosition(Qt.AllDockWidgetAreas, QTabWidget.North)
        self.config = AppConfig()
        self.document = None
        # What the print-preview toolbar can change and a job reads. One
        # object rather than two attributes, because `app/printing.py` is
        # where both are used and a pair of window attributes it wrote back
        # into would be the printing code half out of the window.
        self.print_options = printing.PrintOptions(
            min_line_pt=self.config.print_min_line_pt)

        self._progress("Preparing the canvas…", 62)
        self.view = PdfView(self)
        self.view.config = self.config
        self.view.requestCommentEdit.connect(self._edit_comment)
        self.view.requestTextEdit.connect(self._edit_textbox)
        self.view.requestFillEdit.connect(self._edit_fill)
        self.view.pageChanged.connect(self._on_page_changed)
        self.view.requestTool.connect(self._activate_tool)
        self.view.requestOpen.connect(self.load_document)   # drag/drop a PDF
        self.view.requestReveal.connect(self._reveal_in_panel)   # PDF mark -> panel
        # synchronous prompt used when *creating* a new comment / text box
        self.view.new_text_prompt = self._prompt_new_text
        # synchronous prompt when a drawing tool clicks an existing mark
        self.view.existing_mark_prompt = self._prompt_existing_mark

        self._progress("Setting up the wire-number engine…", 75)
        self.todo_panel = TodoPanel()
        self.wire_panel = WirePanel()
        self.component_panel = ComponentPanel()
        self.tools_panel = ToolsPanel(self)
        self.audit_panel = AuditPanel()

        self.todo_panel.activated.connect(self._jump_to)
        self.todo_panel.authorEditRequested.connect(self._edit_author)
        self.wire_panel.activated.connect(self._jump_to)        # double-click → drawing
        self.component_panel.activated.connect(self._jump_to)
        self.audit_panel.activated.connect(self._jump_to)
        self.audit_panel.runRequested.connect(self.run_audit)
        self.audit_panel.waiveRequested.connect(self._waive_finding)
        self.audit_panel.clearWaiverRequested.connect(self._clear_waiver)

        self._progress("Building the comment & TODO panels…", 85)
        # navigation dock (pages + bookmarks) on the left
        self.nav_panel = NavPanel()
        self.nav_panel.pageActivated.connect(self._nav_to_page)
        nav_dock = QDockWidget("Navigation", self)
        nav_dock.setObjectName("NavDock")
        nav_dock.setWidget(self.nav_panel)
        nav_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.addDockWidget(Qt.LeftDockWidgetArea, nav_dock)
        self.nav_dock = nav_dock

        # comment dock
        self.comment_panel = CommentPanel()
        self.comment_panel.activated.connect(self._jump_to)
        self.comment_panel.deleteRequested.connect(self._delete_annotation)
        self.comment_panel.authorEditRequested.connect(self._edit_author)
        dock = QDockWidget("Comments", self)
        dock.setObjectName("CommentDock")
        dock.setWidget(self.comment_panel)
        dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self.comment_dock = dock

        # Optional second viewer of the SAME document — a read-only reference
        # pane for keeping a legend, TOC or cover sheet in view while you work
        # on another page. It scrolls/zooms/rotates independently; because both
        # views listen to the one AnnotationStore, marks made in the main viewer
        # appear here live. Hidden until asked for (View ▸ Reference viewer).
        self.ref_view = PdfView(read_only=True)
        self.ref_view.config = self.config
        self.ref_view.set_render_enabled(False)   # nothing rendered while hidden
        # A never-shown dock is given its *minimum* width by Qt, which without a
        # floor is a ~70px sliver — and resizeDocks can't be relied on to widen
        # it (it no-ops on Windows). A real floor keeps the pane usable on every
        # platform; it stays freely resizable above this.
        self.ref_view.setMinimumWidth(260)
        self.ref_view.requestOpen.connect(self.load_document)   # drag/drop a PDF
        ref_dock = QDockWidget("Reference viewer", self)
        ref_dock.setObjectName("RefViewDock")
        ref_dock.setWidget(self.ref_view)
        ref_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.addDockWidget(Qt.RightDockWidgetArea, ref_dock)
        ref_dock.hide()
        self.ref_dock = ref_dock

        # The five main panes (Viewer / TODO / Wire Numbers / Component Labels /
        # PDF Tools) live in tabified, floatable dock widgets — like the
        # Comments / Navigation panels — so any tab can be dragged into its own
        # standalone window or docked elsewhere on screen. A zero-size, hidden
        # central widget keeps QMainWindow satisfied while the docks fill the
        # frame; ``self.tabs`` is a QTabWidget-compatible facade over them.
        central = QWidget()
        central.setMaximumSize(0, 0)
        self.setCentralWidget(central)
        self._central_stub = central

        self.tabs = _MainDocks(self)
        view_dock = self.tabs.add(self.view, "Viewer", "ViewerDock")
        todo_dock = self.tabs.add(self.todo_panel, "TODO", "TodoDock")
        wire_dock = self.tabs.add(self.wire_panel, "Wire Numbers", "WireDock")
        comp_dock = self.tabs.add(self.component_panel, "Component Labels",
                                  "ComponentDock")
        tools_dock = self.tabs.add(self.tools_panel, "PDF Tools", "PdfToolsDock")
        audit_dock = self.tabs.add(self.audit_panel, "Audit", "AuditDock")
        # Lay them out as one tab group between the Navigation (left) and
        # Comments (right) docks: [nav | main-tabs | comments]. Both horizontal
        # splits must happen *before* the tabify loop — splitDockWidget against
        # an already-tabbed dock adds a new tab instead of a neighbour, so we
        # carve out view_dock's column (and re-home the Comments dock beside it)
        # while it's still a lone dock, then tab the other panes onto it.
        self.splitDockWidget(nav_dock, view_dock, Qt.Horizontal)
        self.splitDockWidget(view_dock, self.comment_dock, Qt.Horizontal)
        for d in (todo_dock, wire_dock, comp_dock, tools_dock, audit_dock):
            self.tabifyDockWidget(view_dock, d)
        self.main_docks = [view_dock, todo_dock, wire_dock, comp_dock,
                           tools_dock, audit_dock]
        self.tabs.setCurrentWidget(self.view)   # Viewer is the default tab

        self._progress("Assembling the toolbar…", 92)
        self.setStatusBar(QStatusBar())
        self._build_menu()
        self._build_toolbar()
        self._update_actions_enabled(False)

        # Remember the freshly-built default arrangement (for "Reset panel
        # layout"), then apply whatever layout the user left last session.
        self._default_state = self.saveState(_UI_STATE_VERSION)
        self._restore_ui_state()

    # -- menu / toolbar ------------------------------------------------------

    def _build_menu(self):
        mb = self.menuBar()
        m_file = mb.addMenu("&File")
        self.act_open = m_file.addAction("&Open PDF…", self.open_pdf, QKeySequence.Open)
        self.m_recent = m_file.addMenu("Open &Recent")
        self._rebuild_recent_menu()
        self.act_save = m_file.addAction("&Save markup", self.save_markup, QKeySequence.Save)
        self.act_save_as = m_file.addAction(
            "Save &As… (fork working file)", self.save_as_fork,
            QKeySequence("Ctrl+Shift+S"))
        self.act_save_as.setToolTip(
            "Copy this file's markup into a new working file and switch to it; "
            "the original stays untouched.")
        self.act_export_pdf = m_file.addAction(
            "Export annotated PDF…", self.export_pdf, QKeySequence("Ctrl+Shift+E"))
        self.act_export_flat = m_file.addAction(
            "Export flattened PDF (for sharing)…", self.export_flat)
        self.act_export_flat.setToolTip(
            "Bake the marks into the page so they render in every viewer "
            "(browsers, Preview, thumbnails). Not re-editable — keep your "
            "working file for edits.")
        m_file.addSeparator()
        self.act_print = m_file.addAction(
            "&Print…", self.print_document, QKeySequence.Print)   # Ctrl+P
        self.act_print.setToolTip(
            "Print the drawing (with its marks) to any installed printer via the "
            "system print dialog.")
        self.act_print_preview = m_file.addAction(
            "Print pre&view…", self.print_preview)
        self.act_print_preview.setToolTip(
            "See the pages before printing, then print from the preview.")
        m_file.addSeparator()
        m_file.addAction("Settings…", self.open_settings)
        m_file.addSeparator()
        m_file.addAction("Quit", self.close, QKeySequence.Quit)

        m_edit = mb.addMenu("&Edit")
        undo = self.view.undo_stack.createUndoAction(self, "Undo")
        undo.setShortcut(QKeySequence.Undo)
        redo = self.view.undo_stack.createRedoAction(self, "Redo")
        redo.setShortcut(QKeySequence.Redo)
        m_edit.addAction(undo)
        m_edit.addAction(redo)

        m_view = mb.addMenu("&View")
        m_view.addAction("Fit width", self.view.fit_width)
        m_view.addAction("Fit page", self.view.fit_page)
        m_view.addAction("Zoom in", self.view.zoom_in, QKeySequence.ZoomIn)
        m_view.addAction("Zoom out", self.view.zoom_out, QKeySequence.ZoomOut)
        m_view.addSeparator()
        m_view.addAction("Find…", self.view.show_search, QKeySequence.Find)
        m_view.addAction("Find next", self.view.search_next,
                         QKeySequence.FindNext)
        m_view.addAction("Find previous", self.view.search_prev,
                         QKeySequence.FindPrevious)
        m_view.addSeparator()
        act_cmt = m_view.addAction(
            "Toggle comment sidebar",
            lambda: self.comment_dock.setVisible(not self.comment_dock.isVisible()))
        act_cmt.setShortcut("F10")
        act_nav = m_view.addAction(
            "Toggle navigation panel",
            lambda: self.nav_dock.setVisible(not self.nav_dock.isVisible()))
        act_nav.setShortcut("F9")
        act_ref = m_view.addAction(
            "Reference viewer (second view)",
            lambda: self._toggle_reference_view())
        act_ref.setShortcut("F8")
        act_ref.setToolTip(
            "A second, read-only view of the same PDF — keep a legend, TOC or "
            "cover sheet in view while you work on another page.")
        self.act_ref_view = act_ref
        # Show/hide (and re-open a closed) main pane. Each dock has a close
        # button, so these bring one back after it's been closed or floated away.
        m_panes = m_view.addMenu("Panes")
        for d in self.main_docks:
            m_panes.addAction(d.toggleViewAction())
        m_view.addSeparator()
        m_view.addAction("Reset panel layout", self.reset_layout)

        m_tools = mb.addMenu("&Tools")
        m_tools.addAction("Extract pages (visual)…", lambda: self.tools_panel.show_operation("extract"))
        m_tools.addAction("Split into ranges…", lambda: self.tools_panel.show_operation("split"))
        m_tools.addAction("Delete pages (visual)…", lambda: self.tools_panel.show_operation("delete"))
        m_tools.addAction("Rotate pages (visual)…", lambda: self.tools_panel.show_operation("rotate"))
        m_tools.addSeparator()
        m_tools.addAction("Split by sheet number… (wizard)", lambda: self.tools_panel.start_sheet_wizard())
        m_tools.addSeparator()
        m_tools.addAction("Combine PDFs…", lambda: self.tools_panel.open_combine())
        m_tools.addAction("Insert PDF…", lambda: self.tools_panel.open_insert())
        m_tools.addAction("Swap a page…", lambda: self.tools_panel.open_swap())
        m_tools.addSeparator()
        m_tools.addAction("PDF → Word…", lambda: self.tools_panel.open_convert())
        m_tools.addAction("Crop / extract… (wizard)", lambda: self.tools_panel.start_crop_wizard())
        m_tools.addSeparator()
        self.act_run_audit = m_tools.addAction(
            "Run design rule check…", self.run_audit, QKeySequence("F7"))
        self.act_run_audit.setToolTip(
            "Check the drawing against the design rules and list what to confirm")
        self.act_import_drawings = m_tools.addAction(
            "Import project drawings…", self.import_project_drawings)
        self.act_import_drawings.setToolTip(
            "Read the AutoCAD Electrical source drawings (DWG/DXF) to enrich "
            "the design rule check")

        m_help = mb.addMenu("&Help")
        m_help.addAction("User Manual", self._show_help, QKeySequence.HelpContents)
        m_help.addAction("About " + __app_name__, self._show_about)

    def _rebuild_recent_menu(self):
        """Refill File ▸ Open Recent from the saved list (most recent first)."""
        menu = getattr(self, "m_recent", None)
        if menu is None:
            return
        menu.clear()
        paths = self.config.recent_files
        if not paths:
            empty = menu.addAction("(no recent files)")
            empty.setEnabled(False)
            return
        for i, path in enumerate(paths, start=1):
            # &1..&9 then &0 for quick keyboard access
            label = f"&{i % 10}  {os.path.basename(path)}"
            act = menu.addAction(label)
            act.setToolTip(path)
            act.setStatusTip(path)
            if os.path.exists(path):
                act.triggered.connect(
                    lambda _=False, p=path: self.load_document(p))
            else:
                # keep it listed but obviously unusable rather than silently
                # dropping a file that's just on a disconnected drive
                act.setEnabled(False)
                act.setText(f"{label}   (not found)")
        menu.addSeparator()
        menu.addAction("Clear list", self._clear_recent_files)

    def _clear_recent_files(self):
        self.config.clear_recent_files()
        self._rebuild_recent_menu()

    def _show_help(self):
        from .help import HelpWindow
        # keep a reference so the window isn't garbage-collected
        self._help_window = HelpWindow(self)
        self._help_window.show()
        self._help_window.raise_()

    def _show_about(self):
        QMessageBox.about(
            self, "About " + __app_name__,
            f"<h3>{__app_name__}</h3>"
            f"<p>Version {__version__}</p>"
            f"<p>PDF markup &amp; wire-number extraction for AutoCAD "
            f"Electrical drawing sets.</p>"
            f"<p>{__copyright__}</p>",
        )

    def _build_toolbar(self):
        tb = QToolBar("Tools")
        tb.setObjectName("MainToolBar")
        tb.setMovable(False)
        self.addToolBar(tb)

        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusive(True)
        # tools grouped by purpose; None marks a separator between groups
        tool_defs = [
            (T.TOOL_SELECT, "Select"),
            None,                                            # -- freehand markup
            (T.TOOL_HIGHLIGHT, "Highlight"), (T.TOOL_PEN, "Pen"),
            (T.TOOL_ERASER, "Eraser"),
            None,                                            # -- text / notes
            (T.TOOL_COMMENT, "Comment"), (T.TOOL_TEXTBOX, "Text box"),
            (T.TOOL_CALLOUT, "Callout"),
            None,                                            # -- shapes
            (T.TOOL_RECT, "Rectangle"), (T.TOOL_CIRCLE, "Circle"),
            (T.TOOL_ARROW, "Arrow"), (T.TOOL_LINE, "Line"),
            (T.TOOL_CLOUD, "Cloud"),
        ]
        # Ctrl+<digit> shortcuts are pinned to the tool, not to its position in
        # the toolbar, so inserting Circle/Line doesn't reshuffle the shortcuts
        # people already know. Circle and Line have none (the ten digits are
        # taken) — they're a click away on the toolbar.
        tool_keys = [T.TOOL_SELECT, T.TOOL_HIGHLIGHT, T.TOOL_PEN, T.TOOL_ERASER,
                     T.TOOL_COMMENT, T.TOOL_TEXTBOX, T.TOOL_CALLOUT,
                     T.TOOL_RECT, T.TOOL_ARROW, T.TOOL_CLOUD]
        tool_tips = {
            T.TOOL_CALLOUT: "Callout: click the target the arrow points at, click "
                            "again to end the arrow, then drag out the box and "
                            "click to finish (Esc cancels)",
            T.TOOL_CIRCLE: "Circle: drag out an ellipse — same fill, opacity, "
                           "resize and rotate as the rectangle",
            T.TOOL_LINE: "Line: drag a plain line (an arrow without the head)",
            T.TOOL_CLOUD: "Revision cloud: drag freehand, Shift+drag for a "
                          "rectangle, or click corners and double-click / Enter "
                          "to close",
        }
        self._tool_actions = {}
        for entry in tool_defs:
            if entry is None:
                tb.addSeparator()
                continue
            tool, label = entry
            act = QAction(label, self, checkable=True)
            act.setData(tool)
            # Ctrl+1..Ctrl+9 then Ctrl+0, pinned per tool (see tool_keys)
            if tool in tool_keys:
                n = tool_keys.index(tool) + 1
                digit = 0 if n == 10 else n
                act.setShortcut(QKeySequence(f"Ctrl+{digit}"))
                tip = tool_tips.get(tool, label)
                act.setToolTip(f"{tip}  (Ctrl+{digit})")
                act.setStatusTip(act.toolTip())
            else:
                tip = tool_tips.get(tool, label)
                act.setToolTip(tip)
                act.setStatusTip(tip)
            act.triggered.connect(lambda _=False, t=tool: self._activate_tool(t))
            self.tool_group.addAction(act)
            tb.addAction(act)
            self._tool_actions[tool] = act
            if tool == T.TOOL_SELECT:
                act.setChecked(True)
        tb.addSeparator()

        # color + widths
        self.color_btn = QPushButton("Color")
        self.color_btn.clicked.connect(self._pick_color)
        tb.addWidget(self.color_btn)
        self.fill_btn = QPushButton("Fill")
        self.fill_btn.setToolTip(
            "Interior fill for rectangles & text boxes — pick a color and "
            "opacity (drag alpha to 0 for no fill, 100% for an opaque cover)")
        self.fill_btn.clicked.connect(self._pick_fill)
        tb.addWidget(self.fill_btn)
        tb.addWidget(QLabel(" Pen "))
        self.pen_width = QDoubleSpinBox(); self.pen_width.setRange(0.5, 20); self.pen_width.setValue(2.0)
        self.pen_width.valueChanged.connect(lambda v: setattr(self.view.tool, "pen_width", v))
        tb.addWidget(self.pen_width)
        tb.addWidget(QLabel(" Font "))
        self.font_size = QSpinBox(); self.font_size.setRange(4, 96); self.font_size.setValue(12)
        self.font_size.valueChanged.connect(lambda v: setattr(self.view.tool, "font_size", float(v)))
        tb.addWidget(self.font_size)
        self.bold = QCheckBox("B"); self.bold.toggled.connect(lambda v: setattr(self.view.tool, "bold", v))
        self.italic = QCheckBox("I"); self.italic.toggled.connect(lambda v: setattr(self.view.tool, "italic", v))
        tb.addWidget(self.bold); tb.addWidget(self.italic)
        tb.addSeparator()

        # rotate whole document (permanent — writes a rotated copy)
        act_ccw = tb.addAction("↺", lambda: self.rotate_all_pages(270))
        act_ccw.setToolTip("Rotate the view 90° counter-clockwise (in memory; marks rotate too)")
        act_cw = tb.addAction("↻", lambda: self.rotate_all_pages(90))
        act_cw.setToolTip("Rotate the view 90° clockwise (in memory; marks rotate too)")
        tb.addSeparator()

        # zoom (− / editable % / +) + fit
        tb.addAction("−", self.view.zoom_out)
        self.zoom_combo = QComboBox()
        self.zoom_combo.setEditable(True)
        self.zoom_combo.setInsertPolicy(QComboBox.NoInsert)
        self.zoom_combo.addItems(["50%", "75%", "100%", "125%", "150%", "200%", "400%"])
        self.zoom_combo.setCurrentText("100%")
        self.zoom_combo.setFixedWidth(72)
        self.zoom_combo.lineEdit().setAlignment(Qt.AlignCenter)
        self.zoom_combo.setToolTip("Zoom level — pick a preset or type a percentage")
        self.zoom_combo.textActivated.connect(self._apply_zoom_text)
        self.zoom_combo.lineEdit().returnPressed.connect(
            lambda: self._apply_zoom_text(self.zoom_combo.currentText()))
        tb.addWidget(self.zoom_combo)
        tb.addAction("+", self.view.zoom_in)
        tb.addAction("Fit W", self.view.fit_width)
        tb.addAction("Fit P", self.view.fit_page)
        self.view.zoomChanged.connect(self._on_zoom_changed)
        tb.addWidget(QLabel("  Page "))
        self.page_spin = QSpinBox(); self.page_spin.setRange(1, 1)
        self.page_spin.valueChanged.connect(lambda v: self.view.go_to_page(v - 1))
        tb.addWidget(self.page_spin)
        self.page_total = QLabel(" / 0")
        tb.addWidget(self.page_total)
        self._update_color_btn()
        self._update_fill_btn()

    # -- zoom % readout ------------------------------------------------------

    def _on_zoom_changed(self, zoom: float):
        self.zoom_combo.blockSignals(True)
        self.zoom_combo.setCurrentText(f"{round(zoom * 100)}%")
        self.zoom_combo.blockSignals(False)

    def _apply_zoom_text(self, text: str):
        t = (text or "").strip().rstrip("%").strip()
        try:
            pct = float(t)
        except ValueError:
            self._on_zoom_changed(self.view._zoom)   # revert to the real value
            return
        if pct > 0:
            self.view.set_zoom(pct / 100.0)

    # -- rotate whole document (in the viewer, in memory) --------------------

    def rotate_all_pages(self, angle: int):
        """Rotate the whole document in the viewer by ``angle`` degrees. This is
        an **in-memory view rotation only** — nothing is written to disk. Marks,
        comments and highlights rotate with their page and snap back exactly when
        rotated the other way."""
        if self.document is None:
            QMessageBox.information(self, "No document", "Open a PDF first.")
            return
        self.tabs.setCurrentWidget(self.view)   # rotation is a Viewer action
        self.view.rotate_view(angle)

    # -- tool handling -------------------------------------------------------

    def _set_tool(self, tool):
        from PySide6.QtWidgets import QGraphicsView, QGraphicsItem
        # abandon a half-drawn revision-cloud polygon when switching away
        if getattr(self.view, "_cloud_pts", None) is not None:
            self.view._cloud_cancel()
        # abandon a half-placed callout (arrow drawn, box not yet) on tool change
        if getattr(self.view, "_co_stage", 0):
            self.view._callout_cancel()
        self.view._suppress_existing_prompt = False
        self.view.tool.current = tool
        self.view.setDragMode(
            QGraphicsView.RubberBandDrag if tool == T.TOOL_SELECT
            else QGraphicsView.NoDrag)
        select = tool == T.TOOL_SELECT
        for it in self.view._item_by_ann.values():
            if it is None:
                continue
            it.setFlag(QGraphicsItem.ItemIsMovable, select)
            it.setFlag(QGraphicsItem.ItemIsSelectable, select)
        self._update_color_btn()
        self._update_fill_btn()

    def _activate_tool(self, tool):
        """Programmatically switch tools and reflect it in the toolbar."""
        for act in self.tool_group.actions():
            if act.data() == tool:
                act.setChecked(True)
        self._set_tool(tool)

    def _prompt_existing_mark(self, ann):
        """Drawing tool clicked an existing mark: edit / draw-new / cancel."""
        box = QMessageBox(self)
        box.setWindowTitle("Existing mark")
        box.setText("You clicked an existing mark.")
        box.setInformativeText("Edit this mark, or draw a new one here?")
        edit_btn = box.addButton("Edit existing", QMessageBox.AcceptRole)
        new_btn = box.addButton("Draw new", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is edit_btn:
            return "edit"
        if clicked is new_btn:
            return "new"
        return "cancel"

    def _active_color_attr(self):
        t = self.view.tool.current
        return {
            T.TOOL_HIGHLIGHT: "highlight_color", T.TOOL_PEN: "pen_color",
            T.TOOL_TEXTBOX: "text_color", T.TOOL_RECT: "shape_color",
            T.TOOL_CIRCLE: "shape_color",
            T.TOOL_ARROW: "shape_color", T.TOOL_LINE: "shape_color",
            T.TOOL_CALLOUT: "text_color", T.TOOL_CLOUD: "shape_color",
        }.get(t, "pen_color")

    def _update_color_btn(self):
        rgb = getattr(self.view.tool, self._active_color_attr())
        self.color_btn.setIcon(_swatch(QColor(int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))))

    def _pick_color(self):
        attr = self._active_color_attr()
        rgb = getattr(self.view.tool, attr)
        col = QColorDialog.getColor(QColor(int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255)), self)
        if col.isValid():
            setattr(self.view.tool, attr, (col.redF(), col.greenF(), col.blueF()))
            self._update_color_btn()

    def _active_fill_attrs(self):
        """(color_attr, opacity_attr) for the fill-capable tool, else (None, None)."""
        t = self.view.tool.current
        if t in (T.TOOL_RECT, T.TOOL_CIRCLE):
            return "shape_fill", "shape_fill_opacity"
        if t in (T.TOOL_TEXTBOX, T.TOOL_CALLOUT):
            return "text_fill", "text_fill_opacity"
        return None, None

    def _update_fill_btn(self):
        c_attr, o_attr = self._active_fill_attrs()
        enabled = c_attr is not None
        self.fill_btn.setEnabled(enabled)
        rgb = getattr(self.view.tool, c_attr) if enabled else None
        op = getattr(self.view.tool, o_attr) if enabled else 0.0
        self.fill_btn.setIcon(_fill_swatch(rgb, op))

    def _pick_fill(self):
        c_attr, o_attr = self._active_fill_attrs()
        if c_attr is None:
            return
        rgb = getattr(self.view.tool, c_attr)
        op = getattr(self.view.tool, o_attr)
        ok, color, opacity = FillDialog.ask(self, rgb, op, "Fill")
        if not ok:
            return
        setattr(self.view.tool, c_attr, color)
        if color is not None:
            setattr(self.view.tool, o_attr, opacity)
        self._update_fill_btn()

    # -- document lifecycle --------------------------------------------------

    def open_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF (*.pdf)")
        if path:
            self.load_document(path)

    # -- drag & drop (open a dropped PDF in the viewer) ----------------------

    def dragEnterEvent(self, event):
        if pdf_path_from_mime(event.mimeData()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if pdf_path_from_mime(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        # if the drop is over the PDF Tools tab, let that panel handle it
        if self.tabs.currentWidget() is self.tools_panel:
            return
        path = pdf_path_from_mime(event.mimeData())
        if path:
            self.load_document(path)
            event.acceptProposedAction()

    def load_document(self, path):
        from .model.storage import sidecar_path

        def _doc_key(p):
            return os.path.normcase(os.path.realpath(sidecar_path(p)))

        # Feature 1: refuse to open the document that's already open. foo.pdf and
        # foo.marked.pdf share a sidecar, so they count as the same document.
        if self.document is not None and _doc_key(path) == _doc_key(self.document.path):
            QMessageBox.information(
                self, "Already open",
                f"“{os.path.basename(path)}” is already open.")
            return
        # Opening another file drops this one's unsaved marks exactly as
        # finally as closing the window does. Asked before anything is built,
        # so Cancel leaves no half-opened document behind.
        if not self._ok_to_lose_unsaved("Open another file"):
            return
        # Build the new document BEFORE closing the old one. Closing first meant
        # a failed open (corrupt/locked/deleted file) returned with the window
        # still pointed at a *closed* Document — blank pages, "closed database"
        # on save, and search raising — which two views only made worse.
        try:
            doc = Document(path, ignore_patterns=self.config.ignore_patterns())
            doc.load()
        except Exception as e:
            QMessageBox.critical(self, "Open failed", str(e))
            return                      # the current document stays open and usable
        if self.document is not None:
            try:
                self.document.close()
            except Exception:
                pass
        self.document = doc
        # remember it in File ▸ Open Recent (only once the open has succeeded)
        self.config.add_recent_file(path)
        self._rebuild_recent_menu()
        # Feature 4: a .marked.pdf was opened but its original markup database
        # couldn't be found, so a new one was started — let the user know.
        if getattr(doc, "sidecar_recreated", False):
            QMessageBox.information(
                self, "New markup database",
                "This .marked.pdf's original markup database wasn't found next to "
                "it, so a new one has been started. Previously saved marks, TODOs "
                "and extractions for this file may not be available.")
        self.view.set_document(doc, self.config)
        # the reference pane shows the same document (read-only), whether or not
        # it's currently visible, so toggling it on is instant
        self.ref_view.set_document(doc, self.config)
        self.comment_panel.set_store(doc.store, self.config)
        self.todo_panel.set_store(doc.store, self.config, doc)
        self.wire_panel.set_document(doc, self.config)
        self.component_panel.set_document(doc, self.config)
        self.nav_panel.set_document(doc)
        self.audit_panel.set_document(doc, self.config)
        self._refresh_finding_marks()
        self.tools_panel.set_default_pdf(path)
        self.page_spin.setRange(1, max(1, doc.page_count))
        self.page_total.setText(f" / {doc.page_count}")
        self.setWindowTitle(f"{__app_name__} — {os.path.basename(path)}")
        self._update_actions_enabled(True)
        # Edge case: the PDF opened for viewing, but its name can't back a
        # markup database (too long, or unsupported characters), so markup and
        # saving are turned off. Tell the user why and how to fix it.
        if not doc.sidecar_available:
            self._warn_no_sidecar(path)
        self.statusBar().showMessage(
            f"Opened {os.path.basename(path)} ({doc.page_count} pages, "
            f"{len(doc.store.all())} existing marks)", 6000)

    def save_markup(self) -> bool:
        """Write the markup out. Returns whether it actually landed on disk.

        The return value matters to :meth:`_ok_to_lose_unsaved`, which offers
        Save as the way *out* of losing work -- so it has to know the
        difference between a save and a save that raised.
        """
        if self.document is None:
            return False
        try:
            out = self.document.save()
        except Exception as e:
            QMessageBox.warning(self, "Save failed", str(e))
            return False
        self.statusBar().showMessage(f"Saved {os.path.basename(out)}", 5000)
        return True

    def _ok_to_lose_unsaved(self, title: str) -> bool:
        """Ask before dropping marks that only File > Save would have kept.

        True means go ahead. The window used to close with no question and no
        save, so every mark drawn since the last save went with it, silently,
        on every sheet -- the one failure a markup tool does not get to have.

        Only the marks and the wire/component ticks hang on this: findings,
        waivers, sheet numbers and roles all write through as they change.
        """
        doc = self.document
        if doc is None or not doc.dirty:
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(title)
        box.setText(f"“{os.path.basename(doc.path)}” has unsaved markup.")
        box.setInformativeText(
            "Marks are written to disk when you save. Discarding loses every "
            "change made since the last save.")
        box.setStandardButtons(QMessageBox.Save | QMessageBox.Discard
                               | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Save)
        choice = box.exec()
        if choice == QMessageBox.Discard:
            return True
        if choice != QMessageBox.Save:
            return False                  # Cancel, or the dialog was dismissed
        # A save that raised (an unusable sidecar, a read-only folder) is not a
        # save. Stay where we are rather than throw the work away on their
        # behalf -- Discard is still on the box if that is really what they mean.
        return self.save_markup()

    def save_as_fork(self):
        """Fork the current markup to a new working file and switch to editing it."""
        if self.document is None:
            return
        from .model.storage import original_pdf_path, sidecar_path
        base = os.path.splitext(
            os.path.basename(original_pdf_path(self.document.path)))[0]
        start_dir = os.path.dirname(os.path.abspath(self.document.path))
        suggested = os.path.join(start_dir, f"{base}-copy.pdf")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save As — fork to a new working file", suggested, "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"

        def _key(p):
            return os.path.normcase(os.path.realpath(sidecar_path(p)))
        if _key(path) == _key(self.document.path):
            QMessageBox.information(
                self, "Same file",
                "That's the file you're already working on — choose a new name.")
            return
        try:
            self.document.save_as(path)
        except Exception as e:
            QMessageBox.warning(self, "Save As failed", str(e))
            return
        new_path = self.document.path
        self.tools_panel.set_default_pdf(new_path)
        self.setWindowTitle(f"{__app_name__} — {os.path.basename(new_path)}")
        self.statusBar().showMessage(
            f"Forked to {os.path.basename(new_path)} — now editing the copy", 6000)
        QMessageBox.information(
            self, "Forked to a new working file",
            f"Now working on “{os.path.basename(new_path)}”.\n"
            f"The original file is unchanged.")

    def export_pdf(self):
        if self.document is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export annotated PDF",
                                              "annotated.pdf", "PDF (*.pdf)")
        if not path:
            return
        try:
            self.document.export_annotated_pdf(path)
            self.statusBar().showMessage(f"Exported {os.path.basename(path)}", 5000)
        except Exception as e:
            QMessageBox.warning(self, "Export failed", str(e))

    def export_flat(self):
        if self.document is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export flattened PDF",
                                              "flattened.pdf", "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            baked = self.document.export_flattened_pdf(path)
        except Exception as e:
            QMessageBox.warning(self, "Export failed", str(e))
            return
        if baked:
            self.statusBar().showMessage(
                f"Exported flattened {os.path.basename(path)}", 5000)
        else:
            QMessageBox.information(
                self, "Exported (not flattened)",
                "This PyMuPDF build can't flatten annotations, so an annotated "
                "copy was written instead.")

    def print_document(self):
        """Print the drawing through the system print dialog.

        The window's half of it: the parent widget, the open document and the
        status bar. Everything about a printer lives in `app/printing.py`.
        """
        msg = printing.run_print_dialog(self, self.document, self.print_options)
        if msg:
            self.statusBar().showMessage(msg, 5000)

    def print_preview(self):
        """Show the pages in a preview window, then print from there."""
        printing.run_print_preview(self, self.document, self.print_options)


    def open_settings(self):
        dlg = SettingsDialog(self.config, self)
        if dlg.exec() == QDialog.Accepted:
            dlg.apply()
            self.view.config = self.config
            self.ref_view.config = self.config
            # a changed default takes effect on the next print without a restart
            self.print_options.min_line_pt = self.config.print_min_line_pt
            if self.document is not None:
                self.document.ignore_patterns = self.config.ignore_patterns()
                self.comment_panel.refresh()
                self.todo_panel.refresh()
                self.view.rebuild_all_items()
                # keep the reference pane in step (e.g. "Show ignored" changes
                # which marks are drawn) — it renders the same marks
                self.ref_view.rebuild_all_items()
                # Bug 8: re-flag already-extracted component labels against the
                # (possibly edited) family codes / widths — no re-extract needed.
                if self.document.components:
                    from .extraction.component_parser import reclassify
                    reclassify(self.document.components, self.config.component_config())
                    self.document.set_components(self.document.components)
                    self.component_panel.set_document(self.document, self.config)
                # Same idea for the audit: re-apply severities and rule
                # enablement to the findings already on screen rather than
                # making the user run the check again to see the effect.
                # The dialog already loaded every rule's declared severity to
                # populate its combo boxes, so the defaults come from there
                # rather than costing a second pack load.
                self._reapply_audit_settings(
                    {rule_id: default_sev
                     for rule_id, default_sev, _chk, _combo in dlg.drc_rows})

    # -- edit hooks ----------------------------------------------------------

    def _prompt_new_text(self, ann: Annotation, is_textbox: bool):
        """Synchronous prompt for a *new* comment/text box.

        Returns ``(accepted, text, todo)``; a cancel returns ``accepted=False``
        so the view discards the unplaced mark (never added to the document).
        """
        dlg = TextEditDialog(ann, self, is_textbox=is_textbox)
        if dlg.exec() == QDialog.Accepted:
            text, todo = dlg.values()
            fv = dlg.font_values()
            _apply_font(ann, fv)
            self._remember_text_style(fv)   # sticky style for the next new mark
            return True, text, todo
        return False, "", False

    def _remember_text_style(self, fv) -> None:
        """Feed a just-created text box / callout's colour, font and fill back into
        the tool defaults, so the next new one inherits them (never the text)."""
        if not fv:
            return
        t = self.view.tool
        t.text_color = tuple(fv["color"])
        t.font_size = fv["font_size"]
        t.bold = fv["bold"]
        t.italic = fv["italic"]
        if "fill_color" in fv:
            t.text_fill = tuple(fv["fill_color"]) if fv["fill_color"] else None
            t.text_fill_opacity = fv["fill_opacity"]
        # reflect the remembered values in the toolbar controls
        for w, val in ((self.font_size, int(t.font_size)),):
            w.blockSignals(True); w.setValue(val); w.blockSignals(False)
        for w, val in ((self.bold, t.bold), (self.italic, t.italic)):
            w.blockSignals(True); w.setChecked(val); w.blockSignals(False)
        self._update_color_btn()
        self._update_fill_btn()

    def _delete_annotation(self, ann: Annotation):
        """Delete a mark (already user-confirmed) via the undo stack."""
        self.view.push_command(RemoveAnnotationCommand(self.view, ann, "Delete comment"))

    def _edit_comment(self, ann: Annotation):
        self._edit_text(ann, is_textbox=False)

    def _edit_textbox(self, ann: Annotation):
        self._edit_text(ann, is_textbox=True)

    def _edit_text(self, ann: Annotation, is_textbox: bool):
        before = capture(ann)
        was_todo = ann.is_todo
        dlg = TextEditDialog(ann, self, is_textbox=is_textbox)
        if dlg.exec() == QDialog.Accepted:
            text, todo = dlg.values()
            ann.text = text
            ann.is_todo = todo
            _apply_font(ann, dlg.font_values())  # font size/color/bold/italic
            after = capture(ann)
            if after != before:
                self.view.push_command(
                    ModifyAnnotationCommand(self.view, ann, before, after,
                                            "Edit text"))
            elif todo != was_todo:
                self.document.store.update(ann)

    def _edit_fill(self, ann: Annotation):
        """Edit a rectangle's fill color + opacity (color + opacity slider)."""
        before = capture(ann)
        ok, color, opacity = FillDialog.ask(self, ann.fill_color, ann.fill_opacity,
                                            "Rectangle fill")
        if not ok:
            return
        ann.fill_color = color
        if color is not None:
            ann.fill_opacity = opacity
        after = capture(ann)
        if after != before:
            self.view.push_command(
                ModifyAnnotationCommand(self.view, ann, before, after, "Edit fill"))

    def _edit_author(self, ann: Annotation):
        """Change who a mark is by (double-clicking the By / Commenter column):
        confirm first, then edit the name.  Undoable; offers to rename every mark
        by that person when more than one shares the name."""
        from PySide6.QtWidgets import QInputDialog
        if self.document is None:
            return
        current = ann.author or ""
        same = [a for a in self.document.store.all() if (a.author or "") == current]
        scope_all = False
        if current and len(same) > 1:
            box = QMessageBox(self)
            box.setWindowTitle("Change commenter")
            box.setIcon(QMessageBox.Question)
            box.setText(f"Change the commenter name?\n\nCurrently “{current}”.")
            one_btn = box.addButton("This mark only", QMessageBox.AcceptRole)
            all_btn = box.addButton(f"All {len(same)} by “{current}”",
                                    QMessageBox.AcceptRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            clicked = box.clickedButton()
            if clicked not in (one_btn, all_btn):
                return
            scope_all = clicked is all_btn
        else:
            resp = QMessageBox.question(
                self, "Change commenter",
                f"Change the commenter name for this {ann.kind}?\n\n"
                f"Currently “{current or '(none)'}”.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if resp != QMessageBox.Yes:
                return
        new, ok = QInputDialog.getText(self, "Commenter name", "Name:", text=current)
        if not ok:
            return
        new = new.strip()
        if new == current:
            return
        targets = same if scope_all else [ann]
        self.view.undo_stack.beginMacro("Change commenter")
        try:
            for a in targets:
                before = capture(a)
                a.author = new
                after = capture(a)
                if after != before:
                    self.view.push_command(ModifyAnnotationCommand(
                        self.view, a, before, after, "Change commenter"))
        finally:
            self.view.undo_stack.endMacro()

    # -- design rule check ----------------------------------------------------

    def _reapply_audit_settings(self, defaults=None):
        """Re-flag existing findings against changed rule settings.

        Cheap and immediate: a severity override changes how a finding reads,
        not what the drawing says, so there is nothing to recompute.

        Turning a rule *off* only hides its findings — they are not deleted.
        Discarding them here would mean toggling a rule off and on again
        silently lost work, and the next run will settle the stored list
        anyway. The panel does that filtering at display time.
        """
        doc = self.document
        if doc is None or not doc.findings:
            return
        overrides = self.config.audit_severity_overrides()
        defaults = defaults or {}
        for f in doc.findings:
            if f.rule_id in overrides:
                f.severity = overrides[f.rule_id]
            elif f.rule_id in defaults:
                # Withdrawing an override has to put the severity back. Without
                # this the change was one-way: the finding kept whatever it was
                # last set to, `set_findings` wrote it to the sidecar, and it
                # survived closing and reopening the file -- so Settings read
                # "potential" while the panel header, the overlay colour and
                # every exported report said something else. Escalating and
                # then withdrawing left sixteen rows reading "definite
                # violation" that no rule had ever called one.
                #
                # Only for a rule whose default is actually known. A finding
                # from a pack that is no longer loaded has no entry here, and
                # resetting it to a guessed severity would be inventing an
                # answer -- it keeps what it has.
                f.severity = defaults[f.rule_id]
        doc.set_findings(doc.findings, doc.audit_run)
        self.audit_panel.refresh()
        self._refresh_finding_marks()

    def _refresh_finding_marks(self):
        """Paint (or clear) the audit overlay according to the setting."""
        if self.document is None:
            self.view.clear_findings()
            return
        if self.config.audit_draw_on_sheet():
            from .audit.findings import visible_findings
            self.view.draw_findings(visible_findings(
                self.document.findings, self.config.audit_disabled_rules()))
        else:
            self.view.clear_findings()

    def run_audit(self):
        """Check the drawing against the rule packs, off the UI thread."""
        from .audit import status as audit_status
        from .audit.adapter import AdapterOptions
        from .audit.runner import AuditUnavailable, run_audit as _run
        from .tools.runner import run_with_progress

        doc = self.document
        if doc is None:
            return
        ok, message = audit_status()
        if not ok:
            QMessageBox.information(self, "Design rule check", message)
            return

        # Snapshot everything the worker needs. It must not touch the document
        # or the sidecar: sqlite connections belong to the thread that made them.
        pdf_path = doc.path
        labels = dict(doc.sheet_labels)
        sources = dict(doc.sheet_sources)
        roles = {i: doc.sheet_role_of(i) for i in range(doc.page_count)}
        waivers = dict(doc.waivers)
        excluded = frozenset(
            [w.label for w in doc.wires if not getattr(w, "included", True)]
            + [c.label for c in doc.components if not getattr(c, "included", True)])
        acade_json = doc.acade_model_json
        wire_cfg = self.config.wire_config()
        # The source drawings state the wire numbering format; %S%N writes the
        # line number unpadded, which the fixed-width parse would drop.
        if (doc.acade_wire_format or "").strip() == "%S%N":
            wire_cfg.unpadded_rung = True
        project = {"number": "", "title": os.path.splitext(
            os.path.basename(doc.path))[0]}
        packs = self.config.audit_packs()
        disabled = self.config.audit_disabled_rules()
        overrides = self.config.audit_severity_overrides()

        def work(progress, cancel):
            return _run(pdf_path, labels, sources, roles,
                        options=AdapterOptions(
                            wire_config=wire_cfg,
                            component_config=self.config.component_config(),
                            excluded_labels=excluded),
                        pack_ids=packs, disabled_rules=disabled,
                        severity_overrides=overrides, waivers=waivers,
                        acade_model_json=acade_json,
                        project=project, progress=progress, cancel=cancel)

        def done(result):
            if result is None or result.cancelled:
                return
            self.document.set_findings(result.findings, result.run)
            self.audit_panel.refresh()
            self._refresh_finding_marks()
            self.tabs.setCurrentWidget(self.audit_panel)
            self.statusBar().showMessage(result.run.summary_line(), 8000)

        def failed(message):
            if message == "__cancelled__":
                return
            QMessageBox.warning(self, "Design rule check failed", message)

        try:
            self._audit_task = run_with_progress(
                self, "Running design rule check…", work, done, on_error=failed)
        except AuditUnavailable as e:               # pragma: no cover - guarded above
            QMessageBox.information(self, "Design rule check", str(e))

    def import_project_drawings(self):
        """Read the project's source drawings and fold them into the audit."""
        from .audit import status as audit_status
        from .audit import project_import
        from .tools.runner import run_with_progress

        doc = self.document
        if doc is None:
            return
        ok, message = audit_status()
        if not ok:
            QMessageBox.information(self, "Import project drawings", message)
            return
        directory = QFileDialog.getExistingDirectory(
            self, "Project drawings folder",
            os.path.dirname(doc.path) or "")
        if not directory:
            return

        oda_path = self.config.oda_converter_path()

        def work(progress, cancel):
            return project_import.import_project(
                directory, converter_path=oda_path,
                progress=progress, cancel=cancel)

        def done(result):
            if result is None:
                return
            if result.model_json:
                self.document.set_acade_import(result.model_json,
                                               result.wire_format)
                self.statusBar().showMessage(result.summary(), 8000)
                # The point of importing is what the audit can now see.
                self.run_audit()
            else:
                QMessageBox.warning(
                    self, "Import project drawings",
                    "\n".join(result.errors) or "Nothing could be imported.")

        def failed(message):
            if message != "__cancelled__":
                QMessageBox.warning(self, "Import failed", message)

        self._import_task = run_with_progress(
            self, "Reading project drawings…", work, done, on_error=failed)

    def _waive_finding(self, finding):
        """Record that a finding is acceptable on this project."""
        if self.document is None or finding is None:
            return
        dlg = WaiveDialog(finding, self.config.author(), self)
        if dlg.exec() != QDialog.Accepted:
            return
        reason, author = dlg.values()
        if not reason.strip():
            return
        self.document.waive_finding(finding.key, reason, author)
        self.audit_panel.refresh()
        self._refresh_finding_marks()

    def _clear_waiver(self, finding):
        if self.document is None or finding is None:
            return
        waiver = self.document.waiver_for(finding.key)
        detail = f"\n\nReason given: {waiver.reason}" if waiver is not None else ""
        if QMessageBox.question(
                self, "Remove waiver",
                f"Return this finding to the open list?{detail}") != QMessageBox.Yes:
            return
        self.document.clear_waiver(finding.key)
        self.audit_panel.refresh()
        self._refresh_finding_marks()

    # -- navigation ----------------------------------------------------------

    def _jump_to(self, obj):
        # obj is an Annotation, or a WireNumber / ComponentLabel (which carry a
        # page + x/y of their FIRST occurrence after dedupe).
        ann = obj if isinstance(obj, Annotation) else None
        if ann is not None:
            self.tabs.setCurrentWidget(self.view)
            self.view.flash_annotation(ann)
            return
        page = getattr(obj, "page", None)
        if page is None:
            return
        self.tabs.setCurrentWidget(self.view)
        x, y = getattr(obj, "x", None), getattr(obj, "y", None)
        if x is not None and y is not None and (x or y):
            self.view.go_to_location(int(page), float(x), float(y))
        else:
            self.view.go_to_page(int(page))

    def _nav_to_page(self, page_no):
        """Picking a page/bookmark in the Navigation pane jumps the Viewer to it
        — switching to the Viewer tab first if the user is on another tab."""
        self.tabs.setCurrentWidget(self.view)
        self.view.go_to_page(page_no)

    def _reveal_in_panel(self, ann, target):
        """Jump from a PDF mark to its row in the TODO list or comment sidebar."""
        if target == "todo":
            self.tabs.setCurrentWidget(self.todo_panel)
            self.todo_panel.reveal(ann)
        else:
            self.comment_dock.setVisible(True)
            self.comment_dock.raise_()
            self.comment_panel.reveal(ann)

    def _on_page_changed(self, page_no):
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(page_no + 1)
        self.page_spin.blockSignals(False)

    def _update_actions_enabled(self, on: bool):
        # Markup + persistence need a working sidecar. When a document is open
        # but its filename can't back one, keep view/find/nav (and PDF tools)
        # alive but grey out saving, exporting and the drawing tools.
        avail = (getattr(self.document, "sidecar_available", True)
                 if self.document is not None else True)
        markup = on and avail
        for a in (self.act_save, self.act_save_as, self.act_export_pdf,
                  self.act_export_flat):
            a.setEnabled(markup)
        # The audit writes findings and waivers to the sidecar, so it degrades
        # the same way markup does when a filename cannot back one. The import
        # persists there too.
        self.act_run_audit.setEnabled(markup)
        self.act_import_drawings.setEnabled(markup)
        # Printing is a view operation (it just rasterises the pages + marks), so
        # it stays available even when the file has no sidecar.
        self.act_print.setEnabled(on)
        self.act_print_preview.setEnabled(on)
        # Only *block* the tools when a document is open without a sidecar;
        # otherwise leave them as-is (startup with no document keeps them ready).
        self._set_markup_tools_enabled(not (on and not avail))

    def _set_markup_tools_enabled(self, enabled: bool):
        """Enable/disable the drawing tools and their styling widgets. The
        Select tool always stays available so the user can still click marks."""
        for tool, act in getattr(self, "_tool_actions", {}).items():
            act.setEnabled(enabled or tool == T.TOOL_SELECT)
        for w in (self.color_btn, self.fill_btn, self.pen_width, self.font_size,
                  self.bold, self.italic):
            w.setEnabled(enabled)
        if not enabled:
            self._activate_tool(T.TOOL_SELECT)   # snap off any drawing tool

    def _warn_no_sidecar(self, path):
        """Explain why markup is greyed out for a file whose name can't back a
        markup-database sidecar, and how to fix it."""
        from .model.storage import sidecar_path
        sc_name = os.path.basename(sidecar_path(path))
        QMessageBox.warning(
            self, "Markup turned off for this file",
            f"“{os.path.basename(path)}” opened for viewing, but its markup "
            f"tools are turned off.\n\n"
            f"Its filename is too long or contains characters that can't be "
            f"used to create the markup database it needs "
            f"(“{sc_name}”), so drawing marks, notes, TODOs, wire/component "
            f"caching and saving aren't available.\n\n"
            f"You can still view, search, navigate and use the PDF tools.\n\n"
            f"To turn markup back on, rename the file to something shorter and "
            f"simpler — avoid very long names and the characters "
            f"\\ / : * ? \" < > | — then open it again.")

    def showEvent(self, event):
        super().showEvent(event)
        # Force the dock layout to settle once the window is on screen so the
        # nav/comment separators are draggable from the start (otherwise the
        # splitter only becomes active after the dock is hidden and reshown).
        # Skip the default sizing when a saved layout was restored.
        if not getattr(self, "_docks_sized", False):
            self._docks_sized = True
            if not getattr(self, "_state_restored", False):
                QTimer.singleShot(0, self._init_dock_sizes)

    def _init_dock_sizes(self):
        try:
            self.resizeDocks([self.nav_dock, self.comment_dock], [260, 320],
                             Qt.Horizontal)
        except Exception:
            pass

    # -- dock layout persistence (Visual-Studio-style) ----------------------

    def _restore_ui_state(self):
        """Apply the window geometry + dock layout saved last session."""
        self._state_restored = False
        try:
            geo = self.config.s.value("ui/geometry")
            state = self.config.s.value("ui/window_state")
            if geo:
                self.restoreGeometry(geo)
            if state and self.restoreState(state, _UI_STATE_VERSION):
                self._state_restored = True
        except Exception:
            self._state_restored = False

    def _save_ui_state(self):
        try:
            self.config.s.setValue("ui/geometry", self.saveGeometry())
            self.config.s.setValue("ui/window_state",
                                   self.saveState(_UI_STATE_VERSION))
            self.config.s.sync()
        except Exception:
            pass

    def _toggle_reference_view(self):
        """Show/hide the read-only second view of the current document."""
        if self.ref_dock.isVisible():
            self.ref_dock.hide()
            self.ref_view.set_render_enabled(False)   # free its page bitmaps
            return
        # catch up if a document was opened while the pane was hidden
        if self.document is not None and self.ref_view.document is not self.document:
            self.ref_view.set_document(self.document, self.config)
        self.ref_dock.show()
        self.ref_dock.raise_()
        self.ref_view.set_render_enabled(True)
        if not getattr(self, "_ref_dock_sized", False):
            # A dock that has never been shown has no remembered size, so Qt
            # gives it its *minimum* width (a ~70px sliver). Give it a usable
            # share of the window the first time it appears; after that the
            # user's own sizing is remembered.
            #
            # resizeDocks is only advisory — it is silently ignored on some
            # platforms (it no-ops on Windows, which is how the sliver survived
            # the first fix), so it sets the *preferred* width and the pane's own
            # minimum width (set once, in __init__) guarantees the floor.
            self._ref_dock_sized = True
            width = max(380, min(560, self.width() // 3))
            try:
                # pin the target width so the layout must adopt it, then drop
                # back to the pane's own floor on the next event-loop turn so it
                # stays freely resizable — worst case it settles at the floor,
                # which is still a usable pane rather than a sliver
                self.ref_view.setMinimumWidth(width)
                self.resizeDocks([self.ref_dock], [width], Qt.Horizontal)
                QTimer.singleShot(0, lambda: self.ref_view.setMinimumWidth(260))
            except Exception:
                pass
        # the zoom was fitted to the pane's phantom size while it was hidden —
        # re-fit once it has its real viewport
        QTimer.singleShot(0, self.ref_view.fit_width)

    def reset_layout(self):
        """Restore the panes to their default docked arrangement — re-docking
        any floated tab or sidebar and re-tabbing the main panes together."""
        if getattr(self, "_default_state", None) is not None:
            self.restoreState(self._default_state, _UI_STATE_VERSION)
        for d in [self.nav_dock, self.comment_dock] + getattr(self, "main_docks", []):
            d.setFloating(False)
            d.show()
        self.tabs.setCurrentWidget(self.view)
        self._init_dock_sizes()

    def closeEvent(self, event):
        # First, before a single panel is shut down or a handle released: if
        # they cancel, the window has to still be a working window.
        if not self._ok_to_lose_unsaved("Close"):
            event.ignore()
            return
        self._save_ui_state()            # remember the dock layout + geometry
        try:
            self.wire_panel.shutdown()   # stop any running extraction thread
        except Exception:
            pass
        try:
            self.component_panel.shutdown()
        except Exception:
            pass
        try:
            self.tools_panel.grid.close_doc()
        except Exception:
            pass
        if self.document is not None:
            try:
                self.document.close()
            except Exception:
                pass
        super().closeEvent(event)
