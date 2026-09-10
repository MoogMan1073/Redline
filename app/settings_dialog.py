"""The application preferences dialog.

Lifted out of ``main_window`` rather than written here: that module was 2,506
lines and held this dialog, five panes, the menus and the file lifecycle, and
the README's own layout block described it that way. A window's job is the
window; a preferences dialog is its own subject and its own file.

``tests/test_settings_layout.py`` builds this dialog and reads its tab names
back, so the split is checked by driving the real thing rather than by reading
the source — which is the arrangement that already caught the fourth and fifth
tabs going undocumented.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from .config import AppConfig
from .extraction import claude_api


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Settings")
        self.resize(560, 470)
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        lay.addWidget(tabs, 1)

        # identity
        gb_id = QGroupBox("Identity")
        f = QFormLayout(gb_id)
        self.name = QLineEdit(config.your_name)
        f.addRow("Your name (commenter):", self.name)

        # wire fields
        gb_w = QGroupBox("Wire number fields")
        fw = QFormLayout(gb_w)
        self.sheet_w = QSpinBox(); self.sheet_w.setRange(1, 6); self.sheet_w.setValue(int(config.get("wire/sheet_width")))
        self.rung_w = QSpinBox(); self.rung_w.setRange(1, 6); self.rung_w.setValue(int(config.get("wire/rung_width")))
        self.wire_w = QSpinBox(); self.wire_w.setRange(1, 6); self.wire_w.setValue(int(config.get("wire/wire_width")))
        self.zero_pad = QCheckBox("Zero-pad fields"); self.zero_pad.setChecked(bool(config.get("wire/zero_pad")))
        self.regex = QLineEdit(str(config.get("wire/regex_override") or ""))
        self.regex.setPlaceholderText(r"optional override, e.g. ^\d{6}$")
        self.cross_check = QCheckBox("Cross-check sheet (flag mismatches)")
        self.cross_check.setChecked(bool(config.get("wire/cross_check_sheet")))
        self.wire_method = QComboBox(); self.wire_method.addItems(["AI assist", "OCR"])
        self.wire_method.setCurrentIndex(0 if config.wire_extract_method == "ai" else 1)
        self.wire_method.setToolTip(
            "Default engine for scanned (no-text) pages in the Wire Numbers tab. "
            "You can also switch it there per extraction.")
        fw.addRow("Sheet width:", self.sheet_w)
        fw.addRow("Rung width:", self.rung_w)
        fw.addRow("Wire-index width:", self.wire_w)
        fw.addRow(self.zero_pad)
        fw.addRow("Full-label regex:", self.regex)
        fw.addRow(self.cross_check)
        fw.addRow("Scanned-page method:", self.wire_method)

        # component labels (FAMILY-SHEETRUNG, e.g. LT-10010)
        gb_cmp = QGroupBox("Component labels")
        fcmp = QFormLayout(gb_cmp)
        self.cmp_sheet_w = QSpinBox(); self.cmp_sheet_w.setRange(1, 6)
        self.cmp_sheet_w.setValue(int(config.get("component/sheet_width")))
        self.cmp_rung_w = QSpinBox(); self.cmp_rung_w.setRange(1, 6)
        self.cmp_rung_w.setValue(int(config.get("component/rung_width")))
        self.cmp_zero_pad = QCheckBox("Zero-pad fields")
        self.cmp_zero_pad.setChecked(bool(config.get("component/zero_pad")))
        self.cmp_method = QComboBox(); self.cmp_method.addItems(["AI assist", "OCR"])
        self.cmp_method.setCurrentIndex(0 if config.component_extract_method == "ai" else 1)
        self.cmp_labels_per = QSpinBox(); self.cmp_labels_per.setRange(1, 99)
        self.cmp_labels_per.setValue(config.component_labels_per_device)
        self.cmp_families = QPlainTextEdit(", ".join(config.component_families()))
        self.cmp_families.setMaximumHeight(90)
        self.cmp_families.setToolTip(
            "Known device family codes (comma- or newline-separated), e.g. "
            "LT, CR, PB. Labels with codes not listed here are still captured "
            "but flagged 'unknown family'.")
        fcmp.addRow("Sheet width:", self.cmp_sheet_w)
        fcmp.addRow("Rung width:", self.cmp_rung_w)
        fcmp.addRow(self.cmp_zero_pad)
        fcmp.addRow("Scanned-page method:", self.cmp_method)
        fcmp.addRow("Labels per device:", self.cmp_labels_per)
        fcmp.addRow("Family codes:", self.cmp_families)

        # export
        gb_e = QGroupBox("Export defaults")
        fe = QFormLayout(gb_e)
        self.labels_per = QSpinBox(); self.labels_per.setRange(1, 99); self.labels_per.setValue(int(config.get("export/labels_per_wire")))
        self.exp_mode = QComboBox(); self.exp_mode.addItems(["single", "per_sheet"])
        self.exp_mode.setCurrentText(str(config.get("export/mode")))
        self.exp_fmt = QComboBox(); self.exp_fmt.addItems(["xlsx", "csv"])
        self.exp_fmt.setCurrentText(str(config.get("export/format")))
        fe.addRow("Labels per wire:", self.labels_per)
        fe.addRow("Default mode:", self.exp_mode)
        fe.addRow("Default format:", self.exp_fmt)

        # comments / junk
        gb_c = QGroupBox("Comments & junk filter")
        fc = QFormLayout(gb_c)
        self.treat_todo = QCheckBox("Treat all comments as TODO items")
        self.treat_todo.setChecked(bool(config.get("comments/treat_all_as_todo")))
        self.show_ignored = QCheckBox("Show ignored (SHX/AutoCAD junk)")
        self.show_ignored.setChecked(bool(config.get("filter/show_ignored")))
        self.ignore = QPlainTextEdit("\n".join(config.ignore_patterns()))
        self.ignore.setMaximumHeight(90)
        fc.addRow(self.treat_todo)
        fc.addRow(self.show_ignored)
        fc.addRow("Ignore patterns (one regex/line):", self.ignore)

        # ocr / ai
        gb_a = QGroupBox("OCR & AI assist")
        fa = QFormLayout(gb_a)
        self.ocr = QCheckBox("Enable OCR fallback (Tesseract)")
        self.ocr.setChecked(bool(config.get("ocr/enabled")))
        self.ai = QCheckBox("Enable Claude vision assist")
        self.ai.setChecked(bool(config.get("ai/enabled")))
        self.ai.toggled.connect(self._on_ai_toggled)
        self.ai_key = QLineEdit(str(config.get("ai/api_key") or ""))
        self.ai_key.setEchoMode(QLineEdit.Password)
        self.ai_key.setPlaceholderText("sk-ant-…  (leave blank to use ANTHROPIC_API_KEY)")
        self.ai_key.textChanged.connect(self._refresh_api_status)
        self.ai_show = QCheckBox("Show")
        self.ai_show.toggled.connect(
            lambda v: self.ai_key.setEchoMode(QLineEdit.Normal if v else QLineEdit.Password))
        key_row = QHBoxLayout(); key_row.addWidget(self.ai_key, 1); key_row.addWidget(self.ai_show)
        key_wrap = QWidget(); key_wrap.setLayout(key_row)
        self.ai_status = QLabel()
        self.btn_check = QPushButton("Check API status")
        self.btn_check.clicked.connect(self._check_api)
        self.ai_model = QLineEdit(str(config.get("ai/model")))
        self.ai_tiles = QSpinBox(); self.ai_tiles.setRange(1, 4)
        self.ai_tiles.setValue(int(config.get("ai/tiles")))
        self.ai_tiles.setToolTip(
            "Split each scanned page into an N×N grid of tiles, each read at full "
            "resolution so small wire numbers survive. Higher = more accurate but "
            "more API calls per page (N×N). 1 = whole page.")
        fa.addRow(self.ocr)
        fa.addRow(self.ai)
        fa.addRow("API key:", key_wrap)
        fa.addRow("", self.btn_check)
        fa.addRow("Status:", self.ai_status)
        fa.addRow("AI model:", self.ai_model)
        fa.addRow("AI tiling (N×N, calls/page = N²):", self.ai_tiles)
        self._on_ai_toggled(self.ai.isChecked())
        self._refresh_api_status()

        # printing
        gb_p = QGroupBox("Printing")
        fp = QFormLayout(gb_p)
        from .config import PRINT_LINE_WEIGHTS
        self.min_line = QComboBox()
        for label, pt in PRINT_LINE_WEIGHTS:
            self.min_line.addItem(label, pt)
        cur = config.print_min_line_pt
        self.min_line.setCurrentIndex(
            min(range(len(PRINT_LINE_WEIGHTS)),
                key=lambda i: abs(PRINT_LINE_WEIGHTS[i][1] - cur)))
        self.min_line.setToolTip(
            "AutoCAD plots most schematic geometry as a hairline. Printed at "
            "the printer's true resolution those come out around 0.1 pt — "
            "faithful to the file, but anemic on paper. This raises them to a "
            "minimum weight; heavier geometry and all text are untouched.")
        fp.addRow("Minimum line weight:", self.min_line)

        gb_drc = self._build_audit_group()

        # organise the group boxes into tabs so the dialog never outgrows the
        # screen (was a single tall column of every section stacked vertically)
        def _page(*boxes):
            w = QWidget(); v = QVBoxLayout(w)
            for b in boxes:
                v.addWidget(b)
            v.addStretch(1)
            return w
        tabs.addTab(_page(gb_id, gb_e, gb_c, gb_p), "General")
        tabs.addTab(_page(gb_w), "Wire numbers")
        tabs.addTab(_page(gb_cmp), "Component labels")
        tabs.addTab(_page(gb_a), "OCR / AI")
        tabs.addTab(_page(gb_drc), "Design rules")

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def apply(self):
        c = self.config
        c.set("your_name", self.name.text() or "user")
        c.set("wire/sheet_width", self.sheet_w.value())
        c.set("wire/rung_width", self.rung_w.value())
        c.set("wire/wire_width", self.wire_w.value())
        c.set("wire/zero_pad", self.zero_pad.isChecked())
        c.set("wire/regex_override", self.regex.text())
        c.set("wire/cross_check_sheet", self.cross_check.isChecked())
        c.set("wire/extract_method", "ai" if self.wire_method.currentIndex() == 0 else "ocr")
        c.set("component/sheet_width", self.cmp_sheet_w.value())
        c.set("component/rung_width", self.cmp_rung_w.value())
        c.set("component/zero_pad", self.cmp_zero_pad.isChecked())
        c.set("component/extract_method", "ai" if self.cmp_method.currentIndex() == 0 else "ocr")
        c.set("component/labels_per_device", self.cmp_labels_per.value())
        import re as _re
        fams = [f for f in _re.split(r"[,\n]+", self.cmp_families.toPlainText()) if f.strip()]
        c.set_component_families(fams)
        c.set("export/labels_per_wire", self.labels_per.value())
        c.set("export/mode", self.exp_mode.currentText())
        c.set("export/format", self.exp_fmt.currentText())
        c.set("comments/treat_all_as_todo", self.treat_todo.isChecked())
        c.set("filter/show_ignored", self.show_ignored.isChecked())
        c.set_ignore_patterns([l.strip() for l in self.ignore.toPlainText().splitlines() if l.strip()])
        c.set("print/min_line_pt",
              float(self.min_line.currentData() or 0.0))
        c.set("ocr/enabled", self.ocr.isChecked())
        c.set("ai/enabled", self.ai.isChecked())
        c.set("ai/api_key", self.ai_key.text().strip())
        c.set("ai/model", self.ai_model.text())
        c.set("ai/tiles", self.ai_tiles.value())
        self._apply_audit(c)
        c.sync()

    # -- design rules --------------------------------------------------------

    def _build_audit_group(self):
        """Rule list with per-rule enable and a severity override.

        Editing here re-evaluates immediately, the way the family-code list
        already does: severities are applied to the findings already on screen
        rather than forcing a re-run.
        """
        from .audit import available as audit_available, status as audit_status
        from .audit.runner import available_rules
        from .audit.findings import SEVERITIES, SEVERITY_LABELS

        gb = QGroupBox("Design rule check")
        v = QVBoxLayout(gb)

        ok, message = audit_status()
        self.drc_status = QLabel(message)
        self.drc_status.setWordWrap(True)
        v.addWidget(self.drc_status)

        self.drc_rows = []
        self.drc_draw = QCheckBox("Draw findings on the sheet")
        self.drc_draw.setChecked(bool(self.config.audit_draw_on_sheet()))
        v.addWidget(self.drc_draw)

        oda_row = QHBoxLayout()
        oda_row.addWidget(QLabel("ODA File Converter:"))
        self.drc_oda = QLineEdit(self.config.oda_converter_path())
        self.drc_oda.setPlaceholderText("auto-detect (used to read DWG files)")
        btn_oda = QPushButton("Browse…")

        def _pick_oda():
            path, _ = QFileDialog.getOpenFileName(
                self, "ODA File Converter executable")
            if path:
                self.drc_oda.setText(path)

        btn_oda.clicked.connect(_pick_oda)
        oda_row.addWidget(self.drc_oda, 1)
        oda_row.addWidget(btn_oda)
        v.addLayout(oda_row)

        if not ok:
            v.addWidget(QLabel(
                "Install the rule library to choose which rules run."))
            return gb

        disabled = set(self.config.audit_disabled_rules())
        overrides = self.config.audit_severity_overrides()

        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["Run", "Rule", "Severity"])
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setColumnWidth(0, 44)
        table.setColumnWidth(1, 420)

        for rule_id, title, default_sev, _pack in available_rules(
                self.config.audit_packs()):
            row = table.rowCount()
            table.insertRow(row)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Unchecked if rule_id in disabled else Qt.Checked)
            table.setItem(row, 0, chk)
            label = QTableWidgetItem(f"{rule_id} — {title}")
            label.setToolTip(title)
            table.setItem(row, 1, label)
            combo = QComboBox()
            for sev in SEVERITIES:
                combo.addItem(SEVERITY_LABELS[sev], sev)
            current = overrides.get(rule_id, default_sev)
            idx = combo.findData(current)
            combo.setCurrentIndex(idx if idx >= 0 else combo.findData(default_sev))
            table.setCellWidget(row, 2, combo)
            self.drc_rows.append((rule_id, default_sev, chk, combo))

        table.setMinimumHeight(220)
        v.addWidget(table)
        v.addWidget(QLabel(
            "Findings are advisory: they identify things to confirm against "
            "the governing standard, not a determination of compliance."))
        return gb

    def _apply_audit(self, c):
        c.set("audit/draw_on_sheet", self.drc_draw.isChecked())
        c.set("audit/oda_path", self.drc_oda.text().strip())
        if not self.drc_rows:
            return
        disabled, overrides = [], {}
        for rule_id, default_sev, chk, combo in self.drc_rows:
            if chk.checkState() != Qt.Checked:
                disabled.append(rule_id)
            chosen = combo.currentData()
            if chosen and chosen != default_sev:
                overrides[rule_id] = chosen
        c.set_audit_disabled_rules(disabled)
        c.set_audit_severity_overrides(overrides)

    # -- AI assist helpers ---------------------------------------------------

    def _on_ai_toggled(self, on: bool):
        for w in (self.ai_key, self.ai_show, self.btn_check, self.ai_model, self.ai_tiles):
            w.setEnabled(on)
        self._refresh_api_status()

    def _refresh_api_status(self):
        if not self.ai.isChecked():
            self.ai_status.setText("AI assist disabled")
            self.ai_status.setStyleSheet("color: gray;")
            return
        state, msg = claude_api.status(self.ai_key.text())
        color = {"present": "#1b7f3a", "missing": "#b8860b", "no_sdk": "#c0392b"}.get(state, "gray")
        self.ai_status.setText(msg)
        self.ai_status.setStyleSheet(f"color: {color};")

    def _check_api(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok, msg = claude_api.validate_key(
                self.ai_key.text(), self.ai_model.text() or claude_api.DEFAULT_MODEL)
        finally:
            QApplication.restoreOverrideCursor()
        self.ai_status.setText(msg)
        self.ai_status.setStyleSheet("color: #1b7f3a;" if ok else "color: #c0392b;")
