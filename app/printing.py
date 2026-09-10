"""Printing a drawing set: the printer, the dialogs, and the page raster.

Lifted out of `app/main_window.py`, which held it as nine methods and four
class constants. Printing is a **subject**, not a property of being a window —
the same argument that moved the four dialogs out one commit earlier, and the
one `app/tools/dialogs.py` was already following.

What is here is the whole of it: how a `QPrinter` is built (and why not in
HighResolution mode), what dpi a job rasterises at (and why never from the
paint viewport), how one page is fitted, banded and drawn, and the two dialogs
a person reaches it through. The window keeps the two menu actions and the
document; it no longer knows what a printer is.

**The functions take what they need rather than reading a window.** Every one
of the nine either was already `@staticmethod`/`@classmethod` or touched
`self` only for `document` and the two print settings — measured before the
cut — so the conversion is a parameter list rather than a redesign, and the
pure half (`fit`, `render_dpi`, `paint_page`) is callable with no Qt window at
all, which is what `tests/test_v12_print.py` has always driven it as.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass

# One rasterised band is capped at this many pixels, so peak memory stays
# bounded no matter how big the sheet or how high the driver's dpi — an
# E-size plot at 1200 dpi would otherwise be a single ~6 GB bitmap. Two
# bitmaps of a band are live at once (the pixmap, and the trimmed copy handed
# to the painter), so 24 Mpx costs ~145 MB while a band is being drawn.
PRINT_BAND_PX = 24_000_000

# Device pixels per PDF point for the *preview* raster (~150 dpi). The
# preview dialog paints every page into a stored QPicture and keeps them all
# at once, so rasterising there at the printer's real resolution would hold
# the whole document in memory (a 6-page preview at 600 dpi already costs
# ~1 GB). The preview only ever shows a scaled-down page, so it doesn't need
# print resolution; the real print is unaffected.
PREVIEW_SCALE = 150 / 72.0

# ...and never more than this many pixels for one previewed page, whatever
# the sheet size. A dpi cap alone still scales with the paper: an E-size
# sheet at 150 dpi is 34 Mpx, so a preview of a large-format set would still
# retain ~145 MB per page. The preview is only ever shown scaled down.
PREVIEW_MAX_PX = 4_000_000

# Device rows rendered past each end of a band and then trimmed off, so no
# kept row was antialiased against the edge of the band's clip. At this
# depth a banded page comes out identical to a single full-page render.
BAND_MARGIN = 16


@dataclass
class PrintOptions:
    """What the print-preview toolbar can change, and the job reads.

    A small mutable holder rather than two attributes on the window, because
    the preview's two controls write them and `paint_document` reads them —
    and with the code out of the window there is nowhere else for that pair to
    live. `min_line_pt` starts from `AppConfig.print_min_line_pt`; the preview
    changes it for the job in hand and Settings holds the default for next
    time, which is the split the picker's own docstring describes.
    """

    include_marks: bool = True
    min_line_pt: float = 0.0


def new_printer(doc_path):
    """Create a QPrinter for printing the drawing.

    Built in **ScreenResolution** mode on purpose: HighResolution queries the
    default printer's capabilities at construction, which on Windows pops a
    blocking "contacting printer…" dialog (and hangs on a slow/offline
    network printer) before the user can do anything. ScreenResolution
    doesn't contact the printer; we then raise the logical DPI so the output
    still prints at a decent resolution.

    setResolution(600) sets the *logical* coordinate space to the 600 dpi
    working resolution where the engine honours it (Qt's PDF and CUPS
    engines do). The raster resolution itself is chosen per job by
    ``render_dpi`` — on Windows the Win32 engine ignores this call
    for paint metrics and pins the viewport to screen dpi, which is why
    the render dpi must never be derived from the viewport.
    """
    from PySide6.QtPrintSupport import QPrinter
    printer = QPrinter(QPrinter.ScreenResolution)
    printer.setResolution(600)
    printer.setDocName(os.path.basename(doc_path))
    return printer


def run_print_dialog(parent, document, options):
    """Print the drawing (with its marks) straight through the system print
    dialog — the standard Windows printer popup: pick the printer, copies,
    orientation and page range, then print. (Use Print preview… to see the
    pages first.)

    Returns the message the caller should show, or None when there is nothing
    to say (no document, or the print dialog was cancelled). **The status bar
    is the window's**, so this hands back a sentence rather than reaching for
    one: a printing module that knew which widget has a status bar would be
    the window's business back in here under another name.
    """
    if document is None:
        return None
    from PySide6.QtPrintSupport import QPrintDialog
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox
    printer = new_printer(document.path)
    dlg = QPrintDialog(printer, parent)
    dlg.setWindowTitle("Print")
    if document.page_count:
        dlg.setMinMax(1, document.page_count)
        dlg.setOption(QPrintDialog.PrintPageRange, True)
    if dlg.exec() != QPrintDialog.Accepted:
        return None
    # Rendering a full 600 dpi page is what makes the output sharp, but it
    # also costs about a second a page — long enough for a multi-sheet set
    # to look like the app has locked up. Show progress (and let it be
    # cancelled) instead of freezing.
    from PySide6.QtWidgets import QProgressDialog
    progress = QProgressDialog("Printing…", "Cancel", 0, 1, parent)
    progress.setWindowTitle("Printing")
    progress.setWindowModality(Qt.WindowModal)
    progress.setMinimumDuration(800)     # no flash for a quick one-pager

    def on_page(done, total):
        progress.setMaximum(total)
        progress.setValue(done)
        progress.setLabelText(
            f"Printing page {min(done + 1, total)} of {total}…")
        QApplication.processEvents()
        return not progress.wasCanceled()

    try:
        pages = paint_document(document, printer, options, on_page=on_page)
        if progress.wasCanceled():
            return "Printing cancelled"
        return (f"Sent {pages} page{'' if pages == 1 else 's'} to "
                f"{printer.printerName() or 'printer'}")
    except Exception as e:
        QMessageBox.warning(parent, "Print failed", str(e))
        return None
    finally:
        progress.close()


def run_print_preview(parent, document, options):
    """Optional: show the pages in a preview window, then print from there."""
    if document is None:
        return
    from PySide6.QtPrintSupport import QPrintPreviewDialog
    from PySide6.QtWidgets import QMessageBox
    try:
        printer = new_printer(document.path)
        preview = QPrintPreviewDialog(printer, parent)
        preview.setWindowTitle("Print preview")
        preview.resize(1000, 800)
        preview.paintRequested.connect(
            lambda pr: paint_document(document, pr, options))
        _add_markups_toggle(preview, options)
        preview.exec()
    except Exception as e:
        QMessageBox.warning(parent, "Print failed", str(e))


def _add_markups_toggle(preview, options):
    """Add an 'Include markups' checkbox to the print-preview toolbar so the
    user can print the clean drawing or the drawing with the app's marks.
    Defaults to on (marks included)."""
    from PySide6.QtWidgets import QToolBar
    from PySide6.QtPrintSupport import QPrintPreviewWidget
    tb = preview.findChild(QToolBar)
    if tb is None:
        return
    act = tb.addAction("Include markups")
    act.setCheckable(True)
    act.setChecked(options.include_marks)
    act.setToolTip("Print the marks/notes you added on top of the drawing; "
                   "uncheck to print the clean drawing.")

    def _toggle(on):
        options.include_marks = on
        pv = preview.findChild(QPrintPreviewWidget)
        if pv is not None:
            pv.updatePreview()   # re-render with/without marks

    act.toggled.connect(_toggle)
    _add_line_weight_picker(preview, tb, options)


def _add_line_weight_picker(preview, tb, options):
    """Add a minimum line-weight picker to the print-preview toolbar.

    Preview is where you actually judge line weight, so the control lives
    here as well as in Settings. Changing it re-renders immediately and
    applies to the job printed from the preview; Settings holds the
    default for next time.

    **Nothing keeps a reference to the combo, and that is measured rather
    than assumed.** The window used to store it as `_preview_weight_combo`,
    assigned once and read nowhere — a write-only attribute. Driven under Qt:
    a combo added with `QToolBar.addWidget` and dropped on the Python side
    survives a `gc.collect()` and is still usable through
    `widgetForAction`, because the toolbar takes ownership; the `_changed`
    closure holds it too. So the attribute bought nothing and it did not
    travel with the code.
    """
    from PySide6.QtWidgets import QComboBox, QLabel
    from PySide6.QtPrintSupport import QPrintPreviewWidget
    from .config import PRINT_LINE_WEIGHTS
    tb.addSeparator()
    tb.addWidget(QLabel(" Min line: "))
    combo = QComboBox()
    for label, pt in PRINT_LINE_WEIGHTS:
        combo.addItem(label, pt)
    current = min(range(len(PRINT_LINE_WEIGHTS)),
                  key=lambda i: abs(PRINT_LINE_WEIGHTS[i][1]
                                    - options.min_line_pt))
    combo.setCurrentIndex(current)
    combo.setToolTip(
        "Thicken hairlines to at least this weight when printing.\n"
        "Heavier geometry and all text are left exactly as drawn.")

    def _changed(i):
        options.min_line_pt = float(combo.itemData(i) or 0.0)
        pv = preview.findChild(QPrintPreviewWidget)
        if pv is not None:
            pv.updatePreview()

    combo.currentIndexChanged.connect(_changed)
    tb.addWidget(combo)


def paint_document(document, printer, options=None, on_page=None):
    """Paint each requested page onto ``printer``, fitted and centred on the
    sheet. Includes the app's markups unless ``options.include_marks`` is off
    (the print-preview toggle). Kept separate from the dialog so it can be
    unit-tested against a PDF-output printer.

    ``on_page(done, total)`` is called before each page if given; returning
    False stops the job (the user cancelled). Returns the number of pages
    actually painted.

    ``options`` defaults to a fresh `PrintOptions` — marks in, no weight
    floor — which is what a caller that has never opened the preview means.
    """
    from PySide6.QtGui import QPainter
    if options is None:
        options = PrintOptions()
    work = document.annotated_fitz(with_marks=options.include_marks)
    try:
        first = printer.fromPage() or 1
        last = printer.toPage() or work.page_count
        first = max(1, first)
        last = min(work.page_count, last)
        total = max(0, last - first + 1)
        done = 0
        # The painter is created only once a page is actually going to be
        # drawn: starting one and ending it without painting still emits a
        # sheet, so cancelling at the first page would waste a blank page.
        painter = None
        try:
            for n, i in enumerate(range(first - 1, last)):
                if on_page is not None and not on_page(n, total):
                    break
                if painter is None:
                    painter = QPainter(printer)
                    dpi = render_dpi(printer)
                elif done:
                    printer.newPage()
                paint_page(painter, work[i], painter.viewport(),
                           dpi=dpi, min_line_pt=options.min_line_pt)
                done += 1
        finally:
            if painter is not None:
                painter.end()
        return done
    finally:
        work.close()


def render_dpi(printer) -> int:
    """The dpi pages are rasterised at for this print job.

    Never inferred from the paint viewport. On Windows the Win32 print
    engine in ScreenResolution mode pins the painter's logical metrics to
    the *screen* dpi (96) no matter what setResolution() asked for — that
    call only reaches the driver's DEVMODE — so "render 1:1 with the
    viewport" faithfully produced 96 dpi pages that GDI then stretched
    ~6x onto the sheet. Verified from a Microsoft Print to PDF export:
    one 1573x1018 raster on a 17x11 sheet, exactly 96 dpi.

    The device's *physical* dpi is the printer DC's true resolution in
    every mode, so render at that — floored at the app's 600 dpi working
    resolution, and bounded so a 2400 dpi photo driver can't demand an
    absurd raster.
    """
    phys = logical = 0
    try:
        phys = max(int(printer.physicalDpiX() or 0),
                   int(printer.physicalDpiY() or 0))
    except Exception:
        pass
    try:
        logical = int(printer.resolution() or 0)
    except Exception:
        pass
    if logical >= 600:
        # the engine honours the working resolution (Qt's PDF/CUPS path):
        # render 1:1 with it. Don't chase phys here — Qt's PDF engine
        # reports a flat 1200 dpi physical whatever was asked for, which
        # would quadruple every spool for no visible gain.
        return min(logical, 1200)
    # a low logical resolution is the screen-pinned Windows viewport:
    # take the device's own dpi, floored at the 600 working resolution
    return max(600, min(phys, 1200))


@contextlib.contextmanager
def min_line_width(px):
    """Raise MuPDF's minimum stroke width to ``px`` device pixels.

    AutoCAD plots schematic geometry as hairlines, which a renderer draws
    one device pixel wide — 1/96 in at the screen resolution the old print
    path really used, but only 1/600 in once pages are rendered at the
    printer's own dpi. True to the file, far too thin on paper. This lifts
    anything below the floor and leaves heavier geometry (and all text)
    exactly as drawn.

    The setting is *global* to MuPDF, so it is always restored — leaking it
    would silently thicken the on-screen viewer as well.
    """
    import fitz
    if not px or px <= 0:
        yield
        return
    try:
        fitz.TOOLS.set_graphics_min_line_width(float(px))
        yield
    finally:
        fitz.TOOLS.set_graphics_min_line_width(0.0)


def is_preview(painter):
    """True when painting into the print-preview dialog rather than onto a
    real printer — the preview backs its pages with QPicture."""
    from PySide6.QtGui import QPaintEngine
    try:
        eng = painter.paintEngine()
        return eng is not None and eng.type() == QPaintEngine.Picture
    except Exception:
        return False


def fit(rect, target):
    """Where one page lands on the sheet: ``(scale, w, h, x, y)`` in device
    pixels, fitted to ``target`` without distortion and centred on it."""
    pw = max(1.0, float(rect.width))
    ph = max(1.0, float(rect.height))
    scale = min(target.width() / pw, target.height() / ph)
    w = max(1, int(round(pw * scale)))
    h = max(1, int(round(ph * scale)))
    return (scale, w, h,
            int(round((target.width() - w) / 2.0)),
            int(round((target.height() - h) / 2.0)))


def paint_page(painter, page, target, dpi=None, min_line_pt=0.0):
    """Draw one page (with its marks) onto the printer's viewport.

    The page is rasterised at ``dpi`` (see ``render_dpi``) and drawn
    into the *logical* target rect. The two are deliberately decoupled: the
    raster carries the detail, the logical rect only says where it lands,
    and the print engine passes the full-resolution pixels through — the
    PDF engine embeds them, GDI stretches them in device space at the
    driver's real resolution. Sizing the raster to the paint viewport
    instead is what silently produced 96 dpi prints on Windows, where the
    viewport is screen-resolution whatever the device can do.

    With ``dpi=None`` the raster simply matches the logical rect pixel for
    pixel. Tall pages are rasterised in horizontal bands so the peak
    bitmap stays bounded (see ``PRINT_BAND_PX``) at no resolution cost.

    ``min_line_pt`` raises hairlines to that weight in PDF points (see
    ``PRINT_LINE_WEIGHTS``). It is a floor, not a multiplier: geometry
    already heavier is untouched, and text is never affected.
    """
    import fitz
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtCore import QRectF
    r = page.rect
    scale, w, h, x0, y0 = fit(r, target)
    if scale <= 0:
        # No printable area at all — exotic paper, or margins wider than the
        # sheet. There is nothing to draw, and going on would divide by the
        # scale when clipping bands.
        return

    if is_preview(painter):
        area = max(1.0, float(r.width) * float(r.height))
        pscale = min(scale, PREVIEW_SCALE, (PREVIEW_MAX_PX / area) ** 0.5)
        if pscale < scale:
            # a single modest raster, drawn up to the full sheet size.
            # The floor is scaled to *this* raster so the preview shows the
            # same relative weight the print will have.
            with min_line_width(min_line_pt * pscale):
                pm = page.get_pixmap(matrix=fitz.Matrix(pscale, pscale),
                                     alpha=False, annots=True)
            # samples_mv is a view on the pixmap; copy() owns its pixels, so
            # the image outlives pm without duplicating the buffer twice
            img = QImage(pm.samples_mv, pm.width, pm.height, pm.stride,
                         QImage.Format_RGB888).copy()
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.drawImage(QRectF(x0, y0, w, h), img)
            return

    # raster pixels per PDF point: enough that the page lands on paper at
    # ``dpi``, independent of the viewport's own (possibly screen) density
    logical = 0
    try:
        logical = int(painter.device().logicalDpiX() or 0)
    except Exception:
        pass
    if dpi and logical > 0:
        s = scale * float(dpi) / float(logical)
    else:
        s = scale                     # raster == logical px
    mat = fitz.Matrix(s, s)
    origin = (r * mat).irect          # where the whole page starts, scaled
    W = max(1, origin.width)
    H = max(1, origin.height)
    ratio = h / float(H)              # logical units per raster row
    band_rows = max(1, min(H, int(PRINT_BAND_PX // W)))
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    y = 0
    # ``s`` is raster px per PDF point, so this converts the weight floor
    # from points into the device pixels MuPDF wants
    with min_line_width(min_line_pt * s):
        while y < H:
            rows = min(band_rows, H - y)
            # Render a few rows beyond the band and then throw them away. The
            # renderer antialiases against the edge of the clip, so a row sitting
            # right on a band boundary comes out lighter than it should — which
            # would print as a faint line across the sheet at every join. Only
            # rows well inside the clip are kept, so every row is rendered
            # exactly as it would be in a single full-page pass.
            top_px = max(0, y - BAND_MARGIN)
            bot_px = min(H, y + rows + BAND_MARGIN)
            pm = page.get_pixmap(
                matrix=mat, alpha=False, annots=True,
                clip=fitz.Rect(r.x0, r.y0 + top_px / s,
                               r.x1, r.y0 + bot_px / s))
            # samples_mv is a view on the pixmap's own buffer rather than a copy
            # of it, and the single copy() below both trims the band and detaches
            # it — so one band costs one extra bitmap, not three.
            img = QImage(pm.samples_mv, pm.width, pm.height, pm.stride,
                         QImage.Format_RGB888)
            # Where this band's kept rows start inside the rendered strip. Clamp
            # it: QImage.copy() pads out-of-range rows with black, and a black
            # stripe across a drawing is far worse than a rounding artefact.
            off = min(max(0, y - (pm.y - origin.y0)), max(0, img.height() - 1))
            take = min(rows, img.height() - off)
            if take > 0:
                # Band edges share the *identical* float expression
                # (y0 + K * ratio), so however the engine rounds logical to
                # device coordinates, adjacent bands round together — no
                # hairline gap or double-drawn seam between them.
                t0 = y0 + y * ratio
                t1 = y0 + (y + take) * ratio
                painter.drawImage(
                    QRectF(x0 + (pm.x - origin.x0) * ratio, t0,
                           img.width() * ratio, t1 - t0),
                    img.copy(0, off, img.width(), take))
            y += rows
