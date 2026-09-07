# DSI Redline (`PDF_MarkupApp`) — working notes

A desktop reviewer for AutoCAD Electrical drawing sets: continuous-scroll PDF
viewing, markup, a comment/TODO workflow, wire-number extraction and export,
and an optional design-rule audit. PySide6 + PyMuPDF, fully functional offline.

`README.md` is the feature list. `CI.md` is the workflows, the skip rules and
the release ordering, and is authoritative for all three. `docs/` is the user
manual, served in-app by `app/help.py`. This file is the standing rules.

## Run it

```bash
pip install -r requirements.txt        # the app
pip install -r requirements-drc.txt    # ...and design rule checking (private)
python tools/run_tests.py
python main.py
```

**CI runs that on Ubuntu and Windows with `--strict`, and with
`--require-drc` whenever the PyDRC token is present — so a skip fails the
run rather than hiding under a green tick.** That is the claim worth having
and it is gated:
`tests/test_run_tests.py::TestMissingOptional`'s
`test_require_drc_is_passed_only_when_the_library_was_installed` reads the flag
out of the workflow step's own `run:` script. A local run
without Qt's system libraries reports far fewer tests and says so loudly —
see below.

### The count that used to sit here, and why it does not any more

Both of these documents said *"CI's last green run on `main` reports **682
tests across 53 modules; 0 skipped**"*. When somebody next ran it the answer
was **720 across 56**, and this file had by then accumulated **three
different numbers** — 682/53 in the header, 713/55 and 716/56 in two
narratives further down. A reader comparing their own run against the header
cannot tell which to believe.

The sentence merged two claims with opposite properties, which is what let it
rot unnoticed:

| permanent | volatile |
|---|---|
| CI skips nothing, because `--strict` / `--require-drc` turn a skip into a failure | how many tests there are |
| a local run without Qt reports far fewer, and says so | what that number is today |

The permanent half is gated and stays. The volatile half is **removed rather
than restamped** — a number merely updated is wrong again the week after, and
nothing reads it in between. `tools/run_tests.py` prints the current answer,
with the skips grouped by reason.

The two narrative counts below (713/55, 716/56) stay: each is a dated
before/after measurement that is the evidence for the paragraph it sits in,
not a claim about the suite today. That distinction is the whole rule —
**a snapshot cited as evidence keeps its date; a snapshot standing in for the
current answer gets deleted.**

## The original file is never overwritten

Storage is deliberately hybrid, and this is the one boundary a change must not
cross:

- marks are written as standard PDF annotations into a **`*.marked.pdf` copy**,
  so another tool can read them and the source drawing set is untouched;
- app-only state — TODO status, tags, the wire cache — lives in a
  **`*.markup.db` SQLite sidecar** beside it.

A file whose name is too long or carries characters that cannot back a sidecar
opens **view-only** rather than half-working: view, search, print and the PDF
tools stay available and markup is turned off until it is renamed. Degrading to
a named, explained state beats saving somewhere the user did not ask for.

### ...and until 1.5.2 it was a sentence, not a rule

The boundary was stated in five documents and enforced nowhere. `save()`'s own
docstring said *"The original PDF is never overwritten"* directly above the line
that did it: `export_annotated_pdf` forwarded a save dialog's path straight into
`save(marked_path=...)`, and every write in the app took its destination on
trust. Measured, not argued:

| aimed at | result |
|---|---|
| `export_annotated_pdf(the open drawing)` | replaced, **no `.marked.pdf` written at all** |
| ...and every save after that | wrote **two** copies of every mark, for ever |
| `export_annotated_pdf(a neighbouring drawing)` | 3 pages → 1, replaced by the acting document |
| `export_flattened_pdf(a neighbouring drawing)` | same, and **unrecoverable** — baked into page content |
| `extract_pages(src, src, merge=True)` | 4 pages → 1 |
| `split_ranges(src, src, merge=True)` | 5 pages → 2 |
| `combine_pdfs([src, other], src)` | 4 pages → 6 |
| `rotate_pdf(a, an unrelated drawing)` | 4 pages → a 3-page rotated copy of `a` |

**PyMuPDF refuses some of this itself** — `save to original must be
incremental` — and the two things that get past it are worth knowing, because
they are what made a stated boundary a false one:

* **The library's check only sees a save from the document that opened the
  file.** Every page tool builds a *new* `fitz.Document` from the pages it read,
  so the check never fires and the write lands.
* **`save()`'s own atomicity machinery defeats it.** The `out_is_open`
  temp-and-`os.replace` branch exists so an open `.marked.pdf` can be re-saved
  on Windows; aimed at the original it turns a refusal the library would have
  issued into a successful destruction. The safety net was there and the app
  routed around it.

**The doubling is the part a user could not undo.** Once the original carries a
mark, `original_pdf_path` still resolves to it and `is_marked_pdf` says False,
so the `strip_annotations` branch that exists to stop re-saving doubling the
marks is unreachable — and the `.marked.pdf` carries every mark twice from then
on, whatever you do.

**What is enforced now, and where.** One guard, in `app/model/storage.py` beside
the path helpers, called from every write:

1. `refuse_protected(out, doc_path)` — never write **this document's original**.
   Refused even when that file is absent, because writing it would *create* the
   pristine base every later open reads from.
2. the same rule for **another drawing that holds marks here** — a reviewer works
   on a folder, and a save dialog opened in it puts every drawing one click away.
3. `refuse_overwriting_input(out, *inputs)` — a page tool may not eat its own
   input.

`app/tools/pdf_ops.py` routes all eleven of its writers through one `_guard_out`,
and `tests/test_never_overwrite_original.py` walks the module's AST and fails on
a writer that has none — a gate over the artifact rather than over a list of the
functions that existed when it was written.

**Two things the rules deliberately do NOT do**, because measuring said so:

* **Rule 2 asks whether the sidecar holds ANNOTATIONS, not whether it exists.**
  Opening a PDF creates its `.markup.db` unconditionally, so "a sidecar is
  present" means "seen here" and nothing more. The existence test refused an
  ordinary second export and broke two of this repo's own regression tests,
  which fork onto a name whose sidecar was pre-seeded with wires and waivers.
* **A PDF this app has never opened is not protected.** It is indistinguishable
  from a stale export, and the save dialog has already asked about replacing it.
  Redline protects what it can identify; saying which is the point.

### Two dead gates were written before the live ones

Both passed on the exact defect they were written for, and both were found by
injecting it rather than by reading them:

* the AST sweep counted only `.save(`, so `pdf_to_docx` — which writes through
  pdf2docx's `convert()` — was **not counted as a writer at all**, and removing
  its guard changed nothing. It now takes a set of write calls and asserts the
  scan is still *finding* at least ten writers, so a rename cannot make it match
  nothing and go green.
* the `same_path` test used a **symlink**, which `os.path.realpath` resolves —
  so the fallback answered it alone and deleting the `os.path.samefile` branch
  kept the test green. A **hard link** has two real names `realpath` does not
  collapse, and the fixture asserts that before it asserts anything else.

And the falsification loop itself was dead first: `2>/dev/null` on a
`python -m unittest` run discards the results, so eight injections in a row
reported *nothing fired*. **If a falsification says the gate did not fire,
suspect the reading before the gate.**

## Three optional dependencies, one pattern

`pydrc` (design rules), `ezdxf` (reading AutoCAD Electrical source drawings),
and `anthropic` (AI extraction) are each absent on some real installs. Every
one of them **reports itself unavailable in the place it would have been used**
— the Audit tab, the import dialog, the extraction path — rather than raising.

Only `requirements.txt` is the app. PyDRC lives in `requirements-drc.txt`
because that repository is **private**, and a plain
`pip install -r requirements.txt` would otherwise fail for anyone without
credentials, CI runners included.

## ...and seven modules ERRORED rather than skipping, which is the same failure louder

`CONTRIBUTING.md` calls a machine without Qt "not a failure" and the section
above is about skips being invisible. Seven modules did neither: they **errored**
— which is loud, and loud about the wrong thing. `No module named 'PySide6'` on
a checkout where nobody has installed the requirements reads as a broken repo,
and it makes a legitimately-degrading run look like a failing one. Same class as
`TestRolledUpFindingOnScreen`, and the same class this repo fixed in PyDRC for
`ezdxf` one repo over — *fixing a class of bug only where it was noticed.*

**The guard they were missing is not the one they had.** Three of the seven
already carried `try: from PySide6... except: _QT_OK = False` and still died,
because what they import at module scope is `app.config` or `app.help`, and Qt
arrives **through those**. A probe of the direct import cannot see a transitive
one. Two shapes, one cause:

| module | died at | through |
|---|---|---|
| `test_help` | module scope | `app/help.py:16` |
| `test_v12_recent`, `test_v14_search` | module scope | `app/config.py:14` |
| `test_cli_open` | inside the test | `main.py:9` |
| `test_crop_tags`, `test_region_export` | inside the test | `app/tools/wizards.py:11` |
| `test_v12_author` | inside the test | `app/viewer/command_stack.py:13` |

- **A decorator cannot save a module that never loads**, so the three
  module-scope cases needed their `app.*` import guarded as well. The other four
  load fine and only needed the decorator.
- **`tests/_qt.py` is one probe, not a twenty-ninth copy**, and it probes the
  thing rather than a proxy: whether `PySide6` imports at all. `except
  Exception`, not `except ImportError`, because the documented Linux failure is
  `libEGL.so.1` raised from inside the extension module.
- **A test that is semantically Qt-free can still need Qt to run.**
  `TestRecentConfig` says *"the stored list itself (no GUI)"* and builds
  `AppConfig`, which is `QSettings`. Skipping it is honest; erroring was not.
  Making `app.config` Qt-free is a product change and is deliberately not done
  here.

**Verified in BOTH directions, which is the only way to tell a fix from a
withdrawal.** A skip added where a test used to run is coverage lost, and it
looks identical to a fix in the without-Qt direction alone. So PySide6 was
installed and the suite measured before and after: **713 tests across 55
modules, 28 skipped, identical per-module results and identical skip reasons** —
the change is inert when Qt is present, by construction (`skipUnless(True)` is a
no-op and every new import guard is `if _QT_OK:`).

The first attempt was **not** inert: a scripted rewrite half-applied to
`test_v12_author`, adding the decorator without the import it referenced, and
the module died with `NameError`. 713 → **707**, and those 6 lost tests are that
one module exactly. Caught by comparing against the baseline rather than by
reading the diff — the third mechanical-rewrite defect this family has had, after
Canal's two.

`tests/test_qt_absent_degrades.py` is the gate, and it **sweeps the artifact**:
every `tests/test_*.py`, loaded and run with `PySide6` blocked, asserting zero
errors. A gate naming those seven covers what was broken the day it was written;
the eighth module to reach Qt through a new `app.*` import fails here instead.
6.4 s. Falsified nine ways — each of the seven guards stripped in turn (each
caught, each naming its own module), plus the blocker neutered, plus a
module-count floor so a sweep that finds nothing cannot read as a pass.

### ...and the gate itself was the only thing that failed on Windows

The fix landed green on all three Ubuntu legs and red on all three Windows ones.
The suite reported **716 tests across 56 modules, 16 skipped**, with every one of
the seven repaired modules reporting `ok` — and `FAILED MODULES:
tests.test_qt_absent_degrades`. The repair worked on Windows; the gate written to
prove it did not.

- **`/dev/null` does not exist on Windows.** The sweep gave its runner
  `stream=open("/dev/null", "w")`, which there resolves to a directory that is
  not present, so the subprocess died and the module failed. A latent platform
  failure of exactly the shape this file already records for a leaked PyMuPDF
  handle: **green locally, red only on `windows-latest`**, and unreachable from
  the local suite. `io.StringIO()` needs no filesystem at all.
- **The message written to explain a dead sweep explained nothing.** Its f-string
  carried `{{r.stderr[-3000:]}}` — doubled braces, correct inside the *generated
  subprocess source* one line above and wrong in the test's own f-string — so it
  printed that text literally instead of the traceback. The CI log therefore
  named no cause at all, which is why the fix had to be reproduced locally
  before it could be diagnosed.

`tests/test_suite_is_discoverable.py` gained the sweep, since this repo runs
Windows in CI and a POSIX device path in `tests/` is a Windows-only failure by
construction. **Two things stop it firing on itself, and neither is an
exemption** — its first draft flagged its own needle table and its own
docstring, which is the shape this repo keeps paying for, and the standing
answer is to tighten the check rather than waive the text explaining it:

- the needles are **assembled** (`"/" + "dev"`) rather than written, so the file
  contains no literal matching what it searches for;
- **a docstring is not code.** Bare string expressions are excluded
  structurally, which is a general statement about what counts rather than a
  carve-out for one module.

Both directions are asserted in the module itself — a docstring mentioning the
path is not a finding, a path passed to a call is. Falsified three ways: the
POSIX path restored (caught), Windows simulated by pointing at an absent
directory (the message fires *and now carries a real traceback*), and the
docstring exclusion removed (the gate fires on prose, proving the exclusion is
load-bearing).

## A SKIP IS HOW COVERAGE EVAPORATES UNDER A GREEN TICK

The audit tests skip when PyDRC is missing, so a run without it goes green
having exercised none of the design-rule code. `tools/run_tests.py` therefore
prints the library's status first, **groups every skip by its stated reason**,
and ends with a loud banner per reason naming how many tests it covered.
`--strict` (Qt) and `--require-drc` (the rule library) turn those skips into a
failed run, and both workflows pass them.

Two things that were wrong here and are worth not repeating:

- **`--require-drc` was read through a pipe.** A bash pipeline's exit status is
  the *last* command's, so `run_tests.py … | tail` reported success over a red
  suite. Measure an exit code without a pipe.
- **One banner was built for every gap.** A fix that rewrote the cause on all
  skips made 54 Qt skips read *"the design rule library could not be
  imported"* — a banner that is loud, prominent and about the wrong thing.
  Build each banner from its own gap.

## Each test module runs in its own process

Not fussiness. Running the whole suite in one process accumulates Qt GUI
resources across the many window-creating tests and **hard-crashes a late
module on the headless Windows runner**, while every module passes alone.
Per-module isolation bounds resource use and names the module that failed
instead of leaving a bare crash in the log.

Qt needs a display; the runner sets `QT_QPA_PLATFORM=offscreen` itself.

On Linux it also needs Qt's system libraries, which a bare box does not have.
Without them `import PySide6.QtGui` fails with `libEGL.so.1: cannot open shared
object file` and about a third of the suite turns into skips. `CI.md` carries
the package list.

## An open PyMuPDF handle is a Windows file lock, and Linux cannot see it

A `fitz.Document` left open holds the file. On Windows that makes `os.remove`
raise `WinError 32` and makes a save onto that path raise *"cannot remove file
… Permission denied"* from inside PyMuPDF; on Linux both succeed. So a test
that leaks a handle is **green locally and red only on `windows-latest`** —
which is what `tests/test_never_overwrite_original.py` did on its first run:
two errors, both in the fixture, none in the code under test, on a leg the
local suite cannot reach.

The app itself is careful about this and always has been — `open_pdf` closes
the previous document before it swaps (`main_window.py:1364-1368`) and so does
`closeEvent`. It is **test** code that forgets.

**The fix is to assert the CAUSE, which is checkable on Linux.** Waiting for
the effect means waiting for CI. `assertNoOpenHandle(path)` walks the fixture's
own documents and fails when one is still open on that path, so deleting a
`close()` fails immediately on any platform. Five leaks were reintroduced in
turn and every one goes red here.

Two ways the falsification of that was wrong before it was right, both worth
more than the fix:

* **An injection that also deletes the assertion proves nothing.** Three of the
  first four removed the `close()` *and* the check beside it, reported "0
  failing", and read exactly like four dead gates.
* **An assertion pointed at the wrong file reads like a live one.** One checked
  the `.marked.pdf` where the released handle was on the original, so it was
  vacuously true and the leak beside it fired nothing.

## A release names the rules it ships

An installer that cannot say which rules it contains is one nobody can
reproduce. `packaging/pydrc-ref.txt` names the PyDRC ref, whatever it names is
**resolved to a commit SHA** before installing, and that SHA lands in the build
log and the release notes — so a branch cannot move underneath a build and two
runs of one tag cannot quietly differ.

Cutting a release is three steps **in this order**:

1. tag PyDRC (`v0.2.0`);
2. set `packaging/pydrc-ref.txt` to that tag here and commit it;
3. tag the app (`v1.5.0`).

Tagging the app before step 2 produces a release whose notes name a moving
branch, which is the one thing the pin exists to prevent.

The version is declared in **three** places — `app/__init__.py`,
`packaging/installer.iss` and a `CHANGELOG.md` section — and
`tests/test_requirements.py::TestVersionIsStatedOnce` fails when they disagree.
That gate is right and this line used to say "declared once", which is the
claim it exists to disprove: it caught the 1.5.2 bump within a minute of it
being made in one file.

## A test that hides itself runs a smaller number, and nothing reports that

Two ways a module here ran fewer tests than it holds. Neither is a failure —
both are a *smaller number*, and no runner calls that anything.

- **A misplaced `if __name__ == "__main__"` block hides everything below it
  from a direct run.** `python3 tests/test_requirements.py` ran **3** tests
  where `python3 -m unittest tests.test_requirements` ran **5**: the guard sat
  at line 44 and `TestVersionIsStatedOnce` began at 48, so the two that vanished
  were **the version-drift gates** — the ones that exist because the installer
  once sat at 1.4.0 while the app moved on.

  Four modules carried the guard mid-file. In three it was harmless *only*
  because they import `app` at module scope and cannot be run as scripts at all
  — luck rather than design, and the kind that expires the first time somebody
  moves an import.

- **A Qt-dependent class without the `skipUnless` its siblings carry errors
  instead of skipping.** `TestRolledUpFindingOnScreen` had none, so a machine
  without Qt got `FAILED (errors=1, skipped=31)` where it should get a clean
  skip. Loud, which is the safe direction — and loud about the wrong thing,
  which makes a legitimately-skipping run look broken.

`tests/test_suite_is_discoverable.py` sweeps **the artifact** for both, never a
list of the modules that had the problem when it was written — a gate scoped to
today's offenders covers what was there when the list was made.

### ...and its first draft cried wolf, which is the half worth keeping

The Qt sweep flagged `test_v12_order.py::TestDrawNewOnce`, a working class in a
module that skips cleanly (10 of 10). `unittest.skipUnless` sets
`__unittest_skip__` on the class it decorates and **a subclass inherits it** —
measured rather than assumed: a child of a skipped base reports
`OK (skipped=2)` and `Child.__unittest_skip__` is `True`. So `_Base` covers
both classes under it. Ancestry counts now, resolved within the module, which
is where these bases live.

**An audit that flags a working file is one nobody reads twice.** Calibrate
before believing it — and the stated limit is direct use only: a class calling
a module-level helper that touches a guarded name is not caught, and widening
that means resolving calls, which is a different tool.

### The version rule and the version gate had been contradicting each other

`CONTRIBUTING.md` listed *"a version number anywhere but `app/__init__.py`"*
among the things that fail review, three feet from
`TestVersionIsStatedOnce`, which exists **because there are three** and fails
when they disagree. **A rule and a gate that contradict each other teach people
to trust neither**, and here it was the rule that was wrong. `CLAUDE.md` was
corrected at the 1.5.2 bump and `CONTRIBUTING.md` was not — the same
fix-where-it-was-noticed pattern, one file over.

## Three documents that described something other than the code

Each was true when written and read by nobody since. They are together because
the answer is the same in all three: **where a fact is already decided
somewhere, a hand-kept description of it is a copy that drifts**, so the fix is
a gate that asks the deciding thing rather than a better sentence.

### A shipped-release document must not become a help page

`app/help.py`'s `load_vault` reads `folder.glob("*.md")` — non-recursive — so
`docs/*.md` is the user manual and the write-once records in `docs/history/`
do not reach it. **That invariant was stated in `docs/history/README.md` and
enforced by nothing**, and it fails quietly two ways:

- the glob going recursive publishes **seven test plans and feature summaries
  as help pages in one edit**, and every existing assertion in `test_help.py`
  still passes, because they are all about pages that *are* present;
- a record moved up into `docs/` is invisible to any check about
  `docs/history/`, because by then it is no longer in it.

So the first is asked of the **function** — a temp directory with a
subdirectory in it — never of the glob's spelling, because the comment above
that line names the very call a source scan would be hunting for. The second
is asked of the **directory's own manifest**, which is the only thing that
knows what belongs there. Both carry a floor: an empty vault satisfies *"no
history page is in it"* perfectly.

Falsified three ways, each on its own arm: `glob` → `rglob` (2 fail),
`git mv docs/history/V1.3.0_FEATURES.md docs/` (the manifest test, and
**pointedly not** the absence test — which is the design), and the manifest
table emptied.

**And the manifest check was scoped to the page before it was scoped to the
table.** Swept whole, the README also names `docs/*.md` and the five living
documents at the repository root, so it reported six phantom absences on its
first run. Table rows only, and a name carrying a separator or a glob is prose
about a path rather than a file in that directory.

### `docs/Settings.md` named four tabs where the dialog builds five

No section for **Component labels** or **Design rules** — so the family-code
list, the per-rule enable, the severity override and the ODA converter path
were undocumented in the one page a user opens to find out what a setting
does. The page is organised by tab now, one `##` per tab.

- **The tab names are read off the RUNNING dialog**, never off a second
  reading of `app/main_window.py`. `tests/test_settings_layout.py` already
  builds the real `SettingsDialog`, so the gate asks it: the document
  describes what a person sees, and a source scan would form its own opinion
  about which `addTab` calls run.
- **Order as well as membership**, because a manual whose sections are in a
  different order from the tabs is a manual you cannot read alongside the
  dialog.
- **A heading is cheap, so the content is gated too** — the six controls that
  had no mention anywhere are asserted by name. Falsified three ways: the old
  four-tab page restored (2 fail), a tab dropped from the dialog, and the
  sections reordered.

### The reproducibility claim, and the one pin behind it

`packaging/pydrc-ref.txt` ended *"...and rebuilding that tag years later
produces the same installer"*. **It pins one dependency of ten.** Measured:
nine unbounded floors in `requirements.txt` — the PDF engine and the whole GUI
toolkit among them — and a tenth in `packaging/requirements-build.txt`, so a
rebuild resolves each to whatever is newest that day.

The rule library really is pinned and resolved to a SHA before it is
installed, which makes *"which rules does this installer contain"* answerable
— the question that file exists for, and the one a design-rule finding turns
on. What it cannot carry is a claim about the **artifact**, and that is who it
costs: somebody reproducing a finding from a year-old release reads the
sentence and stops looking.

- **Corrected rather than pinned, and the limit is stated.** A lock file for
  the other ten is the fix for the artifact, and it cannot be produced or
  verified from this container — the build is Windows-only.
- **Gated in BOTH directions**: the strong sentence is refused while a floor
  remains, and the narrow one is refused the day they are all pinned, because
  a file underselling a guarantee the build now gives is the same drift
  pointing the other way — and it is the one a person adding a lock file has
  no reason to come back and fix.
- **THE GATE FIRED ON ITS OWN CORRECTION.** The retraction quotes the sentence
  it retracts, deliberately, because the history is what stops it being
  written back. The standing answer here is to tighten the check and never
  waive the text explaining the defect, so what is refused is the sentence
  made **as a claim** — outside quotation marks — with a companion test
  asserting the quotation is still there, or the carve-out passes over a file
  that simply never mentions the subject.
- Falsified five ways, each on its own arm: the strong claim restored, every
  requirement pinned with the narrow claim left standing, the scope sentence
  deleted, the quotation removed, and the ref swallowed by the comment block.

### ...and the suite runs in full in this container now

`CLAUDE.md` has said *"no interpreter in this container has PySide6"* since the
interpreter matrix landed. `pip install PySide6` and `pip install -r
requirements.txt` both succeed here — measured, **735 tests across 57 modules,
28 skipped**, every module passing, with the only skips being PyDRC (private)
and `ezdxf`. So a Qt change no longer has to be shipped on a reading.

What that does **not** cover is unchanged: only 3.11 is installed, so the 3.12
and 3.13 legs are still CI's to verify, and nothing here builds the Windows
installer.

## The window held four dialogs, and the convention says where a dialog lives

`app/main_window.py` was **2,506 lines** — 718 more than the next largest
module, and 8.6% of a 29,260-line codebase — holding the preferences dialog,
five panes, the toolbar, the menus and the file lifecycle. The README's own
layout block described it that way (*"Window: five … panes, toolbar,
Settings"*), so the document was right about a thing that was wrong.

**The finding is not the line count, and it is not a home that was ignored
either** — which is what a first draft of this section claimed, before the
package was measured. The rule this repository already follows is *a dialog
lives beside the subject it serves*: `app/tools/dialogs.py` holds
`_ToolDialog` and seven page-operation dialogs, `app/tools/wizards.py` two
more, and the README names both under `tools/`. That convention is intact and
was never broken. **The four in the window are the ones with no subject
package to go to** — preferences, the text/callout editor, the fill picker,
waive-a-finding — so they accreted at the place they happened to be opened
from, which is the one location the convention does not name.

- **Cut by AST span, and the grouping was MEASURED rather than eyeballed.**
  Asking which top-level names each unit references gives
  `TextEditDialog -> {FillDialog, _swatch, _fill_swatch}`,
  `FillDialog -> {_fill_swatch}`, and **`SettingsDialog -> {}`** — so the
  preferences dialog is a clean standalone and gets its own file, while the
  editor, the fill picker and their swatch icons genuinely travel together.
  `_apply_font` and `WaiveDialog` reference nothing and travel with them
  because they are the same subject, which is stated rather than implied.
- **2,506 → 1,879**, and the rest is **named rather than glossed**: the five
  panes, the toolbar, the menus and the lifecycle are all still in there. The
  module docstring says so, and the row is recorded `partial` for that reason —
  half the value of recording a partial is naming the other half.
- **Eighteen imports went dead the moment the dialogs left**, and every one was
  cross-checked with a text scan before removal: each appeared exactly once,
  which is the import itself. `annotations` stays — it is `from __future__`.
- **The tests were re-pointed at the new homes, and that is the half that makes
  the split checked.** Four modules imported these names `from app.main_window`,
  and they would have gone on passing untouched, because `main_window` legitimately
  imports what it opens — so the names are still in its namespace. A green suite
  there proves the window still works, not that the new module does.
- **Verified in BOTH directions, which is the only way to tell a fix from a
  withdrawal** — this file's own rule from the Qt-degradation round. Before:
  **735 tests across 57 modules, 28 skipped**. After: **740 across 58, 28
  skipped**, identical skip reasons, every module passing under `--strict`. The
  +5 is the new gate module; no test was lost and no skip was added.

### The gate is a KIND of thing, never a line count

A count is a snapshot — wrong by the next commit, and this file already
removed three of them from its own header for exactly that. What
`tests/test_module_layout.py` asserts instead is that **no dialog class is
defined in `app/main_window.py`**, which is permanent, is what was extracted,
and is what an accumulation would look like on its first step.

- **By base class, not by the class's own name.** A class called `FooDialog`
  subclassing `QWidget` is not one and a `QDialog` subclass called `Prefs` is,
  so the sweep reads the bases.
- **...and the first draft read DIRECT bases only, which left a reachable
  hole.** `app/tools/dialogs.py` declares `_ToolDialog(QDialog)` and seven
  subclasses **of it**, all importable — so a `class Foo(_ToolDialog)` back in
  `main_window` was exactly the accumulation this gate exists to catch and
  exactly what it could not see. A base whose *name* ends in `Dialog` counts
  too, which is not the name-check the bullet above argues against: it is a
  claim about what the class derives from rather than about what it is called.
  **Measured before it was taken**, because a widening that admits noise is a
  gate people learn to dismiss: across `app/` it admits those seven and
  **nothing else**, 7 classes over four files becoming 14, zero false
  positives. That number is what made it a fix rather than a stated limit.
- **Two floors, because an absence assertion agrees with an empty checkout.**
  The extracted classes must be findable in their new homes, and the sweep must
  still find dialogs across `app/` at all — without the second, renaming the Qt
  base names the sweep knows switches the whole module off while every
  assertion above it still passes. That arm fires, measured.
- **The README block is gated against the filesystem, never against a second
  document.** Every `.py` it names must exist, and the two new modules must be
  named — the block described the god-object accurately for as long as it was
  true, and a layout block that stops matching the tree sends a reader to the
  wrong file.
- **And one of those floors was a COUNT ASSERTION WEARING A FLOOR'S MESSAGE.**
  The block names five modules and the floor read `> 4`, so removing any line
  from the README fired it — reporting *"the parse is not finding module
  names"* about a block that had parsed perfectly, which is a note carrying a
  reason that is not its own. It is `> 2` now: what it has to catch is the
  parse breaking, which takes it to zero or one. Caught because the arm that
  deletes a README line fired **two** tests where one was expected, so the
  expectation was the thing that was wrong.

Falsified seven ways, each on its own arm and every one firing: a dialog moved
back into the window, an **indirect** dialog moved back into it, each extracted
class stripped of its Qt base in turn, the sweep's base names renamed away
(which fires the floor **and** the new-home check, correctly — one injection,
two things it makes vacuous), the README no longer naming a new module, and the
README naming a module that does not exist.

### The base-rename arm was net-ZERO bytes, and Python's cache could not see it

That arm reported `DEAD` against a gate that fires two failures when the same
injection is made by hand — this repository's own standing rule arriving on
schedule: **if a falsification says nothing fired, suspect the reading before
the gate.**

The cause is arithmetic and worth keeping, because nothing about it looks like
a trap. The rename is `QDialog`→`QNotADialog` (+4), `QMessageBox`→`QNope` (−6),
`QFileDialog`→`QAlsoNope` (−2), `QColorDialog`→`QStillNope` (−2) and then
`"Dialog"`→`"NoSuchSuffix"` (+6) — **exactly 0**, measured rather than noticed:
6,899 bytes before and 6,899 after. CPython invalidates a `.pyc` on
**`(mtime, size)`** at one-second resolution, so a restore-then-edit-then-run
inside one second handed the subprocess **stale bytecode of the uninjected
file**. Every other arm edited an `app/` module whose length changed, which is
why four of seven were unaffected and the two that were not looked like dead
gates.

**A falsification loop that injects into the TEST file must purge
`__pycache__` and run `-B`.** The arms that edit the *subject* are safe by
luck — they change a length — and the arm that edits the *instrument* is the
one nobody thinks to protect, which is the same shape as the snapshot rule one
line over: it is the instrument rather than the subject.

## ...and then printing, which is a subject rather than a property of a window

409 contiguous lines of `main_window.py` — nine methods and four class
constants — were the printer, the two print dialogs and the page raster. They
are `app/printing.py` now, and the module is **1,879 → 1,492**.

- **One contiguous span, which is what made "nothing was lost" assertable.**
  `_new_printer` at 903 through the end of `_print_page` at 1311, with no
  non-printing method between them, so the cut is a slice and the check is that
  the slice put back beside what stayed reproduces the file it came from.
- **The conversion is a parameter list rather than a redesign, and that was
  MEASURED before the cut.** Every one of the nine either already carried
  `@staticmethod`/`@classmethod` or touched `self` for nothing but `document`
  and the two print settings. So the pure half — `fit`, `render_dpi`,
  `paint_page` — is callable with no Qt window at all, which is what
  `tests/test_v12_print.py` had always driven it as.
- **`PrintOptions` exists because the preview WRITES the settings.** The
  toolbar's markups checkbox and line-weight picker set them and the job reads
  them; with the code out of the window, two window attributes it wrote back
  into would be the printing code half out of the window. One small mutable
  object, held by `MainWindow` as `self.print_options`.
- **The status bar stayed the window's.** `run_print_dialog` returns the
  sentence and `MainWindow.print_document` shows it — a printing module that
  knew which widget has a status bar would be the window's business back in
  here under another name.
- **`self._preview_weight_combo` did not travel, because it is write-only —
  measured, not reasoned.** Assigned once and read nowhere in the repository.
  Driven under Qt: a combo added with `QToolBar.addWidget` and then dropped on
  the Python side survives `gc.collect()` and is still usable through
  `widgetForAction`, because the toolbar takes ownership — and the `_changed`
  closure holds it as well. A keep-alive that keeps nothing alive.
- **A clause of the module docstring was WRONG and had been carried forward
  unread.** It named "the five panes" as still in the window; `app/panels/`
  holds eight pane modules and has for a long time. What the window holds is
  their DOCKING. That is the same drift this file already gates one document
  over, in the docstring of the module being unwound.

### The gate is the same KIND of claim, in printing's vocabulary

*The window neither drives a printer nor rasterises a page.* Permanent,
exactly what was extracted, and what an accumulation looks like on its FIRST
step — a print helper written back into the window reaches for
`PySide6.QtPrintSupport` or for `fitz` on its first line, because those are
the two libraries the job needs. Measured before it was taken: every one of
those imports in `main_window.py` was inside the printing block, so the claim
is **zero** rather than a threshold.

- **Function-local imports are walked, which is the whole point.** All nine
  methods imported `QtPrintSupport` or `fitz` *inside* themselves, so a
  top-level scan would have called the window printer-free while it drove a
  printer nine times.
- **Two floors, pointing opposite ways.** The names must be findable in
  `app/printing.py` — an absence assertion is satisfied by a checkout where
  printing was deleted — and `MainWindow` must still offer both print actions,
  because a window that stopped offering them satisfies every other assertion
  here and is not what moving it meant.

### Re-pointing the tests is what found the two real defects

The previous extraction records why the tests must move: `main_window`
legitimately imports what it opens, so `win._print_fit` still resolves and a
green suite there proves the window works rather than that the new module
does. Doing it turned up two things a reading would not have:

- **A monkey-patched class constant SEGFAULTED the interpreter.**
  `test_bands_join_when_raster_outruns_the_viewport` saves and restores
  `MainWindow._PRINT_BAND_PX`, which no longer exists — and the `keep = …` line
  sits *before* its own `try`, so the `AttributeError` escaped with a `QPainter`
  still active on a `QImage`. Qt printed `QPaintDevice: Cannot destroy paint
  device that is being painted` and the process died. Loud, and loud about the
  wrong thing: a `SIGSEGV` reads as a Qt problem, not as a test patching a name
  the code stopped reading.
- **A second test called `win._add_markups_toggle`**, which is now the module's
  and takes the options. It failed by name, which is the good direction.

**Verified in BOTH directions**, this file's own rule from the Qt-degradation
round, because a skip added where a test used to run looks exactly like a fix:
HEAD **740 tests across 58 modules, 28 skipped**; after the extraction and the
re-pointing, **740 / 58 / 28** with identical skip reasons — no test lost, no
skip added — and **745 / 58 / 28** with the five tests this round added.

### ...and two DEAD arms were coverage gaps rather than dead gates

Twelve injections, ten firing. The two that did not are the ones worth the
space, because in both cases the code was right and **nothing was asking it**:

- **`MainWindow.print_preview` was driven by no test at all.** Passing `None`
  where the window hands over its `print_options` fired nothing: the preview's
  own controls are exercised directly against the module, and the wrapper —
  which is now the window's entire remaining half of printing — was covered
  only by the AST gate asserting it exists. `print_document` had a test and
  its sibling did not.
- **The line-weight picker's WRITE was untested while its READ was covered
  four ways.** Deleting `options.min_line_pt = …` left every weight test
  green, because those set the option directly and paint with it. The markups
  toggle beside it had both halves; this one had one, and the asymmetry is
  invisible until something breaks the half nobody drives.

Both now have a test, and re-run they fire — as does passing the wrong
document to the other wrapper, and dropping the picker's signal connection.
**Fourteen arms, every one firing on its own defect**: a print helper written
back into the window reaching for `QtPrintSupport`, the same reaching only for
`fitz`, the sweep narrowed to top-level imports, printing deleted rather than
moved, the window no longer offering the actions, either wrapper handing over
the wrong thing, the toggle and the picker each writing nowhere the job reads,
the picker's signal dropped, the README losing the module, the README naming
one that does not exist, the band margin removed, and `render_dpi` falling
back to the paint viewport.

## "Python 3.11+" was a claim to contributors, and only 3.11 ran

`CONTRIBUTING.md` and `README.md` both say it. The CI matrix varied only the
operating system and pinned `python-version: "3.11"` on both runners, so **3.12
and 3.13 — increasingly the default on a fresh machine — were advertised and
never checked.**

The frozen Windows build pins its own interpreter, so a shipped installer is
unaffected. What this is about is **running from source**, which the README
documents as a first-class way to use the app, against a suite that heavily
exercises PySide6 and PyMuPDF. `build-windows.yml` therefore stays pinned, and
**the reason is written into the file** — an asymmetry with no stated reason
reads as the oversight the test matrix just corrected, and somebody eventually
"fixes" it.

**And both workflows pinned Node-20 action majors.** Every run ended with
*"Node.js 20 is deprecated. The following actions … are being forced to run on
Node.js 24."* The forcing is GitHub's temporary accommodation; when it ends, a
workflow pinned to those majors stops working — and here that is the Windows
build, **the only path that produces the installer**. Bumped to `checkout@v5`,
`setup-python@v6`, `upload-artifact@v5`.

`tests/test_requirements.py::TestTheInterpreterClaimIsExercised` reads the
minimum out of the documents and asserts the matrix covers it *and* names more
than one version, asserts the frozen build stays pinned *with* its reason, and
sweeps both workflows for an action major below its minimum. Comments are
stripped first — the comment explaining this defect necessarily names the
versions the check is hunting, which is the dead gate this repo already paid
for once with `--require-drc`.

### ...and that action sweep was a LIST OF PAST INJURIES before it was a rule

Its first version compared each `uses:` ref against a set of the three that
were stale the day it was written — `checkout@v4`, `setup-python@v5`,
`upload-artifact@v4`. **A gate built from what went wrong last time only ever
catches last time**, and the blindness was measured rather than argued:

| pinned ref | the set | the minimum-major rule |
|---|---|---|
| `actions/checkout@v4` | CAUGHT | `STALE` |
| `actions/checkout@v2` | passed | `STALE` |
| `actions/setup-node@v4` | passed | `STALE` |
| `actions/upload-artifact@v3` | passed | `STALE` |
| `actions/labeler@v9` | passed | `UNDESCRIBED` |
| `actions/checkout@v5` | passed | ok |

One of six caught, and **four genuinely bad pins passed**. `MINIMUM_ACTION_MAJOR`
is the table now, and the two failure kinds are separate on purpose:
`UNDESCRIBED` — a first-party `actions/*` with no minimum recorded — is a
**failure, not a pass**, because a set-membership check answers *"is this one
of the three known-stale refs"*, says no, and lets an unjudged action through.
Third-party actions are left unjudged with the reason stated (nothing here can
know which major of somebody else's action runs on a current runtime), and a
SHA pin is left alone because pinning a commit is the stronger choice.

**And the sweep could pass over nothing.** The glob was `*.yml` only, so a
workflow saved as `.yaml` — or a directory rename — returns no pins and
therefore no offenders, which is a green tick over a sweep of nothing. Both
spellings are globbed and a floor assertion refuses an empty result. Falsified
five ways: each of the four rows above that the old set missed, plus the glob
pointed at an extension nothing uses.

**Scope is this repository, deliberately.** The same defect was portfolio-wide
— ten of fourteen repos on 2026-08-30, every one of them green — and no single
repo's CI can see that, so the cross-repo sweep lives in Pathforward
(`scripts/action_majors.py`) rather than as eleven copies of this.

**What is NOT verified here**: no interpreter in this container has PySide6, so
3.12 and 3.13 could not be exercised locally. CI is the verification, and
`fail-fast: false` was already set, so a failure on the new legs cannot mask the
3.11 result. Say which of the two you did.
