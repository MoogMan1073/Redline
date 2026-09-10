"""Tests for the user-manual vault and its markdown conversion.

Also the gate for an invariant that was **stated in a README and enforced by a
glob**: a shipped-release document must not become an in-app help page.
`load_vault` reads `folder.glob("*.md")` — non-recursive — so `docs/*.md` is
the user manual and the write-once records in `docs/history/` do not reach it.
Nothing checked either half, and both fail quietly:

* the glob going recursive publishes **seven test plans and feature summaries
  as help pages** in one edit, and every existing assertion here still passes
  because they are all about pages that *are* present;
* a record moved up into `docs/` is invisible to a check about `docs/history/`,
  because by then it is no longer in it.

So the first is asked of the FUNCTION rather than of the glob's spelling — a
`rglob` is a behaviour, and a test that greps for `glob("*.md")` is satisfied
by the comment above it — and the second is asked of the directory's own
manifest, which is the only thing that knows what belongs there.
"""

import pathlib
import re
import tempfile
import unittest

from tests._qt import QT_OK as _QT_OK, REASON as _QT_REASON

_DOCS = pathlib.Path(__file__).resolve().parent.parent / "docs"
_HISTORY = _DOCS / "history"

# `app.help` reaches PySide6 (app/help.py:16), so this import -- not any
# PySide6 line in this file -- is what made the whole module ERROR rather
# than skip on a machine without Qt.
if _QT_OK:
    from app.help import load_vault, vault_dir, to_markdown


@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestHelpVault(unittest.TestCase):
    def setUp(self):
        self.pages = load_vault(vault_dir())

    def test_vault_loads_home(self):
        self.assertTrue(self.pages, "docs vault should not be empty")
        self.assertIn("Home", self.pages)

    def test_no_dangling_wikilinks(self):
        dangling = [(n, l) for n, p in self.pages.items()
                    for l in p["links"] if l not in self.pages]
        self.assertEqual(dangling, [], f"dangling links: {dangling}")

    def test_links_and_tags_convert(self):
        md = to_markdown(self.pages["Home"]["raw"])
        self.assertIn("(vault:", md)   # a [[wikilink]] became an anchor
        self.assertIn("(tag:", md)     # a #tag became an anchor

    def test_code_examples_preserved(self):
        # literal `[[link]]`/`#tag` inside backticks must not be converted
        md = to_markdown(self.pages["Home"]["raw"])
        self.assertIn("`[[link]]`", md)

    def test_key_pages_present(self):
        for page in ("Wire Numbers", "Wire Export", "Settings", "Markup Tools",
                     "Comments Sidebar", "TODO", "Eraser"):
            self.assertIn(page, self.pages)


@unittest.skipUnless(_QT_OK, _QT_REASON)
class TestNoShippedReleaseDocumentBecomesAHelpPage(unittest.TestCase):
    """`docs/history/` holds write-once records. None of them is a help page."""

    def setUp(self):
        self.history = sorted(p.name for p in _HISTORY.glob("*.md"))

    def test_the_history_directory_still_holds_records_to_keep_out(self):
        """The floor. Every assertion below is satisfied by a directory that
        has been emptied or renamed — which is what a move degrades to, and it
        reads exactly like an invariant in perfect health."""
        self.assertTrue(_HISTORY.is_dir(), f"{_HISTORY} is gone — re-aim this gate")
        self.assertGreaterEqual(len(self.history), 5,
                                f"only {self.history} left in docs/history/")

    def test_no_history_document_reaches_the_vault(self):
        from app.help import load_vault, vault_dir
        pages = load_vault(vault_dir())
        # The other floor, and it is not decoration: an empty vault satisfies
        # "no history page is in it" perfectly.
        self.assertGreaterEqual(len(pages), 15, "the vault loaded almost nothing")
        leaked = sorted(n for n in self.history if pathlib.Path(n).stem in pages)
        self.assertEqual(leaked, [], (
            f"{leaked} reached the in-app help. These are shipped-release test "
            "plans and feature summaries, not user documentation."))

    def test_the_vault_is_NOT_recursive_asked_of_the_function(self):
        """Asked by putting a file in a subdirectory and looking, never by
        searching the source for `glob("*.md")` — the comment above that line
        names the very call a source check would be hunting for."""
        from app.help import load_vault
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "Home.md").write_text("# Home\n", encoding="utf-8")
            (root / "history").mkdir()
            (root / "history" / "V9.9.9_TEST_PLAN.md").write_text(
                "# plan\n", encoding="utf-8")
            pages = load_vault(root)
        self.assertIn("Home", pages, "the probe did not load at all")
        self.assertNotIn("V9.9.9_TEST_PLAN", pages,
                         "load_vault descends into subdirectories, so every "
                         "record in docs/history/ is now a help page")

    def test_the_history_README_names_exactly_what_is_in_the_directory(self):
        """The half a check about `docs/history/` cannot see: a record that
        LEFT. Its manifest is the only thing that knows what belongs there, so
        a file moved up into `docs/` — where it becomes a help page — fails
        here rather than passing an absence test it is no longer subject to."""
        readme = _HISTORY / "README.md"
        # The MANIFEST is the table, not the page. Swept whole, the prose also
        # names `docs/*.md` and the five living documents at the repository
        # root, and the check reports six phantom absences — a gate scoped to
        # a document where it should be scoped to a section, which is the
        # failure this family keeps paying for. Table rows only, and a name
        # with a separator or a glob in it is prose about a path rather than a
        # file in this directory.
        rows = [l for l in readme.read_text(encoding="utf-8").splitlines()
                if l.lstrip().startswith("|")]
        listed = {n for n in re.findall(r"`([^`]+\.md)`", "\n".join(rows))
                  if "/" not in n and "*" not in n}
        on_disk = set(self.history) - {"README.md"}
        self.assertTrue(listed, "the manifest table named no files")
        self.assertEqual(listed, on_disk, (
            f"listed but absent: {sorted(listed - on_disk)}; "
            f"present but unlisted: {sorted(on_disk - listed)}"))


if __name__ == "__main__":
    unittest.main()
