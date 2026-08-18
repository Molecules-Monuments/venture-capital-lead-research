# Wave G3 adversarial fixtures

`routing_cases.jsonl` is a fail-closed routing contract, not example output. A
denial case may not name an executing agent.

`scoring_boundary_cases.jsonl` probes every band boundary on **unrounded
`final_100`**, the 0–100 scale the recommendation is actually decided from, and
its `final_100` field says so. The scoring rubric must express recommendation
bands in mathematical interval notation on that scale — `[0, 50)`, `[50, 66)`,
`[66, 82)`, `[82, 100]` — so gaps and overlaps are machine-verifiable.

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
exact bytes); **no in-package executor replays them**. The executed analogues
of what they describe are the G4 semantic suite (`tests/g4/test_semantics.py`
— score weights, boundaries, display rounding) and the release validator
(`scripts/validate_skill_system.py` — routing inventory/allowlists). Live
model routing against `routing_cases.jsonl` remains commissioning evidence.
