# Wave G3 adversarial fixtures

`routing_cases.jsonl` is a fail-closed routing contract, not example output. A
denial case may not name an executing agent.

`scoring_boundary_cases.jsonl` probes every lower boundary and the upper end of
the permitted 0.0–5.0 aggregate scale. The scoring rubric must express recommendation
bands with mathematical interval notation, for example `[2.5, 3.3)`, so gaps,
overlaps, and the exact treatment of 4.1 are machine-verifiable.

These fixtures are deliberately independent of model output. They gate the
static governance and capability contract before workflow/runtime tests.

Status in 3.0: both files are hash-pinned reviewed reference cases
(`scripts/check_customization.py` and the G8 deployment gate verify their
exact bytes); **no in-package executor replays them**. The executed analogues
of what they describe are the G4 semantic suite (`tests/g4/test_semantics.py`
— score weights, boundaries, display rounding) and the release validator
(`scripts/validate_skill_system.py` — routing inventory/allowlists). Live
model routing against `routing_cases.jsonl` remains commissioning evidence.
