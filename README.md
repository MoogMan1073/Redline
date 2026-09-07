# DSI Redline

A lightweight, fast desktop app for reviewing AutoCAD Electrical drawing sets
(industrial-controls prints). It feels like the Chrome PDF viewer — clean
continuous vertical scroll, minimal chrome — and adds markup tools, a
comment/TODO workflow, and a **wire-number extraction & export engine**.

Built with Python + PySide6 + PyMuPDF. Fully functional offline; AI is optional.

_© DSI Innovations, LLC 2026_

---

## Features

- **Viewer** — open a PDF, continuous vertical scroll with page shadows, Ctrl+scroll
  zoom, fit-width / fit-page, space/middle-drag pan, page navigation. Pages render
  lazily and re-render crisper as you zoom in.
- **Markup tools** — select/move/**resize/rotate** (Word-style handles), highlight,
  freehand pen, eraser, sticky-note comments, on-page text boxes, rectangle & arrow
  shapes, **callouts** (text box + leader arrow) and **revision clouds** (freehand or
  click-polygon, outline only). Rectangles and text boxes take an **interior fill**
  with adjustable opacity — up to an opaque white cover. **Any** mark can carry a
  **note** (not just comments). Shapes preview live while you drag and stay editable
  afterward. **Copy & paste** marks (`Ctrl+C` / `Ctrl+V` or right-click), a **format
  painter** (copy one mark's colour/opacity/fill/font onto another of the same type),
  **sticky styles** (new marks inherit your last colour/font/fill), and **stacking
  order** (right-click ▸ **Order ▸** Bring to Front / Send to Back …). Full undo/redo
  (`Ctrl+Z` / `Ctrl+Shift+Z`). Every mark records its author and timestamp — and you
  can **rename a commenter** by double-clicking a name in the Comments / TODO list.
- **Hybrid storage** — marks are saved as standard PDF annotations into a
  `*.marked.pdf` copy (the original is **never** overwritten), while app-only state
  (TODO status, tags, wire cache) lives in a `*.markup.db` SQLite sidecar. Existing
  PDF annotations (e.g. a colleague's markup) are imported with their real authors.
  **Save As** (`Ctrl+Shift+S`) forks the whole markup to a new working file and
  switches to it, leaving the original untouched. If a file's name is too long or
  has characters that can't back a sidecar, it opens **view-only** — you can still
  view, search, print and use the PDF tools, but markup and saving are turned off
  until you rename it.
- **SHX / AutoCAD junk filter** — nuisance "SHX font could not be displayed" export
  comments are hidden (not deleted) and excluded from counts. Toggle "Show ignored"
  to reveal them. The pattern list is editable in Settings.
- **Comment sidebar** — dockable, filterable, sortable list of all comments; click to
  scroll to and flash the mark. Delete a comment via right-click, the `Del` key, or the
  🗑 button — always with a confirmation prompt, and always undoable.
- **TODO tab** — flag any comment/text box as a TODO; check off, edit inline, group by
  sheet/commenter, **click any column header to sort within groups** (with an ↑/↓
  indicator), and export to **Markdown** (GitHub task list) or **DOCX** (table with
  ☐/☑ glyphs). Checking a TODO off **strikes it through** both in the list and on the
  mark itself for a quick visual audit.
- **Wire Numbers tab** — extract, classify, spot-check and export wire numbers.
- **Component Labels tab** — the same engine for **device/component tags** like
  `LT-10010` (family code + sheet/rung). Known family codes live in Settings
  (seeded + editable); unlisted codes are captured and flagged. Choose **OCR or
  Claude** for scanned pages; same select/search/sort/export controls as wires.
- **Wire & component export** — `.xlsx` / `.csv`, single-file (`~sheet~` separators,
  labels-only) or one-file-per-sheet (full columns), configurable
  labels-per-wire/device, and multiple sort/filter modes.
- **PDF tools** — an iLovePDF-style **PDF Tools** workspace (thumbnail grid +
  operation rail) where you **pick pages by clicking thumbnails** to extract,
  split into ranges, delete, or rotate (with a live rotation preview) — plus
  combine, insert, swap, and convert to Word. A guided **sheet-number split**
  wizard (box the title-block number; works on rotated and scanned sets) and a
  **crop/extract** wizard that uses Claude to turn captured regions into editable
  docs — **tables → Excel, prose → Word, or everything → Markdown** (OCR with
  best-effort table reconstruction when no key is set). **Drag a PDF onto the
  window** to open it in the viewer or the tools.
- **Navigation dock** — page thumbnails + PDF bookmarks for jumping around a set.
- **Built-in user manual** — **Help ▸ User Manual** opens a read-only, Obsidian-style
  vault (the `docs/` folder) with a page list, clickable `#tags`, `[[wikilinks]]` and
  a graph view. The docs ship next to the app so they travel with every install.

---

## Wire-number encoding

Each wire label is a self-describing numeric string:

```
[ S S S ][ R R ][ W ]
  sheet    rung   wire-index-on-rung (0-based)
```

Default field widths are **sheet = 3, rung = 2, wire = 1** (6 digits total), all
configurable in Settings. Example: the **second** wire on **rung 14** of **sheet 432**
→ `432141` (the index is 0-based, so the first wire is `432140`). The sheet number
always comes from the label's own first digits — never from PDF page order.

Classification:

- **conforming** — parses cleanly to the configured field layout.
- **fixed / OEM** — a wire-ish token that doesn't follow the rule (legacy/OEM sets);
  still captured and labelled so you can include or exclude it.
- **jumper** — tokens on a layer whose name contains "jumper" (excluded by default).
  Jumper handling is silently skipped when the PDF exposes no layer data.

---

## Install

Requires **Python 3.11+**.

```bash
pip install -r requirements.txt
```

### Design rule checking (optional)

The rule library lives in [PyDRC](https://github.com/MoogMan1073/PyDRC), a
separate project. It is kept out of `requirements.txt` so the app installs
without needing access to that repository:

```bash
pip install -r requirements-drc.txt
```

Without it the Audit tab reports the rule library as unavailable and the rest
of the app is unaffected. See [CI.md](CI.md) for the CI side.

### Tesseract (optional — only for scanned/raster pages)

OCR fallback needs the Tesseract system binary in addition to the `pytesseract`
Python wrapper:

- **Ubuntu/Debian:** `sudo apt install tesseract-ocr`
- **macOS:** `brew install tesseract`
- **Windows:** install from the [UB-Mannheim build](https://github.com/UB-Mannheim/tesseract/wiki)
  and ensure it's on your `PATH`.

If Tesseract isn't present, the app still works — it just relies on the PDF text
layer (which is all that's needed for vector AutoCAD plots).

### Claude AI assist (optional — opt-in)

For OCR'ing/disambiguating wire numbers on scanned regions you can enable Claude
vision in **Settings ▸ OCR & AI assist**. Paste your API key directly into the
**API key** field (stored in the app config) and click **Check API status** to verify
it's valid; alternatively set the environment variable:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

The app is **fully functional with no key** — AI is never required.

---

## Run

```bash
python main.py            # then File ▸ Open PDF…
python main.py drawings.pdf   # or open a file directly
```

---

## A quick tour

The five panes below are **movable** — drag a tab out into its own window (e.g.
the TODO list on a second monitor) or dock it to another edge, like the Comments
and Navigation sidebars. **View ▸ Reset panel layout** restores the default.

| Tab | What it does |
|-----|--------------|
| **Viewer** | Read and mark up the drawing. Pick a tool from the toolbar, choose a color/width, and draw. The **Comments** dock on the right lists every note. |
| **TODO** | Everything flagged as a TODO. Check items off, edit text inline, group by sheet/commenter, and export to Markdown or DOCX. |
| **Wire Numbers** | Click **Extract wire numbers** to scan the set. Review the table (label, sheet, rung, index, type, page, count, source), untick any you don't want, then **Export…**. |
| **Component Labels** | Click **Extract component labels** to find device tags (e.g. `LT-10010`). Pick OCR or AI for scanned pages, review/filter the table, then **Export…**. Family codes are editable in Settings. |
| **PDF Tools** | Extract / split / delete / rotate / combine / insert / swap pages, convert to Word, the sheet-number split and crop/extract wizards. |

### Saving

- **File ▸ Save markup** writes `<name>.marked.pdf` + syncs the `<name>.markup.db`
  sidecar. The original PDF is untouched.
- **File ▸ Export annotated PDF…** writes a standalone annotated copy anywhere.
- **File ▸ Print…** (`Ctrl+P`) prints the drawing (with or without its marks — see
  **Print preview…**) to any installed printer via the system print dialog.

### Settings

Your name (commenter), wire field widths & zero-padding, full-label regex override,
labels-per-wire, the SHX/junk ignore-pattern list, "treat all comments as TODO",
OCR/AI toggles, the **Claude API key + live status check**, and export defaults — all
persisted between sessions. **Help ▸ About** shows the app name, version and copyright.

---

## Project layout

```
main.py                      QApplication entry
app/
  main_window.py             Window: docks the five panes (Viewer, TODO, Wire
                             Numbers, Component Labels, PDF Tools), toolbar,
                             menus, file lifecycle
  settings_dialog.py         The preferences dialog (five tabs)
  dialogs.py                 Text/callout editor, fill picker, waive-a-finding
  printing.py                Printer, print + preview dialogs, page raster
  config.py                  Persisted settings (QSettings) + defaults
  help.py                    In-app user-manual (vault) reader
  viewer/                    Continuous-scroll canvas, annotation items, tools, undo
  model/                     Document, annotation model, PDF+SQLite storage
  panels/                    Comment sidebar, TODO, Wire Numbers, Component Labels,
                             PDF Tools, Navigation
  extraction/                Text extraction, OCR, wire parser/classifier, Claude assist
  export/                    TODO (md/docx) and wire (xlsx/csv) exporters
  tools/                     PDF ops (split/combine/…), dialogs, sheet/crop wizards
docs/                        User manual (Obsidian-style markdown vault)
tests/                       Unit tests for extraction/export/storage/docs
```

## Building a Windows executable

A one-folder Windows app and an installer are produced by PyInstaller + Inno
Setup. The simplest path is CI: push a `v*` tag (or run **Actions ▸ Build
Windows**) and download the **portable** and **installer** artifacts. To build
locally on Windows, run `packaging\build_windows.bat` then compile
`packaging\installer.iss` with Inno Setup. The `docs/` manual is bundled with
the app so **Help ▸ User Manual** works on every machine. Full details in
[`packaging/README.md`](packaging/README.md).

## Tests

```bash
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests
```

The pure-logic core (wire parsing/classification, both export modes, the PDF
annotation round-trip and SHX filter, TODO export) is covered by the suite.
