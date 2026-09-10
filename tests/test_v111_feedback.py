"""v1.1.x feedback round: opacity-slider fill dialog, notes as visible sticky
comments, tool hotkeys (Ctrl+1..0), and the rectangle revision-cloud mode."""

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz

from app.model.annotations import (
    Annotation, KIND_HIGHLIGHT, KIND_ARROW, KIND_RECT, KIND_CLOUD, KIND_COMMENT,
)
from app.model.storage import (
    write_annotations_to_pdf, load_pdf_annotations, marked_pdf_path,
    DEFAULT_IGNORE_PATTERNS, _NOTE_SUFFIX,
)

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QPointF, Qt
    _QT_OK = True
except Exception:  # pragma: no cover
    _QT_OK = False


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestFillDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_opacity_slider_reflects_and_returns(self):
        from app.dialogs import FillDialog
        d = FillDialog((0.2, 0.4, 0.6), 0.5)
        self.assertEqual(d.slider.value(), 50)
        self.assertFalse(d.none_cb.isChecked())
        color, op = d.result_fill()
        self.assertEqual(color, (0.2, 0.4, 0.6))
        self.assertAlmostEqual(op, 0.5)

    def test_no_fill_option(self):
        from app.dialogs import FillDialog
        d = FillDialog(None, 1.0)
        self.assertTrue(d.none_cb.isChecked())
        self.assertEqual(d.result_fill(), (None, 1.0))
        # ticking No fill disables the color + slider controls
        d2 = FillDialog((1, 0, 0), 1.0)
        d2.none_cb.setChecked(True)
        self.assertFalse(d2.slider.isEnabled())
        self.assertIsNone(d2.result_fill()[0])

    def test_zero_opacity_means_no_fill(self):
        from app.dialogs import FillDialog
        d = FillDialog((1, 0, 0), 1.0)
        d.slider.setValue(0)
        self.assertIsNone(d.result_fill()[0])


class TestNotesAsStickyComments(unittest.TestCase):
    def _blank(self, path):
        d = fitz.open(); d.new_page(width=400, height=300); d.save(path); d.close()

    def test_note_emits_sticky_and_reloads_without_duplication(self):
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "d.pdf")
        self._blank(src)
        anns = [
            Annotation(page=0, kind=KIND_HIGHLIGHT, rect=(30, 40, 150, 60),
                       color=(1, 1, 0), opacity=0.4, text="check this", author="Eli"),
            Annotation(page=0, kind=KIND_ARROW, rect=(200, 40, 300, 90),
                       color=(0, 0, 1), width=2, text="reroute", author="Eli"),
            Annotation(page=0, kind=KIND_HIGHLIGHT, rect=(30, 80, 150, 100),
                       color=(0, 1, 0), opacity=0.4),          # no note
        ]
        d = fitz.open(src)
        write_annotations_to_pdf(d, anns)
        mp = marked_pdf_path(src)
        d.save(mp, garbage=3, deflate=True)
        d.close()

        d2 = fitz.open(mp)
        stickies = [a for a in d2[0].annots()
                    if a.type[1] == "Text"
                    and (a.info.get("name") or "").endswith(_NOTE_SUFFIX)]
        contents = sorted(a.info.get("content") for a in stickies)
        d2.close()
        self.assertEqual(len(stickies), 2)          # one per noted mark, none for the bare one
        self.assertEqual(contents, ["check this", "reroute"])

        # reload: the auxiliary stickies are skipped, notes stay on the parents
        loaded = load_pdf_annotations(fitz.open(mp), DEFAULT_IGNORE_PATTERNS)
        self.assertEqual(len(loaded), 3)            # 2 highlights + 1 arrow, no extra comments
        self.assertNotIn(KIND_COMMENT, [a.kind for a in loaded])
        noted = sorted(a.text for a in loaded if a.text)
        self.assertEqual(noted, ["check this", "reroute"])

    def test_noted_rect_gets_sticky(self):
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "d.pdf")
        self._blank(src)
        d = fitz.open(src)
        write_annotations_to_pdf(d, [Annotation(page=0, kind=KIND_RECT,
                                                rect=(20, 20, 120, 80), color=(1, 0, 0),
                                                text="raise this", author="Eli")])
        mp = marked_pdf_path(src)
        d.save(mp)
        d.close()
        d2 = fitz.open(mp)
        types = sorted(a.type[1] for a in d2[0].annots())
        d2.close()
        self.assertEqual(types, ["Square", "Text"])   # rect + its sticky note


class TestFlattenedExport(unittest.TestCase):
    def test_flatten_bakes_marks_into_content(self):
        from app.model.document import Document
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "d.pdf")
        d = fitz.open(); d.new_page(width=400, height=300); d.save(src); d.close()
        doc = Document(src); doc.load()
        doc.store.add(Annotation(page=0, kind=KIND_RECT, rect=(30, 30, 150, 90),
                                 color=(1, 0, 0), fill_color=(0, 0.6, 1)))
        doc.store.add(Annotation(page=0, kind=KIND_CLOUD, color=(1, 0, 0), width=1.5,
                                 points=[(200, 150), (300, 140), (310, 220), (210, 230)]))
        flat = os.path.join(tmp, "flat.pdf")
        baked = doc.export_flattened_pdf(flat)
        doc.close()
        self.assertTrue(baked)
        d2 = fitz.open(flat)
        # no live annotations remain — they're page content now
        self.assertEqual(sum(len(list(p.annots() or [])) for p in d2), 0)
        # and they render with annots disabled (i.e. every viewer shows them)
        pix = d2[0].get_pixmap(annots=False)
        nonwhite = sum(1 for i in range(0, len(pix.samples), 3)
                       if pix.samples[i] < 240 or pix.samples[i + 1] < 240
                       or pix.samples[i + 2] < 240)
        d2.close()
        self.assertGreater(nonwhite, 500)


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestReopenRendersMarks(unittest.TestCase):
    """Guards the in-app reopen path: a saved .marked.pdf reloads its marks with
    fill/points/note intact and builds the correct graphics items."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _round_trip(self, rotation):
        from app.main_window import MainWindow
        from app.model.document import Document
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "draw.pdf")
        d = fitz.open(); pg = d.new_page(width=612, height=792)
        if rotation:
            pg.set_rotation(rotation)
        d.save(src); d.close()
        doc = Document(src); doc.load()
        doc.store.add(Annotation(page=0, kind=KIND_RECT, rect=(60, 60, 260, 160),
                                 color=(1, 0, 0), width=2, fill_color=(0, 0.6, 1),
                                 fill_opacity=1.0))
        doc.store.add(Annotation(page=0, kind=KIND_CLOUD, color=(1, 0, 0), width=1.5,
                                 points=[(300, 300), (420, 290), (430, 420), (310, 430)]))
        doc.store.add(Annotation(page=0, kind=KIND_HIGHLIGHT, rect=(60, 200, 260, 230),
                                 color=(1, 1, 0), opacity=0.4, text="note"))
        marked = doc.save(); doc.close()
        win = MainWindow(); win.load_document(marked)
        return win

    def _check(self, win):
        from app.viewer.annotation_items import (RectShapeItem, CloudItem,
                                                 HighlightItem, fill_brush)
        by_kind = {a.kind: a for a in win.document.store.all()}
        # data survived the round-trip
        self.assertEqual(by_kind[KIND_RECT].fill_color, (0, 0.6, 1))
        self.assertEqual(len(by_kind[KIND_CLOUD].points), 4)
        # the right graphics items exist and would paint
        items = win.view._item_by_ann
        rect_item = items[by_kind[KIND_RECT].id]
        cloud_item = items[by_kind[KIND_CLOUD].id]
        self.assertIsInstance(rect_item, RectShapeItem)
        self.assertIsInstance(cloud_item, CloudItem)
        self.assertIsNotNone(fill_brush(by_kind[KIND_RECT]))   # fill paints
        self.assertFalse(cloud_item.path().isEmpty())          # scallops built

    def test_reopen_unrotated(self):
        self._check(self._round_trip(0))

    def test_reopen_rotated(self):
        self._check(self._round_trip(90))


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestToolHotkeys(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_ctrl_digit_shortcuts_assigned(self):
        from app.main_window import MainWindow
        import app.viewer.tools as T
        win = MainWindow()
        expected = {
            T.TOOL_SELECT: "Ctrl+1", T.TOOL_HIGHLIGHT: "Ctrl+2", T.TOOL_PEN: "Ctrl+3",
            T.TOOL_ERASER: "Ctrl+4", T.TOOL_COMMENT: "Ctrl+5", T.TOOL_TEXTBOX: "Ctrl+6",
            T.TOOL_CALLOUT: "Ctrl+7", T.TOOL_RECT: "Ctrl+8", T.TOOL_ARROW: "Ctrl+9",
            T.TOOL_CLOUD: "Ctrl+0",
        }
        for tool, key in expected.items():
            self.assertEqual(win._tool_actions[tool].shortcut().toString(), key)

    def test_shortcut_trigger_activates_tool(self):
        from app.main_window import MainWindow
        import app.viewer.tools as T
        win = MainWindow()
        win._tool_actions[T.TOOL_CLOUD].trigger()
        self.assertEqual(win.view.tool.current, T.TOOL_CLOUD)
        self.assertTrue(win._tool_actions[T.TOOL_CLOUD].isChecked())


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestRectangleCloud(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _win(self):
        import app.viewer.tools as T
        from app.main_window import MainWindow
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "d.pdf")
        d = fitz.open(); d.new_page(width=400, height=300); d.save(src); d.close()
        win = MainWindow(); win.load_document(src)
        win.view.tool.current = T.TOOL_CLOUD
        return win

    def test_shift_drag_makes_rectangular_cloud(self):
        win = self._win()
        v = win.view
        page = v._page_items[0]
        v._cloud_press = page.mapToScene(QPointF(50, 50))
        v._cloud_rect = True                       # Shift was held at press
        v._cloud_on_move(page.mapToScene(QPointF(200, 150)))
        v._update_draft(page.mapToScene(QPointF(220, 160)))
        self.assertEqual(len(v._draft.points), 4)  # four bbox corners
        v._finish_draft()
        clouds = [a for a in v.store.all() if a.kind == KIND_CLOUD]
        self.assertEqual(len(clouds), 1)
        pts = clouds[0].points
        self.assertEqual(len(pts), 4)
        xs = {round(x) for x, _ in pts}
        ys = {round(y) for _, y in pts}
        self.assertEqual(xs, {50, 220})            # axis-aligned rectangle
        self.assertEqual(ys, {50, 160})

    def test_plain_drag_still_freehand(self):
        win = self._win()
        v = win.view
        page = v._page_items[0]
        v._cloud_press = page.mapToScene(QPointF(50, 50))
        v._cloud_rect = False
        v._cloud_on_move(page.mapToScene(QPointF(80, 80)))
        # freehand starts with the two sampled points, not a 4-corner rect
        self.assertEqual(len(v._draft.points), 2)


if __name__ == "__main__":
    unittest.main()
