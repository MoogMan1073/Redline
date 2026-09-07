"""The menu bar, and the Open Recent list that refills itself.

The other half of the cut `app/toolbar.py` describes. Where that module
**constructs** eleven kinds of widget, this one **wires** methods the window
already has: measured, it needs exactly one Qt name (`QKeySequence`), and the
two builders share no attribute in either direction.

That is why they are two modules rather than one `chrome.py` — the split is by
what each makes, which is a fact about them, and not by line count, which is a
fact about nothing.

**Every action here names a `MainWindow` method, and that is now gated.** A
menu wired to a method somebody renamed does not fail at import or at build; it
fails when a person clicks it, which is the worst place to find out and the one
place no test was looking. `tests/test_module_layout.py` walks this module for
`win.<name>` handed to `addAction`/`connect` and fails on a name the window does
not have — measured at **zero** today, which is what makes it a gate rather
than a to-do list.

The window keeps thin wrappers for `_rebuild_recent_menu` and
`_clear_recent_files` and not for the builders, and the rule is *a wrapper
exists where a consumer names it*: those two are called from
`load_document` and from `tests/test_v12_recent.py`, where `_build_menu` and
`_build_toolbar` were named by `__init__` and by nothing else.
"""
from __future__ import annotations

import os

from PySide6.QtGui import QKeySequence

from . import __app_name__


def build(win):
    """Build the whole menu bar and hang its actions on `win`."""
    mb = win.menuBar()
    m_file = mb.addMenu("&File")
    win.act_open = m_file.addAction("&Open PDF…", win.open_pdf, QKeySequence.Open)
    win.m_recent = m_file.addMenu("Open &Recent")
    rebuild_recent(win)
    win.act_save = m_file.addAction("&Save markup", win.save_markup,
                                    QKeySequence.Save)
    win.act_save_as = m_file.addAction(
        "Save &As… (fork working file)", win.save_as_fork,
        QKeySequence("Ctrl+Shift+S"))
    win.act_save_as.setToolTip(
        "Copy this file's markup into a new working file and switch to it; "
        "the original stays untouched.")
    win.act_export_pdf = m_file.addAction(
        "Export annotated PDF…", win.export_pdf, QKeySequence("Ctrl+Shift+E"))
    win.act_export_flat = m_file.addAction(
        "Export flattened PDF (for sharing)…", win.export_flat)
    win.act_export_flat.setToolTip(
        "Bake the marks into the page so they render in every viewer "
        "(browsers, Preview, thumbnails). Not re-editable — keep your "
        "working file for edits.")
    m_file.addSeparator()
    win.act_print = m_file.addAction(
        "&Print…", win.print_document, QKeySequence.Print)   # Ctrl+P
    win.act_print.setToolTip(
        "Print the drawing (with its marks) to any installed printer via the "
        "system print dialog.")
    win.act_print_preview = m_file.addAction(
        "Print pre&view…", win.print_preview)
    win.act_print_preview.setToolTip(
        "See the pages before printing, then print from the preview.")
    m_file.addSeparator()
    m_file.addAction("Settings…", win.open_settings)
    m_file.addSeparator()
    m_file.addAction("Quit", win.close, QKeySequence.Quit)

    m_edit = mb.addMenu("&Edit")
    undo = win.view.undo_stack.createUndoAction(win, "Undo")
    undo.setShortcut(QKeySequence.Undo)
    redo = win.view.undo_stack.createRedoAction(win, "Redo")
    redo.setShortcut(QKeySequence.Redo)
    m_edit.addAction(undo)
    m_edit.addAction(redo)

    m_view = mb.addMenu("&View")
    m_view.addAction("Fit width", win.view.fit_width)
    m_view.addAction("Fit page", win.view.fit_page)
    m_view.addAction("Zoom in", win.view.zoom_in, QKeySequence.ZoomIn)
    m_view.addAction("Zoom out", win.view.zoom_out, QKeySequence.ZoomOut)
    m_view.addSeparator()
    m_view.addAction("Find…", win.view.show_search, QKeySequence.Find)
    m_view.addAction("Find next", win.view.search_next,
                     QKeySequence.FindNext)
    m_view.addAction("Find previous", win.view.search_prev,
                     QKeySequence.FindPrevious)
    m_view.addSeparator()
    act_cmt = m_view.addAction(
        "Toggle comment sidebar",
        lambda: win.comment_dock.setVisible(not win.comment_dock.isVisible()))
    act_cmt.setShortcut("F10")
    act_nav = m_view.addAction(
        "Toggle navigation panel",
        lambda: win.nav_dock.setVisible(not win.nav_dock.isVisible()))
    act_nav.setShortcut("F9")
    act_ref = m_view.addAction(
        "Reference viewer (second view)",
        lambda: win._toggle_reference_view())
    act_ref.setShortcut("F8")
    act_ref.setToolTip(
        "A second, read-only view of the same PDF — keep a legend, TOC or "
        "cover sheet in view while you work on another page.")
    win.act_ref_view = act_ref
    # Show/hide (and re-open a closed) main pane. Each dock has a close
    # button, so these bring one back after it's been closed or floated away.
    m_panes = m_view.addMenu("Panes")
    for d in win.main_docks:
        m_panes.addAction(d.toggleViewAction())
    m_view.addSeparator()
    m_view.addAction("Reset panel layout", win.reset_layout)

    m_tools = mb.addMenu("&Tools")
    m_tools.addAction("Extract pages (visual)…",
                      lambda: win.tools_panel.show_operation("extract"))
    m_tools.addAction("Split into ranges…",
                      lambda: win.tools_panel.show_operation("split"))
    m_tools.addAction("Delete pages (visual)…",
                      lambda: win.tools_panel.show_operation("delete"))
    m_tools.addAction("Rotate pages (visual)…",
                      lambda: win.tools_panel.show_operation("rotate"))
    m_tools.addSeparator()
    m_tools.addAction("Split by sheet number… (wizard)",
                      lambda: win.tools_panel.start_sheet_wizard())
    m_tools.addSeparator()
    m_tools.addAction("Combine PDFs…", lambda: win.tools_panel.open_combine())
    m_tools.addAction("Insert PDF…", lambda: win.tools_panel.open_insert())
    m_tools.addAction("Swap a page…", lambda: win.tools_panel.open_swap())
    m_tools.addSeparator()
    m_tools.addAction("PDF → Word…", lambda: win.tools_panel.open_convert())
    m_tools.addAction("Crop / extract… (wizard)",
                      lambda: win.tools_panel.start_crop_wizard())
    m_tools.addSeparator()
    win.act_run_audit = m_tools.addAction(
        "Run design rule check…", win.run_audit, QKeySequence("F7"))
    win.act_run_audit.setToolTip(
        "Check the drawing against the design rules and list what to confirm")
    win.act_import_drawings = m_tools.addAction(
        "Import project drawings…", win.import_project_drawings)
    win.act_import_drawings.setToolTip(
        "Read the AutoCAD Electrical source drawings (DWG/DXF) to enrich "
        "the design rule check")

    m_help = mb.addMenu("&Help")
    m_help.addAction("User Manual", win._show_help, QKeySequence.HelpContents)
    m_help.addAction("About " + __app_name__, win._show_about)


def rebuild_recent(win):
    """Refill File ▸ Open Recent from the saved list (most recent first)."""
    menu = getattr(win, "m_recent", None)
    if menu is None:
        return
    menu.clear()
    paths = win.config.recent_files
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
                lambda _=False, p=path: win.load_document(p))
        else:
            # keep it listed but obviously unusable rather than silently
            # dropping a file that's just on a disconnected drive
            act.setEnabled(False)
            act.setText(f"{label}   (not found)")
    menu.addSeparator()
    menu.addAction("Clear list", win._clear_recent_files)


def clear_recent(win):
    win.config.clear_recent_files()
    rebuild_recent(win)
