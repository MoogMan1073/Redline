"""Main window: the DOCKING of the panes, and the acts nothing else owns.

Almost nothing this window used to hold is still here, and each piece left by a
boundary rather than by size -- `app/settings_dialog.py` and `app/dialogs.py`
hold every dialog, `app/printing.py` the printer and the page raster,
`app/toolbar.py` the tool group and the style widgets, `app/menus.py` the menu
bar and the Open Recent list, and `app/lifecycle.py` opening, forking and
closing a document. 2,506 -> 1,879 -> 1,492 -> **1,081**.

What is left is named rather than glossed, and one clause of it was WRONG
before: the panes are already their own modules under `app/panels/`, so what
the window holds is their DOCKING rather than the panes -- measured, and the
sentence that said otherwise had been carried forward unread here AND in the
backlog row's own note. What remains is the docks, the tool/style/zoom acts the
toolbar CALLS, the audit and waiver acts, the reference view, drag-and-drop and
the UI-state save."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QFileDialog, QMessageBox, QDockWidget,
    QWidget, QDialog, QColorDialog, QStatusBar,
)

from . import __app_name__, __version__, __copyright__, app_icon
from .config import AppConfig
from .dialogs import (
    FillDialog, TextEditDialog, WaiveDialog, _apply_font, _fill_swatch, _swatch,
)
from .settings_dialog import SettingsDialog
from . import lifecycle, menus, printing, toolbar
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
        menus.build(self)
        toolbar.build(self)
        self._update_actions_enabled(False)

        # Remember the freshly-built default arrangement (for "Reset panel
        # layout"), then apply whatever layout the user left last session.
        self._default_state = self.saveState(_UI_STATE_VERSION)
        self._restore_ui_state()

    # -- menu / toolbar ------------------------------------------------------

    def _rebuild_recent_menu(self):
        menus.rebuild_recent(self)

    def _clear_recent_files(self):
        menus.clear_recent(self)

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
        lifecycle.open_document(self, path)

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
        return lifecycle.ok_to_lose_unsaved(self, title)

    def save_as_fork(self):
        lifecycle.save_as_fork(self)

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
        # Qt's half stays here: only the window may ignore its own close event
        # or reach `super()`. What the DOCUMENT has to do about it is
        # `lifecycle.on_close`.
        if not lifecycle.on_close(self, event):
            event.ignore()
            return
        super().closeEvent(event)
