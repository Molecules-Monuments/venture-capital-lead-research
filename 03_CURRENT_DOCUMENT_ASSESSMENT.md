# Current-document assessment

Date: 2026-07-20  
Scope: the Version 2 baseline, frozen ground source, operational documents,
agent/skill prose, schemas, workflows, configuration, tests, and release files.

## Overall verdict

The baseline was strongest where prose had an executable control: one
channel-facing chief, specialist non-mutation, exact steward launchers,
append-only evidence, scoped approval, document quarantine, idempotency, and
sticky workflow termination. Those mechanisms were preserved.

The weakest documents described capabilities that did not exist or disagreed
with another authority. The largest examples were two unrelated systems both
called memory, an identity-lookup skill much broader than the helper,
intake workflows that bypassed or discarded lookup, prose-defined agent output
contracts with different enums/fields, a universal fixed scoring rubric that
collapsed unknown into negative, XLS support promised while the helper rejected
it, and fixed roster counts presented as both release integrity and immutable
product policy.

## Changes admitted

- Agent prose now points to one closed canonical schema per output boundary.
- The chief must create a schema-valid pre-spawn eval and a separate post-return
  assessment; dependencies, policy/schema hashes, budgets, positive tests,
  falsifiers, stop rules, and failure handling are explicit.
- Postgres has exact-first typed entity resolution, aliases/domains/external
  IDs, review-only fuzzy candidates, current facts with provenance, bounded
  operational history, and append-only decisions consumed atomically by both
  creation workflows.
- Conversational Markdown memory is disabled rather than presented as an empty
  factual store.
- Scoring uses typed evidence state, nullable quality for unknown/blocked/N/A,
  separate coverage, a deterministic calculation, and database-derived
  contradiction/trajectory readiness guards. The bundled rubric is explicitly
  a sample that must be replaced and time-split backtested.
- Runtime timeouts/concurrency now agree with the documented profiles.
- File support is accurately PDF/PPTX/XLSX/CSV; legacy XLS is conversion/quarantine.
- Publication decisions are classified as must customize, review/confirm, or
  do not edit directly. A reviewed profile is bound to policy/eval file hashes.
- Package/runtime/helper versions are consistently 3.0.0 and forward
  migrations preserve applied history.

## Preserved limitations rather than inflated claims

- Agent/model behavioral quality is not established by JSON-schema fixtures.
- Public VC methods remain hypotheses; portfolio association is not fund-return
  evidence and selected winner stories do not supply weights.
- No live channel, OpenClaw model run, connector, notification delivery, or
  production host result is claimed.
- The fuzzy resolver uses a bounded 500-row length bucket; scale recall and p95
  remain to be measured on the declared 100k/1m reference dataset.
- The complete Version 3 G6 pinned-upstream schema harness has not been
  rebuilt; the historical harness has one intentionally obsolete
  `memory-core` expectation.

*(Closed-since note: this assessment is frozen at 2026-07-20 and its last two
limitations were subsequently closed. The 100k-company/1m-fact reference gate
was built and executed — `scripts/run_retrieval_scale.py`, recall =
precision@1 = 1.0 with reference p95 under 250 ms (`evals/V3_EVAL_RESULTS.md`
gates D and I). The Version 3 exact-image harness was rebuilt as
`scripts/run_g6_image.py`, which carries no `memory-core` expectation and
passes 8/8 (`docs/V3_RELEASE_EVIDENCE.md`). The other limitations above still
stand. This document keeps its original text for provenance;
`docs/PRODUCTION_READINESS.md` is the current readiness boundary.)*

The detailed baseline findings, causal change register, rejected amendments,
and rollback conditions are in `02_BASELINE_ASSESSMENT_AND_CHANGE_GATE.md`.
