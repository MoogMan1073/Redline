"""`app/lifecycle.py`'s two orderings, one of which nothing was checking.

Opening, forking and closing a document came out of `app/main_window.py` in the
same cut as the toolbar and the menu bar, and its module docstring calls two
things *"the two hard-won orderings"*. **The falsification found that only one
of them was gated.**

* *Build the new `Document` before closing the old one*, so a corrupt or locked
  file leaves the window pointed at a working document rather than a closed
  one, is covered — in `tests/test_v12_refview.py`, where two views made the
  symptom worse. Left there; it is a regression that module owns.
* *Refuse to open the document that is already open* was covered **nowhere**.
  Measured: with the guard replaced by `if False:` the whole suite is green —
  **751 tests across 58 modules, 28 skipped, all modules passed** — so a feature
  the window's own comment numbers ("Feature 1") could have been deleted without
  a red tick.

What that guard prevents is not cosmetic. `foo.pdf` and `foo.marked.pdf`
resolve to **one** `foo.markup.db`, so opening the second while the first is
open puts two `Document` objects on one SQLite sidecar — the one thing
`app/model/storage.py` is built not to let happen. It reads as an ordinary
"open a file" and it is a second writer on the marks.
"""

import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz

try:
    from PySide6.QtWidgets import QApplication, QMessageBox
    from app.main_window import MainWindow
    from app.model.storage import marked_pdf_path, sidecar_path
    _QT_OK = True
except Exception:  # pragma: no cover
    _QT_OK = False


def _make_pdf(path, pages=2):
    d = fitz.open()
    for i in range(pages):
        p = d.new_page(width=400, height=300)
        p.insert_text((60, 60), f"PAGE {i + 1}")
    d.save(path)
    d.close()
    return path


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestTheSameDocumentIsRefused(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = _make_pdf(os.path.join(self.tmp, "sheet.pdf"))

    def test_the_marked_copy_shares_a_sidecar_and_is_the_same_document(self):
        """The premise, asserted before anything rests on it.

        If these two ever stopped sharing a sidecar the guard below would be
        refusing two genuinely different documents, and the test would be
        pinning the wrong behaviour rather than catching a regression.
        """
        marked = marked_pdf_path(self.src)
        self.assertNotEqual(marked, self.src)
        self.assertEqual(sidecar_path(marked), sidecar_path(self.src))

    def test_reopening_the_open_document_changes_nothing(self):
        win = MainWindow()
        win.load_document(self.src)
        first = win.document
        with mock.patch.object(QMessageBox, "information",
                               return_value=QMessageBox.Ok) as info:
            win.load_document(self.src)
        self.assertIs(win.document, first, "the document was rebuilt")
        self.assertFalse(first.fitz_doc.is_closed)
        self.assertTrue(info.called, "nothing told the user why it did not open")

    def test_the_marked_copy_of_the_open_document_is_refused_too(self):
        """The case the guard exists for, and the one a naive path compare
        misses: a different filename, the same markup database."""
        marked = marked_pdf_path(self.src)
        _make_pdf(marked)
        win = MainWindow()
        win.load_document(self.src)
        first = win.document
        with mock.patch.object(QMessageBox, "information",
                               return_value=QMessageBox.Ok) as info:
            win.load_document(marked)
        self.assertIs(
            win.document, first,
            "opening foo.marked.pdf over an open foo.pdf put a second "
            "Document on one sidecar")
        self.assertTrue(info.called)

    def test_a_DIFFERENT_document_still_opens(self):
        """The complement. A guard that refused everything would satisfy both
        checks above and make the application unable to open a second file."""
        other = _make_pdf(os.path.join(self.tmp, "other.pdf"))
        win = MainWindow()
        win.load_document(self.src)
        first = win.document
        win.load_document(other)
        self.assertIsNot(win.document, first)
        self.assertEqual(os.path.basename(win.document.path), "other.pdf")


if __name__ == "__main__":
    unittest.main()
