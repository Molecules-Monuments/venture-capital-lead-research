# Wave G3 adversarial fixtures

`routing_cases.jsonl` is a fail-closed routing contract, not example output. A
denial case may not name an executing agent.

`scoring_boundary_cases.jsonl` probes every band boundary on **unrounded
`final_100`**, the 0–100 scale the recommendation is actually decided from, and
its `final_100` field says so. The requirement on the rubric is one of NOTATION,
not of values: it must express its recommendation bands as mathematical
intervals on that scale (the shipped sample uses `[0, 50)`, `[50, 66)`,
`[66, 82)`, `[82, 100]`), so gaps and overlaps are machine-verifiable. The bands
themselves are `sample_only_must_customize` — `governance_lint.md` and
`CUSTOMIZATION.md` both say the edges are not fixed — so a deployment with its
own bands re-cuts this file's eight rows to its own edges and the notation
requirement still holds.

These cases carry no display value, deliberately. `display_5` rounds
`final_100 / 20` to one decimal, so each display value covers a two-point
`final_100` window that STRADDLES a band edge rather than starting at it: `2.5`,
`3.3` and `4.1` each map to two different recommendations. A fixture asserting
one band for a display value asserts something untrue of half its own window,
and this file did exactly that until the eighteenth pass. `tests/g4/test_semantics.py`
executes that straddle against the shipped helper.

These fixtures are deliberately independent of model output. They gate the
static governance and capability contract before workflow/runtime tests.

Status in 3.0: both files are hash-pinned reviewed reference cases
(`scripts/check_customization.py` and the G8 deployment gate verify their
exact bytes). `scoring_boundary_cases.jsonl` is additionally **replayed by the
offline gate**: `tests/g4/test_semantics.py::test_the_reviewed_boundary_fixture_is_on_the_unrounded_scale`
re-derives every row's `expected` band through the shipped helper, so a row
whose band is not what `vcops.py` returns fails `verify_offline.py`. Changing
the recommendation bands therefore means re-cutting this file too — see
`CUSTOMIZATION.md`. `routing_cases.jsonl` has no in-package executor; its
analogue is the release validator (`scripts/validate_skill_system.py` — routing
inventory/allowlists). Live
model routing against `routing_cases.jsonl` remains commissioning evidence.
