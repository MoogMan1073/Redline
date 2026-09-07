"""Opening, forking and closing a document — the window's file lifecycle.

The third of the three units `app/main_window.py`'s backlog row named as what
was left after the printing cut, and the one with a boundary rather than a
size behind it: **moving it leaves the window not importing `Document` at
all**. The window stops constructing the model and asks for one, which is the
same shape as `printing` taking `QtPrintSupport` and `fitz` out of it.

Four functions, and each is here because it is about the *document's* life and
not about the window's furniture:

* `open_document` — the one that carries the two hard-won orderings. It refuses
  to reopen what is already open (`foo.pdf` and `foo.marked.pdf` share a
  sidecar, so they are one document), it asks before dropping unsaved marks
  **before** anything is built so Cancel leaves nothing half-opened, and it
  builds the new `Document` **before** closing the old one — closing first left
  a failed open pointed at a *closed* document, which is blank pages, "closed
  database" on save, and search raising.
* `save_as_fork` — copy the markup to a new working file and switch to it.
* `ok_to_lose_unsaved` — the prompt, and the one rule worth restating: a save
  that raised is not a save, so it stays put rather than discarding on the
  user's behalf.
* `on_close` — asks first, **before a single panel is shut down or a handle
  released**, because if they cancel the window has to still be a working
  window.

`MainWindow` keeps a thin method over each, and the rule is the one
`app/menus.py` states: *a wrapper exists where a consumer names it*.
`load_document` is named by `main.py` and by twenty test modules, `closeEvent`
is Qt's own hook, and `save_as_fork` and `_ok_to_lose_unsaved` are named by the
menu and by the tests — so all four keep their names on the window, where
`_build_toolbar` and `_build_menu` had no consumer and kept none.
"""
from __future__ import annotations

import os

from PySide6.QtWidgets import QFileDialog, QMessageBox

from . import __app_name__
from .model.document import Document


def open_document(win, path):
    from .model.storage import sidecar_path

    def _doc_key(p):
        return os.path.normcase(os.path.realpath(sidecar_path(p)))

    # Feature 1: refuse to open the document that's already open. foo.pdf and
    # foo.marked.pdf share a sidecar, so they count as the same document.
    if win.document is not None and _doc_key(path) == _doc_key(win.document.path):
        QMessageBox.information(
            win, "Already open",
            f"“{os.path.basename(path)}” is already open.")
        return
    # Opening another file drops this one's unsaved marks exactly as
    # finally as closing the window does. Asked before anything is built,
    # so Cancel leaves no half-opened document behind.
    if not win._ok_to_lose_unsaved("Open another file"):
        return
    # Build the new document BEFORE closing the old one. Closing first meant
    # a failed open (corrupt/locked/deleted file) returned with the window
    # still pointed at a *closed* Document — blank pages, "closed database"
    # on save, and search raising — which two views only made worse.
    try:
        doc = Document(path, ignore_patterns=win.config.ignore_patterns())
        doc.load()
    except Exception as e:
        QMessageBox.critical(win, "Open failed", str(e))
        return                      # the current document stays open and usable
    if win.document is not None:
        try:
            win.document.close()
        except Exception:
            pass
    win.document = doc
    # remember it in File ▸ Open Recent (only once the open has succeeded)
    win.config.add_recent_file(path)
    win._rebuild_recent_menu()
    # Feature 4: a .marked.pdf was opened but its original markup database
    # couldn't be found, so a new one was started — let the user know.
    if getattr(doc, "sidecar_recreated", False):
        QMessageBox.information(
            win, "New markup database",
            "This .marked.pdf's original markup database wasn't found next to "
            "it, so a new one has been started. Previously saved marks, TODOs "
            "and extractions for this file may not be available.")
    win.view.set_document(doc, win.config)
    # the reference pane shows the same document (read-only), whether or not
    # it's currently visible, so toggling it on is instant
    win.ref_view.set_document(doc, win.config)
    win.comment_panel.set_store(doc.store, win.config)
    win.todo_panel.set_store(doc.store, win.config, doc)
    win.wire_panel.set_document(doc, win.config)
    win.component_panel.set_document(doc, win.config)
    win.nav_panel.set_document(doc)
    win.audit_panel.set_document(doc, win.config)
    win._refresh_finding_marks()
    win.tools_panel.set_default_pdf(path)
    win.page_spin.setRange(1, max(1, doc.page_count))
    win.page_total.setText(f" / {doc.page_count}")
    win.setWindowTitle(f"{__app_name__} — {os.path.basename(path)}")
    win._update_actions_enabled(True)
    # Edge case: the PDF opened for viewing, but its name can't back a
    # markup database (too long, or unsupported characters), so markup and
    # saving are turned off. Tell the user why and how to fix it.
    if not doc.sidecar_available:
        win._warn_no_sidecar(path)
    win.statusBar().showMessage(
        f"Opened {os.path.basename(path)} ({doc.page_count} pages, "
        f"{len(doc.store.all())} existing marks)", 6000)


def save_as_fork(win):
    """Fork the current markup to a new working file and switch to editing it."""
    if win.document is None:
        return
    from .model.storage import original_pdf_path, sidecar_path
    base = os.path.splitext(
        os.path.basename(original_pdf_path(win.document.path)))[0]
    start_dir = os.path.dirname(os.path.abspath(win.document.path))
    suggested = os.path.join(start_dir, f"{base}-copy.pdf")
    path, _ = QFileDialog.getSaveFileName(
        win, "Save As — fork to a new working file", suggested, "PDF (*.pdf)")
    if not path:
        return
    if not path.lower().endswith(".pdf"):
        path += ".pdf"

    def _key(p):
        return os.path.normcase(os.path.realpath(sidecar_path(p)))
    if _key(path) == _key(win.document.path):
        QMessageBox.information(
            win, "Same file",
            "That's the file you're already working on — choose a new name.")
        return
    try:
        win.document.save_as(path)
    except Exception as e:
        QMessageBox.warning(win, "Save As failed", str(e))
        return
    new_path = win.document.path
    win.tools_panel.set_default_pdf(new_path)
    win.setWindowTitle(f"{__app_name__} — {os.path.basename(new_path)}")
    win.statusBar().showMessage(
        f"Forked to {os.path.basename(new_path)} — now editing the copy", 6000)
    QMessageBox.information(
        win, "Forked to a new working file",
        f"Now working on “{os.path.basename(new_path)}”.\n"
        f"The original file is unchanged.")


def ok_to_lose_unsaved(win, title: str) -> bool:
    """Ask before dropping marks that only File > Save would have kept.

    True means go ahead. The window used to close with no question and no
    save, so every mark drawn since the last save went with it, silently,
    on every sheet -- the one failure a markup tool does not get to have.

    Only the marks and the wire/component ticks hang on this: findings,
    waivers, sheet numbers and roles all write through as they change.
    """
    doc = win.document
    if doc is None or not doc.dirty:
        return True
    box = QMessageBox(win)
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
    return win.save_markup()


def on_close(win, event) -> bool:
    """Shut the document down. False means the user cancelled.

    The caller is `MainWindow.closeEvent`, which owns `event.ignore()` and the
    `super()` call — those are Qt's, not the document's.
    """
    # First, before a single panel is shut down or a handle released: if
    # they cancel, the window has to still be a working window.
    if not win._ok_to_lose_unsaved("Close"):
        return False
    win._save_ui_state()            # remember the dock layout + geometry
    try:
        win.wire_panel.shutdown()   # stop any running extraction thread
    except Exception:
        pass
    try:
        win.component_panel.shutdown()
    except Exception:
        pass
    try:
        win.tools_panel.grid.close_doc()
    except Exception:
        pass
    if win.document is not None:
        try:
            win.document.close()
        except Exception:
            pass
    return True
