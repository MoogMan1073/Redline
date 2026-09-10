"""The small modal dialogs the window opens, and the swatch icons they draw.

Lifted out of ``main_window`` for the reason ``settings_dialog`` was: that
module held these five alongside five panes, the menus and the file lifecycle.
``app/tools/dialogs.py`` is the declared home for the PDF-tool dialogs and had
been for releases; these are the annotation and audit ones, and they had simply
grown up beside the window instead.

Kept together because they genuinely reference each other -- measured by AST
rather than assumed: ``TextEditDialog`` opens a ``FillDialog`` and draws both
swatches, and ``FillDialog`` draws one. ``_apply_font`` and ``WaiveDialog``
reference nothing here and travel with them only because they are the same
subject.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSlider,
    QSpinBox, QVBoxLayout,
)

from .model.annotations import (
    Annotation, KIND_CALLOUT, KIND_COMMENT, KIND_TEXTBOX,
)


class TextEditDialog(QDialog):
    def __init__(self, ann: Annotation, parent=None, is_textbox=False):
        super().__init__(parent)
        self.ann = ann
        self.is_textbox = is_textbox
        self._font_color = tuple(ann.color)
        if ann.kind == KIND_CALLOUT:
            title = "Edit callout"
        elif is_textbox or ann.kind == KIND_TEXTBOX:
            title = "Edit text box"
        elif ann.kind == KIND_COMMENT:
            title = "Edit comment"
        else:
            # a free note attached to a highlight / arrow / rectangle / pen
            title = "Edit note" if (ann.text or "").strip() else "Add note"
        self.setWindowTitle(title)
        lay = QVBoxLayout(self)
        self.edit = QPlainTextEdit(ann.text or "")
        self.edit.setMinimumSize(320, 120)
        self.edit.installEventFilter(self)  # Ctrl/Shift+Enter -> OK
        lay.addWidget(self.edit)

        # font styling — only meaningful for on-page text boxes
        if is_textbox:
            self._fill_color = tuple(ann.fill_color) if ann.fill_color else None
            self._fill_opacity = float(ann.fill_opacity)
            frow = QHBoxLayout()
            self.size_spin = QSpinBox(); self.size_spin.setRange(4, 96)
            self.size_spin.setValue(int(ann.font_size))
            self.bold_cb = QCheckBox("B"); self.bold_cb.setChecked(ann.bold)
            self.italic_cb = QCheckBox("I"); self.italic_cb.setChecked(ann.italic)
            self.color_btn = QPushButton("Font color")
            self.color_btn.clicked.connect(self._pick_color)
            self._update_color_swatch()
            self.fill_btn = QPushButton("Fill")
            self.fill_btn.setToolTip("Box background — pick color + opacity "
                                     "(alpha 0 = none, 100% = opaque cover)")
            self.fill_btn.clicked.connect(self._pick_fill)
            self._update_fill_swatch()
            frow.addWidget(QLabel("Size:")); frow.addWidget(self.size_spin)
            frow.addWidget(self.bold_cb); frow.addWidget(self.italic_cb)
            frow.addWidget(self.color_btn); frow.addWidget(self.fill_btn)
            frow.addStretch(1)
            lay.addLayout(frow)

        self.todo = QCheckBox("Flag as TODO")
        self.todo.setChecked(ann.is_todo)
        lay.addWidget(self.todo)
        hint = QLabel("Ctrl+Enter or Shift+Enter to save · Esc to cancel")
        hint.setStyleSheet("color: gray; font-size: 11px;")
        lay.addWidget(hint)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _pick_color(self):
        rgb = self._font_color
        col = QColorDialog.getColor(
            QColor(int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255)), self,
            "Font color")
        if col.isValid():
            self._font_color = (col.redF(), col.greenF(), col.blueF())
            self._update_color_swatch()

    def _update_color_swatch(self):
        self.color_btn.setIcon(_swatch(QColor(
            int(self._font_color[0] * 255), int(self._font_color[1] * 255),
            int(self._font_color[2] * 255))))

    def _pick_fill(self):
        ok, color, opacity = FillDialog.ask(self, self._fill_color,
                                            self._fill_opacity, "Box fill")
        if not ok:
            return
        self._fill_color = color
        if color is not None:
            self._fill_opacity = opacity
        self._update_fill_swatch()

    def _update_fill_swatch(self):
        self.fill_btn.setIcon(_fill_swatch(self._fill_color, self._fill_opacity))

    def eventFilter(self, obj, event):
        if obj is self.edit and event.type() == QEvent.KeyPress:
            if (event.key() in (Qt.Key_Return, Qt.Key_Enter)
                    and (event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier))):
                self.accept()
                return True
        return super().eventFilter(obj, event)

    def values(self):
        return self.edit.toPlainText(), self.todo.isChecked()

    def font_values(self):
        """Font styling for a text box, or ``None`` for a comment."""
        if not self.is_textbox:
            return None
        return {
            "font_size": float(self.size_spin.value()),
            "bold": self.bold_cb.isChecked(),
            "italic": self.italic_cb.isChecked(),
            "color": tuple(self._font_color),
            "fill_color": tuple(self._fill_color) if self._fill_color else None,
            "fill_opacity": float(self._fill_opacity),
        }


def _apply_font(ann: Annotation, fv) -> None:
    if not fv:
        return
    ann.font_size = fv["font_size"]
    ann.bold = fv["bold"]
    ann.italic = fv["italic"]
    ann.color = tuple(fv["color"])
    if "fill_color" in fv:
        ann.fill_color = tuple(fv["fill_color"]) if fv["fill_color"] else None
        ann.fill_opacity = fv["fill_opacity"]


class WaiveDialog(QDialog):
    """Record why a finding is acceptable on this project.

    A reason is required, not optional. Every real panel has justified
    exceptions, and a waiver without one is indistinguishable from someone
    silencing an inconvenient rule — which is how audit tooling loses the trust
    that makes it worth running.
    """

    def __init__(self, finding, author: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Waive finding")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)

        summary = QLabel(finding.message)
        summary.setWordWrap(True)
        lay.addWidget(summary)

        # Every sheet, because the waiver covers every one of them. A reviewer
        # told "sheet 232" while agreeing to something that also stands on 233
        # through 240 has not been asked the question they are answering.
        seen = getattr(finding, "sheets", None) or (
            [finding.sheet] if finding.sheet else [])
        where = ("set-wide" if not seen
                 else f"sheet {seen[0]}" if len(seen) == 1
                 else f"sheets {', '.join(seen)}")
        detail = QLabel(f"{finding.rule_id} · {where}"
                        + (f" · cited: {finding.clause}" if finding.clause else ""))
        detail.setWordWrap(True)
        detail.setStyleSheet("color: palette(mid);")
        lay.addWidget(detail)

        form = QFormLayout()
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Why is this acceptable here?")
        self.author = QLineEdit(author)
        form.addRow("Reason", self.reason)
        form.addRow("Waived by", self.author)
        lay.addLayout(form)

        note = QLabel("The finding stays on the list, struck through, so the "
                      "decision stays visible.")
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid);")
        lay.addWidget(note)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._ok = bb.button(QDialogButtonBox.Ok)
        self._ok.setEnabled(False)
        self.reason.textChanged.connect(
            lambda t: self._ok.setEnabled(bool(t.strip())))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self) -> tuple:
        return self.reason.text().strip(), self.author.text().strip()


def _swatch(color: QColor) -> QIcon:
    pm = QPixmap(16, 16)
    pm.fill(color)
    return QIcon(pm)


def _fill_swatch(rgb, opacity) -> QIcon:
    """Swatch for the Fill button: a checkerboard shows through translucent /
    no-fill states so 'transparent' is visually distinct from 'white cover'."""
    from PySide6.QtGui import QPainter, QColor as _QC
    pm = QPixmap(16, 16)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    # grey checkerboard backdrop
    for i in range(0, 16, 4):
        for j in range(0, 16, 4):
            shade = 200 if ((i + j) // 4) % 2 == 0 else 235
            p.fillRect(i, j, 4, 4, _QC(shade, shade, shade))
    if rgb is not None and opacity > 0:
        a = int(max(0.0, min(1.0, opacity)) * 255)
        p.fillRect(0, 0, 16, 16,
                   _QC(int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255), a))
    p.setPen(_QC(120, 120, 120))
    p.drawRect(0, 0, 15, 15)
    p.end()
    return QIcon(pm)


class FillDialog(QDialog):
    """Pick an interior fill: a color plus a plain-language opacity slider
    (clearer than a raw alpha channel), or 'No fill'."""

    def __init__(self, color, opacity, parent=None, title="Fill"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._color = tuple(color) if color else (1.0, 1.0, 1.0)
        lay = QVBoxLayout(self)

        self.none_cb = QCheckBox("No fill (transparent)")
        self.none_cb.setChecked(color is None)
        self.none_cb.toggled.connect(self._on_none_toggled)
        lay.addWidget(self.none_cb)

        crow = QHBoxLayout()
        self.color_btn = QPushButton("Color…")
        self.color_btn.clicked.connect(self._pick_color)
        crow.addWidget(self.color_btn)
        self.swatch = QLabel()
        self.swatch.setFixedSize(48, 20)
        crow.addWidget(self.swatch)
        crow.addStretch(1)
        lay.addLayout(crow)

        srow = QHBoxLayout()
        srow.addWidget(QLabel("Opacity:"))
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(int(round(max(0.0, min(1.0, opacity)) * 100)))
        self.slider.valueChanged.connect(self._on_slider)
        srow.addWidget(self.slider, 1)
        self.pct = QLabel(f"{self.slider.value()}%")
        self.pct.setFixedWidth(40)
        srow.addWidget(self.pct)
        lay.addLayout(srow)

        hint = QLabel("0% = transparent · 100% = opaque cover")
        hint.setStyleSheet("color: gray; font-size: 11px;")
        lay.addWidget(hint)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._on_none_toggled(self.none_cb.isChecked())
        self._update_swatch()

    def _on_none_toggled(self, none_on: bool):
        for w in (self.color_btn, self.slider, self.pct):
            w.setEnabled(not none_on)
        self._update_swatch()

    def _on_slider(self, v: int):
        self.pct.setText(f"{v}%")
        self._update_swatch()

    def _pick_color(self):
        rgb = self._color
        col = QColorDialog.getColor(
            QColor(int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255)),
            self, "Fill color")           # no alpha channel — opacity is the slider
        if col.isValid():
            self._color = (col.redF(), col.greenF(), col.blueF())
            self._update_swatch()

    def _update_swatch(self):
        if self.none_cb.isChecked():
            self.swatch.setPixmap(_fill_swatch(None, 0.0).pixmap(20, 20))
        else:
            self.swatch.setPixmap(
                _fill_swatch(self._color, self.slider.value() / 100.0).pixmap(20, 20))

    def result_fill(self):
        """Return (color_tuple_or_None, opacity_float)."""
        if self.none_cb.isChecked() or self.slider.value() <= 0:
            return None, 1.0
        return self._color, self.slider.value() / 100.0

    @staticmethod
    def ask(parent, color, opacity, title="Fill"):
        """Show the dialog; return (accepted, color_or_None, opacity)."""
        dlg = FillDialog(color, opacity, parent, title)
        if dlg.exec() == QDialog.Accepted:
            c, o = dlg.result_fill()
            return True, c, o
        return False, color, opacity
