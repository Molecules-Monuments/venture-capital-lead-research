# Evaluation Fixture Contract

Policy version: `3.0`

The three shipped eval JSONL (`routing-eval.jsonl`, `scoring-eval.jsonl`, `memo-eval.jsonl` under `workspaces/vc-chief/vc/evals/`) are hash-pinned reviewed reference fixtures: `check_customization`/the G8 gate verify them byte-exact, but no in-package executor replays them. The executed analogues that actually compare semantic expected/actual results are the G4 semantic suite (`tests/g4/test_semantics.py` — score weights/boundaries/rounding) and the release validators (`scripts/validate_skill_system.py` — routing inventory/allowlists); merely parsing JSON or checking keys is not a pass.

Mandatory non-empty suites cover:

1. exact 12-agent/26-skill resolver inventory and allowlists;
2. score weights, every boundary (0, 49.999, 50, 65.999, 66, 81.999, 82, 100), the display-window straddle (81.001 and 82.999 both display 4.1 while banding `research_deeper` and `high_priority`), overrides, and missing-data zero contribution;
3. contradiction versus ordinary dated change, units/currency/period incompatibility, and `1.2m`/`900k` parsing;
4. approval stable identity, exact scope, expiry, atomic single use, replay, revision, and rollback-safe retry;
5. document path/symlink/MIME/macro/encryption/resource limits and page/sheet/cell provenance;
6. full lifecycle commit/rollback/idempotent retry/cancellation and Task Flow reconciliation;
7. notification quiet hours, batching, duplicate dispatch, provider acknowledgement, retry, and failure;
8. memo citations, snapshot freshness, contradictions, missing data, and recommendation consistency.

A shipped eval JSONL that fails its byte-exact hash check, or an absent, skipped, malformed, or zero-case executed analogue suite, is a hard failure. Record target version, deterministic command, duration, per-case expected/actual, and safe stderr.

## Reachability (Version 3.0)

This contract is enforced by the release pipeline, not by any agent at
runtime: the chief has no `exec`, so `eval-fixture-check` is a review/advisory
lens over operator-supplied results. The eight categories map to shipped,
executed suites as follows — three are JSONL fixture files under
`workspaces/vc-chief/vc/evals/` (hash-pinned reviewed reference cases:
`routing-eval.jsonl`, `scoring-eval.jsonl`, `memo-eval.jsonl`; no in-package
executor replays them in 3.0), and the executed analogues live in the
deterministic gates:

1. resolver inventory/allowlists → `scripts/validate_skill_system.py` (offline gate);
2. score weights/boundaries → `tests/g4/semantic_cases.json` via `test_semantics.py`;
3. contradiction/parsing semantics → `tests/g4` semantic + research-intelligence suites;
4. approval identity/scope/expiry/replay → `tests/g4/test_database_contract.py`;
5. document limits/provenance → `tests/g4/test_document_security.py`;
6. lifecycle commit/rollback/idempotency → `tests/g4/test_workflow_execution.py` + `test_helper_cli_database.py`;
7. notification lifecycle → `tests/g4/test_database_contract.py` (SQL lifecycle; no live dispatcher ships in 3.0);
8. memo citations/consistency → `tests/g4/test_research_intelligence.py` (memo-record path).

Live-model routing/memo quality remains BLOCKED (unmeasured offline) per the
release evidence; nothing in the package grades model output against these
fixtures mid-run.
