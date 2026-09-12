"""`git ls-remote` exits 0 when it matches nothing, and the fallback believed it.

The Windows build resolves `packaging/pydrc-ref.txt` to a commit SHA and
installs *that*, so a branch cannot move underneath a build in progress. The
resolution ends in a fallback for the one ref git cannot list -- a commit SHA
-- and that fallback answered a second case the same way: **a tag that is not
on the remote at all**. Measured, with the tag removed: the log reads

    PyDRC resolved to: v0.2.0

which is a line that says the resolution succeeded, and pip then fails about
something else. The ref this repository pins is a PyDRC *tag*, and the
portfolio's move to a company account creates each repository fresh from
`main` -- so no tag travels, and this is the shape the move produces.

Two checks, because one cannot run everywhere. The structural assertions read
the step's script and run on any platform; the behavioural ones execute it and
need `bash`, and they say so where it is absent -- a skip that names what it
did not check, rather than a green tick over nothing.
"""

import os
import re
import shutil
import subprocess
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(HERE, ".github", "workflows", "build-windows.yml")
STEP = "Install the design rule library (optional)"

# The step's own `run:` block, hand-parsed. PyYAML is not a dependency of this
# repository -- `tests/test_run_tests.py` carries the same parser for the same
# reason -- and what matters is that this returns the SCRIPT rather than the
# whole file: a check over the file text is answered by the comment above the
# line it is hunting, which is a dead gate this repository has already paid for.
def _run_script(path: str, step_name: str) -> str:
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    try:
        i = next(n for n, ln in enumerate(lines)
                 if ln.strip() == f"- name: {step_name}")
    except StopIteration:
        raise AssertionError(f"no step named {step_name!r} in {path}")
    out, in_run, indent = [], False, None
    for ln in lines[i + 1:]:
        if ln.strip().startswith("- name:"):
            break
        if not in_run:
            if ln.strip().startswith("run:"):
                in_run = True
            continue
        if not ln.strip():
            out.append("")
            continue
        lead = len(ln) - len(ln.lstrip())
        if indent is None:
            indent = lead
        if lead < indent:
            break
        out.append(ln[indent:])
    return "\n".join(out)


def _code_only(script: str) -> str:
    return "\n".join(ln for ln in script.splitlines()
                     if not ln.strip().startswith("#"))


OWNER_EXPR = "${{ github.repository_owner }}"

# `git` and `pip` are shell FUNCTIONS rather than stub files on PATH: a
# function needs no directory, no execute bit and no PATH edit, so the harness
# runs the same way under Git bash on the Windows runner as it does here.
_HARNESS = """
git() {
  if [ "$1" = "ls-remote" ]; then
    [ -n "$LSREMOTE_OUT" ] && printf '%s\\n' "$LSREMOTE_OUT"
    return 0
  fi
  return 0
}
pip() { echo "PIP-CALLED: $*"; }
"""


_MARKER = "BASH-CAN-RUN-A-SCRIPT"


def _bash_candidates():
    """Every bash worth trying, most-faithful first.

    Git bash is not a fallback here, it is the SHELL THE STEP IS ACTUALLY RUN
    WITH: the workflow declares `shell: bash`, and on `windows-latest` Actions
    maps that to `C:\Program Files\Git\bin\bash.exe`. Trying it first is what
    makes this harness drive the same interpreter the workflow does, rather
    than whatever answers to the name.
    """
    seen, out = set(), []
    for cand in (r"C:\Program Files\Git\bin\bash.exe",
                 r"C:\Program Files\Git\usr\bin\bash.exe",
                 shutil.which("bash"), "/bin/bash", "/usr/bin/bash"):
        if cand and cand not in seen:
            seen.add(cand)
            out.append(cand)
    return out


def _usable_bash(candidates=None):
    """The first bash that can actually RUN something, not merely be found.

    `shutil.which("bash")` was the whole test, and on `windows-latest` it
    finds `C:\Windows\System32\bash.exe` -- the WSL launcher, present on
    every Windows image and useless without a distribution installed. It
    answers every invocation with *"Windows Subsystem for Linux has no
    installed distributions"*, in UTF-16LE, and exits 1.

    So the class was NOT skipped, every `_drive` returned `(1, <that
    message>)`, and the run reported `Ran 13 tests ... FAILED (failures=8)`
    on all three Windows legs. **Three of the nine behavioural tests PASSED
    on it**, and they are the more dangerous half: a bash that refuses
    everything satisfies any test whose whole claim is that the step refused.
    Measured by reproducing the shape below rather than counted off the log --
    `test_a_branch_that_is_NOT_on_the_remote_refuses`,
    `test_a_short_hex_ref_is_not_long_enough_to_be_a_sha` and
    `test_a_long_ref_that_is_not_hex_is_not_a_sha_either`, each asserting
    `rc == 1` and no `PIP-CALLED` and nothing else.

    The marker is the load-bearing half rather than the exit code. A shell
    that exits 0 and produces nothing is equally unusable, and reading the
    exit code alone is the same is-it-there-or-does-it-work confusion one
    level down.
    """
    for cand in (_bash_candidates() if candidates is None else candidates):
        if not os.path.exists(cand):
            continue
        try:
            r = subprocess.run([cand, "-c", "echo " + _MARKER],
                               capture_output=True, text=True,
                               errors="replace", timeout=60)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0 and _MARKER in (r.stdout or ""):
            return cand
    return None


BASH = _usable_bash()


def _drive(ref_file_body, lsremote_out, tmpdir):
    """Run the real step script against a ref file and a canned ls-remote."""
    script = _run_script(WORKFLOW, STEP)
    # Two today -- the clone URL and the refusal's own message -- and the
    # count is not the claim: what matters is that the owner is DERIVED here
    # rather than written down (`tests/test_requirements.py` gates that), and
    # that nothing Actions would have expanded is left unexpanded when bash
    # reads it. A stray `${{` is a `bad substitution`, not a test result.
    assert script.count(OWNER_EXPR) >= 1, (
        "the step no longer interpolates the owner, so either it hardcodes an "
        "account or this harness is testing a script Actions does not run")
    script = script.replace(OWNER_EXPR, "TheOrg")
    assert "${{" not in script, (
        f"an Actions expression this harness does not substitute is left in "
        f"the script, and bash cannot read it: "
        f"{re.findall(r'[$][{][{][^}]*[}][}]', script)}")
    pkg = os.path.join(tmpdir, "packaging")
    os.makedirs(pkg, exist_ok=True)
    with open(os.path.join(pkg, "pydrc-ref.txt"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(ref_file_body + "\n")
    path = os.path.join(tmpdir, "step.sh")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(_HARNESS + script)
    env = dict(os.environ,
               INPUT_REF="", PYDRC_TOKEN="tok",
               LSREMOTE_OUT=lsremote_out,
               GITHUB_ENV=os.path.join(tmpdir, "env"))
    r = subprocess.run([BASH, path], cwd=tmpdir, env=env,
                       capture_output=True, text=True, errors="replace")
    out = r.stdout + r.stderr
    # THE HARNESS MUST HAVE RUN THE SCRIPT, and nothing asserted that until
    # `windows-latest` proved it matters. Every path through the step prints
    # one of these two -- `PyDRC ref requested:` on any non-empty ref, and
    # `::error::` on the empty one -- so output carrying neither means the
    # shell never reached the script, whatever it returned. Without this the
    # five tests expecting a refusal pass on a bash that refuses everything.
    # `errors="replace"` is a guard: a decode error in an interpreter's own
    # complaint must not arrive as a test error about the step.
    assert "PyDRC ref requested:" in out or "::error::" in out, (
        f"{BASH} produced neither of the step's two unconditional lines, so "
        f"the script did not run and every assertion below it would be about "
        f"the shell rather than the step. Output was:\n{out!r}")
    return r.returncode, out


class TestTheStepStillDiscriminates(unittest.TestCase):
    """Structural, so it runs where bash does not."""

    def setUp(self):
        self.code = _code_only(_run_script(WORKFLOW, STEP))

    def test_an_unlistable_ref_is_tested_for_its_SHAPE(self):
        self.assertIn("ref_is_sha", self.code,
                      "the fallback no longer asks whether the ref could be a "
                      "commit SHA, so a tag that is not on the remote reaches "
                      "pip as though it had resolved")

    def test_the_not_a_sha_arm_refuses(self):
        self.assertRegex(
            self.code, r'if \[ "\$ref_is_sha" = no \]; then\s*\n\s*echo "::error::',
            "the not-a-SHA arm no longer raises an error the log can be read for")
        self.assertIn("exit 1", self.code, "the not-a-SHA arm no longer fails the job")

    def test_the_ref_is_only_taken_as_a_sha_after_that_test(self):
        # One assignment, and it is downstream of the discriminator. Two, or
        # one above it, is the fallback this test exists to keep out.
        self.assertEqual(1, self.code.count('sha="$ref"'),
                         "expected exactly one place that installs the ref verbatim")
        self.assertLess(self.code.index("ref_is_sha"), self.code.index('sha="$ref"'))

    def test_a_ref_file_naming_nothing_can_still_reach_its_own_refusal(self):
        # `set -euo pipefail` plus a grep that matches nothing kills the script
        # at the read, so without `|| true` the refusal five lines below it can
        # never print: exit 1 with no output at all.
        self.assertRegex(self.code, r"tr -d '\[:space:\]' \|\| true\)")


class TestTheHarnessPicksAShellThatCanRun(unittest.TestCase):
    """Structural, and driven against the shape that cost this a red CI run.

    No Windows runner is reachable from here, so what is asserted is not *a
    claim about Windows* -- it is that the probe rejects a shell of the shape
    `windows-latest` supplies, driven against a constructed one.

    The fake is PLATFORM-SHAPED on purpose. A `#!/bin/sh` script is not
    launchable on Windows, so a single POSIX fake would be rejected by the
    `OSError` arm rather than by the probe -- a pass on the one platform this
    exists for, arriving by exactly the mechanism being fixed. Each test
    asserts the fake really is launchable before asserting anything about the
    probe.
    """

    def _fake(self, code, chatter):
        """A launchable stand-in that always exits `code`, saying `chatter`."""
        import stat, tempfile
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        if os.name == "nt":
            path = os.path.join(d, "fakebash.bat")
            body, nl = f"@echo off\r\necho {chatter}\r\nexit /b {code}\r\n", ""
        else:
            path = os.path.join(d, "fakebash")
            body, nl = f"#!/bin/sh\necho {chatter}\nexit {code}\n", "\n"
        with open(path, "w", encoding="utf-8", newline=nl or None) as fh:
            fh.write(body)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        r = subprocess.run([path, "-c", "echo " + _MARKER], capture_output=True,
                           text=True, errors="replace", timeout=60)
        self.assertEqual(code, r.returncode,
                         f"the fake shell is not launchable here, so the probe "
                         f"would reject it for the wrong reason: {r!r}")
        return path

    def test_a_shell_that_refuses_everything_is_not_usable(self):
        # `windows-latest`'s own shape: `C:\Windows\System32\bash.exe` with no
        # WSL distribution installed answers every invocation with a complaint
        # and exits 1. (The real one writes it in UTF-16LE, which is the second
        # reason the marker cannot be found; the exit code alone settles it.)
        wsl = self._fake(1, "no-installed-distributions")
        self.assertIsNone(_usable_bash([wsl]),
                          "a shell that cannot run a script was accepted, so the "
                          "class below runs and its refusal tests pass on the "
                          "refusal of the SHELL rather than of the step")

    def test_a_shell_that_exits_0_and_says_the_wrong_thing_is_not_usable_either(self):
        # The exit code is not the test. This one succeeds and never echoes
        # what it was asked to, which drives every assertion in the class below
        # against output the step did not produce -- and the marker rejects it.
        quiet = self._fake(0, "nothing-you-asked-for")
        self.assertIsNone(_usable_bash([quiet]))

    def test_a_working_bash_IS_usable(self):
        # The complement, or the two above are satisfied by a probe that
        # rejects everything and skips the whole class for ever.
        real = shutil.which("bash") or "/bin/bash"
        if not os.path.exists(real):
            self.skipTest("no bash on this machine to offer the probe")
        self.assertEqual(real, _usable_bash([real]))

    def test_git_bash_is_preferred_over_whatever_answers_to_the_name(self):
        # Actions maps `shell: bash` to Git bash on `windows-latest`, so the
        # order is a claim about driving the same interpreter the workflow
        # does -- not a workaround for one bad entry on PATH.
        order = _bash_candidates()
        self.assertTrue(order, "the candidate list is empty, so the probe can "
                               "never find a shell and the class below skips "
                               "for ever")
        self.assertTrue(order[0].endswith("bash.exe"),
                        f"Git bash is no longer tried first: {order}")


@unittest.skipUnless(BASH, "no bash here can run a script (tried: "
                           + ", ".join(_bash_candidates() or ["nothing on PATH"])
                           + "), so the step script was not executed; only the "
                             "structural assertions above ran")
class TestDrivingTheStep(unittest.TestCase):
    """Behavioural. Runs the real `run:` block with git and pip stubbed out."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def test_a_lightweight_tag_on_the_remote_resolves_to_its_commit(self):
        sha = "abc123def4567890abcdef1234567890abcdef12"
        rc, out = _drive("v0.2.0", f"{sha}\trefs/tags/v0.2.0", self.tmp)
        self.assertEqual(0, rc, out)
        self.assertIn(f"PyDRC resolved to: {sha}", out)
        self.assertIn(f"PIP-CALLED", out)
        self.assertIn(f"@{sha}", out)

    def test_an_annotated_tag_resolves_to_the_commit_it_points_at(self):
        # Two lines come back; the `^{}` one is the commit and the other is a
        # tag object pip cannot check out.
        obj, commit = "1" * 40, "2" * 40
        rc, out = _drive(
            "v0.2.0",
            f"{obj}\trefs/tags/v0.2.0\n{commit}\trefs/tags/v0.2.0^{{}}",
            self.tmp)
        self.assertEqual(0, rc, out)
        self.assertIn(f"PyDRC resolved to: {commit}", out)
        self.assertNotIn(obj, out)

    def test_a_tag_that_is_NOT_on_the_remote_refuses_and_names_it(self):
        rc, out = _drive("v0.2.0", "", self.tmp)
        self.assertEqual(1, rc, out)
        self.assertIn("::error::", out)
        self.assertIn("v0.2.0", out)
        self.assertNotIn("PIP-CALLED", out,
                         "a ref that is not on the remote reached pip anyway")
        self.assertNotIn("PyDRC resolved to:", out,
                         "the log claims a resolution that did not happen")

    def test_a_branch_that_is_NOT_on_the_remote_refuses(self):
        rc, out = _drive("main", "", self.tmp)
        self.assertEqual(1, rc, out)
        self.assertNotIn("PIP-CALLED", out)

    def test_a_short_hex_ref_is_not_long_enough_to_be_a_sha(self):
        rc, out = _drive("abc", "", self.tmp)
        self.assertEqual(1, rc, out)
        self.assertNotIn("PIP-CALLED", out)

    def test_a_long_ref_that_is_not_hex_is_not_a_sha_either(self):
        # The shape test has two halves and each needs a case the other does
        # not answer: every ref above is either hex or under seven characters,
        # so dropping the hex half alone fired nothing. Found by injecting it.
        rc, out = _drive("release/1.0", "", self.tmp)
        self.assertEqual(1, rc, out)
        self.assertNotIn("PIP-CALLED", out)

    def test_a_commit_sha_is_still_installed_though_git_cannot_list_it(self):
        # The case the fallback exists for, and the reason the discriminator
        # is the ref's shape rather than a refusal for everything unlistable.
        sha = "1db2d9daabbccddeeff00112233445566778899a"
        rc, out = _drive(sha, "", self.tmp)
        self.assertEqual(0, rc, out)
        self.assertIn(f"@{sha}", out)

    def test_a_hex_BRANCH_that_IS_on_the_remote_is_not_mistaken_for_a_sha(self):
        # The stated false positive only bites a hex branch that is *absent*;
        # one that resolves never reaches the shape test at all.
        sha = "3" * 40
        rc, out = _drive("deadbeef", f"{sha}\trefs/heads/deadbeef", self.tmp)
        self.assertEqual(0, rc, out)
        self.assertIn(f"PyDRC resolved to: {sha}", out)

    def test_a_ref_file_naming_nothing_says_so(self):
        for body, label in (("", "empty"), ("# pin me later", "only a comment"),
                            ("   ", "only whitespace")):
            with self.subTest(label):
                rc, out = _drive(body, "", self.tmp)
                self.assertEqual(1, rc, out)
                self.assertIn("::error::", out,
                              "the job failed without saying why -- the refusal "
                              "written for this case never printed")
                self.assertNotIn("PIP-CALLED", out)


if __name__ == "__main__":
    unittest.main()
