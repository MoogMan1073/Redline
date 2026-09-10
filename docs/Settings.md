---
tags: [settings, reference]
---

# Settings

Open with **File ▸ Settings…**. Everything here persists between sessions. The
dialog is split into tabs so it stays compact on any screen, and this page has
one section per tab, in the order they appear.

## General

Four groups: who you are, what an export defaults to, what is treated as a
comment, and how pages print.

- **Your name** — stamped as the commenter on every new mark.

### Export defaults
- **Labels per wire**, **default mode** (single / per-sheet), **default format**
  (xlsx / csv). See [[Wire Export]].

### Comments & junk filter
- **Treat all comments as TODO** — new comments start flagged ([[TODO]]).
- **Show ignored** — reveal SHX/AutoCAD junk that's hidden by default.
- **Ignore patterns** — one regex per line; matching annotations are hidden, not
  deleted. See [[Storage and Files]].

### Printing
- **Minimum line weight** — AutoCAD plots most schematic geometry as a hairline,
  which prints at around 0.1 pt: faithful to the file and anemic on paper. This
  raises those to a minimum weight and leaves heavier geometry and all text
  alone.

## Wire numbers
- **Sheet / Rung / Wire-index width** and **Zero-pad** — define the label layout
  ([[Wire Encoding]]).
- **Full-label regex** — optional override of the detection pattern (e.g. `^\d{6}$`).
- **Cross-check sheet** — flag labels whose sheet differs from a title-block
  reading (off by default to avoid false flags on multi-sheet pages).
- **Scanned-page method** — default engine (**AI assist** or **OCR**) for pages
  with no text layer. You can also switch it per run from the Wire Numbers tab.

## Component labels

The same idea as wire numbers, for device tags ([[Component Labels]]).

- **Sheet width**, **Rung width** and **Zero-pad fields** — the label layout.
- **Scanned-page method** — **AI assist** or **OCR** for pages with no text
  layer, chosen separately from the wire-number setting.
- **Labels per device** — how many labels one device is expected to carry.
- **Family codes** — known device family codes, comma- or newline-separated
  (`LT`, `CR`, `PB`, …). A label whose code is not listed is **still captured**
  and flagged *unknown family* rather than dropped.

## OCR / AI
- **Enable OCR fallback** — use Tesseract on scanned pages ([[OCR]]).
- **Enable Claude vision assist**, **API key**, **Check API status**,
  **AI model** — see [[AI Assist]].
- **AI tiling (N×N)** — split each scanned page into an N×N grid, each tile read
  at full resolution so small wire numbers survive. Higher is more accurate and
  costs **N² API calls per page**; 1 is the whole page.

## Design rules

Only present in a build that has the rule library; without it the tab says so
rather than showing an empty list ([[Design Rule Check]]).

- **Draw findings on the sheet** — mark them on the drawing as well as listing
  them.
- **ODA File Converter** — path to the executable used to read DWG files, or
  blank to auto-detect.
- **The rule table** — one row per rule, with **Run** to turn it off and a
  **Severity** override. Editing here re-evaluates the findings already on
  screen rather than forcing a re-run.

#settings #reference
