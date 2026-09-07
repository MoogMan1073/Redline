"""``app/main_window.py`` is a window, and the README says which files hold what.

Measured 2026-08-26 and unchanged on 2026-09-03: ``app/main_window.py`` was
**2,506 lines**, 718 more than the next largest module, and held the preferences
dialog, five panes, the toolbar, the menus and the file lifecycle. One file was
8.6% of a 29,260-line codebase.

The dialogs are out (``app/settings_dialog.py``, ``app/dialogs.py``), which took
it to 1,879. **The rest of the split is not done**, and this module says so
rather than implying the row is closed: the five panes, the toolbar, the menus
and the lifecycle are all still in there.

What is gated is the two things that would quietly undo it.

**A dialog class defined back in the window.** That is not a line count — a
count is a snapshot, wrong by the next commit, and this family's standing rule
is to name the script that prints the current answer instead. A ``QDialog``
subclass in ``main_window`` is a *kind* of thing, permanent and checkable, and
it is exactly what was extracted.

**The README's layout block going stale.** It described the god-object in as
many words (*"Window: five ... panes, toolbar, Settings"*), so it was right
about a thing that was wrong, and a block that stops matching the tree is the
drift this repository already gates one document over.
"""

from __future__ import annotations

import ast
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
APP = REPO / "app"


def _dialog_classes(path: pathlib.Path) -> list[str]:
    """Every class in ``path`` whose bases name a dialog.

    By BASE rather than by the class's own name: a class called ``FooDialog``
    that subclasses ``QWidget`` is not one, and a ``QDialog`` subclass called
    ``Prefs`` is.

    A base whose *name* ends in ``Dialog`` counts too, and that is not the
    name-check the paragraph above argues against — it is a claim about what the
    class derives from. It is here because the indirect case is **reachable**:
    ``app/tools/dialogs.py`` declares ``_ToolDialog(QDialog)`` and seven
    subclasses of it, all importable, so a ``class Foo(_ToolDialog)`` back in
    ``main_window`` would have slipped straight through a direct-bases-only
    sweep. Measured across ``app/``: the widening admits exactly those seven and
    **nothing else** — 7 classes over 4 files becomes 14, with no false
    positive, which is what made it worth taking rather than stating as a limit.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
            if name in ("QDialog", "QMessageBox", "QFileDialog", "QColorDialog"):
                out.append(node.name)
            elif name.endswith("Dialog"):
                out.append(node.name)
    return out


class TestTheWindowHoldsNoDialog(unittest.TestCase):
    def test_main_window_defines_no_dialog_class(self):
        found = _dialog_classes(APP / "main_window.py")
        self.assertEqual(
            found,
            [],
            "app/main_window.py defines "
            f"{found} again. That module already holds the five panes, the "
            "toolbar, the menus and the file lifecycle; the dialogs were moved "
            "to app/settings_dialog.py and app/dialogs.py, and a new one here "
            "starts the same accumulation over.",
        )

    def test_the_extracted_dialogs_are_where_they_were_moved_to(self):
        # The floor. "No dialog in main_window" is satisfied perfectly by a
        # checkout with no dialogs at all, or by a sweep that parses nothing.
        self.assertIn("SettingsDialog", _dialog_classes(APP / "settings_dialog.py"))
        moved = _dialog_classes(APP / "dialogs.py")
        for name in ("TextEditDialog", "WaiveDialog", "FillDialog"):
            self.assertIn(
                name,
                moved,
                f"{name} is not in app/dialogs.py, so the check above is "
                "asserting the absence of something that no longer exists "
                "anywhere",
            )

    def test_every_dialog_class_in_the_package_is_found_by_this_sweep(self):
        # ...and the wider floor: the sweep must find dialogs across the
        # package, or a rename of the Qt base class silently switches the whole
        # module off while every assertion above still passes.
        #
        # A floor rather than the measured number (14 across four files on
        # 2026-09-05), because a count is a snapshot and wrong by the next
        # commit. What it has to survive is the arm that matters: rename away
        # the base names this sweep knows and the total goes to zero.
        total = sum(len(_dialog_classes(p)) for p in APP.rglob("*.py"))
        self.assertGreater(
            total,
            5,
            "the dialog sweep found almost nothing in app/ — it is not "
            "recognising Qt dialog subclasses, so nothing above is a "
            "measurement",
        )


def _imported_names(path: pathlib.Path) -> set[str]:
    """Every module this file imports from, walked with `ast`.

    Function-local imports included, which is the whole point here: every one
    of the nine printing methods imported `QtPrintSupport` or `fitz` *inside*
    itself, so a top-level scan would have reported the window as printer-free
    while it drove a printer nine times.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            out.add(node.module)
    return out


class TestTheWindowDoesNotPrint(unittest.TestCase):
    """Printing is a subject, and it lives in ``app/printing.py``.

    The same KIND of claim the dialog sweep makes, in printing's vocabulary. A
    line count is a snapshot; *the window neither drives a printer nor
    rasterises a page* is permanent, is exactly what was extracted, and is what
    an accumulation looks like on its FIRST step — a print helper written back
    into the window reaches for `QtPrintSupport` or for `fitz` on its first
    line, because those are the two libraries the job needs.

    Measured before it was taken: every `QtPrintSupport` import and every
    `fitz` use in `main_window.py` was inside the 409-line printing block, so
    the claim is zero rather than a threshold.
    """

    PRINT_LIBS = ("PySide6.QtPrintSupport", "fitz", "pymupdf")

    def test_the_window_imports_no_printing_library(self):
        found = sorted(_imported_names(APP / "main_window.py")
                       & set(self.PRINT_LIBS))
        self.assertEqual(
            found,
            [],
            f"app/main_window.py imports {found} again. Printing moved to "
            "app/printing.py -- the printer, the two print dialogs and the "
            "page raster -- and a window that reaches for one of those "
            "libraries is the same accumulation starting over.",
        )

    def test_printing_is_where_it_was_moved_to(self):
        # The floor. "The window imports no print library" is satisfied just as
        # well by a checkout where printing was deleted, or by a sweep that
        # parses nothing.
        names = _imported_names(APP / "printing.py")
        for lib in ("PySide6.QtPrintSupport", "fitz"):
            self.assertIn(
                lib,
                names,
                f"app/printing.py does not import {lib}, so the check above "
                "is asserting the absence of something that no longer exists "
                "anywhere",
            )
        src = (APP / "printing.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        top = {n.name for n in tree.body
               if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        for name in ("new_printer", "run_print_dialog", "run_print_preview",
                     "paint_document", "paint_page", "render_dpi", "fit",
                     "min_line_width", "is_preview", "PrintOptions"):
            self.assertIn(name, top, f"app/printing.py has no {name}")

    def test_the_window_still_offers_both_print_actions(self):
        # ...and the other floor, pointed the other way: the extraction must
        # not have taken the FEATURE with it. The two menu actions are the
        # window's, and a window that stopped offering them would satisfy every
        # assertion above.
        tree = ast.parse((APP / "main_window.py").read_text(encoding="utf-8"))
        cls = next(n for n in tree.body
                   if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
        meths = {n.name for n in cls.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for name in ("print_document", "print_preview"):
            self.assertIn(
                name,
                meths,
                f"MainWindow.{name} is gone, so the window no longer offers "
                "printing at all -- which is not what moving it meant",
            )


class TestTheReadmeLayoutMatchesTheTree(unittest.TestCase):
    """Every module the layout block names exists, and the new ones are named.

    Asked of the filesystem, never of a second document: a prose-versus-prose
    check is two copies that drift together.
    """

    def _layout_block(self) -> str:
        text = (REPO / "README.md").read_text(encoding="utf-8")
        start = text.index("## Project layout")
        end = text.index("## ", start + 3)
        return text[start:end]

    def test_the_new_modules_are_named(self):
        block = self._layout_block()
        for name in ("settings_dialog.py", "dialogs.py", "printing.py"):
            self.assertIn(
                name,
                block,
                f"README's Project layout does not name app/{name}. It named "
                "main_window as holding 'Settings' for as long as that was "
                "true; a block that stops matching the tree sends a reader to "
                "the wrong file.",
            )

    def test_every_app_module_the_block_names_exists(self):
        block = self._layout_block()
        named = [
            w.strip()
            for line in block.splitlines()
            for w in [line.split()[0] if line.split() else ""]
            if w.endswith(".py") and w != "main.py"
        ]
        # A floor, deliberately well below the five names the block carries
        # today. At `> 4` it fired on *any* line removed from the README —
        # which is a count assertion wearing a floor's message, and it reported
        # "the parse is not finding module names" about a block that parsed
        # perfectly. What this has to catch is the parse breaking, which takes
        # it to zero or one.
        self.assertGreater(
            len(named), 2, f"parsed {named} out of the layout block — the "
            "parse is not finding module names, so the check below is vacuous"
        )
        for mod in named:
            self.assertTrue(
                (APP / mod).exists(),
                f"README's Project layout names app/{mod}, which does not exist",
            )


if __name__ == "__main__":
    unittest.main()
