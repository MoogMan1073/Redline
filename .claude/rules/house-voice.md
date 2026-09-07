# House voice

Loaded every turn. Adapted from `pstack/unslop` (MIT). What was dropped and why
is in `kit/dsi-toolbox/rules/ATTRIBUTION.md`, which is deliberately NOT beside
the installed copy: every `.md` in `.claude/rules/` is loaded at launch, so an
attribution file living there would cost context on every turn to explain a file
nobody is reading at the time.

Apply to prose you write: commit messages, PR bodies, `CLAUDE.md` sections,
plan documents, comments, and replies. Not to quoted material, not to a
vendor's own wording, and never at the cost of a fact.

## Say the mechanism, not the feeling

The one rule the rest serve. A sentence that could appear unchanged in another
project's document says nothing about this one — cut it or replace it with the
number, the command, or the file and line.

- Not "significantly faster" — `94 s → 0.81 s`.
- Not "the gate is robust" — "falsified by reinstating the defect; it fires."
- Not "this improves reliability" — "measured 0 findings across 446 fixtures."

If you cannot restate a sentence as a fact, an instruction, or a number, delete it.

## Say which gate passed

"It works", "the suite is green", "CI is green on both runners", "the vendor tool
imported it" and "I read the code" are five different claims. Name the one you
have. A desk read is a desk read; do not let it wear a compile gate's clothes.

## A count is true at the commit that lands it

Every number in prose is a snapshot. Two kinds, and they are treated oppositely:

- A snapshot **cited as evidence** for the paragraph it sits in keeps its date
  and is never restamped. Restamping it makes the paragraph describe a
  measurement nobody took.
- A snapshot **standing in for the current answer** is deleted, and the command
  that prints it is named instead. It is wrong again the week after.

## Three numbers, never two

Passed and failed is not the whole answer. Skipped, unreachable, not-checked-out
and could-not-read are their own states, and folding any of them into "clean" is
how a gate reports success without having run.

## Patterns to cut

1. **Puffery and promotional words.** "pivotal", "testament to", "seamless",
   "robust", "powerful", "groundbreaking", "comprehensive". State what happened.
2. **AI vocabulary.** additionally, crucial, delve, enhance, foster, garner,
   intricate, landscape, leverage, showcase, tapestry, underscore, utilize.
   Use the plain word.
3. **Fancy ways to say "is".** "serves as", "stands as", "boasts", "features".
4. **"Not just X, but Y."** State the point.
5. **Vague attribution.** "experts believe", "it is generally accepted". Name
   the source, the file, or the clause — or delete the sentence.
6. **Rule of three by reflex.** Use the number the facts have.
7. **Superficial -ing tails.** "...ensuring reliability", "...highlighting the
   need". Delete, or expand into the real consequence.
8. **Hedging stacks.** "could potentially possibly" → "may". One hedge maximum,
   and only where the uncertainty is real and worth stating.
9. **Filler.** "in order to" → "to". "due to the fact that" → "because".
   "it is important to note that" → delete.
10. **Passive with a knowable actor.** "queries are validated" → "the compiler
    validates queries".
11. **Adverbs propping up weak verbs.** "runs quickly" → "is fast", or the
    number. An adverb doing the work means the verb is wrong.
12. **Sycophancy and chat artifacts.** "Great question!", "You're absolutely
    right!", "I hope this helps!", "Let me know if...". Answer and stop.
13. **Inline-header lists that restate themselves.** "**Performance:**
    Performance improved..." A bold lead-in that names the item and is followed
    by new detail is fine.
14. **Title Case Headings** and decorative emoji. Sentence case, no emoji.
15. **Curly quotes.** Straight quotes.
16. **Generic conclusions.** "The future looks bright." Name the next commit.

## What is NOT a tell here

Measured on this portfolio's own twelve `CLAUDE.md` files (2026-09-07):
**2,623 em dashes across 17,030 lines — 15.4 per 100, in every one of the
twelve, from 10.5 to 17.4.** The em dash is the house's own punctuation for the
turn from a claim to the evidence that refutes it, and a ban on it would rewrite
the corpus that defines this voice. Upstream's rule 13 is dropped, not relaxed.

Also not tells here, and deliberately so: a long document, a dense paragraph, a
repeated leading word, a heading that names a defect. This voice is
precision-first. Do not "let some mess in" to look human.

## American spelling

color, initialize, analyze, canceled, license, behavior, catalog. Never the
British variant. One exception: a name is a fact — a directory called
`catalogue`, a vendor's `Colour` attribute, a quoted sentence. Never rewrite an
identifier to match this rule.
