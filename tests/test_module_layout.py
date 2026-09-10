"""``app/main_window.py`` is a window, and the README says which files hold what.

Measured 2026-08-26 and unchanged on 2026-09-03: ``app/main_window.py`` was
**2,506 lines**, 718 more than the next largest module, and held the preferences
dialog, five panes, the toolbar, the menus and the file lifecycle. One file was
8.6% of a 29,260-line codebase.

The dialogs went first (``app/settings_dialog.py``, ``app/dialogs.py``), then
printing (``app/printing.py``), then the toolbar, the menu bar and the document
lifecycle (``app/toolbar.py``, ``app/menus.py``, ``app/lifecycle.py``):
**2,506 -> 1,879 -> 1,492 -> 1,081**. What is left is the docking of the panes
and the acts nothing else owns.

Those numbers are dated evidence for the paragraph they sit in, never a current
claim — none of the gates below reads one. **Every gate here is a KIND of
thing**: a dialog class defined back in the window, a printing library it
imports, a widget class it constructs, a model it builds. A count is a snapshot
and wrong by the next commit; a kind is permanent, is exactly what was
extracted, and is what an accumulation looks like on its FIRST step.

**And the README's layout block going stale.** It described the god-object in as
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
            f"{found} again. The dialogs were moved to "
            "app/settings_dialog.py and app/dialogs.py, and a new one here "
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


def _imported_symbols(path: pathlib.Path) -> set[str]:
    """Every NAME a `from X import a, b` brings in, function-local included."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            out.update(a.asname or a.name for a in node.names)
    return out


class TestTheWindowDoesNotBuildChrome(unittest.TestCase):
    """The toolbar and the menus are ``app/toolbar.py`` and ``app/menus.py``.

    The row's own ``remains`` said the two *"build the same actions and may not
    be separable, which is a measurement somebody has to take before cutting"*.
    **The measurement refutes it**, and the discriminator is what each one
    makes: they write 11 self-attributes each and share none, and they overlap
    in exactly one import (``QKeySequence``). The toolbar CONSTRUCTS eleven
    kinds of widget; the menu WIRES methods that already exist and needs no
    widget class at all.

    So the claim here is the printing gate's, in chrome's vocabulary: a window
    that reaches for ``QToolBar`` or ``QComboBox`` is building a toolbar again,
    whatever it calls the method. Measured before it was taken — moving the
    toolbar out left **ten** imports unused in the window, which is why this is
    zero rather than a threshold. (``QApplication`` was dead already and is not
    counted as freed by the cut; it went with them.)
    """

    CHROME = ("QToolBar", "QComboBox", "QSpinBox", "QDoubleSpinBox",
              "QPushButton", "QCheckBox", "QActionGroup", "QAction",
              "QLabel", "QKeySequence")

    def test_the_window_imports_no_chrome_widget(self):
        found = sorted(_imported_symbols(APP / "main_window.py")
                       & set(self.CHROME))
        self.assertEqual(
            found,
            [],
            f"app/main_window.py imports {found} again. The toolbar moved to "
            "app/toolbar.py and the menu bar to app/menus.py; a window that "
            "reaches for a widget class is building chrome, which is the "
            "accumulation this cut undid.",
        )

    def test_the_window_no_longer_constructs_a_document(self):
        # The lifecycle half, and the sharper of the two boundaries: the window
        # stops importing the MODEL. It asks `lifecycle.open_document` for one.
        self.assertNotIn(
            "Document",
            _imported_symbols(APP / "main_window.py"),
            "app/main_window.py imports Document again — opening, forking and "
            "closing moved to app/lifecycle.py, and constructing the model is "
            "what that module is for.",
        )

    def test_the_chrome_is_where_it_was_moved_to(self):
        # The floor. Every assertion above is satisfied just as well by a
        # checkout where the toolbar and the menus were deleted.
        tb = _imported_symbols(APP / "toolbar.py")
        for name in ("QToolBar", "QComboBox", "QSpinBox", "QActionGroup"):
            self.assertIn(name, tb, f"app/toolbar.py does not import {name}")
        for path, funcs in (
            (APP / "toolbar.py", ("build",)),
            (APP / "menus.py", ("build", "rebuild_recent", "clear_recent")),
            (APP / "lifecycle.py", ("open_document", "save_as_fork",
                                    "ok_to_lose_unsaved", "on_close")),
        ):
            top = {n.name for n in ast.parse(path.read_text(encoding="utf-8")).body
                   if isinstance(n, ast.FunctionDef)}
            for f in funcs:
                self.assertIn(f, top, f"app/{path.name} has no {f}()")

    def test_the_window_still_offers_what_moved(self):
        # ...and the other floor: the extraction must not have taken the
        # FEATURE. A wrapper exists on the window exactly where a consumer
        # names it -- `main.py` and twenty test modules call `load_document`,
        # `closeEvent` is Qt's own hook -- while `_build_toolbar` and
        # `_build_menu` had no consumer and kept no wrapper. So this asserts
        # both halves: the four wrappers are there and the two builders are not.
        cls = next(n for n in ast.parse(
            (APP / "main_window.py").read_text(encoding="utf-8")).body
            if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
        meths = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
        for name in ("load_document", "save_as_fork", "_ok_to_lose_unsaved",
                     "closeEvent", "_rebuild_recent_menu",
                     "_clear_recent_files"):
            self.assertIn(
                name, meths,
                f"MainWindow.{name} is gone, and a consumer names it -- which "
                "is not what moving its body meant",
            )
        for name in ("_build_toolbar", "_build_menu"):
            self.assertNotIn(
                name, meths,
                f"MainWindow.{name} is back. Nothing outside __init__ ever "
                "named it, so a wrapper here is a second place to look for "
                "one builder.",
            )


class TestEveryMenuActionNamesSomethingTheWindowHas(unittest.TestCase):
    """A menu wired to a method nobody has fails when somebody CLICKS it.

    Not at import, not at build — at click time, in front of a user, which is
    the worst place to find out and the one place no test here was looking. The
    risk is real rather than theoretical now that the wiring lives in another
    module: ``app/menus.py`` names fifteen ``win.<handler>`` and cannot see the
    class.

    Measured on the day the cut landed: **zero** handlers name something
    ``MainWindow`` does not have, which is what makes this a gate rather than a
    worklist.
    """

    #: Handlers that are NOT MainWindow's own, with the reason. Gated in both
    #: directions below: an entry that becomes a MainWindow method is an excuse
    #: that has stopped excusing anything.
    INHERITED = {
        "close": "QWidget.close — Qt's, and the Quit action is meant to use it",
    }

    def _window_methods(self) -> set[str]:
        cls = next(n for n in ast.parse(
            (APP / "main_window.py").read_text(encoding="utf-8")).body
            if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
        return {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}

    def _handlers(self) -> set[str]:
        """Every bare ``win.<name>`` handed to a call in ``app/menus.py``.

        Bare on purpose: ``win.view.fit_width`` is an attribute chain into a
        pane the window merely holds, and whether *that* resolves is the pane's
        contract rather than the window's.
        """
        tree = ast.parse((APP / "menus.py").read_text(encoding="utf-8"))
        out: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for arg in list(node.args) + [k.value for k in node.keywords]:
                if (isinstance(arg, ast.Attribute)
                        and isinstance(arg.value, ast.Name)
                        and arg.value.id == "win"):
                    out.add(arg.attr)
        return out

    def test_every_handler_resolves(self):
        handlers = self._handlers()
        self.assertGreater(
            len(handlers), 8,
            f"only found {sorted(handlers)} — the walk is not finding the "
            "menu's handlers, so the check below is vacuous",
        )
        missing = sorted(h for h in handlers
                         if h not in self._window_methods()
                         and h not in self.INHERITED)
        self.assertEqual(
            missing, [],
            f"app/menus.py wires {missing}, which MainWindow does not have. "
            "That fails when somebody clicks the menu item, not when the "
            "window is built.",
        )

    def test_the_inherited_exemption_still_excuses_something(self):
        # Both directions, because an exemption is a claim about today.
        methods = self._window_methods()
        for name, why in self.INHERITED.items():
            self.assertNotIn(
                name, methods,
                f"MainWindow now defines {name}, so the exemption ({why}) is "
                "excusing nothing — retire it",
            )
            self.assertIn(
                name, self._handlers(),
                f"nothing in app/menus.py wires {name} any more, so the "
                "exemption is a stale waiver",
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
        for name in ("settings_dialog.py", "dialogs.py", "printing.py",
                     "toolbar.py", "menus.py", "lifecycle.py"):
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
