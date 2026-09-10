"""The main toolbar: the tool group, the style widgets, zoom and page.

Cut out of `app/main_window.py`, which the backlog row records at **2,506
lines** and which is 60 methods of window. The row's own `remains` named the
toolbar and the menus together and said they *"build the same actions and may
not be separable, which is a measurement somebody has to take before cutting"*.

**The measurement says they are separable, and the discriminator is what each
one MAKES.** Over the two builders as they stood:

* they write **11 self-attributes each and share none** — the toolbar owns
  `tool_group`, `_tool_actions`, `color_btn`, `fill_btn`, `pen_width`,
  `font_size`, `bold`, `italic`, `zoom_combo`, `page_spin`, `page_total`; the
  menu owns ten `act_*` QActions and `m_recent`. Neither reads what the other
  writes.
* they overlap in exactly **one import** (`QKeySequence`). This module needs
  eleven widget classes the menu builder needs none of, because the toolbar
  **constructs** widgets where the menu **wires** methods that already exist.

So the cut is by kind rather than by size, and the claim it makes checkable is
`tests/test_module_layout.py::TestTheWindowDoesNotBuildChrome`: moving this out
leaves `QToolBar`, `QComboBox`, `QSpinBox`, `QDoubleSpinBox`, `QPushButton`,
`QCheckBox`, `QActionGroup`, `QAction`, `QLabel` and `QKeySequence` unused in
the window — measured, ten imports, not an argument.

`build(win)` hangs its widgets on the window because that is where every
consumer already reads them from: `_update_color_btn`, `_activate_tool`,
`_on_page_changed` and `load_document` all name `win.page_spin`,
`win.color_btn` and the rest. Handing back a namespace would be a second place
to look for one widget.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QLabel,
                               QPushButton, QSpinBox, QToolBar)

from .viewer import tools as T


def build(win):
    """Build the main toolbar and hang its widgets on `win`."""
    tb = QToolBar("Tools")
    tb.setObjectName("MainToolBar")
    tb.setMovable(False)
    win.addToolBar(tb)

    win.tool_group = QActionGroup(win)
    win.tool_group.setExclusive(True)
    # tools grouped by purpose; None marks a separator between groups
    tool_defs = [
        (T.TOOL_SELECT, "Select"),
        None,                                            # -- freehand markup
        (T.TOOL_HIGHLIGHT, "Highlight"), (T.TOOL_PEN, "Pen"),
        (T.TOOL_ERASER, "Eraser"),
        None,                                            # -- text / notes
        (T.TOOL_COMMENT, "Comment"), (T.TOOL_TEXTBOX, "Text box"),
        (T.TOOL_CALLOUT, "Callout"),
        None,                                            # -- shapes
        (T.TOOL_RECT, "Rectangle"), (T.TOOL_CIRCLE, "Circle"),
        (T.TOOL_ARROW, "Arrow"), (T.TOOL_LINE, "Line"),
        (T.TOOL_CLOUD, "Cloud"),
    ]
    # Ctrl+<digit> shortcuts are pinned to the tool, not to its position in
    # the toolbar, so inserting Circle/Line doesn't reshuffle the shortcuts
    # people already know. Circle and Line have none (the ten digits are
    # taken) — they're a click away on the toolbar.
    tool_keys = [T.TOOL_SELECT, T.TOOL_HIGHLIGHT, T.TOOL_PEN, T.TOOL_ERASER,
                 T.TOOL_COMMENT, T.TOOL_TEXTBOX, T.TOOL_CALLOUT,
                 T.TOOL_RECT, T.TOOL_ARROW, T.TOOL_CLOUD]
    tool_tips = {
        T.TOOL_CALLOUT: "Callout: click the target the arrow points at, click "
                        "again to end the arrow, then drag out the box and "
                        "click to finish (Esc cancels)",
        T.TOOL_CIRCLE: "Circle: drag out an ellipse — same fill, opacity, "
                       "resize and rotate as the rectangle",
        T.TOOL_LINE: "Line: drag a plain line (an arrow without the head)",
        T.TOOL_CLOUD: "Revision cloud: drag freehand, Shift+drag for a "
                      "rectangle, or click corners and double-click / Enter "
                      "to close",
    }
    win._tool_actions = {}
    for entry in tool_defs:
        if entry is None:
            tb.addSeparator()
            continue
        tool, label = entry
        act = QAction(label, win, checkable=True)
        act.setData(tool)
        # Ctrl+1..Ctrl+9 then Ctrl+0, pinned per tool (see tool_keys)
        if tool in tool_keys:
            n = tool_keys.index(tool) + 1
            digit = 0 if n == 10 else n
            act.setShortcut(QKeySequence(f"Ctrl+{digit}"))
            tip = tool_tips.get(tool, label)
            act.setToolTip(f"{tip}  (Ctrl+{digit})")
            act.setStatusTip(act.toolTip())
        else:
            tip = tool_tips.get(tool, label)
            act.setToolTip(tip)
            act.setStatusTip(tip)
        act.triggered.connect(lambda _=False, t=tool: win._activate_tool(t))
        win.tool_group.addAction(act)
        tb.addAction(act)
        win._tool_actions[tool] = act
        if tool == T.TOOL_SELECT:
            act.setChecked(True)
    tb.addSeparator()

    # color + widths
    win.color_btn = QPushButton("Color")
    win.color_btn.clicked.connect(win._pick_color)
    tb.addWidget(win.color_btn)
    win.fill_btn = QPushButton("Fill")
    win.fill_btn.setToolTip(
        "Interior fill for rectangles & text boxes — pick a color and "
        "opacity (drag alpha to 0 for no fill, 100% for an opaque cover)")
    win.fill_btn.clicked.connect(win._pick_fill)
    tb.addWidget(win.fill_btn)
    tb.addWidget(QLabel(" Pen "))
    win.pen_width = QDoubleSpinBox()
    win.pen_width.setRange(0.5, 20)
    win.pen_width.setValue(2.0)
    win.pen_width.valueChanged.connect(
        lambda v: setattr(win.view.tool, "pen_width", v))
    tb.addWidget(win.pen_width)
    tb.addWidget(QLabel(" Font "))
    win.font_size = QSpinBox()
    win.font_size.setRange(4, 96)
    win.font_size.setValue(12)
    win.font_size.valueChanged.connect(
        lambda v: setattr(win.view.tool, "font_size", float(v)))
    tb.addWidget(win.font_size)
    win.bold = QCheckBox("B")
    win.bold.toggled.connect(lambda v: setattr(win.view.tool, "bold", v))
    win.italic = QCheckBox("I")
    win.italic.toggled.connect(lambda v: setattr(win.view.tool, "italic", v))
    tb.addWidget(win.bold)
    tb.addWidget(win.italic)
    tb.addSeparator()

    # rotate whole document (permanent — writes a rotated copy)
    act_ccw = tb.addAction("↺", lambda: win.rotate_all_pages(270))
    act_ccw.setToolTip(
        "Rotate the view 90° counter-clockwise (in memory; marks rotate too)")
    act_cw = tb.addAction("↻", lambda: win.rotate_all_pages(90))
    act_cw.setToolTip(
        "Rotate the view 90° clockwise (in memory; marks rotate too)")
    tb.addSeparator()

    # zoom (− / editable % / +) + fit
    tb.addAction("−", win.view.zoom_out)
    win.zoom_combo = QComboBox()
    win.zoom_combo.setEditable(True)
    win.zoom_combo.setInsertPolicy(QComboBox.NoInsert)
    win.zoom_combo.addItems(
        ["50%", "75%", "100%", "125%", "150%", "200%", "400%"])
    win.zoom_combo.setCurrentText("100%")
    win.zoom_combo.setFixedWidth(72)
    win.zoom_combo.lineEdit().setAlignment(Qt.AlignCenter)
    win.zoom_combo.setToolTip(
        "Zoom level — pick a preset or type a percentage")
    win.zoom_combo.textActivated.connect(win._apply_zoom_text)
    win.zoom_combo.lineEdit().returnPressed.connect(
        lambda: win._apply_zoom_text(win.zoom_combo.currentText()))
    tb.addWidget(win.zoom_combo)
    tb.addAction("+", win.view.zoom_in)
    tb.addAction("Fit W", win.view.fit_width)
    tb.addAction("Fit P", win.view.fit_page)
    win.view.zoomChanged.connect(win._on_zoom_changed)
    tb.addWidget(QLabel("  Page "))
    win.page_spin = QSpinBox()
    win.page_spin.setRange(1, 1)
    win.page_spin.valueChanged.connect(lambda v: win.view.go_to_page(v - 1))
    tb.addWidget(win.page_spin)
    win.page_total = QLabel(" / 0")
    tb.addWidget(win.page_total)
    win._update_color_btn()
    win._update_fill_btn()
    return tb
