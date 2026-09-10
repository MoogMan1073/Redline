"""Print… (Ctrl+P): render the drawing + its marks and send it to the system
print service. Exercised here against a PDF-output printer so no hardware is
needed."""

import os
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# QPrinter / QPrintPreviewDialog talk to the OS print subsystem. On the headless
# Windows CI runner (offscreen QPA + no real printer) constructing/rendering them
# can hard-crash the interpreter, even though it's fine on Linux offscreen and on
# a real Windows desktop (the print feature is verified there manually).
_SKIP_NATIVE_PRINT = sys.platform.startswith("win")

# Only the tests that actually construct one of those wear this. Everything else
# in the class below — the fit maths, the band joins, the preview caps — paints
# into a plain QImage/QPicture and runs everywhere, which matters because
# Windows is where this code does its real printing.
needs_native_print = unittest.skipIf(
    _SKIP_NATIVE_PRINT,
    "native QPrinter/QPrintPreviewDialog is unreliable on the headless Windows "
    "CI runner; verified manually on the real build")

import fitz

from app import printing
from app.model.annotations import Annotation, KIND_RECT

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtPrintSupport import QPrinter
    from PySide6.QtGui import QImage
    _QT_OK = True
except Exception:  # pragma: no cover
    _QT_OK = False


def _make_pdf(dirpath, pages=2, name="d.pdf"):
    src = os.path.join(dirpath, name)
    d = fitz.open()
    for _ in range(pages):
        p = d.new_page(width=400, height=300)
        p.insert_text((72, 72), "sheet")
    d.save(src); d.close()
    return src


class TestAnnotatedFitz(unittest.TestCase):
    def test_returns_doc_with_marks(self):
        from app.model.document import Document
        tmp = tempfile.mkdtemp()
        src = _make_pdf(tmp, pages=1)
        doc = Document(src); doc.load()
        doc.store.add(Annotation(page=0, kind=KIND_RECT,
                                 rect=(10, 10, 100, 80), color=(1, 0, 0)),
                      silent=True)
        work = doc.annotated_fitz()
        try:
            self.assertEqual(work.page_count, 1)
            self.assertTrue(len(list(work[0].annots() or [])) >= 1)
        finally:
            work.close()
            doc.close()


    def test_annotated_fitz_without_marks_is_clean(self):
        from app.model.document import Document
        tmp = tempfile.mkdtemp()
        src = _make_pdf(tmp, pages=1)
        doc = Document(src); doc.load()
        doc.store.add(Annotation(page=0, kind=KIND_RECT,
                                 rect=(10, 10, 100, 80), color=(1, 0, 0)),
                      silent=True)
        with_marks = doc.annotated_fitz(with_marks=True)
        without = doc.annotated_fitz(with_marks=False)
        try:
            self.assertGreaterEqual(len(list(with_marks[0].annots() or [])), 1)
            self.assertEqual(len(list(without[0].annots() or [])), 0)
        finally:
            with_marks.close(); without.close(); doc.close()


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestPrint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _win_with(self, pages=2):
        from app.main_window import MainWindow
        tmp = tempfile.mkdtemp()
        src = _make_pdf(tmp, pages=pages)
        win = MainWindow(); win.load_document(src)
        return win, tmp

    def test_page_fills_the_sheet_at_device_resolution(self):
        # Regression: the page used to be rasterised at a fixed 200 dpi relative
        # to the *source page* and then scaled UP to fill the sheet, so prints
        # were soft — and asking the driver for more dpi made it worse (a bigger
        # upscale). The page must now be laid out in the device's own pixels.
        from PySide6.QtCore import QRect
        win, _ = self._win_with(pages=1)
        target = QRect(0, 0, 4792, 6853)          # a 600 dpi Letter viewport
        work = win.document.annotated_fitz()
        try:
            scale, w, h, x, y = printing.fit(work[0].rect, target)
        finally:
            work.close()
        # fills one axis of the sheet exactly, and is centred on the other
        self.assertTrue(w == target.width() or h == target.height())
        self.assertGreater(w, 2000)               # not a 200 dpi thumbnail
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertAlmostEqual(x * 2 + w, target.width(), delta=1)
        self.assertAlmostEqual(y * 2 + h, target.height(), delta=1)

    @needs_native_print
    def test_printed_raster_matches_the_driver_resolution(self):
        # End-to-end guard for the same regression, measured on the output: the
        # raster actually placed on the sheet must be at the driver's dpi, not a
        # low-dpi render stretched to fill it (which is what made prints soft,
        # and made *raising* the driver's quality setting look worse).
        win, tmp = self._win_with(pages=1)
        out = os.path.join(tmp, "dpi.pdf")
        printer = QPrinter(QPrinter.ScreenResolution)
        printer.setResolution(600)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(out)
        printing.paint_document(win.document, printer, win.print_options)
        chk = fitz.open(out)
        try:
            infos = chk[0].get_image_info()
            self.assertTrue(infos, "no raster was placed on the page")
            im = max(infos, key=lambda i: i["width"] * i["height"])
            placed_inches = fitz.Rect(im["bbox"]).width / 72.0
            effective_dpi = im["width"] / placed_inches
            self.assertGreater(effective_dpi, 550)     # ~600; was ~200 before
        finally:
            chk.close()

    def test_page_fits_the_sheet_without_distortion(self):
        from PySide6.QtCore import QRect
        win, tmp = self._win_with(pages=1)
        # a landscape page must keep its aspect ratio inside a portrait sheet
        src = os.path.join(tmp, "wide.pdf")
        d = fitz.open(); d.new_page(width=792, height=612); d.save(src); d.close()
        win.load_document(src)
        target = QRect(0, 0, 2550, 3300)
        work = win.document.annotated_fitz()
        try:
            page = work[0]
            src_aspect = page.rect.width / page.rect.height   # read before close
            scale, w, h, x, y = printing.fit(page.rect, target)
        finally:
            work.close()
        self.assertAlmostEqual(w / h, src_aspect, places=2)
        self.assertLessEqual(w, target.width())
        self.assertLessEqual(h, target.height())

    @needs_native_print
    def test_large_sheet_is_banded_so_no_single_bitmap_is_huge(self):
        # An E-size plot at a high driver dpi would be a multi-GB bitmap in one
        # piece. It is rasterised in horizontal bands instead — bounded memory,
        # without giving up any resolution.
        from PySide6.QtCore import QRect
        win, tmp = self._win_with(pages=1)
        src = os.path.join(tmp, "big.pdf")
        d = fitz.open(); d.new_page(width=1584, height=2448)   # ANSI D
        d.save(src); d.close()
        win.load_document(src)
        out = os.path.join(tmp, "big_out.pdf")
        printer = QPrinter(QPrinter.ScreenResolution)
        printer.setResolution(600)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(out)
        printing.paint_document(win.document, printer, win.print_options)
        chk = fitz.open(out)
        try:
            infos = chk[0].get_image_info()
            self.assertGreater(len(infos), 1, "large sheet should be banded")
            for im in infos:
                self.assertLessEqual(im["width"] * im["height"],
                                     printing.PRINT_BAND_PX * 1.02)
            # ...and the bands together still cover the page at full resolution
            widest = max(infos, key=lambda i: i["width"])
            span_in = fitz.Rect(widest["bbox"]).width / 72.0
            self.assertGreater(widest["width"] / span_in, 550)
        finally:
            chk.close()

    def test_zero_area_viewport_is_survivable(self):
        # A viewport with no area must not raise: the band clip divides by the
        # fit scale, so a zero scale used to be a ZeroDivisionError surfacing to
        # the user as "Print failed: float division by zero".
        from PySide6.QtGui import QImage, QPainter
        from PySide6.QtCore import QRect
        win, _ = self._win_with(pages=1)
        work = win.document.annotated_fitz()
        try:
            canvas = QImage(10, 10, QImage.Format_RGB888)
            painter = QPainter(canvas)
            try:
                printing.paint_page(painter, work[0], QRect(0, 0, 0, 0))
                printing.paint_page(painter, work[0], QRect(0, 0, -50, -50))
            finally:
                painter.end()
        finally:
            work.close()

    @needs_native_print
    def test_empty_printable_area_is_survivable(self):
        # The same thing reached through a real printer: exotic paper (or
        # margins wider than the sheet) leaves nothing to print on.
        from PySide6.QtGui import QPageSize
        from PySide6.QtCore import QSizeF
        win, tmp = self._win_with(pages=1)
        printer = QPrinter(QPrinter.ScreenResolution)
        printer.setResolution(600)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(os.path.join(tmp, "tiny.pdf"))
        printer.setPageSize(QPageSize(QSizeF(20, 20), QPageSize.Point))
        printing.paint_document(win.document, printer, win.print_options)          # must not raise

    def test_bands_join_without_seams(self):
        # The band boundaries must be invisible: banded output has to match a
        # single-shot render of the same page. Checked on a rotated page too —
        # AutoCAD plots are almost always rotated.
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QImage, QPainter
        from app.main_window import MainWindow
        win, tmp = self._win_with(pages=1)
        for rot in (0, 90):
            src = os.path.join(tmp, f"seam{rot}.pdf")
            d = fitz.open(); pg = d.new_page(width=612, height=792)
            for i in range(0, 780, 3):           # dense: any seam would show
                pg.draw_line((20, i), (592, i + 2), width=0.3)
            if rot:
                pg.set_rotation(rot)
            d.save(src); d.close()

            def render(band_px):
                doc = fitz.open(src)
                target = QRect(0, 0, 1200, 1550)
                canvas = QImage(1200, 1550, QImage.Format_RGB888)
                canvas.fill(0xFFFFFFFF)
                painter = QPainter(canvas)
                keep = printing.PRINT_BAND_PX
                printing.PRINT_BAND_PX = band_px
                try:
                    printing.paint_page(painter, doc[0], target)
                finally:
                    printing.PRINT_BAND_PX = keep
                    painter.end(); doc.close()
                return canvas

            one, many = render(10 ** 9), render(120_000)      # 1 band vs many
            worst = 0
            for y in range(one.height()):
                a, b = bytes(one.constScanLine(y)), bytes(many.constScanLine(y))
                if a != b:
                    worst = max(worst, max(abs(p - q) for p, q in zip(a, b)))
            if rot == 0:
                # banding must be completely invisible: the same pixels as a
                # single full-page render
                self.assertEqual(worst, 0, "banding changed the page")
            else:
                # a rotated page rasterises its (now vertical) lines with a
                # slightly different antialiasing phase per band; that is spread
                # over the whole band, not at the joins. A gap or a misplaced
                # band would instead leave white on black — a huge delta.
                self.assertLess(worst, 40, f"visible seam at rotation {rot}")

    @needs_native_print
    def test_print_to_pdf_printer_emits_all_pages(self):
        win, tmp = self._win_with(pages=3)
        out = os.path.join(tmp, "out.pdf")
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(out)
        printing.paint_document(win.document, printer, win.print_options)
        self.assertTrue(os.path.exists(out) and os.path.getsize(out) > 0)
        chk = fitz.open(out)
        try:
            self.assertEqual(chk.page_count, 3)
        finally:
            chk.close()

    @needs_native_print
    def test_print_to_honours_page_range(self):
        win, tmp = self._win_with(pages=4)
        out = os.path.join(tmp, "range.pdf")
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(out)
        printer.setFromTo(2, 3)          # print only pages 2–3
        printing.paint_document(win.document, printer, win.print_options)
        chk = fitz.open(out)
        try:
            self.assertEqual(chk.page_count, 2)
        finally:
            chk.close()

    def test_preview_raster_is_capped(self):
        # The preview dialog paints *every* page into a stored QPicture and keeps
        # them all, so rasterising there at the printer's real resolution held
        # the whole document in memory (~160 MB per page at 600 dpi). The preview
        # only shows a scaled-down page, so its raster is capped — while a real
        # print of the same page stays at full device resolution.
        from PySide6.QtGui import QPainter, QPicture
        from PySide6.QtCore import QRect
        win, tmp = self._win_with(pages=1)
        captured = []
        orig = fitz.Page.get_pixmap

        def spy(page, *a, **k):
            m = k.get("matrix")
            captured.append((m.a if m is not None else 1.0,
                             float(page.rect.width), float(page.rect.height)))
            return orig(page, *a, **k)

        # a dpi cap alone still scales with the paper, so check a big sheet too
        for label, (W, H) in (("letter", (612, 792)), ("esize", (2448, 3168))):
            src = os.path.join(tmp, f"prev_{label}.pdf")
            d = fitz.open(); d.new_page(width=W, height=H)
            d.save(src); d.close()
            win.load_document(src)
            target = QRect(0, 0, int(W / 72 * 600), int(H / 72 * 600))
            work = win.document.annotated_fitz()
            captured.clear()
            fitz.Page.get_pixmap = spy
            try:
                pic = QPicture()                   # what the preview paints into
                painter = QPainter(pic)
                try:
                    printing.paint_page(painter, work[0], target)
                finally:
                    painter.end()
            finally:
                fitz.Page.get_pixmap = orig
                work.close()

            self.assertEqual(len(captured), 1,
                             f"{label}: preview must be a single raster")
            scale, pw, ph = captured[0]
            self.assertLessEqual(scale, printing.PREVIEW_SCALE + 1e-9,
                                 f"{label}: preview exceeded its dpi cap")
            self.assertLessEqual((pw * scale) * (ph * scale),
                                 printing.PREVIEW_MAX_PX * 1.02,
                                 f"{label}: preview exceeded its pixel budget")
        # the big sheet must be the case where the pixel budget, not the dpi cap,
        # is what bites — otherwise this test isn't checking anything new
        self.assertLess(captured[0][0], printing.PREVIEW_SCALE)

    def test_preview_is_detected_from_the_paint_engine(self):
        # _print_page decides which path to take from the painter's engine:
        # QPicture-backed means the preview dialog, anything else is a printer.
        from PySide6.QtGui import QImage, QPainter, QPicture
        win, _ = self._win_with(pages=1)
        pic = QPicture()
        p = QPainter(pic)
        try:
            self.assertTrue(printing.is_preview(p))
        finally:
            p.end()
        img = QImage(50, 50, QImage.Format_RGB888)
        p = QPainter(img)
        try:
            self.assertFalse(printing.is_preview(p))
        finally:
            p.end()

    @needs_native_print
    def test_progress_is_reported_per_page(self):
        win, tmp = self._win_with(pages=3)
        out = os.path.join(tmp, "prog.pdf")
        printer = QPrinter(QPrinter.ScreenResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(out)
        seen = []
        painted = printing.paint_document(win.document, printer, win.print_options, on_page=lambda d, t: (seen.append((d, t))
                                                              or True))
        self.assertEqual(seen, [(0, 3), (1, 3), (2, 3)])
        self.assertEqual(painted, 3)

    @needs_native_print
    def test_cancelling_stops_the_job_early(self):
        # returning False from the progress callback (the user hit Cancel) must
        # stop cleanly, leaving only the pages printed so far
        win, tmp = self._win_with(pages=4)
        out = os.path.join(tmp, "cancel.pdf")
        printer = QPrinter(QPrinter.ScreenResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(out)
        painted = printing.paint_document(win.document, printer, win.print_options, on_page=lambda d, t: d < 2)
        self.assertEqual(painted, 2)
        chk = fitz.open(out)
        try:
            self.assertEqual(chk.page_count, 2)
        finally:
            chk.close()

    @needs_native_print
    def test_cancelling_before_the_first_page_prints_nothing(self):
        # Starting a QPainter on a printer and ending it without painting still
        # emits a sheet, so cancelling at page 1 used to waste a blank page.
        win, tmp = self._win_with(pages=3)
        out = os.path.join(tmp, "cancel0.pdf")
        printer = QPrinter(QPrinter.ScreenResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(out)
        painted = printing.paint_document(win.document, printer, win.print_options, on_page=lambda d, t: False)
        self.assertEqual(painted, 0)
        if os.path.exists(out) and os.path.getsize(out):
            chk = fitz.open(out)
            try:
                self.assertEqual(chk.page_count, 0, "a blank sheet was printed")
            finally:
                chk.close()

    @needs_native_print
    def test_progress_total_follows_the_page_range(self):
        win, tmp = self._win_with(pages=5)
        out = os.path.join(tmp, "range_prog.pdf")
        printer = QPrinter(QPrinter.ScreenResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(out)
        printer.setFromTo(2, 4)
        totals = []
        printing.paint_document(win.document, printer, win.print_options, on_page=lambda d, t: (totals.append(t) or True))
        self.assertEqual(totals, [3, 3, 3])

    def test_render_dpi_uses_the_device_not_the_viewport(self):
        # On Windows the Win32 print engine pins the paint viewport to the
        # screen's 96 dpi whatever setResolution() asked for, so the render
        # dpi must come from the device's physical resolution instead —
        # measured from a real Microsoft Print to PDF export that came out at
        # exactly 96 dpi on a 17x11 sheet.
        from app.main_window import MainWindow

        class Fake:
            def __init__(self, logical, phys):
                self._l, self._p = logical, phys
            def resolution(self): return self._l
            def physicalDpiX(self): return self._p
            def physicalDpiY(self): return self._p

        dpi = printing.render_dpi
        self.assertEqual(dpi(Fake(96, 600)), 600)     # the Windows situation
        self.assertEqual(dpi(Fake(96, 1200)), 1200)   # high-res driver
        self.assertEqual(dpi(Fake(96, 0)), 600)       # unknown device: floor
        self.assertEqual(dpi(Fake(96, 2400)), 1200)   # photo driver: cap
        # engines that honour the logical resolution render 1:1 with it; the
        # Qt PDF engine claims a flat 1200 physical, which must NOT win here
        self.assertEqual(dpi(Fake(600, 1200)), 600)
        self.assertEqual(dpi(Fake(1200, 1200)), 1200)

    @needs_native_print
    def test_screen_resolution_viewport_still_prints_at_device_dpi(self):
        # End-to-end regression for the Windows blur: a printer whose logical
        # viewport is screen resolution but whose device is 600 dpi must still
        # place a ~600 dpi raster on the sheet — not a 96 dpi one stretched.
        class ScreenPinned(QPrinter):
            def __init__(self):
                super().__init__(QPrinter.ScreenResolution)
                self.setResolution(96)          # what Windows paints at
            def physicalDpiX(self): return 600  # what the device can do
            def physicalDpiY(self): return 600

        win, tmp = self._win_with(pages=1)
        out = os.path.join(tmp, "winlike.pdf")
        printer = ScreenPinned()
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(out)
        printing.paint_document(win.document, printer, win.print_options)
        chk = fitz.open(out)
        try:
            infos = chk[0].get_image_info()
            self.assertTrue(infos, "no raster was placed on the page")
            im = max(infos, key=lambda i: i["width"] * i["height"])
            bb = fitz.Rect(im["bbox"])
            effective_dpi = im["width"] / (bb.width / 72.0)
            self.assertGreater(effective_dpi, 550)     # was exactly 96
            # and the page still fills the sheet rather than shrinking
            page_rect = chk[0].rect
            self.assertGreater(bb.width / page_rect.width, 0.5)
        finally:
            chk.close()

    def test_bands_join_when_raster_outruns_the_viewport(self):
        # The scaled path (device dpi above the logical viewport, i.e. the
        # Windows fix): banded output must match a single-shot render of the
        # same page. Band placement uses shared-edge float rects, so a band
        # shifted by even one raster row would blow these thresholds apart.
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QImage, QPainter
        from app.main_window import MainWindow
        win, tmp = self._win_with(pages=1)
        src = os.path.join(tmp, "dense.pdf")
        d = fitz.open(); pg = d.new_page(width=612, height=792)
        for i in range(0, 780, 3):              # dense: any seam would show
            pg.draw_line((20, i), (592, i + 2), width=0.3)
        d.save(src); d.close()

        def render(band_px):
            doc = fitz.open(src)
            target = QRect(0, 0, 768, 994)      # a 96 dpi Letter viewport
            canvas = QImage(768, 994, QImage.Format_RGB888)
            canvas.fill(0xFFFFFFFF)
            painter = QPainter(canvas)
            keep = printing.PRINT_BAND_PX
            printing.PRINT_BAND_PX = band_px
            try:
                printing.paint_page(painter, doc[0], target, dpi=600)
            finally:
                printing.PRINT_BAND_PX = keep
                painter.end(); doc.close()
            return canvas

        one, many = render(10 ** 9), render(400_000)
        worst_row = 0
        total = 0
        for y in range(one.height()):
            a, b = bytes(one.constScanLine(y)), bytes(many.constScanLine(y))
            if a != b:
                deltas = [abs(p - q) for p, q in zip(a, b)]
                worst_row = max(worst_row, sum(deltas) / len(deltas))
                total += sum(deltas)
        mean = total / (one.height() * one.width() * 3)
        self.assertLess(mean, 2.0, "banded render diverged from single-shot")
        self.assertLess(worst_row, 30.0, "a band is visibly out of place")

    # -- minimum line weight -------------------------------------------------

    @staticmethod
    def _hairline_px(path, dpi=600):
        """Thickness in device px of the single hairline in a probe PDF."""
        import numpy as np
        doc = fitz.open(path)
        try:
            pm = doc[0].get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72),
                                   alpha=False)
            a = np.frombuffer(pm.samples, dtype=np.uint8)
            a = a.reshape(pm.height, pm.width, 3).mean(axis=2)
        finally:
            doc.close()
        return int((a[:, a.shape[1] // 2] < 200).sum())

    def _hairline_pdf(self, tmp, name="hair.pdf"):
        # width 0.12 pt: a real hairline. (Note width=0.0 in PyMuPDF means the
        # *default* 1 pt, not a hairline — it would mask the whole effect.)
        p = os.path.join(tmp, name)
        d = fitz.open(); pg = d.new_page(width=612, height=792)
        pg.draw_line((72, 300), (540, 300), width=0.12)
        pg.insert_text((72, 500), "WIRE 300801", fontsize=5)
        d.save(p); d.close()
        return p

    def test_min_line_width_thickens_only_below_the_floor(self):
        # The floor lifts hairlines and leaves heavier geometry alone.
        from app.main_window import MainWindow
        tmp = tempfile.mkdtemp()
        p = os.path.join(tmp, "mixed.pdf")
        d = fitz.open(); pg = d.new_page(width=612, height=792)
        pg.draw_line((72, 200), (540, 200), width=0.12)   # hairline
        pg.draw_line((72, 400), (540, 400), width=2.0)    # already heavy
        d.save(p); d.close()

        def widths():
            import numpy as np
            doc = fitz.open(p)
            try:
                pm = doc[0].get_pixmap(matrix=fitz.Matrix(600 / 72, 600 / 72),
                                       alpha=False)
                a = np.frombuffer(pm.samples, dtype=np.uint8)
                a = a.reshape(pm.height, pm.width, 3).mean(axis=2)
            finally:
                doc.close()
            col = a[:, a.shape[1] // 2] < 200
            runs, n = [], 0
            for v in col:
                if v:
                    n += 1
                elif n:
                    runs.append(n); n = 0
            if n:
                runs.append(n)
            return runs

        plain = widths()
        with printing.min_line_width(0.75 / 72 * 600):     # Heavy, in px
            boosted = widths()
        self.assertEqual(len(plain), len(boosted))
        self.assertGreater(boosted[0], plain[0], "hairline was not thickened")
        self.assertEqual(boosted[1], plain[1], "heavy line must be untouched")

    def test_min_line_width_leaves_text_alone(self):
        # Thickening strokes must not blob small title-block text.
        import numpy as np
        from app.main_window import MainWindow
        tmp = tempfile.mkdtemp()
        p = self._hairline_pdf(tmp)

        def text_ink():
            doc = fitz.open(p)
            try:
                pm = doc[0].get_pixmap(matrix=fitz.Matrix(600 / 72, 600 / 72),
                                       alpha=False)
                a = np.frombuffer(pm.samples, dtype=np.uint8)
                a = a.reshape(pm.height, pm.width, 3).mean(axis=2)
            finally:
                doc.close()
            band = a[int(492 / 72 * 600):int(504 / 72 * 600)]
            return int((band < 128).sum())

        plain = text_ink()
        with printing.min_line_width(0.75 / 72 * 600):
            self.assertEqual(text_ink(), plain)

    def test_min_line_width_is_always_restored(self):
        # It is a *global* MuPDF setting: leaking it would silently thicken the
        # on-screen viewer too, so it must be restored even when rendering
        # raises.
        from app.main_window import MainWindow
        tmp = tempfile.mkdtemp()
        p = self._hairline_pdf(tmp)
        before = self._hairline_px(p)

        with printing.min_line_width(0.75 / 72 * 600):
            self.assertGreater(self._hairline_px(p), before)
        self.assertEqual(self._hairline_px(p), before)

        class Boom(Exception):
            pass

        with self.assertRaises(Boom):
            with printing.min_line_width(0.75 / 72 * 600):
                raise Boom()
        self.assertEqual(self._hairline_px(p), before,
                         "the global floor leaked after an exception")

    def test_zero_min_line_width_is_a_no_op(self):
        from app.main_window import MainWindow
        tmp = tempfile.mkdtemp()
        p = self._hairline_pdf(tmp)
        before = self._hairline_px(p)
        for value in (0, 0.0, None):
            with printing.min_line_width(value):
                self.assertEqual(self._hairline_px(p), before)

    @needs_native_print
    def test_printing_applies_the_line_weight_floor(self):
        # End to end: the same page printed Heavy carries more ink than printed
        # as drawn, and the floor scales with the render dpi rather than being
        # a fixed pixel count.
        import numpy as np
        tmp = tempfile.mkdtemp()
        src = self._hairline_pdf(tmp)
        from app.main_window import MainWindow
        win = MainWindow(); win.load_document(src)

        def ink(min_pt):
            win.print_options.min_line_pt = min_pt
            out = os.path.join(tmp, f"out{min_pt}.pdf")
            pr = QPrinter(QPrinter.ScreenResolution)
            pr.setResolution(600)
            pr.setOutputFormat(QPrinter.PdfFormat)
            pr.setOutputFileName(out)
            printing.paint_document(win.document, pr, win.print_options)
            doc = fitz.open(out)
            try:
                pm = doc[0].get_pixmap(matrix=fitz.Matrix(300 / 72, 300 / 72),
                                       alpha=False)
                a = np.frombuffer(pm.samples, dtype=np.uint8)
                a = a.reshape(pm.height, pm.width, 3).mean(axis=2)
            finally:
                doc.close()
            return int((a < 200).sum())

        as_drawn = ink(0.0)
        medium = ink(0.5)
        heavy = ink(0.75)
        self.assertGreater(medium, as_drawn, "Medium added no ink")
        self.assertGreater(heavy, medium, "Heavy is not heavier than Medium")

    @needs_native_print
    def test_new_printer_avoids_highres_query(self):
        # HighResolution (1200 dpi) queries the printer at construction and can
        # hang; _new_printer builds a ScreenResolution printer raised to a
        # working 600 dpi (fine line work and small text print crisply).
        win, _ = self._win_with(pages=1)
        p = printing.new_printer(win.document.path)
        self.assertEqual(p.resolution(), 600)

    @needs_native_print
    def test_print_document_prints_via_native_dialog(self):
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        win, tmp = self._win_with(pages=2)
        out = os.path.join(tmp, "native.pdf")

        def fake_exec(dlg):
            dlg.printer().setOutputFormat(QPrinter.PdfFormat)
            dlg.printer().setOutputFileName(out)
            return QPrintDialog.Accepted

        from unittest import mock
        with mock.patch.object(QPrintDialog, "exec", fake_exec):
            win.print_document()
        self.assertTrue(os.path.exists(out) and os.path.getsize(out) > 0)
        chk = fitz.open(out)
        try:
            self.assertEqual(chk.page_count, 2)
        finally:
            chk.close()

    @needs_native_print
    def test_print_document_cancelled_prints_nothing(self):
        from PySide6.QtPrintSupport import QPrintDialog
        win, tmp = self._win_with(pages=1)
        from unittest import mock
        with mock.patch.object(QPrintDialog, "exec",
                               lambda d: QPrintDialog.Rejected):
            win.print_document()   # must simply return, no exception

    def test_the_window_hands_the_job_its_own_document_and_options(self):
        """Both wrappers pass what the window owns, and nothing else.

        Found by falsification: replacing `self.print_options` with `None` in
        `print_preview` fired NOTHING, because no test drove that wrapper at
        all — the preview's own controls are exercised directly against the
        module. The two menu actions are the window's whole remaining half of
        printing, so the wiring is what has to be checked here; the dialogs
        themselves are `app/printing.py`'s and are tested there.
        """
        from unittest import mock
        from app import printing as P
        win, _ = self._win_with(pages=1)
        for wrapper, target in (("print_document", "run_print_dialog"),
                                ("print_preview", "run_print_preview")):
            seen = []
            with mock.patch.object(
                    P, target,
                    lambda *a, **k: seen.append(a) or "printed 1 page"):
                getattr(win, wrapper)()
            self.assertEqual(len(seen), 1, wrapper)
            parent, doc, opts = seen[0]
            self.assertIs(parent, win, wrapper)
            self.assertIs(doc, win.document, wrapper)
            self.assertIs(opts, win.print_options, wrapper)

    def test_the_preview_line_weight_picker_writes_what_the_job_reads(self):
        """The picker's other half — and it was untested until falsification.

        `options.min_line_pt = …` in `_add_line_weight_picker` could be
        deleted with every test still green: the weight tests set the option
        directly and paint with it, so what was covered was the JOB reading it
        and never the control writing it. The markups toggle beside it had
        both halves; this one had one.
        """
        from PySide6.QtWidgets import QComboBox, QToolBar
        from app import printing as P
        from app.config import PRINT_LINE_WEIGHTS
        win, _ = self._win_with(pages=1)
        # A plain toolbar rather than a QPrintPreviewDialog: the picker only
        # needs something to add itself to, and the preview dialog is the part
        # `needs_native_print` exists to keep off the Windows runner.
        tb = QToolBar()
        P._add_line_weight_picker(tb, tb, win.print_options)
        combo = tb.findChild(QComboBox)
        self.assertIsNotNone(combo)
        # Pick an entry that is not the one it opened on, so a picker that
        # wrote nothing cannot pass by accident.
        want = next(i for i in range(combo.count())
                    if float(combo.itemData(i) or 0.0)
                    != win.print_options.min_line_pt)
        combo.setCurrentIndex(want)
        self.assertEqual(win.print_options.min_line_pt,
                         float(PRINT_LINE_WEIGHTS[want][1]))

    def test_include_marks_defaults_on(self):
        win, _ = self._win_with(pages=1)
        self.assertTrue(win.print_options.include_marks)

    @needs_native_print
    def test_preview_toggle_flips_include_marks(self):
        from PySide6.QtPrintSupport import QPrintPreviewDialog
        from PySide6.QtGui import QAction
        win, _ = self._win_with(pages=1)
        printer = printing.new_printer(win.document.path)
        preview = QPrintPreviewDialog(printer, win)
        printing._add_markups_toggle(preview, win.print_options)
        act = next((a for a in preview.findChildren(QAction)
                    if a.text() == "Include markups"), None)
        self.assertIsNotNone(act)
        self.assertTrue(act.isChecked())            # default on
        act.trigger()                                # uncheck it
        self.assertFalse(win.print_options.include_marks)
        act.trigger()                                # back on
        self.assertTrue(win.print_options.include_marks)

    @needs_native_print
    def test_print_clean_when_marks_off(self):
        # printing with marks off must still emit all pages (just no app marks)
        from PySide6.QtPrintSupport import QPrinter
        win, tmp = self._win_with(pages=2)
        win.print_options.include_marks = False
        out = os.path.join(tmp, "clean.pdf")
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(out)
        printing.paint_document(win.document, printer, win.print_options)
        chk = fitz.open(out)
        try:
            self.assertEqual(chk.page_count, 2)
        finally:
            chk.close()

    def test_print_action_enabled_with_document(self):
        win, _ = self._win_with(pages=1)
        self.assertTrue(win.act_print.isEnabled())

    def test_print_action_disabled_without_document(self):
        from app.main_window import MainWindow
        win = MainWindow()
        self.assertFalse(win.act_print.isEnabled())


if __name__ == "__main__":
    unittest.main()
