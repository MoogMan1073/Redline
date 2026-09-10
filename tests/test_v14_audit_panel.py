"""The Audit tab: findings on screen, marks on the sheet, and waivers.

Two things get tested harder than the rest, because they are the requirements
most easily lost in a refactor: coverage is stated where a reader cannot miss
it, and a finding drawn on the sheet can never obscure or be mistaken for a
user's own markup.
"""

import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QTabWidget
    _QT_OK = True
except Exception:                                     # pragma: no cover
    _QT_OK = False

import fitz

from app import audit
from app.audit.findings import (AuditRun, Coverage, Finding, DEFINITE,
                                POTENTIAL, INFO, STATUS_WAIVED)

HAVE_PYDRC = audit.available()


def _drawing(path):
    doc = fitz.open()
    for title, number, body in (
        ("TITLE PAGE", "EL2507777-000", ()),
        ("24 VDC DISTRIBUTION", "EL2507777-400", ("400010", "PB-40010")),
        ("TERMINAL BLOCK LAYOUT", "EL2507777-800", ("400010", "999990")),
    ):
        page = doc.new_page(width=792, height=1224)
        page.insert_text((40.0, 1000.0), title, rotate=270)
        page.insert_text((70.0, 1000.0), number, rotate=270)
        for i, line in enumerate(body):
            page.insert_text((300.0, 200.0 + i * 16.0), line, rotate=270)
        page.set_rotation(270)
    doc.save(path)
    doc.close()
    return path


def _findings():
    return [
        Finding(key="k1", rule_id="DRC-XREF-WIRE-RECIP-001", severity=POTENTIAL,
                message="Wire 999990 declares sheet 999 but appears only on 800.",
                clause="internal wire numbering convention", sheet="800", page=2,
                subject_id="999990", x=100.0, y=200.0, w=30.0, h=8.0),
        Finding(key="k2", rule_id="DRC-TAG-FAMILY-001", severity=INFO,
                message="Tag PB-40010 uses family code PB.", sheet="400", page=1,
                subject_id="PB-40010", x=50.0, y=60.0, w=40.0, h=8.0),
        Finding(key="k3", rule_id="DRC-SHEET-INDEX-001", severity=POTENTIAL,
                message="Index declares section 200 but no sheet carries it.",
                sheet="", page=0, subject_id="200"),
    ]


def _run():
    return AuditRun(eligible=63, checked=47, skipped=16, packs=["drc-base@1.0.0"],
                    coverage=[Coverage(rule_id="ERC-AMP-001", eligible=63,
                                       checked=47, skipped=16,
                                       reasons={"missing conductor size": 16})])


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestAuditPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from app.model.document import Document
        self.tmp = tempfile.mkdtemp()
        self.src = _drawing(os.path.join(self.tmp, "set.pdf"))
        self.doc = Document(self.src)
        self.doc.load()
        self.doc.set_findings(_findings(), _run())

    def tearDown(self):
        self.doc.close()

    def _panel(self):
        from app.panels.audit_panel import AuditPanel
        p = AuditPanel()
        p.set_document(self.doc)
        return p

    def _rows(self, panel):
        out = []

        def walk(node):
            f = node.data(0, Qt.UserRole)
            if f is not None:
                out.append(f)
            for i in range(node.childCount()):
                walk(node.child(i))

        for i in range(panel.tree.topLevelItemCount()):
            walk(panel.tree.topLevelItem(i))
        return out

    def test_lists_every_finding(self):
        panel = self._panel()
        self.assertEqual({f.key for f in self._rows(panel)}, {"k1", "k2", "k3"})

    def test_coverage_is_stated_in_the_header(self):
        # Above the list, not below it: "no findings" and "could not check"
        # must never read the same.
        panel = self._panel()
        text = panel.coverage_label.text()
        self.assertIn("47 of 63", text)
        self.assertIn("16 not checked", text)
        self.assertIn("missing conductor size", text)

    def test_header_says_the_review_is_advisory(self):
        panel = self._panel()          # keep a reference; Qt owns the widgets
        self.assertIn("dvisory", panel.coverage_label.text())

    def test_header_before_any_run(self):
        from app.panels.audit_panel import AuditPanel
        panel = AuditPanel()
        self.assertIn("No design rule check", panel.coverage_label.text())

    def test_groups_by_severity_by_default(self):
        panel = self._panel()
        groups = [panel.tree.topLevelItem(i).text(0)
                  for i in range(panel.tree.topLevelItemCount())]
        self.assertEqual(groups, ["Potential issue", "Informational"])

    def test_filter_narrows_the_list(self):
        panel = self._panel()
        panel.search.setText("999990")
        self.assertEqual([f.key for f in self._rows(panel)], ["k1"])

    def test_informational_can_be_hidden(self):
        panel = self._panel()
        panel.show_info.setChecked(False)
        self.assertNotIn("k2", {f.key for f in self._rows(panel)})

    def test_waived_rows_are_struck_through_and_can_be_hidden(self):
        self.doc.waive_finding("k1", "Accepted", "LWH")
        panel = self._panel()
        row = next(n for n in self._walk_items(panel)
                   if n.data(0, Qt.UserRole) is not None
                   and n.data(0, Qt.UserRole).key == "k1")
        self.assertTrue(row.font(0).strikeOut())
        self.assertEqual(row.text(panel.COL_STATUS), "Waived")
        panel.hide_waived.setChecked(True)
        self.assertNotIn("k1", {f.key for f in self._rows(panel)})

    def _walk_items(self, panel):
        out = []

        def walk(node):
            out.append(node)
            for i in range(node.childCount()):
                walk(node.child(i))

        for i in range(panel.tree.topLevelItemCount()):
            walk(panel.tree.topLevelItem(i))
        return out

    def test_double_click_asks_to_jump(self):
        panel = self._panel()
        seen = []
        panel.activated.connect(seen.append)
        row = next(n for n in self._walk_items(panel)
                   if n.data(0, Qt.UserRole) is not None)
        panel._on_double(row, 0)
        self.assertEqual(len(seen), 1)

    def test_double_click_on_a_group_header_does_nothing(self):
        panel = self._panel()
        seen = []
        panel.activated.connect(seen.append)
        panel._on_double(panel.tree.topLevelItem(0), 0)
        self.assertEqual(seen, [])

    def test_sorting_by_sheet_puts_numbers_in_order(self):
        panel = self._panel()
        panel.group_by.setCurrentIndex(3)          # no grouping
        panel._on_header_clicked(panel.COL_SHEET)
        sheets = [f.sheet for f in self._rows(panel)]
        self.assertEqual(sheets, sorted(sheets, key=lambda s: (0, int(s)) if s else (1, 0)))

    def test_disabling_a_rule_hides_rather_than_deletes_its_findings(self):
        # Toggling a rule off and on again must not lose work.
        from app.config import AppConfig
        config = AppConfig()
        before = config.audit_disabled_rules()
        try:
            config.set_audit_disabled_rules(["DRC-TAG-FAMILY-001"])
            panel = self._panel()
            panel.config = config
            panel.refresh()
            self.assertNotIn("k2", {f.key for f in self._rows(panel)})
            # …still stored, so re-enabling brings it straight back.
            self.assertIn("k2", {f.key for f in self.doc.findings})
            config.set_audit_disabled_rules([])
            panel.refresh()
            self.assertIn("k2", {f.key for f in self._rows(panel)})
        finally:
            config.set_audit_disabled_rules(before)
            config.sync()

    def test_count_line_reports_severities_and_waivers(self):
        self.doc.waive_finding("k1", "Accepted")
        panel = self._panel()
        text = panel.count_label.text()
        self.assertIn("waived", text)
        self.assertIn("informational", text)


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestFindingMarks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from app.model.document import Document
        self.tmp = tempfile.mkdtemp()
        self.src = _drawing(os.path.join(self.tmp, "set.pdf"))
        self.doc = Document(self.src)
        self.doc.load()

    def tearDown(self):
        self.doc.close()

    def _view(self):
        from app.viewer.pdf_view import PdfView
        v = PdfView()
        v.set_document(self.doc, None)
        return v

    def test_draws_one_mark_per_locatable_finding(self):
        view = self._view()
        view.draw_findings(_findings())
        # The set-wide index finding has nowhere to point.
        self.assertEqual(len(view._finding_items), 2)

    def test_marks_sit_below_every_user_mark(self):
        # Structural, not cosmetic: an audit overlay must not be able to hide
        # something a person drew.
        from app.viewer.annotation_items import ANNOT_Z
        view = self._view()
        view.draw_findings(_findings())
        for item in view._finding_items:
            self.assertLess(item.zValue(), ANNOT_Z)

    def test_marks_are_not_annotations(self):
        # The eraser, selection and hit-testing all key on an item's `.ann`.
        # Findings deliberately have none, so they cannot be rubbed out or
        # dragged, and they never reach the annotation store or the saved PDF.
        view = self._view()
        view.draw_findings(_findings())
        for item in view._finding_items:
            self.assertIsNone(getattr(item, "ann", None))
        self.assertEqual(len(self.doc.store.all()), 0)

    def test_redrawing_replaces_rather_than_accumulates(self):
        view = self._view()
        view.draw_findings(_findings())
        view.draw_findings(_findings())
        self.assertEqual(len(view._finding_items), 2)

    def test_clearing_removes_them(self):
        view = self._view()
        view.draw_findings(_findings())
        view.clear_findings()
        self.assertEqual(view._finding_items, [])

    def test_a_finding_with_no_extent_still_gets_a_visible_target(self):
        view = self._view()
        view.draw_findings([Finding(key="z", severity=POTENTIAL, page=1,
                                    x=40.0, y=40.0)])
        self.assertEqual(len(view._finding_items), 1)
        self.assertGreater(view._finding_items[0].rect().width(), 0)


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestWaiveDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_a_reason_is_required(self):
        from app.dialogs import WaiveDialog
        dlg = WaiveDialog(_findings()[0], "LWH")
        self.assertFalse(dlg._ok.isEnabled())
        dlg.reason.setText("   ")
        self.assertFalse(dlg._ok.isEnabled())
        dlg.reason.setText("Accepted by client")
        self.assertTrue(dlg._ok.isEnabled())
        self.assertEqual(dlg.values(), ("Accepted by client", "LWH"))

    def test_shows_what_is_being_waived(self):
        from app.dialogs import WaiveDialog
        from PySide6.QtWidgets import QLabel
        dlg = WaiveDialog(_findings()[0])
        texts = " ".join(w.text() for w in dlg.findChildren(QLabel))
        self.assertIn("999990", texts)
        self.assertIn("DRC-XREF-WIRE-RECIP-001", texts)


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestSettingsTab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_design_rules_tab_exists(self):
        from app.settings_dialog import SettingsDialog
        from app.config import AppConfig
        dlg = SettingsDialog(AppConfig())
        tabs = dlg.findChild(QTabWidget)
        self.assertIn("Design rules",
                      [tabs.tabText(i) for i in range(tabs.count())])

    @unittest.skipUnless(HAVE_PYDRC, "PyDRC is not installed")
    def test_lists_the_rules_and_round_trips_a_change(self):
        from app.settings_dialog import SettingsDialog
        from app.config import AppConfig
        config = AppConfig()
        before_disabled = config.audit_disabled_rules()
        before_overrides = config.audit_severity_overrides()
        try:
            dlg = SettingsDialog(config)
            self.assertTrue(dlg.drc_rows)
            rule_id, default_sev, chk, combo = dlg.drc_rows[0]
            chk.setCheckState(Qt.Unchecked)
            other = DEFINITE if default_sev != DEFINITE else INFO
            combo.setCurrentIndex(combo.findData(other))
            dlg.apply()
            self.assertIn(rule_id, config.audit_disabled_rules())
            self.assertEqual(config.audit_severity_overrides()[rule_id], other)
        finally:
            config.set_audit_disabled_rules(before_disabled)
            config.set_audit_severity_overrides(before_overrides)
            config.sync()


@unittest.skipUnless(_QT_OK and HAVE_PYDRC, "needs PySide6 and PyDRC")
class TestMainWindowIntegration(unittest.TestCase):
    """One end-to-end pass: run the check, see it, waive one, keep it."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = _drawing(os.path.join(self.tmp, "set.pdf"))
        # Run the worker inline: no thread, no modal dialog.
        import app.tools.runner as runner_mod
        self._real = runner_mod.run_with_progress

        def sync(parent, title, fn, on_done, on_error=None):
            try:
                on_done(fn(lambda d, t: None, lambda: False))
            except Exception as e:                 # pragma: no cover
                (on_error or (lambda m: None))(str(e))
            return None

        runner_mod.run_with_progress = sync

    def tearDown(self):
        import app.tools.runner as runner_mod
        runner_mod.run_with_progress = self._real

    def test_withdrawing_a_severity_override_puts_the_severity_back(self):
        """The change used to be one-way.

        A finding kept whatever it was last set to, `set_findings` wrote it to
        the sidecar, and it survived closing and reopening the file -- so
        Settings read the pack default while the panel header, the overlay
        colour and every exported report said something else. Escalating and
        then withdrawing left rows reading "definite violation" that no rule
        had ever called one.
        """
        from app.main_window import MainWindow
        win = MainWindow()
        win.load_document(self.src)
        win.run_audit()
        doc = win.document
        self.assertTrue(doc.findings)
        rule = doc.findings[0].rule_id
        was = {f.key: f.severity for f in doc.findings if f.rule_id == rule}
        self.assertTrue(was)
        defaults = {rule: next(iter(was.values()))}

        win.config.set_audit_severity_overrides({rule: DEFINITE})
        win._reapply_audit_settings(defaults)
        self.assertTrue(all(f.severity == DEFINITE for f in doc.findings
                            if f.rule_id == rule))

        win.config.set_audit_severity_overrides({})
        win._reapply_audit_settings(defaults)
        self.assertEqual({f.key: f.severity for f in doc.findings
                          if f.rule_id == rule}, was)
        win.close()

    def test_a_rule_with_no_known_default_keeps_what_it_has(self):
        # A finding from a pack that is no longer loaded has no entry among
        # the defaults. Resetting it to a guessed severity would be inventing
        # an answer, so it is left alone.
        from app.main_window import MainWindow
        win = MainWindow()
        win.load_document(self.src)
        win.run_audit()
        doc = win.document
        rule = doc.findings[0].rule_id
        win.config.set_audit_severity_overrides({rule: DEFINITE})
        win._reapply_audit_settings({rule: POTENTIAL})
        win.config.set_audit_severity_overrides({})
        win._reapply_audit_settings({})          # defaults unknown
        self.assertTrue(all(f.severity == DEFINITE for f in doc.findings
                            if f.rule_id == rule))
        win.close()

    def test_run_populates_panel_and_sheet_then_waiver_persists(self):
        from app.main_window import MainWindow
        from app.model.document import Document
        win = MainWindow()
        win.load_document(self.src)
        self.assertTrue(win.act_run_audit.isEnabled())

        win.run_audit()
        doc = win.document
        self.assertTrue(doc.findings)
        self.assertIsNotNone(doc.audit_run)
        self.assertIn("checked", win.audit_panel.coverage_label.text())
        self.assertTrue(win.view._finding_items)

        target = doc.findings[0]
        doc.waive_finding(target.key, "Accepted here", "LWH")
        win.run_audit()                     # a re-run must not undo it
        self.assertEqual(
            next(f for f in doc.findings if f.key == target.key).status,
            STATUS_WAIVED)

        doc.save()
        win.close()

        again = Document(self.src)
        again.load()
        self.assertEqual(again.waiver_for(target.key).reason, "Accepted here")
        again.close()

    def test_audit_is_unavailable_without_a_sidecar(self):
        from app.main_window import MainWindow
        win = MainWindow()
        win.load_document(self.src)
        win.document.sidecar_available = False
        win._update_actions_enabled(True)
        self.assertFalse(win.act_run_audit.isEnabled())
        win.close()


def _rolled(**kw):
    """A finding that covers three sheets, as the rule library now reports one."""
    from app.audit.findings import Place
    base = dict(
        key="roll1", rule_id="DRC-SYM-RUNG-001", severity=POTENTIAL,
        message="CBL-*15 on each of 3 sheets sits on rung 16 where the tag "
                "says rung 15.",
        clause="internal source drawing hygiene", subject_id="CBL-*15",
        sheet="400", page=1, x=50.0, y=60.0, w=40.0, h=8.0,
        places=[Place(sheet="400", rung=15, page=1, x=50.0, y=60.0,
                      w=40.0, h=8.0, subject_id="CBL-40015"),
                Place(sheet="800", rung=15, page=2, x=110.0, y=210.0,
                      w=40.0, h=8.0, subject_id="CBL-80015"),
                Place(sheet="000", rung=15, page=0, subject_id="CBL-00015")])
    base.update(kw)
    return Finding(**base)


class TestPlacesFromTheReport(unittest.TestCase):
    """Every place a rolled-up finding names has to survive the conversion.

    The rule library reports a repeated drafting event once and lists all of
    it. On a real 41-sheet audit that is 379 places across 92 findings -- so a
    converter that keeps only the first drops 287 of them, on 16 sheets that
    then look clean.
    """

    def _raw(self, **kw):
        raw = {
            "rule_id": "DRC-SYM-RUNG-001", "fingerprint": "sha256:abc",
            "severity": POTENTIAL, "message": "m",
            "location": {"sheet": "232", "rung": 16, "page_index": 5},
            "subject": {"id": "CBL-*15", "kind": "device"},
            "evidence": {"also_at": ["233-16", "234-16"], "total_places": 3,
                         "on": ["CBL-23215@232-16", "CBL-23315@233-16",
                                "CBL-23415@234-16"]},
        }
        raw.update(kw)
        return raw

    def test_every_place_the_evidence_names_becomes_a_place(self):
        f = Finding.from_pydrc(self._raw(), extents={},
                               pages_by_sheet={"232": 5, "233": 6, "234": 7})
        self.assertEqual([p.label for p in f.places],
                         ["232-16", "233-16", "234-16"])
        self.assertEqual([p.page for p in f.places], [5, 6, 7])
        self.assertEqual(f.sheets, ["232", "233", "234"])
        self.assertEqual(f.place_count, 3)

    def test_a_place_is_outlined_around_the_symbol_standing_there(self):
        # The subject of a rolled-up finding -- "CBL-*15" -- is printed on no
        # sheet. The symbol at each place is, and the evidence names it.
        f = Finding.from_pydrc(
            self._raw(),
            extents={(5, "CBL-23215"): (1.0, 2.0, 3.0, 4.0),
                     (6, "CBL-23315"): (10.0, 20.0, 30.0, 8.0)},
            pages_by_sheet={"232": 5, "233": 6, "234": 7})
        self.assertEqual((f.places[0].x, f.places[0].y), (1.0, 2.0))
        self.assertEqual((f.places[1].x, f.places[1].y), (10.0, 20.0))
        # No box for the third: known as a sheet and a rung, and that is not a
        # failure -- it still belongs to the sheet and still lists under it.
        self.assertFalse(f.places[2].has_location)
        self.assertEqual(f.places[2].sheet, "234")

    def test_the_scalars_agree_with_the_first_place(self):
        # Two answers to "where is this" that disagree is how an overlay ends
        # up drawn somewhere the list does not mention.
        f = Finding.from_pydrc(
            self._raw(), extents={(5, "CBL-23215"): (1.0, 2.0, 3.0, 4.0)},
            pages_by_sheet={"232": 5})
        self.assertEqual((f.x, f.y, f.w, f.h), (1.0, 2.0, 3.0, 4.0))
        self.assertTrue(f.has_location)

    def test_a_finding_with_one_place_is_unchanged(self):
        raw = self._raw(evidence={})
        f = Finding.from_pydrc(raw, extents={}, pages_by_sheet={"232": 5})
        self.assertEqual(f.place_count, 1)
        self.assertEqual(f.sheet_label, "232")

    def test_a_sheet_the_import_never_saw_still_lists(self):
        # A place on a sheet outside the imported span has no page to draw on,
        # and the finding still belongs to it.
        f = Finding.from_pydrc(self._raw(), extents={},
                               pages_by_sheet={"232": 5})
        self.assertEqual(f.sheets, ["232", "233", "234"])
        self.assertFalse(f.places[1].has_location)

    def test_two_symbols_on_one_rung_less_sheet_are_two_places(self):
        """A place is a sheet and a rung, so symbols with no rung all share
        their sheet's label. Keeping one tag per label drew two boxes for
        sixteen field instruments the drawing gives sixteen positions for."""
        raw = self._raw(
            rule_id="DRC-TAG-CONFORM-001",
            location={"sheet": "301", "rung": None, "page_index": 13},
            subject={"id": "ZIR", "kind": "device"},
            evidence={"also_at": ["302"], "total_places": 2,
                      "on": ["ZIR-301@301", "ZIR-302@301",
                             "ZIR-303@302", "ZIR-304@302"]})
        f = Finding.from_pydrc(
            raw,
            extents={(13, "ZIR-301"): (10.0, 20.0, 5.0, 5.0),
                     (13, "ZIR-302"): (10.0, 80.0, 5.0, 5.0),
                     (14, "ZIR-303"): (30.0, 20.0, 5.0, 5.0),
                     (14, "ZIR-304"): (30.0, 80.0, 5.0, 5.0)},
            pages_by_sheet={"301": 13, "302": 14})
        self.assertEqual([p.subject_id for p in f.places],
                         ["ZIR-301", "ZIR-302", "ZIR-303", "ZIR-304"])
        self.assertEqual([(p.x, p.y) for p in f.places],
                         [(10.0, 20.0), (10.0, 80.0), (30.0, 20.0), (30.0, 80.0)])
        self.assertTrue(all(p.has_location for p in f.places))

    def test_the_first_named_symbol_is_the_finding_itself(self):
        """Not a place beside the primary -- the primary's own identity. Both
        producers put it first, and appending it instead reported seventeen
        places for sixteen symbols with a box drawn twice on the first."""
        raw = self._raw(
            location={"sheet": "232", "rung": 16, "page_index": 5},
            evidence={"also_at": ["233-16"], "total_places": 2,
                      "on": ["CBL-23215@232-16", "CBL-23315@233-16"]})
        f = Finding.from_pydrc(
            raw, extents={(5, "CBL-23215"): (1.0, 2.0, 3.0, 4.0)},
            pages_by_sheet={"232": 5, "233": 6})
        self.assertEqual(len(f.places), 2)
        self.assertEqual(f.places[0].subject_id, "CBL-23215")
        self.assertEqual((f.x, f.y), (1.0, 2.0))

    def test_a_name_the_page_does_not_print_gets_no_box_not_a_wrong_one(self):
        raw = self._raw(evidence={"also_at": ["233-16"], "total_places": 2,
                                  "on": ["CBL-23215@232-16", "GHOST@233-16"]})
        f = Finding.from_pydrc(raw, extents={}, pages_by_sheet={"232": 5,
                                                                "233": 6})
        self.assertEqual(f.places[1].subject_id, "GHOST")
        self.assertFalse(f.places[1].has_location)
        self.assertEqual(f.places[1].sheet, "233")

    def test_a_finding_without_on_still_reads_its_places(self):
        """`also_at` remains the universal shape; `on` is the finer spelling
        where a producer offers it."""
        raw = self._raw(evidence={"also_at": ["233-16", "234-16"],
                                  "total_places": 3})
        f = Finding.from_pydrc(raw, extents={},
                               pages_by_sheet={"232": 5, "233": 6, "234": 7})
        self.assertEqual([p.label for p in f.places],
                         ["232-16", "233-16", "234-16"])

    def test_places_round_trip_through_the_sidecar(self):
        f = _rolled()
        again = Finding.from_dict(f.to_dict())
        self.assertEqual([p.to_dict() for p in again.places],
                         [p.to_dict() for p in f.places])

    def test_a_sidecar_written_before_places_still_opens(self):
        d = _findings()[0].to_dict()
        d.pop("places", None)
        f = Finding.from_dict(d)
        self.assertEqual(f.place_count, 1)
        self.assertEqual(f.places[0].sheet, "800")
        self.assertEqual(f.places[0].page, 2)


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestWhichPageAFindingOpensOn(unittest.TestCase):
    """Not every entity kind carries a page index.

    A protective device, a terminal, a source, a load, a cross-reference and
    an index entry all reach the converter with no page at all. Defaulting
    them to 0 files them on the first sheet of the set — usually the drawing
    index — so double-clicking the row navigates somewhere the finding has
    nothing to do with. On the demo pair that was 10 of 61 findings.
    """

    def _raw(self, **loc):
        base = {"rule_id": "ERC-OCPD-SMALL-001", "fingerprint": "sha256:p",
                "severity": POTENTIAL, "message": "m",
                "subject": {"id": "FU-30014", "kind": "protective_device"},
                "evidence": {}}
        base["location"] = dict({"sheet": "300", "rung": 4}, **loc)
        return base

    def test_the_page_comes_from_the_sheet_the_finding_names(self):
        f = Finding.from_pydrc(self._raw(), extents={},
                               pages_by_sheet={"300": 6, "800": 9})
        self.assertEqual(f.page, 6)
        self.assertEqual(f.places[0].page, 6)

    def test_an_explicit_page_index_still_wins(self):
        f = Finding.from_pydrc(self._raw(page_index=2), extents={},
                               pages_by_sheet={"300": 6})
        self.assertEqual(f.page, 2)

    def test_a_finding_that_names_no_sheet_keeps_page_zero(self):
        # DRC-SHEET-INDEX-001 is about the index itself and has nowhere better
        # to point; taking the default away would cost it its navigation.
        raw = self._raw()
        raw["location"] = {}
        raw["subject"] = {"id": "302", "kind": "index_entry"}
        f = Finding.from_pydrc(raw, extents={}, pages_by_sheet={"300": 6})
        self.assertEqual(f.page, 0)

    def test_an_unknown_sheet_falls_back_rather_than_guessing(self):
        f = Finding.from_pydrc(self._raw(sheet="999"), extents={},
                               pages_by_sheet={"300": 6})
        self.assertEqual(f.page, 0)


class TestACoordinateFromTheSourceDrawing(unittest.TestCase):
    """A drawing's model space is not the page's coordinate space.

    Both are bare numbers, so nothing downstream can tell them apart. A
    drawing runs about 31 x 21 inches; read as PDF points that is half an inch
    square in the top-left corner of a 17 x 11 in sheet, y inverted -- every
    such finding boxed in the same wrong place. Measured on a real audit with
    the source drawings imported: 16 of 57 located places.
    """

    def _arrow(self, **kw):
        raw = {
            "rule_id": "DRC-XREF-ARROW-RECIP-001", "fingerprint": "sha256:a",
            "severity": POTENTIAL, "message": "m",
            # 12.5 x 8.25 inches into the drawing -- a plausible spot on a
            # schematic, and a nonsense one on a page measured in points.
            "location": {"sheet": "232", "rung": 16, "page_index": 5,
                         "x": 12.5, "y": 8.25},
            "subject": {"id": "232-16", "kind": "signal_arrow"},
            # Both halves matter: this coordinate is drawing space because the
            # finding came from a source drawing, not merely because it is an
            # arrow. A plot-derived arrow's coordinates are page points.
            "provenance": {"source": "acade", "resolved_by": "dxf"},
            "evidence": {},
        }
        raw.update(kw)
        return raw

    def test_it_is_dropped_rather_than_drawn_in_the_wrong_place(self):
        f = Finding.from_pydrc(self._arrow(), extents={}, pages_by_sheet={})
        self.assertEqual((f.x, f.y), (0.0, 0.0))
        self.assertFalse(f.places[0].has_location)

    def test_the_finding_still_names_its_sheet(self):
        # Dropping the box must not cost the reader the place: no location
        # means the overlay skips it and the row still says sheet 232.
        f = Finding.from_pydrc(self._arrow(), extents={}, pages_by_sheet={})
        self.assertEqual(f.sheets, ["232"])
        self.assertEqual(f.places[0].label, "232-16")

    def test_a_box_found_on_the_page_is_still_used(self):
        # The gate is "no page coordinate was found", not "never trust this
        # kind": if the subject's text is printed, that box is authoritative.
        f = Finding.from_pydrc(self._arrow(),
                               extents={(5, "232-16"): (400.0, 300.0, 26.0, 10.0)},
                               pages_by_sheet={})
        self.assertEqual((f.x, f.y, f.w, f.h), (400.0, 300.0, 26.0, 10.0))
        self.assertTrue(f.places[0].has_location)

    def test_a_plot_derived_arrow_keeps_its_page_coordinate(self):
        """The regression this gate caused when it keyed on kind alone.

        An arrow read from the plot is found by its reference text on the
        page, so its coordinates are page points and correct. Gating on kind
        alone zeroed all three arrow findings on a PDF-only audit of the demo
        set, which were carrying good boxes at (254.8, 461.0), (383.9, 570.2)
        and (565.8, 48.2) on a 1224 x 792 page.
        """
        raw = self._arrow(location={"sheet": "232", "rung": 16,
                                    "page_index": 5, "x": 254.8, "y": 461.0},
                          provenance={"source": "pdf-text",
                                      "resolved_by": "text"})
        f = Finding.from_pydrc(raw, extents={}, pages_by_sheet={})
        self.assertEqual((f.x, f.y), (254.8, 461.0))
        self.assertTrue(f.places[0].has_location)

    def test_a_devices_own_coordinate_is_left_alone(self):
        """Keyed on the subject kind, not on provenance.

        A device's id is printed on the sheet, so its coordinate comes from
        the page and is correct however the model was built. Gating on
        provenance instead would discard it: the merge that enriches a
        plot-derived model copies `provenance` onto matched base devices that
        kept their page coordinates.
        """
        raw = self._arrow(subject={"id": "FU-23216", "kind": "device"},
                          provenance={"source": "acade", "resolved_by": "dxf"})
        f = Finding.from_pydrc(raw, extents={}, pages_by_sheet={})
        self.assertEqual((f.x, f.y), (12.5, 8.25))

    def test_the_overlay_skips_a_place_with_no_location(self):
        from app.audit.findings import Place
        self.assertFalse(Place(sheet="232", rung=16, page=5).has_location)
        self.assertTrue(Place(sheet="232", rung=16, page=5, x=400.0).has_location)


@unittest.skipUnless(_QT_OK, "PySide6 not available")
class TestRolledUpFindingOnScreen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _panel(self):
        from app.panels.audit_panel import AuditPanel, GROUP_SHEET

        class _Doc:
            findings = [_rolled()] + _findings()
            audit_run = _run()

            @staticmethod
            def waiver_for(_key):
                return None
        panel = AuditPanel()
        panel.set_document(_Doc())
        return panel, GROUP_SHEET

    def _sheet_groups(self, panel):
        out = {}
        for i in range(panel.tree.topLevelItemCount()):
            node = panel.tree.topLevelItem(i)
            out[node.text(0)] = [node.child(j).data(0, Qt.UserRole)
                                 for j in range(node.childCount())]
        return out

    def test_it_lists_under_every_sheet_it_covers(self):
        panel, group_sheet = self._panel()
        panel.group_by.setCurrentIndex(2)          # group by sheet
        panel.refresh()
        groups = self._sheet_groups(panel)
        for sheet in ("Sheet 000", "Sheet 400", "Sheet 800"):
            self.assertIn(sheet, groups, sorted(groups))
            self.assertIn("roll1", [f.key for f in groups[sheet]], sheet)

    def test_the_sheet_column_says_it_covers_more_than_one(self):
        panel, _ = self._panel()
        panel.group_by.setCurrentIndex(3)          # no grouping
        panel.refresh()
        labels = {panel.tree.topLevelItem(i).data(0, Qt.UserRole).key:
                  panel.tree.topLevelItem(i).text(2)
                  for i in range(panel.tree.topLevelItemCount())}
        self.assertEqual(labels["roll1"], "400 +2")
        self.assertEqual(labels["k1"], "800")

    def test_double_clicking_a_row_lands_on_that_row_s_sheet(self):
        # Sending a reviewer who clicked under Sheet 800 to sheet 400 is how a
        # rolled-up finding earns a reputation for lying about where things are.
        panel, _ = self._panel()
        panel.group_by.setCurrentIndex(2)
        panel.refresh()
        seen = []
        panel.activated.connect(seen.append)
        for i in range(panel.tree.topLevelItemCount()):
            node = panel.tree.topLevelItem(i)
            if node.text(0) != "Sheet 800":
                continue
            for j in range(node.childCount()):
                row = node.child(j)
                if row.data(0, Qt.UserRole).key == "roll1":
                    panel._on_double(row, 0)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].sheet, "800")
        self.assertEqual(seen[0].page, 2)

    def test_searching_a_sheet_finds_the_finding_that_covers_it(self):
        panel, _ = self._panel()
        panel.search.setText("800")
        panel.refresh()
        keys = {f.key for f in panel._findings()}
        self.assertIn("roll1", keys)

    def test_the_overlay_marks_every_place_with_a_box(self):
        from app.viewer.pdf_view import PdfView
        view = PdfView()
        view._page_items = [object(), object(), object()]
        drawn = []

        class _Item:
            def __init__(self, *a, **k):
                drawn.append(a)

            def __getattr__(self, _n):
                return lambda *a, **k: None
        import PySide6.QtWidgets as W
        real = W.QGraphicsRectItem
        W.QGraphicsRectItem = _Item
        try:
            view.draw_findings([_rolled()])
        finally:
            W.QGraphicsRectItem = real
        # Two of the three places carry a box; the third is sheet-and-rung only.
        self.assertEqual(len(drawn), 2)
        self.assertEqual({round(a[0], 1) for a in drawn}, {47.5, 107.5})


if __name__ == "__main__":
    unittest.main()
