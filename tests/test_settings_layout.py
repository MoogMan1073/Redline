"""Settings dialog is organised into tabs (so it never outgrows the screen),
and both the Wire Numbers and Component Labels tabs expose a scanned-page
AI/OCR engine picker.

Also the gate that keeps `docs/Settings.md` in step with the dialog. That page
named **four** tabs where the dialog builds **five**, and had no section for
either *Component labels* or *Design rules* — so two whole tabs, including the
family-code list and every design-rule control, were undocumented in the one
page a user opens to find out what a setting does. Nothing was wrong; nobody
re-read it.

The tab names are read **off the running dialog**, never off a second reading
of `app/main_window.py`: the document describes what a person sees, and a
source scan would form its own opinion about which `addTab` calls run.
"""

import os
import pathlib
import re
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QTabWidget
    _QT_OK = True
except Exception:  # pragma: no cover
    _QT_OK = False


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestSettingsTabs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self):
        from app.config import AppConfig
        from app.settings_dialog import SettingsDialog
        return SettingsDialog(AppConfig())

    def test_settings_split_into_tabs(self):
        d = self._dialog()
        tw = d.findChild(QTabWidget)
        self.assertIsNotNone(tw, "settings should use a QTabWidget")
        titles = [tw.tabText(i) for i in range(tw.count())]
        self.assertIn("General", titles)
        self.assertIn("Wire numbers", titles)
        self.assertIn("Component labels", titles)
        # several tabs keeps any single page short
        self.assertGreaterEqual(tw.count(), 4)

    def test_wire_method_picker_round_trips(self):
        d = self._dialog()
        original = d.config.get("wire/extract_method")
        try:
            self.assertEqual(
                [d.wire_method.itemText(i) for i in range(d.wire_method.count())],
                ["AI assist", "OCR"])
            d.wire_method.setCurrentIndex(1)   # OCR
            d.apply()
            self.assertEqual(d.config.wire_extract_method, "ocr")
        finally:
            d.config.set("wire/extract_method", original)
            d.config.sync()

    # ---- the manual and the dialog ----

    _DOC = pathlib.Path(__file__).resolve().parent.parent / "docs" / "Settings.md"

    def _doc_sections(self):
        return [m.group(1).strip() for m in
                re.finditer(r"^## +(.+)$", self._DOC.read_text(encoding="utf-8"),
                            flags=re.M)]

    def test_the_manual_has_a_section_per_tab_in_the_dialogs_own_order(self):
        d = self._dialog()
        tw = d.findChild(QTabWidget)
        tabs = [tw.tabText(i) for i in range(tw.count())]
        # The floor. Every assertion here is satisfied by a dialog that built
        # no tabs and a page with no `##` headings, which is what a rename of
        # either degrades to — and an empty list matching an empty list reads
        # exactly like a page in perfect agreement with the code.
        self.assertGreaterEqual(len(tabs), 4, f"the dialog built {tabs}")
        self.assertEqual(self._doc_sections(), tabs, (
            "docs/Settings.md's sections and the dialog's tabs have parted "
            "company. One section per tab, in the order they appear — a tab "
            "with no section is a control nobody can look up."))

    def test_the_two_tabs_that_were_undocumented_carry_their_own_controls(self):
        """A section heading is cheap; what the row was about is the CONTENT
        under it. These are the settings that had no mention anywhere: the
        family-code list, and the design-rule severity table."""
        text = self._DOC.read_text(encoding="utf-8")
        for phrase in ("Family codes", "unknown family", "Labels per device",
                       "Draw findings on the sheet", "ODA File Converter",
                       "Severity"):
            self.assertIn(phrase, text,
                          f"{phrase!r} is a Settings control the manual does "
                          "not mention")


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestWirePanelMethodPicker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_wire_panel_has_scanned_method_dropdown(self):
        from app.panels.wire_panel import WirePanel
        wp = WirePanel()
        self.assertEqual(
            [wp.method.itemText(i) for i in range(wp.method.count())],
            ["AI assist", "OCR"])


if __name__ == "__main__":
    unittest.main()
