# Gates

Loaded every turn. Three rules; the catalogue of how each one has been broken here is
`/writing-a-gate`, which is typed rather than fired.

## Falsify it before you trust it

A gate that has never failed is a gate-shaped comment. Write it, reinstate the defect,
watch it go red, and say in one line what you injected.

If the injection reports that nothing fired, suspect the reading before the gate: a
pipeline's exit status is the last command's, and a command substitution earlier on the
line overwrites `$?`. Measure an exit code without a pipe.

## Three numbers, never two

Passed and failed is not the whole answer. Skipped, unreachable, not-checked-out,
could-not-read and not-installed are their own states, and folding any of them into
"clean" is how a gate reports success without having run. A skip is how coverage
evaporates under a green tick.

## An empty sweep is refused, never reported clean

A sweep that matched nothing reports what a clean one reports. Exit 2, name what was
tried, and floor the count — both what was **found** and what was actually **checked**,
because a loop that skips past an exclusion list can find plenty and check none.

## And the gate's oracle is not the thing it is checking

A drift check that regenerates its own input goes green over a measurement of nothing.
Read the measurement, not the artifact. A staleness check that consults the same source as
the claim will agree with it.
